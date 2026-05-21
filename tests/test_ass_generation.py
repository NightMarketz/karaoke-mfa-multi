import unittest

from scripts.s06_generate_ass import PRESETS, _build_karaoke_text


class AssGenerationTests(unittest.TestCase):
    def test_build_karaoke_text_escapes_braces(self):
        text = _build_karaoke_text(
            [{"word": "{bad}", "start": 1.0, "end": 1.5}],
            line_start_ms=1000,
            effect="highlight",
        )

        self.assertNotIn("{bad}", text)
        self.assertIn("bad", text)

    def test_inverted_word_gets_minimum_duration(self):
        text = _build_karaoke_text(
            [{"word": "fast", "start": 2.0, "end": 1.9}],
            line_start_ms=1900,
            effect="highlight",
        )

        self.assertIn("\\kf8", text)

    def test_section_coded_preset_exists(self):
        self.assertIn("section-coded", PRESETS)
        self.assertIn("drop", PRESETS["section-coded"])


if __name__ == "__main__":
    unittest.main()
