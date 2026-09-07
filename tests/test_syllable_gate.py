import unittest

from scripts import syllables


class SyllabificationPlausibilityGateTests(unittest.TestCase):
    def test_more_groups_than_orthographic_vowels_is_rejected(self):
        # "Wolf" (one vowel run) getting 5 phone groups = phoneme bleed in a fast
        # rap line. Not plausible → render whole word, not 5 fake syllables.
        self.assertFalse(syllables.syllabification_is_plausible("Wolf", 5, 0.24))
        self.assertFalse(syllables.syllabification_is_plausible("red", 2, 0.17))

    def test_too_short_to_hold_the_syllables_is_rejected(self):
        # Two real syllables need >= 2*80ms; a 100ms span cannot show them.
        self.assertFalse(syllables.syllabification_is_plausible("under", 2, 0.10))

    def test_plausible_multisyllable_word_is_kept(self):
        self.assertTrue(syllables.syllabification_is_plausible("coração", 3, 0.80))
        self.assertTrue(syllables.syllabification_is_plausible("beneath", 2, 0.90))

    def test_single_group_always_plausible(self):
        self.assertTrue(syllables.syllabification_is_plausible("Wolf", 1, 0.05))


class FastWordRendersWholeTests(unittest.TestCase):
    def _word(self, text, span, groups):
        # build `groups` vowel nuclei spread across the span (simulates bled phones)
        phones = []
        step = span / (groups * 2)
        t = 0.0
        for i in range(groups):
            phones.append({"ph": "K", "start": round(t, 4), "end": round(t + step, 4)})
            t += step
            phones.append({"ph": "AA", "start": round(t, 4), "end": round(t + step, 4)})
            t += step
        return {"word": text, "start": 0.0, "end": span, "source": "ctc_forced+hubertfa", "phonemes": phones}

    def test_fast_word_with_bled_phonemes_renders_one_segment(self):
        # "Wolf" span 0.24s but 5 vowel nuclei → one whole-word segment.
        seg = syllables.split_word_syllables(self._word("Wolf", 0.24, 5))
        self.assertEqual(len(seg), 1)
        self.assertEqual(seg[0]["text"], "Wolf")
        self.assertEqual(seg[0]["end"], 0.24)

    def test_sustained_multisyllable_word_still_splits(self):
        # "coração" 0.8s with 3 nuclei → still three syllables.
        seg = syllables.split_word_syllables(self._word("coração", 0.8, 3))
        self.assertEqual(len(seg), 3)


if __name__ == "__main__":
    unittest.main()
