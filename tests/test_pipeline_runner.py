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


if __name__ == "__main__":
    unittest.main()
