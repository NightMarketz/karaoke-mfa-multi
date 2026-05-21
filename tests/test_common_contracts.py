import json
import tempfile
import unittest
from pathlib import Path

from scripts.common.contracts import JobMeta, JobStatus
from scripts.common.status import read_status, write_status


class ContractTests(unittest.TestCase):
    def test_job_meta_round_trip_uses_meta_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            meta = JobMeta(
                job_id="abc123def456",
                song_name="Struggle",
                preset="section-coded",
                created_at=123.4,
                duration_s=210.0,
                has_lyrics=True,
                source="zip",
            )
            meta.write(job_dir)
            loaded = JobMeta.read(job_dir)
            self.assertEqual(loaded.job_id, "abc123def456")
            self.assertEqual(loaded.song_name, "Struggle")
            self.assertTrue((job_dir / "meta.json").exists())
            self.assertFalse((job_dir / "metadata.json").exists())

    def test_status_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            write_status(job_dir, "aligning", 25)
            status = read_status(job_dir)
            self.assertIsInstance(status, JobStatus)
            self.assertEqual(status.stage, "aligning")
            self.assertEqual(status.progress, 25)
            raw = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertIn("updated_at", raw)


if __name__ == "__main__":
    unittest.main()
