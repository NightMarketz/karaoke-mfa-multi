import unittest

from scripts.review_wizard.text_prep import prepare_text_for_review


class ReviewWizardTextPrepTests(unittest.TestCase):
    def test_prepare_text_detects_sections_lines_words_and_basic_syllables(self):
        prepared, issues = prepare_text_for_review(
            "[Verse]\nCoração aberto\n[Chorus]\nAmor maior",
            language="pt",
        )

        payload = prepared.to_dict()

        self.assertEqual(prepared.language, "pt")
        self.assertEqual([section.label for section in prepared.sections], ["Verse", "Chorus"])
        self.assertEqual(payload["sections"][0]["lines"][0]["text"], "Coração aberto")
        self.assertEqual(payload["sections"][0]["lines"][0]["words"][0]["text"], "Coração")
        self.assertGreaterEqual(len(payload["sections"][0]["lines"][0]["words"][0]["syllables"]), 2)
        self.assertEqual(issues, [])

    def test_prepare_text_creates_issue_for_long_line(self):
        long_line = " ".join(["palavra"] * 18)

        _, issues = prepare_text_for_review(long_line, language="pt")

        self.assertEqual(issues[0].type, "text_line_too_long")
        self.assertEqual(issues[0].suggested_action, "split_line")

    def test_prepare_text_keeps_display_text_when_contraction_is_likely(self):
        prepared, issues = prepare_text_for_review("para amor", language="pt")

        line = prepared.sections[0].lines[0]

        self.assertEqual(line.text, "para amor")
        self.assertTrue(any(issue.type == "possible_contraction" for issue in issues))


if __name__ == "__main__":
    unittest.main()
