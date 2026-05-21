import unittest

from scripts.common.validation import find_timestamp_errors, normalize_words


class TimestampValidationTests(unittest.TestCase):
    def test_find_timestamp_errors_detects_inverted_word(self):
        words = [{"word": "of", "start": 2.0, "end": 1.5}]

        errors = find_timestamp_errors(words)

        self.assertEqual(len(errors), 1)
        self.assertIn("of", errors[0])

    def test_repair_word_timestamps_fixes_inverted_word_inside_segment(self):
        words = [
            {"word": "light", "start": 1.0, "end": 1.4},
            {"word": "of", "start": 2.0, "end": 1.5},
            {"word": "fire", "start": 2.2, "end": 2.8},
        ]

        repaired = normalize_words(words, segment_start=1.0, segment_end=3.0)

        self.assertLess(repaired[1]["start"], repaired[1]["end"])
        self.assertLessEqual(repaired[0]["end"], repaired[1]["start"])
        self.assertLessEqual(repaired[1]["end"], repaired[2]["start"])


if __name__ == "__main__":
    unittest.main()
