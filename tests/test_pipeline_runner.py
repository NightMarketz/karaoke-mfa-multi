import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
