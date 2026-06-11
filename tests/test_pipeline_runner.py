import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from scripts.common.observability import read_events
from scripts.pipeline_runner import Stage
from scripts.pipeline_runner import PipelineRunner, build_stage_plan


class PipelineRunnerTests(unittest.TestCase):
    def test_build_stage_plan_uses_forced_alignment_when_lyrics_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "lyrics.txt").write_text("[Verse]\nhello", encoding="utf-8")

            stages = build_stage_plan(job_dir, "cyberpunk", "python")

            names = [stage.name for stage in stages]
            self.assertEqual(names[0], "aligning_lyrics")
            self.assertIn("validating", names)

    def test_runner_marks_failed_when_stage_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            runner = PipelineRunner(job_dir=job_dir, python_exe="python")

            ok = runner.run_command(
                ["python", "-c", "import sys; sys.exit(3)"],
                "testing",
                10,
                timeout=10,
            )

            self.assertFalse(ok)
            self.assertIn("failed", (job_dir / "status.json").read_text(encoding="utf-8"))
            events = read_events(job_dir)
            self.assertTrue(any(event["event"] == "stage_failed" for event in events))

    def test_runner_records_timeout_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            runner = PipelineRunner(job_dir=job_dir, python_exe="python")

            ok = runner.run_command(
                ["python", "-c", "import time; time.sleep(2)"],
                "sleeping",
                10,
                timeout=1,
            )

            self.assertFalse(ok)
            events = read_events(job_dir)
            self.assertTrue(any(event["event"] == "stage_timeout" for event in events))

    def test_runner_records_pipeline_finish_and_registry_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            registry = {"abc123def456": object()}
            runner = PipelineRunner(
                job_dir=job_dir,
                python_exe="python",
                running_registry=registry,
                job_id="abc123def456",
            )
            stages = [Stage("testing", ["python", "-c", "print('ok')"], 10)]

            with patch("scripts.pipeline_runner.build_stage_plan", return_value=stages):
                ok = runner.run()

            self.assertTrue(ok)
            self.assertNotIn("abc123def456", registry)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertIn("pipeline_finished", names)
            self.assertIn("running_registry_cleanup", names)
            summary = json.loads((job_dir / "observability_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["latest_event"]["event"], "running_registry_cleanup")

    def test_runner_assigns_run_id_to_status_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            stages = [Stage("testing", ["python", "-c", "print('ok')"], 10)]

            with patch("scripts.pipeline_runner.build_stage_plan", return_value=stages):
                ok = PipelineRunner(job_dir=job_dir, python_exe="python").run()

            self.assertTrue(ok)
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            run_id = status.get("run_id")
            self.assertIsInstance(run_id, str)
            self.assertTrue(run_id)

            events = read_events(job_dir)
            for event_name in {
                "pipeline_started",
                "stage_command_started",
                "stage_command_finished",
                "pipeline_finished",
            }:
                matching = [event for event in events if event["event"] == event_name]
                self.assertTrue(matching, event_name)
                self.assertEqual(run_id, matching[-1]["details"].get("run_id"))

    def test_runner_uses_supplied_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            stages = [Stage("testing", ["python", "-c", "print('ok')"], 10)]

            with patch("scripts.pipeline_runner.build_stage_plan", return_value=stages):
                ok = PipelineRunner(job_dir=job_dir, python_exe="python", run_id="run-test").run()

            self.assertTrue(ok)
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual("run-test", status.get("run_id"))
            events = read_events(job_dir)
            self.assertTrue(events)
            for event in events:
                if event["event"] in {
                    "pipeline_started",
                    "stage_command_started",
                    "stage_command_finished",
                    "pipeline_finished",
                }:
                    self.assertEqual("run-test", event["details"].get("run_id"))

    def test_stage05_invalidates_analysis_and_downstream_artifacts_before_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_artifacts(
                job_dir,
                [
                    "analysis.json",
                    "output.ass",
                    "output.ass.manifest.json",
                    "output.mp4",
                    "output.mp4.manifest.json",
                    "preview_full.mp4",
                    "preview_full.manifest.json",
                ],
            )
            command = (
                "from pathlib import Path; "
                "job=Path(r'%s'); "
                "missing=['analysis.json','output.ass','output.ass.manifest.json','output.mp4','output.mp4.manifest.json','preview_full.mp4','preview_full.manifest.json']; "
                "assert all(not (job/name).exists() for name in missing)"
            ) % str(job_dir)
            stages = [Stage("analyzing", ["python", "-c", command], 50)]

            with patch("scripts.pipeline_runner.build_stage_plan", return_value=stages):
                ok = PipelineRunner(job_dir=job_dir, python_exe="python", run_id="run-invalidate").run()

            self.assertTrue(ok)
            self.assertFalse((job_dir / "analysis.json").exists())
            self._assert_invalidation_event(
                job_dir,
                "analyzing",
                [
                    "analysis.json",
                    "output.ass",
                    "output.ass.manifest.json",
                    "output.mp4",
                    "output.mp4.manifest.json",
                    "preview_full.mp4",
                    "preview_full.manifest.json",
                ],
            )

    def test_stage06_invalidates_ass_and_mp4_artifacts_before_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_artifacts(
                job_dir,
                [
                    "analysis.json",
                    "output.ass",
                    "output.ass.manifest.json",
                    "output.mp4",
                    "output.mp4.manifest.json",
                    "preview_full.mp4",
                    "preview_full.manifest.json",
                ],
            )
            command = (
                "from pathlib import Path; "
                "job=Path(r'%s'); "
                "assert (job/'analysis.json').exists(); "
                "missing=['output.ass','output.ass.manifest.json','output.mp4','output.mp4.manifest.json','preview_full.mp4','preview_full.manifest.json']; "
                "assert all(not (job/name).exists() for name in missing)"
            ) % str(job_dir)
            stages = [Stage("generating", ["python", "-c", command], 70)]

            with patch("scripts.pipeline_runner.build_stage_plan", return_value=stages):
                ok = PipelineRunner(job_dir=job_dir, python_exe="python", run_id="run-invalidate").run()

            self.assertTrue(ok)
            self.assertTrue((job_dir / "analysis.json").exists())
            self._assert_invalidation_event(
                job_dir,
                "generating",
                [
                    "output.ass",
                    "output.ass.manifest.json",
                    "output.mp4",
                    "output.mp4.manifest.json",
                    "preview_full.mp4",
                    "preview_full.manifest.json",
                ],
            )

    def test_stage07_invalidates_mp4_artifacts_before_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_artifacts(
                job_dir,
                [
                    "output.ass",
                    "output.ass.manifest.json",
                    "output.mp4",
                    "output.mp4.manifest.json",
                    "preview_full.mp4",
                    "preview_full.manifest.json",
                ],
            )
            command = (
                "from pathlib import Path; "
                "job=Path(r'%s'); "
                "assert (job/'output.ass').exists(); "
                "assert (job/'output.ass.manifest.json').exists(); "
                "missing=['output.mp4','output.mp4.manifest.json','preview_full.mp4','preview_full.manifest.json']; "
                "assert all(not (job/name).exists() for name in missing)"
            ) % str(job_dir)
            stages = [Stage("rendering", ["python", "-c", command], 85)]

            with patch("scripts.pipeline_runner.build_stage_plan", return_value=stages):
                ok = PipelineRunner(job_dir=job_dir, python_exe="python", run_id="run-invalidate").run()

            self.assertTrue(ok)
            self.assertTrue((job_dir / "output.ass").exists())
            self._assert_invalidation_event(
                job_dir,
                "rendering",
                [
                    "output.mp4",
                    "output.mp4.manifest.json",
                    "preview_full.mp4",
                    "preview_full.manifest.json",
                ],
            )

    def _write_artifacts(self, job_dir: Path, names: list[str]) -> None:
        for name in names:
            (job_dir / name).write_text("stale", encoding="utf-8")

    def _assert_invalidation_event(self, job_dir: Path, stage: str, deleted: list[str]) -> None:
        events = read_events(job_dir)
        invalidations = [
            event
            for event in events
            if event["event"] == "downstream_artifacts_invalidated" and event["stage"] == stage
        ]
        self.assertTrue(invalidations, stage)
        details = invalidations[-1]["details"]
        self.assertEqual("run-invalidate", details.get("run_id"))
        self.assertEqual(deleted, details.get("deleted_artifacts"))


if __name__ == "__main__":
    unittest.main()
