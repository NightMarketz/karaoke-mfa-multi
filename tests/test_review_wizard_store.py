import json
import unittest
from pathlib import Path

from scripts.review_wizard.contracts import Project
from scripts.review_wizard.store import load_project, save_project


class StoreEdgeCaseTests(unittest.TestCase):
    def test_load_project_returns_raises_for_missing_file(self):
        with self.assertRaises(Exception):
            load_project(Path("/nonexistent/path/that/does/not/exist"))

    def test_load_project_raises_for_corrupt_json(self, tmp_path=None):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            review_file = job_dir / "review_wizard.json"
            review_file.write_text("not valid json {{{", encoding="utf-8")
            with self.assertRaises(Exception):
                load_project(job_dir)

    def test_save_project_creates_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            project = Project.new(project_id="proj-1", job_id="job-1")
            save_project(job_dir, project)
            self.assertTrue((job_dir / "review_wizard.json").exists())

    def test_save_project_round_trips_data(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            project = Project.new(project_id="proj-42", job_id="job-99")
            save_project(job_dir, project)
            loaded = load_project(job_dir)
            self.assertEqual(loaded.project_id, "proj-42")
            self.assertEqual(loaded.job_id, "job-99")
            self.assertEqual(loaded.schema_version, project.schema_version)


if __name__ == "__main__":
    unittest.main()
