import unittest

import pytest

pytest.importorskip("numpy")
from scripts.review_wizard.timing_layers import (
    apply_audio_backed_tail_extensions,
    build_audio_backed_timing,
    summarize_audio_backed_timing,
    build_timing_diagnostics,
    classify_line_timing,
    gap_should_be_absorbed,
    summarize_timing_layers,
)
from scripts.s06_generate_ass import _build_karaoke_text


class TimingLayersTests(unittest.TestCase):
    def test_bridge_internal_large_gap_is_bad_gap(self):
        line = {
            "style": "bridge",
            "words": [
                {"word": "It", "start": 236.98, "end": 237.04},
                {"word": "calls", "start": 238.60, "end": 238.98},
                {"word": "my", "start": 239.08, "end": 239.74},
                {"word": "name", "start": 242.04, "end": 242.36},
            ],
        }

        timing = classify_line_timing(line)

        classifications = [gap["classification"] for gap in timing["inter_word_gaps"]]
        self.assertEqual(classifications, ["bad_gap", "small_gap", "bad_gap"])

    def test_outro_internal_very_large_gap_is_instrumental_pause(self):
        line = {
            "style": "outro",
            "words": [
                {"word": "I", "start": 300.22, "end": 300.27},
                {"word": "must", "start": 306.26, "end": 306.58},
                {"word": "carry", "start": 306.62, "end": 307.00},
                {"word": "on", "start": 307.14, "end": 307.38},
            ],
        }

        timing = classify_line_timing(line)

        self.assertEqual(timing["inter_word_gaps"][0]["classification"], "instrumental_pause")
        self.assertEqual(timing["inter_word_gaps"][-1]["classification"], "small_gap")

    def test_long_semantic_word_is_vowel_extension_vocal_period(self):
        line = {
            "text": "About to snap",
            "style": "prechorus",
            "words": [
                {"word": "About", "start": 274.48, "end": 275.22},
                {"word": "to", "start": 275.26, "end": 275.31},
                {"word": "snap", "start": 275.42, "end": 282.02},
            ],
        }

        timing = classify_line_timing(line)

        self.assertEqual(timing["tail"]["classification"], "tail_vowel_extension")
        self.assertEqual(timing["tail"]["sustain_type"], "vowel_extension")
        self.assertEqual(timing["vocal_periods"][0]["classification"], "vowel_extension")

    def test_long_adlib_word_is_melisma_vocal_period(self):
        line = {
            "text": "oooohh uuuhhh",
            "style": "bridge",
            "words": [
                {"word": "oooohh", "start": 89.24, "end": 90.70},
                {"word": "uuuhhh", "start": 90.96, "end": 92.30},
            ],
        }

        timing = classify_line_timing(line)

        self.assertEqual(timing["vocal_periods"][0]["classification"], "melisma")
        self.assertEqual(timing["tail"]["classification"], "tail_melisma")

    def test_short_hummed_intro_is_melisma_even_below_sustain_threshold(self):
        line = {
            "text": "Hmmmmm",
            "style": "intro",
            "words": [
                {"word": "Hmmmmm", "start": 12.74, "end": 13.18},
            ],
        }

        timing = classify_line_timing(line)

        self.assertEqual(timing["vocal_periods"][0]["classification"], "melisma")
        self.assertEqual(timing["tail"]["classification"], "tail_melisma")

    def test_audio_backed_timing_requires_vocal_activity_for_textual_melisma(self):
        lines = [
            {
                "text": "Hmmmmm",
                "style": "intro",
                "words": [
                    {"word": "Hmmmmm", "start": 0.5, "end": 0.9},
                ],
            }
        ]
        audio_activity = {(0, 0): {"active": False, "voiced_ratio": 0.0}}

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["vocal_periods"], [])
        self.assertEqual(timing["tail"]["classification"], "none")

    def test_audio_backed_timing_promotes_unwritten_vowel_extension_from_vocals(self):
        lines = [
            {
                "text": "About to snap",
                "style": "prechorus",
                "words": [
                    {"word": "snap", "start": 10.0, "end": 10.3},
                ],
            },
            {
                "text": "So burn it all",
                "style": "chorus",
                "start": 13.0,
                "words": [{"word": "So", "start": 13.0, "end": 13.2}],
            },
        ]
        audio_activity = {
            (0, 0): {"active": True, "voiced_ratio": 0.95},
            ("tail", 0): {"active": True, "voiced_ratio": 0.82, "end_s": 12.7},
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["tail"]["classification"], "probable_unwritten_vowel_extension")
        self.assertEqual(timing["tail"]["audio_evidence"]["voiced_ratio"], 0.82)
        self.assertEqual(
            timing["tail"]["sound_suggestion"],
            {
                "sound_type": "sustained_final_vowel",
                "suggested_caption": "snap...",
                "suggested_user_action": "extend_final_vowel",
            },
        )

    def test_audio_backed_timing_extends_short_written_melisma_when_tail_voice_continues(self):
        lines = [
            {
                "text": "Hmmmmm",
                "style": "intro",
                "start": 12.74,
                "end": 13.18,
                "words": [{"word": "Hmmmmm", "start": 12.74, "end": 13.18}],
            },
            {
                "text": "Still",
                "style": "intro",
                "start": 18.28,
                "end": 19.16,
                "words": [{"word": "Still", "start": 18.28, "end": 19.16}],
            },
        ]
        audio_activity = {
            (0, 0): {"active": True, "voiced_ratio": 1.0},
            ("tail", 0): {
                "active": True,
                "voiced_ratio": 0.90,
                "start_s": 13.18,
                "end_s": 16.20,
                "duration_s": 3.02,
            },
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["tail"]["classification"], "written_melisma_extension")
        self.assertEqual(timing["tail"]["audio_evidence"]["end_s"], 16.20)

    def test_audio_backed_timing_uses_attached_tail_region_in_long_gap(self):
        lines = [
            {
                "text": "Hmmmmm",
                "style": "intro",
                "start": 12.74,
                "end": 13.18,
                "words": [{"word": "Hmmmmm", "start": 12.74, "end": 13.18}],
            },
            {
                "text": "Still",
                "style": "intro",
                "start": 18.28,
                "end": 19.16,
                "words": [{"word": "Still", "start": 18.28, "end": 19.16}],
            },
        ]
        audio_activity = {
            (0, 0): {"active": True, "voiced_ratio": 1.0},
            ("tail", 0): {
                "active": False,
                "voiced_ratio": 0.20,
                "start_s": 13.18,
                "end_s": 18.28,
                "duration_s": 5.10,
            },
            ("tail_regions", 0): [
                {
                    "active": True,
                    "voiced_ratio": 0.92,
                    "start_s": 13.24,
                    "end_s": 14.40,
                    "duration_s": 1.16,
                }
            ],
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["tail"]["classification"], "written_melisma_extension")
        self.assertEqual(timing["tail"]["audio_evidence"]["end_s"], 14.40)

    def test_audio_backed_timing_extends_written_melisma_with_late_attached_region(self):
        lines = [
            {
                "text": "Oooo wooow",
                "style": "intro",
                "start": 30.0,
                "end": 30.8,
                "words": [
                    {"word": "Oooo", "start": 30.0, "end": 30.32},
                    {"word": "wooow", "start": 30.44, "end": 30.80},
                ],
            },
            {
                "text": "Past the fear",
                "style": "verse",
                "start": 34.0,
                "end": 35.0,
                "words": [{"word": "Past", "start": 34.0, "end": 34.2}],
            },
        ]
        audio_activity = {
            (0, 1): {"active": True, "voiced_ratio": 0.95},
            ("tail", 0): {
                "active": False,
                "voiced_ratio": 0.25,
                "start_s": 30.80,
                "end_s": 34.0,
                "duration_s": 3.20,
            },
            ("tail_regions", 0): [
                {
                    "active": True,
                    "voiced_ratio": 0.90,
                    "start_s": 31.34,
                    "end_s": 32.40,
                    "duration_s": 1.06,
                }
            ],
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["tail"]["classification"], "written_melisma_extension")
        self.assertEqual(timing["tail"]["audio_evidence"]["end_s"], 32.40)

    def test_audio_backed_timing_extends_short_attached_written_melisma_tail(self):
        lines = [
            {
                "text": "Oooo wooow",
                "style": "outro",
                "start": 361.72,
                "end": 362.52,
                "words": [
                    {"word": "Oooo", "start": 361.72, "end": 361.98},
                    {"word": "wooow", "start": 362.30, "end": 362.52},
                ],
            },
            {
                "text": "I must carry on",
                "style": "outro",
                "start": 362.78,
                "end": 363.8,
                "words": [{"word": "I", "start": 362.78, "end": 362.83}],
            },
        ]
        audio_activity = {
            (0, 1): {"active": True, "voiced_ratio": 1.0},
            ("tail", 0): {
                "active": True,
                "voiced_ratio": 1.0,
                "start_s": 362.52,
                "end_s": 362.78,
                "duration_s": 0.26,
            },
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["tail"]["classification"], "written_melisma_extension")
        self.assertEqual(timing["tail"]["audio_evidence"]["end_s"], 362.78)

    def test_audio_backed_timing_promotes_strong_tail_after_fear(self):
        lines = [
            {
                "text": "Past the fear",
                "style": "prechorus",
                "start": 160.14,
                "end": 161.24,
                "words": [
                    {"word": "Past", "start": 160.14, "end": 160.48},
                    {"word": "the", "start": 160.54, "end": 160.62},
                    {"word": "fear", "start": 160.72, "end": 161.24},
                ],
            },
            {
                "text": "Standing still",
                "style": "verse",
                "start": 166.48,
                "end": 167.5,
                "words": [{"word": "Standing", "start": 166.48, "end": 166.8}],
            },
        ]
        audio_activity = {
            (0, 2): {"active": True, "voiced_ratio": 1.0},
            ("tail", 0): {
                "active": True,
                "voiced_ratio": 1.0,
                "start_s": 161.24,
                "end_s": 166.48,
                "duration_s": 5.24,
            },
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["tail"]["classification"], "probable_unwritten_vowel_extension")
        self.assertEqual(timing["tail"]["audio_evidence"]["end_s"], 166.48)
        self.assertEqual(timing["tail"]["structural_tail_classification"], "instrumental_pause")
        self.assertEqual(
            timing["tail"]["review_flags"],
            ["structural_pause_overridden_by_audio_tail", "long_structural_pause_audio_extension"],
        )

    def test_audio_backed_timing_flags_moderate_tail_after_fear_for_review_only(self):
        lines = [
            {
                "text": "Past the fear",
                "style": "verse",
                "start": 40.0,
                "end": 40.92,
                "words": [
                    {"word": "Past", "start": 40.0, "end": 40.22},
                    {"word": "the", "start": 40.28, "end": 40.36},
                    {"word": "fear", "start": 40.56, "end": 40.92},
                ],
            },
            {
                "text": "Blinded by the hate",
                "style": "verse",
                "start": 43.0,
                "end": 44.0,
                "words": [{"word": "Blinded", "start": 43.0, "end": 43.3}],
            },
        ]
        audio_activity = {
            (0, 2): {"active": True, "voiced_ratio": 0.70},
            ("tail", 0): {
                "active": True,
                "voiced_ratio": 0.62,
                "start_s": 40.92,
                "end_s": 42.20,
                "duration_s": 1.28,
            },
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["tail"]["classification"], "possible_lost_tail")
        self.assertEqual(timing["tail"]["recommended_fallback"], "manual_review_or_local_realign")
        self.assertNotIn(timing["tail"]["classification"], {"probable_unwritten_vowel_extension", "written_melisma_extension"})

    def test_audio_backed_timing_flags_false_long_tail_when_audio_is_inactive(self):
        lines = [
            {
                "text": "I must carry on",
                "style": "outro",
                "start": 362.78,
                "end": 378.86,
                "words": [
                    {"word": "I", "start": 362.78, "end": 362.83},
                    {"word": "must", "start": 368.86, "end": 369.38},
                    {"word": "carry", "start": 372.32, "end": 372.74},
                    {"word": "on", "start": 372.78, "end": 378.86},
                ],
            }
        ]
        audio_activity = {
            (0, 3): {"active": False, "voiced_ratio": 0.09, "start_s": 372.78, "end_s": 378.86},
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["tail"]["classification"], "false_long_tail")
        self.assertEqual(timing["tail"]["recommended_fallback"], "trim_to_last_active_vocal")

    def test_audio_backed_timing_does_not_preserve_long_tail_when_audio_is_inactive(self):
        lines = [
            {
                "text": "I won't fall",
                "style": "outro",
                "start": 288.22,
                "end": 290.36,
                "words": [
                    {"word": "I", "start": 287.80, "end": 287.86},
                    {"word": "won't", "start": 288.00, "end": 288.18},
                    {"word": "fall", "start": 288.22, "end": 290.36},
                ],
            }
        ]
        audio_activity = {
            (0, 2): {
                "active": False,
                "voiced_ratio": 0.444,
                "start_s": 288.22,
                "end_s": 290.36,
                "duration_s": 2.14,
            },
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["tail"]["classification"], "false_long_tail")
        self.assertEqual(timing["tail"]["recommended_fallback"], "trim_to_last_active_vocal")
        self.assertEqual(timing["tail"]["audio_evidence"]["voiced_ratio"], 0.444)

    def test_audio_backed_timing_flags_unwritten_interline_melisma(self):
        lines = [
            {
                "text": "I won't fall",
                "style": "outro",
                "start": 294.18,
                "end": 298.64,
                "words": [
                    {"word": "I", "start": 294.18, "end": 294.23},
                    {"word": "won't", "start": 294.24, "end": 294.52},
                    {"word": "fall", "start": 294.70, "end": 298.64},
                ],
            },
            {
                "text": "I must carry on",
                "style": "outro",
                "start": 300.22,
                "end": 307.38,
                "words": [{"word": "I", "start": 300.22, "end": 300.27}],
            },
        ]
        audio_activity = {
            (0, 2): {"active": True, "voiced_ratio": 1.0},
            ("tail", 0): {
                "active": True,
                "voiced_ratio": 0.88,
                "start_s": 298.64,
                "end_s": 300.12,
                "duration_s": 1.48,
            },
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]
        summary = summarize_audio_backed_timing([timing])

        self.assertEqual(timing["tail"]["classification"], "unwritten_interline_melisma")
        self.assertEqual(timing["tail"]["recommended_fallback"], "flag_review_or_create_extension_bar")
        self.assertEqual(
            timing["tail"]["sound_suggestion"],
            {
                "sound_type": "unwritten_vocal_melisma",
                "suggested_caption": "[vocalizacao]",
                "suggested_user_action": "review_or_add_non_lyric_vocal_caption",
            },
        )
        self.assertEqual(summary["tails"]["unwritten_interline_melisma"], 1)

    def test_audio_backed_timing_marks_backing_vocal_drift_without_auto_fix(self):
        lines = [
            {
                "text": "Lights go low",
                "style": "bridge",
                "words": [
                    {"word": "Lights", "start": 223.28, "end": 227.24},
                    {"word": "go", "start": 232.52, "end": 232.64},
                    {"word": "low", "start": 233.12, "end": 233.68},
                ],
            }
        ]
        audio_activity = {
            (0, 0): {"active": True, "voiced_ratio": 1.0},
            (0, 1): {"active": True, "voiced_ratio": 0.95},
            (0, 2): {"active": True, "voiced_ratio": 0.95},
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["line_classification"], "review_only_backing_or_drift")
        self.assertEqual(timing["recommended_fallback"], "manual_review_or_local_realign")
        self.assertEqual(
            timing["sound_suggestion"],
            {
                "sound_type": "possible_backing_or_alignment_issue",
                "suggested_caption": "[revisar vocal/alinhamento]",
                "suggested_user_action": "review_backing_vocal_or_local_realign",
            },
        )

    def test_audio_backed_timing_prefers_alignment_hole_over_backing_caption(self):
        lines = [
            {
                "text": "sealed in the tomb",
                "style": "verse",
                "words": [
                    {"word": "sealed", "start": 120.0, "end": 120.34},
                    {"word": "in", "start": 120.42, "end": 120.52},
                    {"word": "the", "start": 120.60, "end": 120.70},
                    {"word": "tomb", "start": 123.20, "end": 123.42},
                ],
            }
        ]
        audio_activity = {
            (0, 0): {"active": True, "voiced_ratio": 0.95},
            (0, 3): {"active": True, "voiced_ratio": 0.90},
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["line_classification"], "review_only_backing_or_drift")
        self.assertEqual(timing["diagnostic_tags"], ["final_word_after_alignment_hole"])
        self.assertEqual(
            timing["sound_suggestion"],
            {
                "sound_type": "alignment_hole",
                "suggested_caption": "",
                "suggested_user_action": "review_local_realign",
            },
        )

    def test_audio_backed_timing_prefers_entry_drift_over_backing_caption(self):
        lines = [
            {
                "text": "Blinded by the hate",
                "style": "verse",
                "start": 150.0,
                "end": 153.0,
                "words": [
                    {"word": "Blinded", "start": 150.0, "end": 150.5},
                    {"word": "hate", "start": 150.90, "end": 153.0},
                ],
            },
            {
                "text": "I'm taking back my fate",
                "style": "verse",
                "start": 152.78,
                "end": 155.0,
                "words": [
                    {"word": "I'm", "start": 152.78, "end": 152.92},
                    {"word": "taking", "start": 154.40, "end": 154.72},
                ],
            },
        ]
        audio_activity = {
            (1, 0): {"active": True, "voiced_ratio": 0.95},
            (1, 1): {"active": True, "voiced_ratio": 0.95},
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[1]

        self.assertEqual(timing["line_classification"], "review_only_backing_or_drift")
        self.assertEqual(timing["diagnostic_tags"], ["early_next_line_entry_drift"])
        self.assertEqual(
            timing["sound_suggestion"],
            {
                "sound_type": "alignment_drift",
                "suggested_caption": "",
                "suggested_user_action": "move_line_start_later_or_review_previous_tail",
            },
        )

    def test_audio_backed_timing_marks_short_first_word_before_bad_gap_as_entry_drift(self):
        lines = [
            {
                "text": "I'm taking back my fate",
                "style": "verse",
                "start": 84.76,
                "end": 89.18,
                "words": [
                    {"word": "I'm", "start": 84.76, "end": 84.92},
                    {"word": "taking", "start": 87.94, "end": 88.20},
                    {"word": "back", "start": 88.32, "end": 88.68},
                    {"word": "my", "start": 88.86, "end": 88.91},
                    {"word": "fate", "start": 88.96, "end": 89.18},
                ],
            }
        ]
        audio_activity = {
            (0, 0): {"active": True, "voiced_ratio": 0.95},
            (0, 1): {"active": True, "voiced_ratio": 0.95},
            (0, 2): {"active": True, "voiced_ratio": 0.95},
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["line_classification"], "review_only_backing_or_drift")
        self.assertEqual(timing["diagnostic_tags"], ["early_next_line_entry_drift"])
        self.assertEqual(timing["sound_suggestion"]["sound_type"], "alignment_drift")

    def test_audio_backed_summary_counts_audio_supported_classes(self):
        timings = [
            {
                "inter_word_gaps": [],
                "vocal_periods": [{"classification": "melisma"}],
                "tail": {"classification": "tail_melisma"},
            },
            {
                "inter_word_gaps": [],
                "vocal_periods": [],
                "tail": {"classification": "probable_unwritten_vowel_extension"},
            },
        ]

        summary = summarize_audio_backed_timing(timings)

        self.assertEqual(summary["vocal_periods"]["melisma"], 1)
        self.assertEqual(summary["tails"]["tail_melisma"], 1)
        self.assertEqual(summary["tails"]["probable_unwritten_vowel_extension"], 1)

    def test_apply_audio_backed_tail_extensions_extends_only_confirmed_final_word(self):
        lines = [
            {
                "text": "About to snap",
                "start": 69.82,
                "end": 70.90,
                "style": "prechorus",
                "words": [
                    {"word": "About", "start": 69.82, "end": 70.44},
                    {"word": "to", "start": 70.52, "end": 70.58},
                    {"word": "snap", "start": 70.72, "end": 70.90},
                ],
            },
            {
                "text": "So burn it all",
                "start": 76.24,
                "end": 78.82,
                "style": "chorus",
                "words": [{"word": "So", "start": 76.24, "end": 76.34}],
            },
        ]
        timings = [
            {
                "tail": {
                    "classification": "probable_unwritten_vowel_extension",
                    "word_index": 2,
                    "audio_evidence": {"end_s": 76.20, "voiced_ratio": 0.95},
                }
            },
            {"tail": {"classification": "none"}},
        ]

        extended = apply_audio_backed_tail_extensions(lines, timings)

        self.assertEqual(lines[0]["words"][2]["end"], 70.90)
        self.assertEqual(extended[0]["words"][2]["end"], 76.20)
        self.assertEqual(extended[0]["end"], 76.20)
        self.assertEqual(extended[0]["words"][2]["audio_extension"]["source"], "vocals.wav")

    def test_apply_audio_backed_tail_extensions_extends_written_melisma(self):
        lines = [
            {
                "text": "Hmmmmm",
                "start": 12.74,
                "end": 13.18,
                "style": "intro",
                "words": [{"word": "Hmmmmm", "start": 12.74, "end": 13.18}],
            }
        ]
        timings = [
            {
                "tail": {
                    "classification": "written_melisma_extension",
                    "word_index": 0,
                    "audio_evidence": {"end_s": 16.20, "voiced_ratio": 0.90},
                }
            }
        ]

        extended = apply_audio_backed_tail_extensions(lines, timings)

        self.assertEqual(extended[0]["words"][0]["end"], 16.20)
        self.assertEqual(extended[0]["end"], 16.20)
        self.assertEqual(extended[0]["words"][0]["audio_extension"]["classification"], "written_melisma_extension")

    def test_apply_audio_backed_tail_extensions_skips_review_only_lines(self):
        lines = [
            {
                "text": "Lights go low",
                "start": 223.28,
                "end": 233.68,
                "style": "bridge",
                "words": [
                    {"word": "Lights", "start": 223.28, "end": 227.24},
                    {"word": "go", "start": 232.52, "end": 232.64},
                    {"word": "low", "start": 233.12, "end": 233.68},
                ],
            }
        ]
        timings = [
            {
                "line_classification": "review_only_backing_or_drift",
                "tail": {
                    "classification": "probable_unwritten_vowel_extension",
                    "word_index": 2,
                    "audio_evidence": {"end_s": 234.80, "voiced_ratio": 0.91},
                },
            }
        ]

        extended = apply_audio_backed_tail_extensions(lines, timings)

        self.assertEqual(extended[0]["words"][2]["end"], 233.68)
        self.assertNotIn("audio_extension", extended[0]["words"][2])

    def test_apply_audio_backed_tail_extensions_trims_false_long_tail_to_word_start_plus_minimum(self):
        lines = [
            {
                "text": "I must carry on",
                "start": 362.78,
                "end": 378.86,
                "style": "outro",
                "words": [
                    {"word": "I", "start": 362.78, "end": 362.83},
                    {"word": "must", "start": 368.86, "end": 369.38},
                    {"word": "carry", "start": 372.32, "end": 372.74},
                    {"word": "on", "start": 372.78, "end": 378.86},
                ],
            }
        ]
        timings = [
            {
                "tail": {
                    "classification": "false_long_tail",
                    "word_index": 3,
                    "audio_evidence": {"voiced_ratio": 0.09},
                }
            }
        ]

        adjusted = apply_audio_backed_tail_extensions(lines, timings)

        self.assertLess(adjusted[0]["words"][3]["end"], 378.86)
        self.assertGreaterEqual(adjusted[0]["words"][3]["end"], 373.18)
        self.assertEqual(adjusted[0]["words"][3]["audio_trim"]["classification"], "false_long_tail")

    def test_bad_gap_is_preserved_in_karaoke_text(self):
        text = _build_karaoke_text(
            [
                {"word": "It", "start": 236.98, "end": 237.04},
                {"word": "calls", "start": 238.60, "end": 238.98},
                {"word": "my", "start": 239.08, "end": 239.74},
                {"word": "name", "start": 242.04, "end": 242.36},
            ],
            line_start_ms=236980,
            effect="highlight",
            line_style="bridge",
        )

        self.assertIn("\\k154", text)
        self.assertIn("\\k230", text)
        self.assertNotIn("\\kf162}It", text)
        self.assertNotIn("\\kf296}my", text)

    def test_only_small_gaps_are_absorbed_by_renderer(self):
        self.assertTrue(gap_should_be_absorbed({"classification": "small_gap"}))
        self.assertFalse(gap_should_be_absorbed({"classification": "breath_gap"}))
        self.assertFalse(gap_should_be_absorbed({"classification": "bad_gap"}))

    def test_timing_summary_counts_gaps_and_tail_melismas(self):
        lines = [
            {
                "style": "bridge",
                "words": [
                    {"word": "my", "start": 239.08, "end": 239.74},
                    {"word": "name", "start": 242.04, "end": 242.36},
                ],
            },
            {
                "style": "outro",
                "words": [
                    {"word": "I", "start": 294.18, "end": 294.23},
                    {"word": "fall", "start": 294.70, "end": 298.64},
                ],
            },
        ]

        summary = summarize_timing_layers(lines)

        self.assertEqual(summary["inter_word_gaps"]["bad_gap"], 1)
        self.assertEqual(summary["inter_word_gaps"]["breath_gap"], 1)
        self.assertEqual(summary["tails"]["tail_vowel_extension"], 1)
        self.assertEqual(summary["vocal_periods"]["vowel_extension"], 1)

    def test_short_final_word_before_long_pause_is_possible_lost_tail(self):
        lines = [
            {
                "text": "About to snap",
                "style": "prechorus",
                "words": [
                    {"word": "About", "start": 69.82, "end": 70.44},
                    {"word": "to", "start": 70.52, "end": 70.58},
                    {"word": "snap", "start": 70.72, "end": 70.90},
                ],
            },
            {
                "text": "So burn it all",
                "style": "chorus",
                "start": 76.24,
                "words": [{"word": "So", "start": 76.24, "end": 76.34}],
            },
            {
                "text": "About to snap",
                "style": "prechorus",
                "words": [
                    {"word": "About", "start": 274.48, "end": 275.22},
                    {"word": "to", "start": 275.26, "end": 275.31},
                    {"word": "snap", "start": 275.42, "end": 282.02},
                ],
            },
        ]

        known_tail_melisma_lines = {"about to snap"}
        timing = classify_line_timing(
            lines[0],
            lines[1],
            known_tail_melisma_lines=known_tail_melisma_lines,
        )
        summary = summarize_timing_layers(lines)

        self.assertEqual(timing["tail"]["classification"], "possible_lost_tail")
        self.assertEqual(summary["tails"]["possible_lost_tail"], 1)

    def test_diagnostics_marks_possible_lost_tail_as_medium_confidence_with_fallback(self):
        lines = [
            {
                "text": "About to snap",
                "style": "prechorus",
                "words": [
                    {"word": "About", "start": 69.82, "end": 70.44},
                    {"word": "to", "start": 70.52, "end": 70.58},
                    {"word": "snap", "start": 70.72, "end": 70.90},
                ],
            },
            {
                "text": "So burn it all",
                "style": "chorus",
                "start": 76.24,
                "words": [{"word": "So", "start": 76.24, "end": 76.34}],
            },
            {
                "text": "About to snap",
                "style": "prechorus",
                "words": [
                    {"word": "About", "start": 274.48, "end": 275.22},
                    {"word": "to", "start": 275.26, "end": 275.31},
                    {"word": "snap", "start": 275.42, "end": 282.02},
                ],
            },
        ]

        diagnostics = build_timing_diagnostics(lines)
        lost_tail = next(event for event in diagnostics["events"] if event["classification"] == "possible_lost_tail")

        self.assertEqual(lost_tail["confidence"], "medium")
        self.assertIn("same_line_has_confirmed_tail", lost_tail["evidence"])
        self.assertEqual(lost_tail["recommended_fallback"], "extend_final_vowel_candidate")

    def test_diagnostics_marks_bad_gap_with_vocal_period_as_suspect_vocal_drift(self):
        lines = [
            {
                "text": "Lights go low",
                "style": "bridge",
                "words": [
                    {"word": "Lights", "start": 223.28, "end": 227.24},
                    {"word": "go", "start": 232.52, "end": 232.64},
                    {"word": "low", "start": 233.12, "end": 233.68},
                ],
            }
        ]

        diagnostics = build_timing_diagnostics(lines)

        self.assertIn("suspect_vocal_drift", diagnostics["summary"])
        event = next(event for event in diagnostics["events"] if event["classification"] == "suspect_vocal_drift")
        self.assertEqual(event["confidence"], "high")
        self.assertEqual(event["recommended_fallback"], "local_realignment_review")

    def test_diagnostics_marks_final_word_after_alignment_hole(self):
        lines = [
            {
                "text": "sealed in the tomb",
                "style": "verse",
                "words": [
                    {"word": "sealed", "start": 120.0, "end": 120.34},
                    {"word": "in", "start": 120.42, "end": 120.52},
                    {"word": "the", "start": 120.60, "end": 120.70},
                    {"word": "tomb", "start": 123.20, "end": 123.42},
                ],
            }
        ]

        diagnostics = build_timing_diagnostics(lines)

        event = next(event for event in diagnostics["events"] if event["classification"] == "final_word_after_alignment_hole")
        self.assertEqual(event["confidence"], "high")
        self.assertEqual(event["recommended_fallback"], "review_local_realignment")

    def test_diagnostics_marks_previous_tail_stolen_by_next_line_drift(self):
        lines = [
            {
                "text": "Blinded by the hate",
                "style": "verse",
                "start": 150.0,
                "end": 153.0,
                "words": [
                    {"word": "Blinded", "start": 150.0, "end": 150.5},
                    {"word": "by", "start": 150.56, "end": 150.66},
                    {"word": "the", "start": 150.72, "end": 150.82},
                    {"word": "hate", "start": 150.90, "end": 153.0},
                ],
            },
            {
                "text": "I'm taking back my fate",
                "style": "verse",
                "start": 152.78,
                "end": 155.0,
                "words": [
                    {"word": "I'm", "start": 152.78, "end": 152.92},
                    {"word": "taking", "start": 153.10, "end": 153.42},
                ],
            },
        ]

        diagnostics = build_timing_diagnostics(lines)

        previous = next(event for event in diagnostics["events"] if event["classification"] == "previous_tail_likely_stolen_by_next_line")
        current = next(event for event in diagnostics["events"] if event["classification"] == "early_next_line_entry_drift")
        self.assertEqual(previous["recommended_fallback"], "extend_previous_tail_or_move_next_line_start_later")
        self.assertEqual(current["details"]["early_word"], "I'm")

    def test_audio_backed_timing_marks_possible_backing_vocal_not_in_lyrics(self):
        lines = [
            {
                "text": "Lights go low",
                "style": "bridge",
                "words": [
                    {"word": "Lights", "start": 223.28, "end": 227.24},
                    {"word": "go", "start": 232.52, "end": 232.64},
                    {"word": "low", "start": 233.12, "end": 233.68},
                ],
            }
        ]
        audio_activity = {
            (0, 0): {"active": True, "voiced_ratio": 1.0},
            (0, 1): {"active": True, "voiced_ratio": 0.95},
            (0, 2): {"active": True, "voiced_ratio": 0.95},
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["line_classification"], "review_only_backing_or_drift")
        self.assertEqual(timing["diagnostic_tags"], ["possible_backing_vocal_not_in_lyrics"])

    def test_audio_backed_timing_flags_line_with_no_vocal_evidence_for_review(self):
        lines = [
            {
                "text": "for that",
                "style": "verse",
                "words": [
                    {"word": "for", "start": 346.70, "end": 346.82},
                    {"word": "that", "start": 346.86, "end": 347.14},
                ],
            }
        ]
        audio_activity = {
            (0, 0): {"active": False, "voiced_ratio": 0.0},
            (0, 1): {"active": False, "voiced_ratio": 0.4},
        }

        timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

        self.assertEqual(timing["line_classification"], "review_only_low_vocal_evidence")
        self.assertEqual(timing["diagnostic_tags"], ["line_low_vocal_evidence"])
        self.assertEqual(timing["recommended_fallback"], "review_line_alignment_or_silence")

    def test_diagnostics_marks_instrumental_pause_as_high_confidence_preserve_gap(self):
        lines = [
            {
                "text": "Still",
                "style": "intro",
                "words": [{"word": "Still", "start": 24.48, "end": 24.78}],
            },
            {
                "text": "Breathing",
                "style": "verse",
                "start": 37.42,
                "words": [{"word": "Breathing", "start": 37.42, "end": 38.08}],
            },
        ]

        diagnostics = build_timing_diagnostics(lines)
        event = next(event for event in diagnostics["events"] if event["classification"] == "instrumental_pause")

        self.assertEqual(event["confidence"], "high")
        self.assertEqual(event["recommended_fallback"], "preserve_silence_gap")


class TimingLayersEdgeCaseTests(unittest.TestCase):
    def test_build_timing_diagnostics_empty_lines(self):
        result = build_timing_diagnostics([])
        self.assertIsInstance(result, dict)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["summary"], {})

    def test_build_timing_diagnostics_single_word_line(self):
        lines = [
            {
                "text": "Hello",
                "style": "verse",
                "words": [{"word": "Hello", "start": 1.0, "end": 1.4}],
            }
        ]
        result = build_timing_diagnostics(lines)
        self.assertIsInstance(result, dict)
        self.assertIn("events", result)
        self.assertIn("summary", result)


if __name__ == "__main__":
    unittest.main()
