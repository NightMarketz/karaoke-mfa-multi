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


    def test_find_timestamp_errors_flags_word_exceeding_segment_end(self):
        words = [{"word": "hello", "start": 0.5, "end": 2.5}]
        errors = find_timestamp_errors(words, segment_end=2.0)
        self.assertEqual(len(errors), 1)
        self.assertIn("exceeds segment boundary", errors[0])

    def test_find_timestamp_errors_allows_word_within_segment_end(self):
        words = [{"word": "hello", "start": 0.5, "end": 1.8}]
        errors = find_timestamp_errors(words, segment_end=2.0)
        self.assertEqual(errors, [])

    def test_find_timestamp_errors_segment_end_none_skips_boundary_check(self):
        words = [{"word": "hello", "start": 0.5, "end": 9999.0}]
        errors = find_timestamp_errors(words, segment_end=None)
        self.assertEqual(errors, [])

    def test_find_timestamp_errors_segment_end_with_tolerance(self):
        words = [{"word": "hello", "start": 0.5, "end": 2.03}]
        errors = find_timestamp_errors(words, segment_end=2.0, overlap_tolerance_s=0.05)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
