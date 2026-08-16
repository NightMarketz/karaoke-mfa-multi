import unittest

from scripts import syllables


def _word(text, phones, **extra):
    word = {"word": text, "start": phones[0]["start"] if phones else 0.0,
            "end": phones[-1]["end"] if phones else 0.5, "phonemes": phones}
    word.update(extra)
    return word


# "coração" → co / ra / ção : three ARPAbet vowel nuclei (OW, AH, AW).
CORACAO_PHONES = [
    {"ph": "K", "start": 0.00, "end": 0.05},
    {"ph": "OW", "start": 0.05, "end": 0.20},
    {"ph": "R", "start": 0.20, "end": 0.25},
    {"ph": "AH", "start": 0.25, "end": 0.45},
    {"ph": "S", "start": 0.45, "end": 0.50},
    {"ph": "AW", "start": 0.50, "end": 0.80},
]


class SyllableGroupingTests(unittest.TestCase):
    def test_groups_phonemes_by_vowel_nucleus(self):
        groups = syllables.phone_syllable_groups(
            [{"phone": p["ph"], "start": p["start"], "end": p["end"]} for p in CORACAO_PHONES]
        )
        self.assertEqual(len(groups), 3)
        self.assertEqual(
            [[ph["phone"] for ph in g] for g in groups],
            [["K", "OW"], ["R", "AH"], ["S", "AW"]],
        )

    def test_split_word_produces_one_segment_per_nucleus(self):
        segments = syllables.split_word_syllables(_word("coração", CORACAO_PHONES))
        self.assertEqual([s["text"] for s in segments], ["co", "ra", "ção"])


class OrthographicSyllableTests(unittest.TestCase):
    def test_maximal_onset_keeps_digraphs_and_clusters_with_next_syllable(self):
        self.assertEqual(syllables.basic_text_syllables("breathing"), ["brea", "thing"])
        self.assertEqual(syllables.basic_text_syllables("hungry"), ["hun", "gry"])

    def test_single_consonant_goes_to_next_syllable(self):
        self.assertEqual(syllables.basic_text_syllables("coração"), ["co", "ra", "ção"])
        self.assertEqual(syllables.basic_text_syllables("mama"), ["ma", "ma"])

    def test_monosyllable_is_not_split(self):
        self.assertEqual(syllables.basic_text_syllables("skin"), ["skin"])
        self.assertEqual(syllables.basic_text_syllables("beast"), ["beast"])


class SyllableTimingTests(unittest.TestCase):
    def test_timing_comes_from_phonemes_and_covers_word_span(self):
        word = _word("coração", CORACAO_PHONES)
        segments = syllables.split_word_syllables(word)
        self.assertEqual(segments[0]["start"], 0.0)
        self.assertEqual(segments[-1]["end"], word["end"])
        # ordered, contiguous-or-forward, inside the word span
        for earlier, later in zip(segments, segments[1:]):
            self.assertLessEqual(earlier["end"], later["start"] + 1e-6)
        for seg in segments:
            self.assertGreaterEqual(seg["start"], word["start"] - 1e-6)
            self.assertLessEqual(seg["end"], word["end"] + 1e-6)

    def test_floor_extends_short_segment_without_exceeding_word_end(self):
        phones = [
            {"ph": "AA", "start": 10.00, "end": 10.02},   # 20ms — below the 80ms floor
            {"ph": "M", "start": 10.02, "end": 10.03},
            {"ph": "IY", "start": 10.03, "end": 10.50},
        ]
        word = {"word": "ami", "start": 10.0, "end": 10.5, "phonemes": phones}
        segments = syllables.split_word_syllables(word, min_segment_ms=80)
        self.assertEqual(len(segments), 2)
        self.assertGreaterEqual(round(segments[0]["end"] - segments[0]["start"], 4), 0.08)
        self.assertLessEqual(segments[-1]["end"], word["end"] + 1e-6)


class SyllableConfidenceTests(unittest.TestCase):
    def test_forced_mode_confidence_is_lower_than_hubertfa(self):
        forced = syllables.split_word_syllables(_word("coração", CORACAO_PHONES, source="ctc_forced"))
        native = syllables.split_word_syllables(_word("coração", CORACAO_PHONES, source="hubertfa"))
        self.assertLess(forced[0]["confidence"], native[0]["confidence"])

    def test_ctc_forced_lands_below_default_uncertain_threshold(self):
        forced = syllables.split_word_syllables(_word("coração", CORACAO_PHONES, source="ctc_forced"))
        self.assertTrue(all(s["confidence"] < 0.6 for s in forced))

    def test_ctc_forced_plus_hubertfa_is_reliable_after_positional_assignment(self):
        # s04 now attaches phonemes positionally, so ctc_forced+hubertfa carries
        # real intra-word timing and should clear the uncertain threshold.
        combined = syllables.split_word_syllables(
            _word("coração", CORACAO_PHONES, source="ctc_forced+hubertfa")
        )
        self.assertTrue(all(s["confidence"] >= 0.6 for s in combined))
        # ...but still below pure hubertfa (word span is CTC, not phoneme-derived).
        native = syllables.split_word_syllables(_word("coração", CORACAO_PHONES, source="hubertfa"))
        self.assertLess(combined[0]["confidence"], native[0]["confidence"])

    def test_low_confidence_flag_downgrades_further(self):
        base = syllables.split_word_syllables(_word("coração", CORACAO_PHONES, source="hubertfa"))
        flagged = syllables.split_word_syllables(
            _word("coração", CORACAO_PHONES, source="hubertfa", low_confidence=True)
        )
        self.assertLess(flagged[0]["confidence"], base[0]["confidence"])

    def test_fast_function_word_with_measured_timing_clears_review(self):
        # A 40ms sung "the" (measured by HubertFA) is genuinely fast, not a timing
        # error — it must NOT be flagged for review just for being short. This is
        # the syllable-queue pollution the fix removes.
        phones = [{"ph": "DH", "start": 5.00, "end": 5.02}, {"ph": "AH", "start": 5.02, "end": 5.04}]
        word = {"word": "the", "start": 5.0, "end": 5.04, "source": "ctc_forced+hubertfa", "phonemes": phones}
        seg = syllables.split_word_syllables(word)
        self.assertTrue(all(s["confidence"] >= 0.6 for s in seg), seg)

    def test_held_note_with_measured_timing_clears_review(self):
        # A 4-second sustained note (measured) is a normal vocal, not implausible.
        phones = [{"ph": "S", "start": 10.0, "end": 10.1}, {"ph": "OW", "start": 10.1, "end": 14.0}]
        word = {"word": "snap", "start": 10.0, "end": 14.0, "source": "ctc_forced+hubertfa", "phonemes": phones}
        seg = syllables.split_word_syllables(word)
        self.assertTrue(all(s["confidence"] >= 0.6 for s in seg), seg)

    def test_stale_ctc_probability_does_not_flag_measured_timing(self):
        # CTC probability 0 says nothing about HubertFA-measured timing.
        word = _word("coração", CORACAO_PHONES, source="ctc_forced+hubertfa", probability=0.0)
        seg = syllables.split_word_syllables(word)
        self.assertTrue(all(s["confidence"] >= 0.6 for s in seg), seg)

    def test_boundary_overshoot_alone_does_not_force_review(self):
        # CTC compressed the word so its HubertFA phone spills outside the word
        # span. That is a word-span sizing artifact, not a mis-split syllable the
        # reviewer can fix — measured timing keeps it out of the queue.
        phones = [{"ph": "AA", "start": 8.90, "end": 9.30}]  # spills past the tiny word
        word = {"word": "oh", "start": 9.0, "end": 9.05, "source": "ctc_forced+hubertfa", "phonemes": phones}
        seg = syllables.split_word_syllables(word)
        self.assertTrue(all(s["confidence"] >= 0.6 for s in seg), seg)

    def test_measured_timing_still_downgrades_on_low_confidence_flag(self):
        # The one thing that still surfaces a phone-backed word: a flagged
        # transcription (low_confidence) drops it under the review threshold.
        word = _word("coração", CORACAO_PHONES, source="ctc_forced+hubertfa", low_confidence=True)
        seg = syllables.split_word_syllables(word)
        self.assertTrue(any(s["confidence"] < 0.6 for s in seg), seg)


class SyllableFallbackTests(unittest.TestCase):
    def test_no_phonemes_yields_single_low_confidence_segment(self):
        word = {"word": "yeah", "start": 3.0, "end": 4.5, "phonemes": [], "source": "whisper_fallback"}
        segments = syllables.split_word_syllables(word)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["text"], "yeah")
        self.assertEqual(segments[0]["start"], 3.0)
        self.assertEqual(segments[0]["end"], 4.5)
        self.assertEqual(segments[0]["source"], syllables.DURATION_FALLBACK_SOURCE)
        self.assertLess(segments[0]["confidence"], 0.6)

    def test_inverted_phoneme_timing_falls_back_to_word(self):
        phones = [{"ph": "AA", "start": 1.0, "end": 0.5}]  # inverted → dropped
        word = {"word": "no", "start": 1.0, "end": 2.0, "phonemes": phones}
        segments = syllables.split_word_syllables(word)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["source"], syllables.DURATION_FALLBACK_SOURCE)


class SyllableRealDataRobustnessTests(unittest.TestCase):
    def test_duplicated_backwards_phoneme_run_is_dropped(self):
        # Some aligners emit each phone twice ("breathing" b r iy dh ih ng ×2);
        # the backwards duplicate block must be ignored (§8), not create ghost syllables.
        run = [
            {"ph": "B", "start": 37.47, "end": 37.49},
            {"ph": "R", "start": 37.49, "end": 37.65},
            {"ph": "IY", "start": 37.65, "end": 37.72},
            {"ph": "DH", "start": 37.72, "end": 37.77},
            {"ph": "IH", "start": 37.77, "end": 37.78},
            {"ph": "NG", "start": 37.78, "end": 38.08},
        ]
        word = {"word": "breathing", "start": 37.42, "end": 38.08,
                "source": "ctc_forced+hubertfa", "phonemes": run + run}
        segments = syllables.split_word_syllables(word)
        self.assertEqual(len(segments), 2)  # brea / thing — not 4

    def test_log_probability_does_not_zero_confidence(self):
        # probability stored as a log-prob (negative) must be ignored, not
        # interpreted as a 0..1 value that collapses confidence to 0.
        phones = [
            {"ph": "B", "start": 0.0, "end": 0.05},
            {"ph": "IY", "start": 0.05, "end": 0.30},
        ]
        word = {"word": "be", "start": 0.0, "end": 0.30,
                "source": "ctc_forced+hubertfa", "probability": -20.621, "phonemes": phones}
        segments = syllables.split_word_syllables(word)
        self.assertGreater(segments[0]["confidence"], 0.0)


if __name__ == "__main__":
    unittest.main()
