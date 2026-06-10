import unittest

from scripts.review_wizard.highlight_velocity import (
    _vowel_span,
    build_line_highlight_segments,
    build_word_highlight_segments,
)


class HighlightVelocityTests(unittest.TestCase):
    def test_short_word_remains_single_highlight_segment(self):
        segments = build_word_highlight_segments({"word": "to", "start": 10.0, "end": 10.18})

        self.assertEqual([segment["text"] for segment in segments], ["to"])
        self.assertEqual(segments[0]["start"], 10.0)
        self.assertEqual(segments[0]["end"], 10.18)
        self.assertEqual(segments[0]["role"], "normal")

    def test_long_word_slows_fill_on_vowel_nucleus(self):
        segments = build_word_highlight_segments({"word": "snap", "start": 275.42, "end": 282.02})

        self.assertEqual([segment["text"] for segment in segments], ["sn", "a", "p"])
        self.assertEqual(segments[0]["role"], "consonant_attack")
        self.assertEqual(segments[1]["role"], "sustained_vowel")
        self.assertEqual(segments[2]["role"], "consonant_release")
        self.assertEqual(segments[0]["start"], 275.42)
        self.assertEqual(segments[-1]["end"], 282.02)
        self.assertGreater(segments[1]["end"] - segments[1]["start"], 6.0)

    def test_explicit_highlight_segments_are_preserved_and_normalized(self):
        segments = build_word_highlight_segments(
            {
                "word": "oooohh",
                "start": 89.24,
                "end": 91.24,
                "highlight_segments": [
                    {"text": "oooo", "start": 89.24, "end": 90.7, "role": "melisma_sustain"},
                    {"text": "hh", "start": 90.7, "end": 91.24, "role": "release"},
                ],
            }
        )

        self.assertEqual([segment["text"] for segment in segments], ["oooo", "hh"])
        self.assertEqual(segments[0]["start"], 89.24)
        self.assertEqual(segments[-1]["end"], 91.24)
        self.assertEqual(segments[0]["source"], "explicit")


class HighlightVelocityEdgeCaseTests(unittest.TestCase):
    def test_vowel_span_no_vowels_returns_none(self):
        result = _vowel_span("bcdfg")
        self.assertIsNone(result)

    def test_vowel_span_single_vowel(self):
        result = _vowel_span("a")
        self.assertEqual(result, (0, 1))

    def test_build_line_highlight_segments_empty_words(self):
        result = build_line_highlight_segments([])
        self.assertEqual(result, [])

    def test_build_line_highlight_segments_assigns_word_index(self):
        words = [
            {"word": "hi", "start": 0.0, "end": 0.2},
            {"word": "there", "start": 0.3, "end": 0.6},
        ]
        result = build_line_highlight_segments(words)
        self.assertTrue(all("word_index" in seg for seg in result))
        word_indices = [seg["word_index"] for seg in result]
        self.assertIn(1, word_indices)
        self.assertIn(2, word_indices)


if __name__ == "__main__":
    unittest.main()
