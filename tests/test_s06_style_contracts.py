"""Style-contract tests for s06_generate_ass internal helpers.

Guards the colour-parsing roundtrip, ASS structural validation, and
metrics extraction that every render path depends on.
"""

import unittest

from tests._optional_imports import import_or_skip

import_or_skip("numpy")
import_or_skip("pysubs2")

from scripts.s06_generate_ass import (
    _ass_metrics,
    _build_karaoke_text,
    _c,
    _parse_color,
    _validate_ass,
)


class SyllableKaraokeTextTests(unittest.TestCase):
    def test_long_word_with_syllables_emits_multiple_kf(self):
        # A sustained word carrying two timed syllables must render 2+ \kf.
        word = {
            "word": "aah",
            "id": "L001_W001",
            "start": 10.0,
            "end": 11.6,
            "syllables": [
                {"text": "aa", "karaoke_start": 10.0, "karaoke_end": 10.8, "confidence": 0.9},
                {"text": "ah", "karaoke_start": 10.8, "karaoke_end": 11.6, "confidence": 0.9},
            ],
        }
        text = _build_karaoke_text([word], line_start_ms=10000, effect="highlight")
        self.assertGreaterEqual(text.count("\\kf"), 2)

    def test_short_word_without_phonemes_stays_single_kf(self):
        # No regression: a short word with no syllable data gets exactly one \kf.
        word = {"word": "go", "id": "L001_W001", "start": 1.0, "end": 1.3}
        text = _build_karaoke_text([word], line_start_ms=1000, effect="highlight")
        self.assertEqual(text.count("\\kf"), 1)

    def test_explicit_highlight_segments_override_syllables(self):
        # Manual boundary edit (highlight_segments) wins over derived syllables.
        word = {
            "word": "aah",
            "id": "L001_W001",
            "start": 10.0,
            "end": 11.6,
            "syllables": [
                {"text": "aah", "karaoke_start": 10.0, "karaoke_end": 11.6, "confidence": 0.9},
            ],
            "highlight_segments": [
                {"id": "m1", "text": "aa", "start": 10.0, "end": 10.5, "role": "syllable"},
                {"id": "m2", "text": "ah", "start": 10.5, "end": 11.0, "role": "syllable"},
                {"id": "m3", "text": "h", "start": 11.0, "end": 11.6, "role": "syllable"},
            ],
        }
        text = _build_karaoke_text([word], line_start_ms=10000, effect="highlight")
        self.assertGreaterEqual(text.count("\\kf"), 3)


class ParseColorTests(unittest.TestCase):
    def test_parse_white_returns_255_255_255(self):
        r, g, b = _parse_color("&H00FFFFFF")
        self.assertEqual((255, 255, 255), (r, g, b))

    def test_parse_black_returns_0_0_0(self):
        r, g, b = _parse_color("&H00000000")
        self.assertEqual((0, 0, 0), (r, g, b))

    def test_parse_pure_red_bgr(self):
        # R=255, G=0, B=0 → ASS BGR bytes: 000000FF → &H000000FF
        r, g, b = _parse_color("&H000000FF")
        self.assertEqual((255, 0, 0), (r, g, b))

    def test_parse_pure_blue_bgr(self):
        # B=255, G=0, R=0 → ASS BGR bytes: 00FF0000 → &H00FF0000
        r, g, b = _parse_color("&H00FF0000")
        self.assertEqual((0, 0, 255), (r, g, b))

    def test_parse_color_ignores_alpha_channel(self):
        # AA=80 (semi-transparent), same RGB as white
        r, g, b = _parse_color("&H80FFFFFF")
        self.assertEqual((255, 255, 255), (r, g, b))

    def test_parse_color_roundtrip_with_c_helper(self):
        # Build a color with _c() then parse it back — RGB should survive.
        original = (100, 150, 200)
        encoded = _c(*original)
        r, g, b = _parse_color(encoded)
        self.assertEqual(original, (r, g, b))

    def test_parse_color_raises_on_too_short_string(self):
        with self.assertRaises((ValueError, IndexError)):
            _parse_color("&H00FF")

    def test_parse_color_raises_on_non_hex(self):
        with self.assertRaises(ValueError):
            _parse_color("&H00GGGGGG")


class ValidateAssTests(unittest.TestCase):
    MINIMAL_VALID_ASS = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n\n"
        "[V4+ Styles]\n"
        "Format: Name\n"
        "Style: Verse\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Text\n"
        "\nDialogue: 0,0:00:01.00,0:00:02.00,Verse,,{\\kf80}hello\n"
    )

    def test_valid_ass_returns_no_errors(self):
        errors = _validate_ass(self.MINIMAL_VALID_ASS)
        self.assertEqual([], errors)

    def test_missing_script_info_is_flagged(self):
        content = self.MINIMAL_VALID_ASS.replace("[Script Info]", "[WRONG]")
        errors = _validate_ass(content)
        self.assertTrue(any("Script Info" in e for e in errors), errors)

    def test_missing_v4_styles_is_flagged(self):
        content = self.MINIMAL_VALID_ASS.replace("[V4+ Styles]", "[WRONG]")
        errors = _validate_ass(content)
        self.assertTrue(any("V4+" in e for e in errors), errors)

    def test_missing_events_section_is_flagged(self):
        content = self.MINIMAL_VALID_ASS.replace("[Events]", "[WRONG]")
        errors = _validate_ass(content)
        self.assertTrue(any("Events" in e for e in errors), errors)

    def test_missing_kf_tags_is_flagged(self):
        content = self.MINIMAL_VALID_ASS.replace("\\kf", "\\k")
        errors = _validate_ass(content)
        self.assertTrue(any("kf" in e for e in errors), errors)

    def test_no_dialogue_lines_is_flagged(self):
        # Remove the Dialogue line entirely.
        content = "\n".join(
            line for line in self.MINIMAL_VALID_ASS.splitlines()
            if not line.startswith("Dialogue:")
        )
        errors = _validate_ass(content)
        self.assertTrue(any("Dialogue" in e or "dialogue" in e for e in errors), errors)

    def test_empty_string_reports_multiple_errors(self):
        errors = _validate_ass("")
        self.assertGreater(len(errors), 1)


class AssMetricsTests(unittest.TestCase):
    def test_metrics_counts_dialogue_and_kf(self):
        content = (
            "\nDialogue: line one {\\kf80}hello {\\kf60}world\n"
            "\nDialogue: line two {\\kf40}sing\n"
        )
        metrics = _ass_metrics(content)
        self.assertEqual(2, metrics["dialogue_count"])
        self.assertEqual(3, metrics["kf_count"])

    def test_metrics_returns_zero_for_empty(self):
        metrics = _ass_metrics("")
        self.assertEqual(0, metrics["dialogue_count"])
        self.assertEqual(0, metrics["kf_count"])

    def test_metrics_result_contains_expected_keys(self):
        metrics = _ass_metrics("\nDialogue: x {\\kf10}y\n")
        self.assertIn("dialogue_count", metrics)
        self.assertIn("kf_count", metrics)


if __name__ == "__main__":
    unittest.main()
