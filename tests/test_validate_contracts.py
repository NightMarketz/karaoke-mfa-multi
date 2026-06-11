import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from scripts import s08_validate
from scripts.common.provenance import file_sha256, write_manifest


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

    def test_provenance_fails_when_ass_manifest_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir)
            self._write_ass(job_dir)

            with patch("builtins.print"):
                s08_validate.validate_provenance(job_dir)

            self.assertTrue(
                any("output.ass.manifest.json" in failure for failure in s08_validate._failures)
            )

    def test_provenance_fails_when_ass_hash_changes_after_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir)
            self._write_ass(job_dir)
            self._write_ass_manifest(job_dir)
            self._write_ass(job_dir, text="changed")

            with patch("builtins.print"):
                s08_validate.validate_provenance(job_dir)

            self.assertTrue(any("output.ass" in failure and "hash" in failure for failure in s08_validate._failures))

    def test_provenance_fails_when_analysis_hash_changes_after_ass_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir, text="hello")
            self._write_ass(job_dir)
            self._write_ass_manifest(job_dir)
            self._write_analysis(job_dir, text="changed")

            with patch("builtins.print"):
                s08_validate.validate_provenance(job_dir)

            self.assertTrue(any("analysis.json" in failure and "hash" in failure for failure in s08_validate._failures))

    def test_provenance_fails_when_mp4_manifest_ass_input_hash_mismatches_current_ass(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir)
            self._write_ass(job_dir)
            self._write_ass_manifest(job_dir)
            (job_dir / "output.mp4").write_bytes(b"fake mp4 bytes")
            self._write_mp4_manifest(job_dir, ass_sha256="0" * 64)

            with patch("builtins.print"):
                s08_validate.validate_provenance(job_dir)

            self.assertTrue(
                any("output.mp4.manifest.json" in failure and "output.ass" in failure for failure in s08_validate._failures)
            )

    def test_provenance_fails_when_mp4_manifest_is_missing_for_existing_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir)
            self._write_ass(job_dir)
            self._write_ass_manifest(job_dir)
            (job_dir / "output.mp4").write_bytes(b"fake mp4 bytes")

            with patch("builtins.print"):
                s08_validate.validate_provenance(job_dir)

            self.assertTrue(
                any("output.mp4.manifest.json" in failure for failure in s08_validate._failures)
            )

    def test_provenance_fails_when_mp4_hash_changes_after_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir)
            self._write_ass(job_dir)
            self._write_ass_manifest(job_dir)
            (job_dir / "output.mp4").write_bytes(b"fake mp4 bytes")
            self._write_mp4_manifest(job_dir)
            (job_dir / "output.mp4").write_bytes(b"changed mp4 bytes")

            with patch("builtins.print"):
                s08_validate.validate_provenance(job_dir)

            self.assertTrue(
                any("output.mp4" in failure and "hash" in failure for failure in s08_validate._failures)
            )

    def test_provenance_fails_when_renderer_mode_is_not_current_standard(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir)
            self._write_ass(job_dir)
            self._write_ass_manifest(job_dir, renderer_mode="dual_layer_legacy")

            with patch("builtins.print"):
                s08_validate.validate_provenance(job_dir)

            self.assertTrue(any("renderer_mode" in failure for failure in s08_validate._failures))

    def test_provenance_dialogue_count_uses_stage06_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir)
            (job_dir / "output.ass").write_text(
                "Dialogue: 0,0:00:00.00,0:00:01.00,Verse,,0,0,0,,{\\kf100}hello\n",
                encoding="utf-8-sig",
            )
            self._write_ass_manifest(job_dir, dialogue_count=0)

            with patch("builtins.print"):
                s08_validate.validate_provenance(job_dir)

            self.assertFalse(
                any("dialogue_count mismatch" in failure for failure in s08_validate._failures)
            )

    def test_provenance_fails_when_manifest_dialogue_count_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir)
            self._write_ass(job_dir)
            self._write_ass_manifest(job_dir, dialogue_count=2)

            with patch("builtins.print"):
                s08_validate.validate_provenance(job_dir)

            self.assertTrue(any("dialogue_count mismatch" in failure for failure in s08_validate._failures))

    def test_provenance_valid_graph_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir)
            self._write_ass(job_dir)
            self._write_ass_manifest(job_dir)
            (job_dir / "output.mp4").write_bytes(b"fake mp4 bytes")
            self._write_mp4_manifest(job_dir)

            with patch("builtins.print"):
                s08_validate.validate_provenance(job_dir)

            self.assertFalse(s08_validate._failures)

    def test_ctc_forced_source_counts_as_recorded_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "aligned.json").write_text(
                json.dumps(
                    {
                        "words": [
                            {
                                "word": "hello",
                                "start": 0.0,
                                "end": 1.0,
                                "source": "ctc_forced",
                                "phonemes": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                s08_validate.validate_aligned(job_dir)

            self.assertFalse(s08_validate._failures)
            self.assertTrue(any("0% HubertFA" in warning for warning in s08_validate._warnings))

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

    def _write_analysis(self, job_dir: Path, text: str = "hello") -> None:
        (job_dir / "analysis.json").write_text(
            json.dumps(
                {
                    "lines": [
                        {
                            "text": text,
                            "start": 0,
                            "end": 1,
                            "style": "verse",
                            "words": [{"word": text, "start": 0, "end": 1}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def _write_ass(self, job_dir: Path, text: str = "hello") -> None:
        (job_dir / "output.ass").write_text(
            "\n".join(
                [
                    "[Script Info]",
                    "[V4+ Styles]",
                    "[Events]",
                    f"Dialogue: 0,0:00:00.00,0:00:01.00,Verse,,0,0,0,,{{\\kf100}}{text}",
                ]
            ),
            encoding="utf-8-sig",
        )

    def _write_ass_manifest(
        self,
        job_dir: Path,
        *,
        renderer_mode: str = "single_layer_kf",
        dialogue_count: int = 1,
        analysis_line_count: int = 1,
    ) -> None:
        write_manifest(
            job_dir / "output.ass.manifest.json",
            {
                "stage": "stage06",
                "renderer_mode": renderer_mode,
                "inputs": {
                    "analysis.json": {
                        "path": "analysis.json",
                        "sha256": file_sha256(job_dir / "analysis.json"),
                    }
                },
                "outputs": {
                    "output.ass": {
                        "path": "output.ass",
                    }
                },
                "metrics": {
                    "dialogue_count": dialogue_count,
                    "analysis_line_count": analysis_line_count,
                },
            },
            output_paths={"output.ass": job_dir / "output.ass"},
        )

    def _write_mp4_manifest(self, job_dir: Path, *, ass_sha256: str | None = None) -> None:
        write_manifest(
            job_dir / "output.mp4.manifest.json",
            {
                "stage": "stage07",
                "inputs": {
                    "output.ass": {
                        "path": "output.ass",
                        "sha256": ass_sha256 or file_sha256(job_dir / "output.ass"),
                    }
                },
                "outputs": {
                    "output.mp4": {
                        "path": "output.mp4",
                    }
                },
            },
            output_paths={"output.mp4": job_dir / "output.mp4"},
        )


if __name__ == "__main__":
    unittest.main()
