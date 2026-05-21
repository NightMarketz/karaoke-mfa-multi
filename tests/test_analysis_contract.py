import unittest

from scripts.common.validation import find_word_coverage_errors
from scripts.s05_analyze import _validate_analysis


class AnalysisContractTests(unittest.TestCase):
    def test_line_missing_words_fails_even_when_not_first_line(self):
        data = {
            "lines": [
                {
                    "text": "hello",
                    "start": 1.0,
                    "end": 1.5,
                    "style": "verse",
                    "words": [{"word": "hello", "start": 1.0, "end": 1.5}],
                },
                {"text": "world", "start": 2.0, "end": 2.5, "style": "verse"},
            ]
        }

        errors = _validate_analysis(data)

        self.assertTrue(any("Line 1 missing key: 'words'" in error for error in errors))

    def test_line_with_inverted_timestamps_fails(self):
        data = {
            "lines": [
                {
                    "text": "bad",
                    "start": 2.0,
                    "end": 1.5,
                    "style": "verse",
                    "words": [{"word": "bad", "start": 2.0, "end": 1.5}],
                }
            ]
        }

        errors = _validate_analysis(data)

        self.assertTrue(any("end <= start" in error for error in errors))

    def test_line_boundaries_must_match_first_and_last_word(self):
        data = {
            "lines": [
                {
                    "text": "hello world",
                    "start": 0.9,
                    "end": 2.1,
                    "style": "verse",
                    "words": [
                        {"word": "hello", "start": 1.0, "end": 1.5},
                        {"word": "world", "start": 1.6, "end": 2.0},
                    ],
                }
            ]
        }

        errors = _validate_analysis(data)

        self.assertTrue(any("does not match first word" in error for error in errors))
        self.assertTrue(any("does not match last word" in error for error in errors))

    def test_repeated_word_coverage_compares_counts_not_plain_set(self):
        aligned = [{"word": "hello"}, {"word": "hello"}, {"word": "world"}]
        analysis = [{"word": "hello"}, {"word": "world"}]

        errors = find_word_coverage_errors(aligned, analysis)

        self.assertTrue(any("hello" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
