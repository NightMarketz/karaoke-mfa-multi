import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.common.observability import read_events
from scripts.common.provenance import file_sha256, write_manifest
from scripts.hw_detect import HardwareProfile
from scripts import s07_output


def _hardware_profile() -> HardwareProfile:
    return HardwareProfile(
        demix_device="cpu",
        demix_compute="float32",
        demix_segment=4,
        demix_jobs=1,
        transcribe_device="cpu",
        transcribe_compute="int8",
        transcribe_beam_size=1,
        transcribe_vad=False,
        align_device="cpu",
        align_batch_size=8,
        ollama_model="qwen2.5:7b",
        ollama_num_ctx=4096,
        ollama_num_thread=6,
        ffmpeg_vcodec="libx264",
        ffmpeg_quality=23,
    )


class Stage07ObservabilityTests(unittest.TestCase):
    def _write_inputs(self, job_dir: Path, *, vocals: bool = True) -> None:
        (job_dir / "instrumental.wav").write_bytes(b"instrumental audio")
        if vocals:
            (job_dir / "vocals.wav").write_bytes(b"vocals audio")
        (job_dir / "output.ass").write_text(
            "[Script Info]\nTitle: test\n[V4+ Styles]\n[Events]\n",
            encoding="utf-8",
        )

    def _write_ass_manifest(self, job_dir: Path) -> Path:
        inputs = {}
        analysis_path = job_dir / "analysis.json"
        if analysis_path.exists():
            inputs["analysis.json"] = {
                "path": "analysis.json",
                "sha256": file_sha256(analysis_path),
                "size_bytes": analysis_path.stat().st_size,
            }
        return write_manifest(
            job_dir / "output.ass.manifest.json",
            {
                "stage": "stage06",
                "run_id": "test-run",
                "inputs": inputs,
                "outputs": {
                    "output.ass": {
                        "path": "output.ass",
                    },
                },
            },
            output_paths={"output.ass": job_dir / "output.ass"},
        )

    def _run_stage07(self, job_dir: Path, *extra_args: str) -> int:
        argv = ["s07_output.py", "--job-dir", str(job_dir), *extra_args]
        root_logger = logging.getLogger()
        existing_handlers = set(root_logger.handlers)
        try:
            with patch("sys.argv", argv), patch("scripts.s07_output.detect", return_value=_hardware_profile()):
                return s07_output.main()
        finally:
            for handler in root_logger.handlers[:]:
                if handler in existing_handlers:
                    continue
                root_logger.removeHandler(handler)
                if isinstance(handler, logging.FileHandler):
                    handler.close()

    def test_success_records_render_events_and_missing_vocals_warning_in_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_inputs(job_dir, vocals=False)
            self._write_ass_manifest(job_dir)

            def fake_run(cmd, **kwargs):
                if cmd[0] == "ffprobe":
                    return SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps(
                            {
                                "format": {"duration": "12.5"},
                                "streams": [
                                    {"codec_type": "video", "codec_name": "h264"},
                                    {"codec_type": "audio", "duration": "10.5"},
                                ],
                            }
                        ),
                    )
                (job_dir / "output.mp4").write_bytes(b"x" * 20_000)
                return SimpleNamespace(returncode=0)

            with patch("scripts.s07_output.subprocess.run", side_effect=fake_run):
                exit_code = self._run_stage07(job_dir, "--timeout", "42")

            self.assertEqual(exit_code, 0)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertIn("stage07.started", names)
            self.assertEqual(
                sum(event["event"] == "stage07.input_artifact_checked" for event in events),
                3,
            )
            self.assertTrue(
                any(
                    event["event"] == "stage07.audio_mix_selected"
                    and event["details"].get("mode") == "instrumental_only"
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage07.ffmpeg_started"
                    and event["details"].get("timeout_seconds") == 42
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage07.output_written"
                    and event["details"].get("size_bytes") == 20_000
                    and event["details"].get("duration_seconds") == 12.5
                    for event in events
                )
            )
            self.assertEqual(names[-1], "stage07.completed")
            summary = json.loads((job_dir / "observability_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(
                any(
                    warning["event"] == "stage07.input_missing"
                    and warning["details"].get("artifact") == "vocals.wav"
                    for warning in summary["warnings"]
                )
            )

    def test_ffmpeg_failure_records_failed_events_and_preserves_status_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_inputs(job_dir)
            self._write_ass_manifest(job_dir)

            def fake_run(cmd, **kwargs):
                if cmd[0] == "ffprobe":
                    return SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps(
                            {"streams": [{"codec_type": "audio", "duration": "3.0"}]}
                        ),
                    )
                return SimpleNamespace(returncode=9)

            with patch("scripts.s07_output.subprocess.run", side_effect=fake_run):
                exit_code = self._run_stage07(job_dir)

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage07.ffmpeg_finished"
                    and event["details"].get("returncode") == 9
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage07.render_failed"
                    and event["details"].get("reason") == "ffmpeg_nonzero"
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage07.failed"
                    and event["details"].get("reason") == "ffmpeg_nonzero"
                    for event in events
                )
            )
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["stage"], "failed")
            self.assertIn("ffmpeg exit 9", status["error"])

    def test_missing_ass_manifest_fails_before_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_inputs(job_dir)

            def fake_run(cmd, **kwargs):
                if cmd[0] == "ffmpeg":
                    self.fail("ffmpeg should not run without output.ass provenance")
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {"streams": [{"codec_type": "audio", "duration": "3.0"}]}
                    ),
                )

            with patch("scripts.s07_output.subprocess.run", side_effect=fake_run):
                exit_code = self._run_stage07(job_dir)

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertNotIn("stage07.ffmpeg_started", names)
            self.assertTrue(
                any(
                    event["event"] == "stage07.failed"
                    and event["details"].get("reason") == "ass_manifest_invalid"
                    for event in events
                )
            )
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertNotEqual(status.get("stage"), "done")

    def test_ass_manifest_hash_mismatch_fails_before_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_inputs(job_dir)
            self._write_ass_manifest(job_dir)
            (job_dir / "output.ass").write_text(
                "[Script Info]\nTitle: changed\n[V4+ Styles]\n[Events]\n",
                encoding="utf-8",
            )

            def fake_run(cmd, **kwargs):
                if cmd[0] == "ffmpeg":
                    self.fail("ffmpeg should not run with stale output.ass provenance")
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {"streams": [{"codec_type": "audio", "duration": "3.0"}]}
                    ),
                )

            with patch("scripts.s07_output.subprocess.run", side_effect=fake_run):
                exit_code = self._run_stage07(job_dir)

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertNotIn("stage07.ffmpeg_started", names)
            self.assertTrue(
                any(
                    event["event"] == "stage07.failed"
                    and event["details"].get("reason") == "ass_manifest_invalid"
                    and event["details"].get("artifact") == "output.ass"
                    for event in events
                )
            )

    def test_success_writes_mp4_manifest_and_records_manifest_event_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_inputs(job_dir)
            self._write_ass_manifest(job_dir)

            def fake_run(cmd, **kwargs):
                if cmd[0] == "ffprobe":
                    return SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps(
                            {
                                "format": {"duration": "12.5"},
                                "streams": [
                                    {"codec_type": "video", "codec_name": "h264"},
                                    {"codec_type": "audio", "duration": "10.5"},
                                ],
                            }
                        ),
                    )
                (job_dir / "output.mp4").write_bytes(b"x" * 20_000)
                return SimpleNamespace(returncode=0)

            with patch("scripts.s07_output.subprocess.run", side_effect=fake_run):
                exit_code = self._run_stage07(
                    job_dir,
                    "--vcodec",
                    "libx264",
                    "--quality",
                    "18",
                    "--resolution",
                    "1280x720",
                    "--framerate",
                    "24",
                    "--audio-codec",
                    "aac",
                    "--audio-bitrate",
                    "160k",
                )

            self.assertEqual(exit_code, 0)
            manifest_path = job_dir / "output.mp4.manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["stage"], "stage07")
            self.assertEqual(
                manifest["inputs"]["output.ass"]["sha256"],
                file_sha256(job_dir / "output.ass"),
            )
            self.assertEqual(
                manifest["outputs"]["output.mp4"]["sha256"],
                file_sha256(job_dir / "output.mp4"),
            )
            self.assertEqual(manifest["outputs"]["output.mp4"]["size_bytes"], 20_000)
            self.assertEqual(manifest["settings"]["vcodec"], "libx264")
            self.assertEqual(manifest["settings"]["quality"], 18)
            self.assertEqual(manifest["settings"]["resolution"], "1280x720")
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage07.output_written"
                    and event["details"].get("manifest_path") == str(manifest_path)
                    and event["details"].get("manifest_sha256")
                    == file_sha256(manifest_path)
                    for event in events
                )
            )

    def test_ass_manifest_analysis_hash_mismatch_fails_before_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_inputs(job_dir)
            (job_dir / "analysis.json").write_text(
                json.dumps({"lines": [{"text": "original"}]}),
                encoding="utf-8",
            )
            self._write_ass_manifest(job_dir)
            (job_dir / "analysis.json").write_text(
                json.dumps({"lines": [{"text": "changed"}]}),
                encoding="utf-8",
            )

            def fake_run(cmd, **kwargs):
                if cmd[0] == "ffmpeg":
                    self.fail("ffmpeg should not run with stale analysis provenance")
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {"streams": [{"codec_type": "audio", "duration": "3.0"}]}
                    ),
                )

            with patch("scripts.s07_output.subprocess.run", side_effect=fake_run):
                exit_code = self._run_stage07(job_dir)

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertNotIn("stage07.ffmpeg_started", names)
            self.assertTrue(
                any(
                    event["event"] == "stage07.failed"
                    and event["details"].get("reason") == "ass_manifest_invalid"
                    and "analysis.json" in event.get("message", "")
                    for event in events
                )
            )

    def test_missing_job_dir_records_global_failure_without_creating_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_job = Path(tmp) / "missing-job"

            exit_code = self._run_stage07(missing_job)

            self.assertEqual(exit_code, 1)
            self.assertFalse(missing_job.exists())
            events = read_events(Path(tmp) / "_stage07")
            self.assertEqual(["stage07.failed"], [event["event"] for event in events])
            self.assertEqual("job_dir_missing", events[0]["details"]["reason"])


if __name__ == "__main__":
    unittest.main()
