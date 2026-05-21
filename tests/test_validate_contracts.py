import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import s08_validate


class ValidateContractsTests(unittest.TestCase):
    def setUp(self):
        s08_validate._failures.clear()
        s08_validate._warnings.clear()

    def test_meta_json_is_required_for_new_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            with patch("builtins.print"):
                s08_validate.validate_job_contracts(job_dir)

            self.assertTrue(any("meta.json" in failure for failure in s08_validate._failures))

    def test_status_json_requires_updated_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "meta.json").write_text(
                '{"job_id":"abc123def456","song_name":"x","preset":"section-coded","created_at":1,"duration_s":1,"has_lyrics":true,"source":"zip"}',
                encoding="utf-8",
            )
            (job_dir / "status.json").write_text(
                '{"stage":"queued","progress":0,"error":""}',
                encoding="utf-8",
            )

            with patch("builtins.print"):
                s08_validate.validate_job_contracts(job_dir)

            self.assertTrue(any("updated_at" in failure for failure in s08_validate._failures))

    def test_metadata_json_without_meta_is_legacy_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "metadata.json").write_text('{"job_id":"abc123def456"}', encoding="utf-8-sig")
            (job_dir / "status.json").write_text(
                '{"stage":"queued","progress":0,"error":"","updated_at":1}',
                encoding="utf-8",
            )

            with patch("builtins.print"):
                s08_validate.validate_job_contracts(job_dir)

            self.assertFalse(s08_validate._failures)
            self.assertTrue(any("legacy" in warning for warning in s08_validate._warnings))


if __name__ == "__main__":
    unittest.main()
