import tempfile
import unittest
from pathlib import Path

from scripts.s04_align import _hfa_batch_dir


class Stage04TempWorkspaceTests(unittest.TestCase):
    def test_hfa_batch_dir_lives_under_job_dir_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            with _hfa_batch_dir(job_dir) as batch_dir:
                self.assertTrue(batch_dir.exists())
                batch_dir.relative_to(job_dir)
                (batch_dir / "probe.txt").write_text("ok", encoding="utf-8")

            self.assertFalse(batch_dir.exists())


if __name__ == "__main__":
    unittest.main()
