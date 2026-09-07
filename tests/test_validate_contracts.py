import math
import tempfile
import unittest
import json
import wave
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

    def test_ctc_forced_source_fails_without_reference_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_transcript(job_dir, reference_timing_applied=False)
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

            self.assertTrue(any("fallback timings" in failure for failure in s08_validate._failures))

    def test_ctc_forced_source_warns_with_reference_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_transcript(job_dir, reference_timing_applied=True)
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

    def test_automatic_timing_quality_fails_line_outside_vocal_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_sine_window(job_dir / "vocals.wav", duration_s=6.0, active_start_s=4.0, active_end_s=5.5)
            transcript = {
                "segments": [
                    {"text": "too early", "start": 0.0, "end": 3.0, "words": []},
                    {"text": "on vocal", "start": 4.1, "end": 5.0, "words": []},
                ]
            }

            with patch("builtins.print"):
                s08_validate.validate_automatic_timing_quality(job_dir, transcript)

            self.assertTrue(any("low vocal overlap" in failure for failure in s08_validate._failures))

    def test_automatic_timing_quality_skips_reference_backed_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            transcript = {"reference_timing_applied": True, "segments": []}

            with patch("builtins.print"):
                s08_validate.validate_automatic_timing_quality(job_dir, transcript)

            self.assertFalse(s08_validate._failures)

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

    def test_syllable_alignment_fails_when_syllable_exceeds_own_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "id": "L001",
                                "text": "beneath",
                                "start": 10.0,
                                "end": 11.0,
                                "style": "verse",
                                "words": [
                                    {
                                        "id": "L001_W001",
                                        "word": "beneath",
                                        "start": 10.0,
                                        "end": 10.8,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "syllable_alignment.json").write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "line_id": "L001",
                        "syllables": [
                            {
                                "syllable_id": "L001_W001_S001",
                                "word_id": "L001_W001",
                                "text": "neath",
                                "start": 10.6,
                                "end": 10.95,
                                "phones": [{"phone": "IY", "start": 10.6, "end": 10.95}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                s08_validate.validate_syllable_alignment(job_dir)

            self.assertTrue(any("outside word" in failure for failure in s08_validate._failures))

    def test_syllable_alignment_accepts_valid_word_scoped_syllables(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "id": "L001",
                                "text": "mama",
                                "start": 10.0,
                                "end": 10.8,
                                "style": "verse",
                                "words": [
                                    {
                                        "id": "L001_W001",
                                        "word": "mama",
                                        "start": 10.0,
                                        "end": 10.8,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "syllable_alignment.json").write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "source": "stage05_word_phoneme_projection",
                        "syllable_timing_mode": "projected_from_stage04_phonemes",
                        "phonetic_backend": "stage04_existing_phonemes",
                        "g2p_backend": None,
                        "native_phone_aligner": False,
                        "safe_for_final_export": True,
                        "syllables": [
                            {
                                "syllable_id": "L001_W001_S001",
                                "line_id": "L001",
                                "word_id": "L001_W001",
                                "text": "ma",
                                "start": 10.05,
                                "end": 10.30,
                                "source": "phone_projection",
                                "confidence": 0.9,
                                "flags": [],
                                "score_breakdown": {"phone_coverage": 1.0},
                                "phones": [
                                    {"phone": "M", "start": 10.0, "end": 10.05},
                                    {"phone": "AA", "start": 10.05, "end": 10.30},
                                ],
                            },
                            {
                                "syllable_id": "L001_W001_S002",
                                "line_id": "L001",
                                "word_id": "L001_W001",
                                "text": "ma",
                                "start": 10.35,
                                "end": 10.80,
                                "source": "phone_projection",
                                "confidence": 0.9,
                                "flags": [],
                                "score_breakdown": {"phone_coverage": 1.0},
                                "phones": [
                                    {"phone": "M", "start": 10.30, "end": 10.35},
                                    {"phone": "AH", "start": 10.35, "end": 10.80},
                                ],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                s08_validate.validate_syllable_alignment(job_dir)

            self.assertFalse(s08_validate._failures)

    def test_syllable_alignment_rejects_missing_source_and_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "id": "L001",
                                "text": "mama",
                                "start": 10.0,
                                "end": 10.8,
                                "style": "verse",
                                "words": [{"id": "L001_W001", "word": "mama", "start": 10.0, "end": 10.8}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "syllable_alignment.json").write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "source": "stage05_word_phoneme_projection",
                        "safe_for_final_export": True,
                        "syllables": [
                            {
                                "syllable_id": "L001_W001_S001",
                                "line_id": "L001",
                                "word_id": "L001_W001",
                                "text": "ma",
                                "start": 10.05,
                                "end": 10.30,
                                "phones": [{"phone": "AA", "start": 10.05, "end": 10.30}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                s08_validate.validate_syllable_alignment(job_dir)

            self.assertTrue(any("missing source" in failure for failure in s08_validate._failures))
            self.assertTrue(any("missing confidence" in failure for failure in s08_validate._failures))

    def test_syllable_alignment_rejects_fallback_source_for_final_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "id": "L001",
                                "text": "mama",
                                "start": 10.0,
                                "end": 10.8,
                                "style": "verse",
                                "words": [{"id": "L001_W001", "word": "mama", "start": 10.0, "end": 10.8}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "syllable_alignment.json").write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "source": "stage05_word_phoneme_projection",
                        "safe_for_final_export": True,
                        "syllables": [
                            {
                                "syllable_id": "L001_W001_S001",
                                "line_id": "L001",
                                "word_id": "L001_W001",
                                "text": "ma",
                                "start": 10.05,
                                "end": 10.30,
                                "source": "duration_interpolation_fallback",
                                "confidence": 0.32,
                                "flags": ["not_phoneme_grounded"],
                                "score_breakdown": {"phone_coverage": 0.0},
                                "phones": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                s08_validate.validate_syllable_alignment(job_dir)

            self.assertTrue(any("fallback source" in failure for failure in s08_validate._failures))

    def test_syllable_alignment_rejects_syllables_outside_windows_and_long_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "id": "L001",
                                "text": "mama",
                                "start": 10.0,
                                "end": 10.8,
                                "style": "verse",
                                "words": [{"id": "L001_W001", "word": "mama", "start": 10.0, "end": 10.8}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "alignment_windows.json").write_text(
                json.dumps({"windows": [{"block_id": "B001", "line_ids": ["L001"], "audio_start": 9.0, "audio_end": 9.5}]}),
                encoding="utf-8",
            )
            (job_dir / "vocal_regions.json").write_text(
                json.dumps({"regions": [], "non_vocal_gaps": [{"start": 10.1, "end": 10.6, "duration": 9.0}]}),
                encoding="utf-8",
            )
            (job_dir / "syllable_alignment.json").write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "source": "stage05_word_phoneme_projection",
                        "safe_for_final_export": True,
                        "syllables": [
                            {
                                "syllable_id": "L001_W001_S001",
                                "line_id": "L001",
                                "word_id": "L001_W001",
                                "text": "ma",
                                "start": 10.2,
                                "end": 10.4,
                                "source": "phone_projection",
                                "confidence": 0.9,
                                "flags": [],
                                "score_breakdown": {"phone_coverage": 1.0},
                                "phones": [{"phone": "AA", "start": 10.2, "end": 10.4}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                s08_validate.validate_syllable_alignment(job_dir)

            self.assertTrue(any("outside alignment window" in failure for failure in s08_validate._failures))
            self.assertTrue(any("long non-vocal gap" in failure for failure in s08_validate._failures))

    def test_syllable_window_containment_is_skipped_when_windows_were_declined(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "id": "L001",
                                "text": "mama",
                                "start": 10.0,
                                "end": 10.8,
                                "style": "verse",
                                "words": [{"id": "L001_W001", "word": "mama", "start": 10.0, "end": 10.8}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "alignment_windows.json").write_text(
                json.dumps({"windows": [{"block_id": "B001", "line_ids": ["L001"], "audio_start": 9.0, "audio_end": 9.5}]}),
                encoding="utf-8",
            )
            (job_dir / "ctc_window_safety_report.json").write_text(
                json.dumps({"safe_for_ctc": False, "summary": {"unsafe_windows": 1}, "windows": []}),
                encoding="utf-8",
            )
            (job_dir / "transcript.json").write_text(
                json.dumps({"alignment_mode": "forced", "ctc_windowed_alignment": False, "segments": []}),
                encoding="utf-8",
            )
            (job_dir / "vocal_regions.json").write_text(
                json.dumps({"regions": [], "non_vocal_gaps": []}),
                encoding="utf-8",
            )
            (job_dir / "syllable_alignment.json").write_text(
                json.dumps(
                    {
                        "version": "1.0",
                        "source": "stage05_word_phoneme_projection",
                        "safe_for_final_export": True,
                        "syllables": [
                            {
                                "syllable_id": "L001_W001_S001",
                                "line_id": "L001",
                                "word_id": "L001_W001",
                                "text": "ma",
                                "start": 10.2,
                                "end": 10.4,
                                "source": "phone_projection",
                                "confidence": 0.9,
                                "flags": [],
                                "score_breakdown": {"phone_coverage": 1.0},
                                "phones": [{"phone": "AA", "start": 10.2, "end": 10.4}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch("builtins.print"):
                s08_validate.validate_syllable_alignment(job_dir)

            self.assertEqual(
                [failure for failure in s08_validate._failures if "outside alignment window" in failure],
                [],
            )

    def _write_syllable_job(self, job_dir: Path, syllable: dict) -> None:
        (job_dir / "analysis.json").write_text(
            json.dumps(
                {
                    "lines": [
                        {
                            "id": "L001",
                            "text": "mama",
                            "start": 10.0,
                            "end": 11.0,
                            "style": "verse",
                            "words": [{"id": "L001_W001", "word": "mama", "start": 10.0, "end": 11.0}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (job_dir / "syllable_alignment.json").write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "source": "stage05_word_phoneme_projection",
                    "safe_for_final_export": True,
                    "syllables": [syllable],
                }
            ),
            encoding="utf-8",
        )

    def test_syllable_stretched_to_the_min_floor_still_counts_as_phone_backed(self):
        # s05 floors a short syllable to DEFAULT_MIN_SEGMENT_MS (80ms), which is
        # more than the 50ms coverage tolerance — a documented stretch, not a defect.
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_syllable_job(
                job_dir,
                {
                    "syllable_id": "L001_W001_S001",
                    "line_id": "L001",
                    "word_id": "L001_W001",
                    "text": "ma",
                    "start": 10.2,
                    "end": 10.28,
                    "source": "phone_projection",
                    "confidence": 0.9,
                    "flags": [],
                    "score_breakdown": {"phone_coverage": 1.0},
                    "phones": [{"phone": "AA", "start": 10.2, "end": 10.21}],
                },
            )

            with patch("builtins.print"):
                s08_validate.validate_syllable_alignment(job_dir)

            self.assertEqual(
                [failure for failure in s08_validate._failures if "phones do not cover" in failure],
                [],
            )

    def test_syllable_longer_than_the_floor_still_needs_phone_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_syllable_job(
                job_dir,
                {
                    "syllable_id": "L001_W001_S001",
                    "line_id": "L001",
                    "word_id": "L001_W001",
                    "text": "ma",
                    "start": 10.2,
                    "end": 10.9,
                    "source": "phone_projection",
                    "confidence": 0.9,
                    "flags": [],
                    "score_breakdown": {"phone_coverage": 1.0},
                    "phones": [{"phone": "AA", "start": 10.2, "end": 10.21}],
                },
            )

            with patch("builtins.print"):
                s08_validate.validate_syllable_alignment(job_dir)

            self.assertTrue(any("phones do not cover" in failure for failure in s08_validate._failures))

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

    def _write_transcript(self, job_dir: Path, *, reference_timing_applied: bool) -> None:
        (job_dir / "transcript.json").write_text(
            json.dumps(
                {
                    "alignment_mode": "forced",
                    "reference_timing_applied": reference_timing_applied,
                    "segments": [
                        {
                            "text": "hello",
                            "start": 0.0,
                            "end": 1.0,
                            "words": [{"word": "hello", "start": 0.0, "end": 1.0, "probability": 1.0}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _write_sine_window(
        self,
        path: Path,
        *,
        duration_s: float,
        active_start_s: float,
        active_end_s: float,
    ) -> None:
        sample_rate = 16000
        frames = int(duration_s * sample_rate)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            payload = bytearray()
            for index in range(frames):
                t = index / sample_rate
                amp = 0.35 * math.sin(2 * math.pi * 220 * t) if active_start_s <= t <= active_end_s else 0.0
                payload.extend(int(max(-1.0, min(1.0, amp)) * 32767).to_bytes(2, "little", signed=True))
            handle.writeframes(bytes(payload))

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
