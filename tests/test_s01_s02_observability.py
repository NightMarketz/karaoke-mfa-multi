import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import s01_input, s02_demix
from scripts.common.observability import read_events
from scripts.hw_detect import HardwareProfile


def _profile() -> HardwareProfile:
    return HardwareProfile(
        demix_device="cpu",
        demix_compute="float32",
        demix_segment=4,
        demix_jobs=1,
        transcribe_device="cpu",
        transcribe_compute="int8",
        transcribe_beam_size=1,
        transcribe_vad=True,
        align_device="cpu",
        align_batch_size=1,
        ollama_model="qwen2.5:7b",
        ollama_num_ctx=4096,
        ollama_num_thread=4,
        ffmpeg_vcodec="libx264",
        ffmpeg_quality=23,
    )


class Stage01Stage02ObservabilityTests(unittest.TestCase):
    def _close_logging(self) -> None:
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            if isinstance(handler, logging.FileHandler):
                handler.close()

    def _run_s02(self) -> int:
        try:
            return s02_demix.main()
        finally:
            self._close_logging()

    def tearDown(self) -> None:
        self._close_logging()

    def test_stage01_success_records_probe_extract_and_metadata_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "song.wav"
            input_path.write_bytes(b"wav")
            job_dir = root / "job"

            def fake_extract(_input: str, output: str) -> None:
                Path(output).write_bytes(b"normalized")

            with patch(
                "scripts.s01_input.probe_media",
                return_value={
                    "format": {"duration": "12.5"},
                    "streams": [{"codec_type": "audio", "sample_rate": "44100", "channels": 2}],
                },
            ), patch("scripts.s01_input.extract_audio", side_effect=fake_extract):
                metadata = s01_input.run(str(input_path), str(job_dir))

            self.assertEqual(metadata["duration_seconds"], 12.5)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertIn("stage01.started", names)
            self.assertIn("stage01.probe_finished", names)
            self.assertIn("stage01.audio_extract_started", names)
            self.assertIn("stage01.metadata_written", names)
            self.assertIn("stage01.completed", names)

    def test_stage01_unsupported_format_records_failure_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "song.txt"
            input_path.write_text("not audio", encoding="utf-8")
            job_dir = root / "job"

            with self.assertRaises(ValueError):
                s01_input.run(str(input_path), str(job_dir))

            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage01.failed"
                    and event["details"].get("reason") == "unsupported_format"
                    for event in events
                )
            )

    def test_stage02_success_records_demucs_and_output_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "job"
            job_dir.mkdir()
            (job_dir / "input.wav").write_bytes(b"wav")
            demucs_python = root / "python.exe"
            demucs_python.write_bytes(b"exe")

            def fake_collect(_model: str, _input: Path, _output: Path, out_dir: Path) -> None:
                (out_dir / "vocals.wav").write_bytes(b"vocals")
                (out_dir / "instrumental.wav").write_bytes(b"instrumental")

            argv = [
                "s02_demix.py",
                "--job-dir",
                str(job_dir),
                "--demucs-python",
                str(demucs_python),
            ]
            with patch("sys.argv", argv), patch("scripts.s02_demix.detect", return_value=_profile()), patch(
                "scripts.s02_demix._run_demucs"
            ), patch("scripts.s02_demix._collect_stems", side_effect=fake_collect):
                exit_code = self._run_s02()

            self.assertEqual(exit_code, 0)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertIn("stage02.started", names)
            self.assertIn("stage02.demucs_started", names)
            self.assertIn("stage02.stems_collected", names)
            self.assertIn("stage02.output_validated", names)
            self.assertIn("stage02.completed", names)

    def test_stage02_missing_demucs_python_records_failure_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job"
            job_dir.mkdir()
            (job_dir / "input.wav").write_bytes(b"wav")
            argv = [
                "s02_demix.py",
                "--job-dir",
                str(job_dir),
                "--demucs-python",
                str(Path(tmp) / "missing-python.exe"),
            ]

            with patch("sys.argv", argv), patch("scripts.s02_demix.detect", return_value=_profile()):
                exit_code = self._run_s02()

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage02.failed"
                    and event["details"].get("reason") == "demucs_python_missing"
                    for event in events
                )
            )

    def test_stage02_demucs_python_default_can_come_from_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job"
            job_dir.mkdir()
            (job_dir / "input.wav").write_bytes(b"wav")
            env_python = str(Path(tmp) / "env-python.exe")
            argv = [
                "s02_demix.py",
                "--job-dir",
                str(job_dir),
            ]

            with patch.dict("os.environ", {"KARAOKE_DEMUCS_PYTHON": env_python}, clear=False), patch(
                "sys.argv", argv
            ), patch("scripts.s02_demix.detect", return_value=_profile()):
                exit_code = self._run_s02()

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage02.failed"
                    and event["details"].get("reason") == "demucs_python_missing"
                    and event["details"].get("path") == env_python
                    for event in events
                )
            )


if __name__ == "__main__":
    unittest.main()
