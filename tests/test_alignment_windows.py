from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import s03b_lyrics_align, s08_validate


class AlignmentWindowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        s08_validate._failures.clear()
        s08_validate._warnings.clear()

    def test_lyrics_blocks_preserve_parenthetical_lyrics_and_split_on_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lyrics_path = Path(tmp) / "lyrics.txt"
            lyrics_path.write_text(
                "[Verse]\n"
                "First line\n"
                "(break in, break in)\n"
                "\n"
                "[Chorus]\n"
                "Ég er dýrið\n",
                encoding="utf-8",
            )

            lines = s03b_lyrics_align._parse_lyrics(lyrics_path)
            blocks = s03b_lyrics_align._build_lyrics_blocks(lines, max_lines=6)

            self.assertEqual("(break in, break in)", lines[1]["text"])
            self.assertEqual(2, len(blocks))
            self.assertEqual(["L001", "L002"], blocks[0]["line_ids"])
            self.assertEqual(["L003"], blocks[1]["line_ids"])

    def test_region_groups_do_not_cross_long_non_vocal_gap(self) -> None:
        regions = [
            {"start": 1.0, "end": 3.0, "vocal_prob": 0.9},
            {"start": 5.0, "end": 7.0, "vocal_prob": 0.8},
            {"start": 20.0, "end": 24.0, "vocal_prob": 0.9},
        ]

        normalized = s03b_lyrics_align._normalize_vocal_regions(regions)
        groups = s03b_lyrics_align._build_vocal_region_groups(normalized, max_group_size=3)

        self.assertFalse(any(group["region_ids"] == ["VR001", "VR002", "VR003"] for group in groups))
        self.assertTrue(any(group["region_ids"] == ["VR001", "VR002"] for group in groups))

    def test_assignments_skip_weak_region_and_build_padded_windows(self) -> None:
        blocks = [
            {
                "block_id": "B001",
                "line_ids": ["L001"],
                "text": "one two three",
                "word_count": 3,
                "estimated_duration_min": 0.5,
                "estimated_duration_max": 8.0,
                "repetition_signature": "a",
            },
            {
                "block_id": "B002",
                "line_ids": ["L002"],
                "text": "four five six",
                "word_count": 3,
                "estimated_duration_min": 0.5,
                "estimated_duration_max": 8.0,
                "repetition_signature": "b",
            },
        ]
        regions = s03b_lyrics_align._normalize_vocal_regions([
            {"start": 1.0, "end": 3.0, "vocal_prob": 0.9},
            {"start": 5.0, "end": 5.3, "vocal_prob": 0.2},
            {"start": 9.0, "end": 11.0, "vocal_prob": 0.9},
        ])
        groups = s03b_lyrics_align._build_vocal_region_groups(regions)

        assignments = s03b_lyrics_align._assign_blocks_to_regions(blocks, groups)
        windows = s03b_lyrics_align._build_alignment_windows(assignments)

        self.assertEqual(["VR001"], assignments[0]["region_ids"])
        self.assertEqual(["VR003"], assignments[1]["region_ids"])
        self.assertEqual(0.7, windows[0]["audio_start"])
        self.assertEqual(3.5, windows[0]["audio_end"])
        self.assertEqual(["L001"], windows[0]["line_ids"])

    def test_assignments_reuse_regions_monotonically_when_blocks_outnumber_regions(self) -> None:
        blocks = [
            {
                "block_id": f"B{index:03d}",
                "line_ids": [f"L{index:03d}"],
                "text": "one two",
                "word_count": 2,
                "estimated_duration_min": 0.5,
                "estimated_duration_max": 10.0,
                "repetition_signature": str(index),
            }
            for index in range(1, 5)
        ]
        regions = s03b_lyrics_align._normalize_vocal_regions([
            {"start": 1.0, "end": 5.0, "vocal_prob": 0.9},
            {"start": 20.0, "end": 25.0, "vocal_prob": 0.9},
        ])
        groups = s03b_lyrics_align._build_vocal_region_groups(regions)

        assignments = s03b_lyrics_align._assign_blocks_to_regions(blocks, groups)

        self.assertEqual(4, len(assignments))
        self.assertTrue(all(assignment["region_ids"] for assignment in assignments))
        assigned_starts = [assignment["window_start"] for assignment in assignments]
        self.assertEqual(sorted(assigned_starts), assigned_starts)

    def test_blocks_sharing_a_region_get_distinct_subdivided_windows(self) -> None:
        # Handing every sharing block the whole region makes the window carry no
        # information and guarantees a "too wide" veto downstream.
        blocks = [
            {
                "block_id": f"B{index:03d}",
                "line_ids": [f"L{index:03d}"],
                "text": "one two",
                "word_count": 2,
                "estimated_duration_min": 0.5,
                "estimated_duration_max": 10.0,
                "repetition_signature": str(index),
            }
            for index in range(1, 5)
        ]
        regions = s03b_lyrics_align._normalize_vocal_regions([
            {"start": 1.0, "end": 21.0, "vocal_prob": 0.9},
            {"start": 40.0, "end": 60.0, "vocal_prob": 0.9},
        ])
        groups = s03b_lyrics_align._build_vocal_region_groups(regions)

        assignments = s03b_lyrics_align._assign_blocks_to_regions(blocks, groups)

        starts = [assignment["window_start"] for assignment in assignments]
        self.assertEqual(4, len(assignments))
        self.assertEqual(4, len(set(starts)), f"windows must be distinct, got {starts}")
        self.assertEqual(sorted(starts), starts)
        for assignment in assignments:
            span = assignment["window_end"] - assignment["window_start"]
            self.assertGreater(span, 0.0)
            self.assertLess(span, 20.0, "a subdivided window must be shorter than the whole region")

    def _write_burst_wav(self, path: Path, bursts, burst_s: float = 1.0, gap_s: float = 0.4) -> None:
        import math
        import struct
        import wave

        lengths = [burst_s] * bursts if isinstance(bursts, int) else list(bursts)
        rate = 16000
        frames = bytearray()
        for length in lengths:
            for index in range(int(rate * length)):
                value = int(20000 * math.sin(2 * math.pi * 220 * index / rate))
                frames += struct.pack("<h", value)
            frames += b"\x00\x00" * int(rate * gap_s)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(bytes(frames))

    def _write_dense_song_job(self, job_dir: Path, blocks: int = 4, phrases_per_block: int = 3) -> list[dict]:
        """A track sung end to end: phrase gaps below the default probe merge gap."""
        self._write_burst_wav(
            job_dir / "vocals.wav",
            bursts=[1.0] * (blocks * phrases_per_block),
            gap_s=0.35,
        )
        self._write_json(
            job_dir / "vocal_regions.json",
            s03b_lyrics_align._build_vocal_regions_artifact(job_dir / "vocals.wav"),
        )
        lines = []
        for block_index in range(blocks):
            for phrase_index in range(phrases_per_block):
                index = block_index * phrases_per_block + phrase_index
                lines.append({
                    "line_id": f"L{index + 1:03d}",
                    "line_index": index,
                    "text": f"frase numero {index + 1} cantada",
                    "section": "verse",
                    "blank_before": phrase_index == 0 and block_index > 0,
                })
        return lines

    def test_probe_granularity_is_chosen_so_the_windows_pass_the_safety_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            lines = self._write_dense_song_job(job_dir)
            coarse = s03b_lyrics_align._normalize_vocal_regions(
                json.loads((job_dir / "vocal_regions.json").read_text(encoding="utf-8"))["regions"]
            )
            self.assertLess(len(coarse), 4, "fixture must start from merged mega-regions")

            s03b_lyrics_align._write_alignment_window_artifacts(job_dir, lines)

            report = json.loads((job_dir / "ctc_window_safety_report.json").read_text(encoding="utf-8"))
            self.assertTrue(
                report["safe_for_ctc"],
                f"expected usable windows, got {report['summary']}",
            )

    def _phrase_blocks(self, count: int) -> list[dict]:
        return [
            {
                "block_id": f"B{index:03d}",
                "line_ids": [f"L{index:03d}"],
                "text": "uma frase cantada",
                "word_count": 3,
                "estimated_duration_min": 0.6,
                "estimated_duration_max": 3.0,
                "repetition_signature": str(index),
            }
            for index in range(1, count + 1)
        ]

    def test_best_regions_prefers_the_granularity_with_the_safest_windows(self) -> None:
        blocks = self._phrase_blocks(4)
        one_blob = s03b_lyrics_align._normalize_vocal_regions([{"start": 0.0, "end": 40.0, "vocal_prob": 0.9}])
        phrases = s03b_lyrics_align._normalize_vocal_regions(
            [{"start": 2.0 + index * 3.0, "end": 4.0 + index * 3.0, "vocal_prob": 0.9} for index in range(4)]
        )

        chosen = s03b_lyrics_align._best_regions_for_blocks([one_blob, phrases], blocks, [])

        self.assertEqual(phrases, chosen)

    def test_best_regions_keeps_the_first_candidate_when_it_is_already_safe(self) -> None:
        blocks = self._phrase_blocks(2)
        phrases = s03b_lyrics_align._normalize_vocal_regions(
            [{"start": 2.0, "end": 4.0, "vocal_prob": 0.9}, {"start": 8.0, "end": 10.0, "vocal_prob": 0.9}]
        )
        shredded = s03b_lyrics_align._normalize_vocal_regions(
            [{"start": 2.0 + index * 0.9, "end": 2.4 + index * 0.9, "vocal_prob": 0.9} for index in range(12)]
        )

        chosen = s03b_lyrics_align._best_regions_for_blocks([phrases, shredded], blocks, [])

        self.assertEqual(phrases, chosen)

    def test_written_windows_follow_real_phrases_not_an_even_split(self) -> None:
        # Uneven phrases: a blind even split of one merged mega-region would run the
        # first window well into the second phrase; probing finer lands on the phrase.
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_burst_wav(job_dir / "vocals.wav", bursts=[1.0, 2.5, 1.0, 2.5], gap_s=0.4)
            self._write_json(
                job_dir / "vocal_regions.json",
                s03b_lyrics_align._build_vocal_regions_artifact(job_dir / "vocals.wav"),
            )
            lines = [
                {
                    "line_id": f"L{index:03d}",
                    "line_index": index - 1,
                    "text": "uma linha cantada aqui",
                    "section": "verse",
                    "blank_before": index > 1,
                }
                for index in range(1, 5)
            ]

            windows = s03b_lyrics_align._write_alignment_window_artifacts(job_dir, lines)

            self.assertEqual(4, len(windows))
            starts = [window["audio_start"] for window in windows]
            self.assertEqual(len(windows), len(set(starts)), f"windows must be distinct, got {starts}")
            self.assertLess(
                windows[0]["audio_end"],
                1.8,
                f"first window should stop at the short first phrase, got {windows[0]}",
            )

    def test_quality_guard_keeps_windowed_alignment_and_skips_the_second_pass(self) -> None:
        clean = [
            {"text": "uma", "start": 1.0, "end": 1.4},
            {"text": "frase", "start": 1.5, "end": 2.0},
        ]
        calls = []

        words, used_windowed, details = s03b_lyrics_align._alignment_with_quality_guard(
            clean, lambda: calls.append(1) or []
        )

        self.assertEqual(clean, words)
        self.assertTrue(used_windowed)
        self.assertEqual([], calls, "full-audio pass must not run when the windowed result is clean")
        self.assertFalse(details["fallback_used"])

    def test_quality_guard_falls_back_when_windowed_words_overlap(self) -> None:
        overlapping = [
            {"text": "uma", "start": 1.0, "end": 1.9},
            {"text": "frase", "start": 1.2, "end": 2.0},
        ]
        clean = [
            {"text": "uma", "start": 1.0, "end": 1.4},
            {"text": "frase", "start": 1.5, "end": 2.0},
        ]

        words, used_windowed, details = s03b_lyrics_align._alignment_with_quality_guard(
            overlapping, lambda: clean
        )

        self.assertEqual(clean, words)
        self.assertFalse(used_windowed)
        self.assertTrue(details["fallback_used"])
        self.assertGreater(details["windowed_timestamp_errors"], details["full_audio_timestamp_errors"])

    def test_quality_guard_keeps_windowed_when_the_full_audio_pass_is_no_better(self) -> None:
        overlapping = [
            {"text": "uma", "start": 1.0, "end": 1.9},
            {"text": "frase", "start": 1.2, "end": 2.0},
        ]
        worse = [
            {"text": "uma", "start": 1.0, "end": 1.9},
            {"text": "frase", "start": 1.1, "end": 1.05},
        ]

        words, used_windowed, details = s03b_lyrics_align._alignment_with_quality_guard(
            overlapping, lambda: worse
        )

        self.assertEqual(overlapping, words)
        self.assertTrue(used_windowed)
        self.assertTrue(details["fallback_used"])

    def test_ctc_window_safety_rejects_too_much_text_for_short_window(self) -> None:
        lines = [{"line_id": "L001", "text": " ".join(["word"] * 40), "section": "verse"}]
        windows = [{"line_ids": ["L001"], "audio_start": 10.0, "audio_end": 10.5}]

        self.assertFalse(s03b_lyrics_align._windows_safe_for_ctc(windows, lines))

        windows[0]["audio_end"] = 30.0
        self.assertTrue(s03b_lyrics_align._windows_safe_for_ctc(windows, lines))

    def test_vocal_islands_split_on_long_non_vocal_gap(self) -> None:
        regions = s03b_lyrics_align._normalize_vocal_regions([
            {"start": 1.0, "end": 3.0, "vocal_prob": 0.9},
            {"start": 5.0, "end": 7.0, "vocal_prob": 0.8},
            {"start": 20.0, "end": 24.0, "vocal_prob": 0.9},
        ])

        islands = s03b_lyrics_align._build_vocal_islands(regions)

        self.assertEqual(2, len(islands))
        self.assertEqual(["VR001", "VR002"], islands[0]["region_ids"])
        self.assertEqual(["VR003"], islands[1]["region_ids"])

    def test_ctc_window_safety_report_explains_unsafe_window(self) -> None:
        blocks = [
            {
                "block_id": "B001",
                "line_ids": ["L001"],
                "text": "one two",
                "word_count": 2,
                "estimated_duration_min": 0.5,
                "estimated_duration_max": 3.0,
            }
        ]
        assignments = [
            {
                "block_id": "B001",
                "line_ids": ["L001"],
                "region_ids": ["VR001", "VR002"],
                "confidence": 0.9,
                "flags": [],
            }
        ]
        regions = s03b_lyrics_align._normalize_vocal_regions([
            {"start": 1.0, "end": 2.0, "vocal_prob": 0.9},
            {"start": 20.0, "end": 21.0, "vocal_prob": 0.9},
        ])
        islands = s03b_lyrics_align._build_vocal_islands(regions)
        windows = [
            {
                "block_id": "B001",
                "line_ids": ["L001"],
                "audio_start": 0.7,
                "audio_end": 21.5,
            }
        ]
        gaps = [{"start": 2.0, "end": 20.0, "duration": 18.0}]

        report = s03b_lyrics_align._evaluate_ctc_window_safety(
            windows=windows,
            blocks=blocks,
            assignments=assignments,
            vocal_regions=regions,
            non_vocal_gaps=gaps,
            vocal_islands=islands,
        )

        self.assertFalse(report["safe_for_ctc"])
        codes = {violation["code"] for violation in report["windows"][0]["violations"]}
        self.assertIn("crosses_long_non_vocal_gap", codes)
        self.assertIn("window_too_wide_for_block", codes)
        self.assertIn("window_contains_multiple_vocal_islands", codes)

    def test_ctc_window_safety_report_flags_text_too_dense_for_ctc(self) -> None:
        blocks = [
            {
                "block_id": "B001",
                "line_ids": ["L001"],
                "text": " ".join(["word"] * 40),
                "word_count": 40,
                "estimated_duration_min": 0.5,
                "estimated_duration_max": 30.0,
            }
        ]
        assignments = [
            {
                "block_id": "B001",
                "line_ids": ["L001"],
                "region_ids": ["VR001"],
                "confidence": 0.9,
                "flags": [],
            }
        ]
        regions = s03b_lyrics_align._normalize_vocal_regions([
            {"start": 1.0, "end": 3.0, "vocal_prob": 0.9},
        ])
        report = s03b_lyrics_align._evaluate_ctc_window_safety(
            windows=[{"block_id": "B001", "line_ids": ["L001"], "audio_start": 1.0, "audio_end": 3.0}],
            blocks=blocks,
            assignments=assignments,
            vocal_regions=regions,
            non_vocal_gaps=[],
            vocal_islands=s03b_lyrics_align._build_vocal_islands(regions),
        )

        codes = {violation["code"] for violation in report["windows"][0]["violations"]}
        self.assertIn("ctc_target_too_dense_for_window", codes)

    def test_alignment_window_artifacts_include_islands_and_safety_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            lyrics_path = job_dir / "lyrics.txt"
            lyrics_path.write_text("[Verse]\nhello world\n", encoding="utf-8")
            self._write_json(job_dir / "vocal_regions.json", {
                "regions": [{"start": 1.0, "end": 3.0, "vocal_prob": 0.9}],
                "non_vocal_gaps": [],
            })

            lines = s03b_lyrics_align._parse_lyrics(lyrics_path)
            s03b_lyrics_align._write_alignment_window_artifacts(job_dir, lines)

            islands = json.loads((job_dir / "vocal_islands.json").read_text(encoding="utf-8"))
            report = json.loads((job_dir / "ctc_window_safety_report.json").read_text(encoding="utf-8"))

            self.assertEqual(1, len(islands["vocal_islands"]))
            self.assertIn("safe_for_ctc", report)
            self.assertEqual(1, report["summary"]["total_windows"])

    def test_s08_fails_automatic_line_outside_own_alignment_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_json(job_dir / "transcript.json", {
                "alignment_mode": "forced",
                "reference_timing_applied": False,
                "segments": [
                    {"line_id": "L001", "text": "hello", "start": 10.0, "end": 11.0, "words": []},
                ],
            })
            self._write_json(job_dir / "lyrics_blocks.json", {
                "blocks": [{"block_id": "B001", "line_ids": ["L001"]}],
            })
            self._write_json(job_dir / "block_region_assignments.json", {
                "assignments": [
                    {
                        "block_id": "B001",
                        "line_ids": ["L001"],
                        "region_ids": ["VR001"],
                        "window_start": 1.0,
                        "window_end": 3.0,
                        "confidence": 0.9,
                        "flags": [],
                    }
                ],
            })
            self._write_json(job_dir / "alignment_windows.json", {
                "windows": [
                    {
                        "block_id": "B001",
                        "line_ids": ["L001"],
                        "audio_start": 0.7,
                        "audio_end": 3.5,
                    }
                ],
            })
            self._write_json(job_dir / "vocal_regions.json", {
                "regions": [{"start": 1.0, "end": 3.0, "vocal_prob": 0.9}],
                "non_vocal_gaps": [],
            })

            transcript = json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
            with patch("builtins.print"):
                s08_validate.validate_alignment_windows(job_dir, transcript)

            self.assertTrue(any("outside alignment window" in failure for failure in s08_validate._failures))

    def test_s08_reports_ctc_window_safety_violation_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_json(job_dir / "transcript.json", {
                "alignment_mode": "forced",
                "reference_timing_applied": False,
                "ctc_windowed_alignment": False,
                "segments": [],
            })
            self._write_json(job_dir / "lyrics_blocks.json", {
                "blocks": [{"block_id": "B001", "line_ids": ["L001"]}],
            })
            self._write_json(job_dir / "block_region_assignments.json", {
                "assignments": [
                    {
                        "block_id": "B001",
                        "line_ids": ["L001"],
                        "region_ids": ["VR001"],
                        "confidence": 0.9,
                        "flags": [],
                    }
                ],
            })
            self._write_json(job_dir / "alignment_windows.json", {
                "windows": [{"block_id": "B001", "line_ids": ["L001"], "audio_start": 0.0, "audio_end": 10.0}],
            })
            self._write_json(job_dir / "vocal_regions.json", {
                "regions": [{"start": 1.0, "end": 2.0, "vocal_prob": 0.9}],
                "non_vocal_gaps": [],
            })
            self._write_json(job_dir / "ctc_window_safety_report.json", {
                "safe_for_ctc": False,
                "summary": {"unsafe_windows": 1},
                "windows": [
                    {
                        "block_id": "B001",
                        "violations": [
                            {"code": "window_too_wide_for_block", "severity": "fail"}
                        ],
                    }
                ],
            })

            transcript = json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
            with patch("builtins.print"):
                s08_validate.validate_alignment_windows(job_dir, transcript)

            self.assertTrue(any("window_too_wide_for_block" in failure for failure in s08_validate._failures))

    def test_s08_skips_line_containment_when_unsafe_windows_were_declined(self) -> None:
        # s03b refuses unsafe windows and aligns on full audio; the lines then sit
        # outside windows that were never used, so containment measures nothing.
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_json(job_dir / "transcript.json", {
                "alignment_mode": "forced",
                "reference_timing_applied": False,
                "ctc_windowed_alignment": False,
                "segments": [
                    {"line_id": "L001", "text": "hello", "start": 10.0, "end": 11.0, "words": []},
                ],
            })
            self._write_json(job_dir / "lyrics_blocks.json", {
                "blocks": [{"block_id": "B001", "line_ids": ["L001"]}],
            })
            self._write_json(job_dir / "block_region_assignments.json", {
                "assignments": [
                    {
                        "block_id": "B001",
                        "line_ids": ["L001"],
                        "region_ids": ["VR001"],
                        "confidence": 0.9,
                        "flags": [],
                    }
                ],
            })
            self._write_json(job_dir / "alignment_windows.json", {
                "windows": [{"block_id": "B001", "line_ids": ["L001"], "audio_start": 0.7, "audio_end": 3.5}],
            })
            self._write_json(job_dir / "vocal_regions.json", {
                "regions": [{"start": 1.0, "end": 3.0, "vocal_prob": 0.9}],
                "non_vocal_gaps": [],
            })
            self._write_json(job_dir / "ctc_window_safety_report.json", {
                "safe_for_ctc": False,
                "summary": {"unsafe_windows": 1},
                "windows": [
                    {"block_id": "B001", "violations": [{"code": "window_too_wide_for_block", "severity": "fail"}]}
                ],
            })

            transcript = json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
            with patch("builtins.print"):
                s08_validate.validate_alignment_windows(job_dir, transcript)

            self.assertFalse(any("outside alignment window" in failure for failure in s08_validate._failures))
            self.assertFalse(any("did not use alignment windows" in failure for failure in s08_validate._failures))
            # the window defect itself is still reported
            self.assertTrue(any("window_too_wide_for_block" in failure for failure in s08_validate._failures))

    def test_s08_accepts_safe_windows_dropped_by_the_quality_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_json(job_dir / "transcript.json", {
                "alignment_mode": "forced",
                "reference_timing_applied": False,
                "ctc_windowed_alignment": False,
                "ctc_window_quality_guard": {
                    "windowed_timestamp_errors": 36,
                    "full_audio_timestamp_errors": 0,
                    "fallback_used": True,
                },
                "segments": [
                    {"line_id": "L001", "text": "hello", "start": 10.0, "end": 11.0, "words": []},
                ],
            })
            self._write_json(job_dir / "lyrics_blocks.json", {
                "blocks": [{"block_id": "B001", "line_ids": ["L001"]}],
            })
            self._write_json(job_dir / "block_region_assignments.json", {
                "assignments": [
                    {"block_id": "B001", "line_ids": ["L001"], "region_ids": ["VR001"], "confidence": 0.9, "flags": []}
                ],
            })
            self._write_json(job_dir / "alignment_windows.json", {
                "windows": [{"block_id": "B001", "line_ids": ["L001"], "audio_start": 0.7, "audio_end": 3.5}],
            })
            self._write_json(job_dir / "vocal_regions.json", {
                "regions": [{"start": 1.0, "end": 3.0, "vocal_prob": 0.9}],
                "non_vocal_gaps": [],
            })
            self._write_json(job_dir / "ctc_window_safety_report.json", {
                "safe_for_ctc": True,
                "summary": {"unsafe_windows": 0},
                "windows": [{"block_id": "B001", "violations": []}],
            })

            transcript = json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
            with patch("builtins.print"):
                s08_validate.validate_alignment_windows(job_dir, transcript)

            self.assertFalse(any("did not use alignment windows" in failure for failure in s08_validate._failures))
            self.assertFalse(any("outside alignment window" in failure for failure in s08_validate._failures))

    def test_s08_still_fails_when_safe_windows_were_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_json(job_dir / "transcript.json", {
                "alignment_mode": "forced",
                "reference_timing_applied": False,
                "ctc_windowed_alignment": False,
                "segments": [],
            })
            self._write_json(job_dir / "lyrics_blocks.json", {
                "blocks": [{"block_id": "B001", "line_ids": ["L001"]}],
            })
            self._write_json(job_dir / "block_region_assignments.json", {
                "assignments": [
                    {"block_id": "B001", "line_ids": ["L001"], "region_ids": ["VR001"], "confidence": 0.9, "flags": []}
                ],
            })
            self._write_json(job_dir / "alignment_windows.json", {
                "windows": [{"block_id": "B001", "line_ids": ["L001"], "audio_start": 0.7, "audio_end": 3.5}],
            })
            self._write_json(job_dir / "vocal_regions.json", {
                "regions": [{"start": 1.0, "end": 3.0, "vocal_prob": 0.9}],
                "non_vocal_gaps": [],
            })
            self._write_json(job_dir / "ctc_window_safety_report.json", {
                "safe_for_ctc": True,
                "summary": {"unsafe_windows": 0},
                "windows": [{"block_id": "B001", "violations": []}],
            })

            transcript = json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
            with patch("builtins.print"):
                s08_validate.validate_alignment_windows(job_dir, transcript)

            self.assertTrue(any("did not use alignment windows" in failure for failure in s08_validate._failures))

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
