import tempfile
import unittest
import json
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

    def test_analysis_missing_aligned_words_is_contract_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                '{"lines":[{"text":"hello","start":0,"end":1,"style":"verse","words":[{"word":"hello","start":0,"end":1}]}]}',
                encoding="utf-8",
            )
            aligned = {"words": [{"word": "hello"}, {"word": "world"}]}

            with patch("builtins.print"):
                s08_validate.validate_analysis(job_dir, transcript=None, aligned=aligned)

            self.assertTrue(any("world" in failure for failure in s08_validate._failures))

    def test_ass_layer_zero_overlap_is_contract_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "output.ass").write_text(
                "\n".join([
                    "[Script Info]",
                    "[V4+ Styles]",
                    "[Events]",
                    "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\kf10}one",
                    "Dialogue: 1,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\kf10}one",
                    "Dialogue: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,{\\kf10}two",
                    "Dialogue: 1,0:00:02.00,0:00:04.00,Default,,0,0,0,,{\\kf10}two",
                ]),
                encoding="utf-8-sig",
            )

            with patch("builtins.print"):
                s08_validate.validate_ass(job_dir)

            self.assertTrue(any("overlap" in failure for failure in s08_validate._failures))

    def test_main_writes_observability_summary_for_validation_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "status.json").write_text(
                '{"stage":"validating","progress":95,"error":"","updated_at":1}',
                encoding="utf-8",
            )

            argv = ["s08_validate.py", "--job-dir", str(job_dir)]
            with patch("sys.argv", argv), patch("builtins.print"):
                exit_code = s08_validate.main()

            self.assertEqual(exit_code, 1)
            summary = json.loads((job_dir / "observability_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["failures"])
            self.assertTrue(any("meta.json" in item["message"] for item in summary["failures"]))
            self.assertEqual(summary["latest_event"]["event"], "validation_finished")

    def test_main_writes_summary_when_validator_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            argv = ["s08_validate.py", "--job-dir", str(job_dir)]

            with patch("sys.argv", argv), patch("builtins.print"), patch(
                "scripts.s08_validate.validate_job_contracts",
                side_effect=RuntimeError("validator exploded"),
            ):
                with self.assertRaises(RuntimeError):
                    s08_validate.main()

            summary = json.loads((job_dir / "observability_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(any("validator exploded" in item["message"] for item in summary["failures"]))
            self.assertEqual(summary["latest_event"]["event"], "validation_finished")


if __name__ == "__main__":
    unittest.main()
