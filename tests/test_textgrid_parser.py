"""
tests/test_textgrid_parser.py

Unit tests for karaoke.textgrid_parser
Category: Unit (no I/O, no subprocess, runs in <1s)
"""
import pytest
from conftest import load_textgrid
from karaoke.textgrid_parser import (
    parse_textgrid,
    list_tier_names,
    select_word_tier,
    extract_words,
    SILENCE_TOKENS,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _tg(name):
    return parse_textgrid(load_textgrid(name))


# ── list_tier_names ───────────────────────────────────────────────────────────

class TestListTierNames:
    def test_en_ok_has_words_and_phones(self):
        tiers = _tg("en_ok.TextGrid")
        names = list_tier_names(tiers)
        assert "words" in names
        assert "phones" in names

    def test_returns_ordered(self):
        tiers = _tg("en_ok.TextGrid")
        names = list_tier_names(tiers)
        assert names == ["words", "phones"]  # fixture order


# ── select_word_tier ──────────────────────────────────────────────────────────

class TestSelectWordTier:
    def test_prefers_words_tier(self):
        tiers = _tg("en_ok.TextGrid")
        tier = select_word_tier(tiers)
        assert tier.name == "words"

    def test_falls_back_to_transcript_when_words_empty(self):
        """
        weird_tier_names.TextGrid: 'words' tier is all-empty,
        'transcript' has real speech. Selector must fall back to 'transcript'.
        """
        tiers = _tg("weird_tier_names.TextGrid")
        tier = select_word_tier(tiers)
        # 'words' is empty → heuristic must prefer 'transcript'
        assert tier.name in ("transcript", "phones")
        assert len(tier.speech_intervals) > 0

    def test_raises_when_no_speech_anywhere(self):
        tiers = _tg("empty_intervals.TextGrid")
        with pytest.raises(ValueError, match="No speech intervals"):
            select_word_tier(tiers)

    def test_word_tier_speech_interval_count(self):
        tiers = _tg("en_ok.TextGrid")
        tier = select_word_tier(tiers)
        # fixture has Hello, world, goodbye (3 real words)
        assert len(tier.speech_intervals) == 3


# ── Interval properties ───────────────────────────────────────────────────────

class TestInterval:
    def test_duration_is_correct(self):
        tiers = _tg("en_ok.TextGrid")
        tier = select_word_tier(tiers)
        hello = tier.speech_intervals[0]
        assert hello.text == "Hello"
        assert abs(hello.duration - 0.35) < 0.001   # 0.85 - 0.5

    def test_silence_tokens_are_excluded(self):
        tiers = _tg("en_ok.TextGrid")
        tier = select_word_tier(tiers)
        texts = [i.text for i in tier.speech_intervals]
        for tok in SILENCE_TOKENS:
            assert tok not in texts

    def test_intervals_ordered_by_start(self):
        words = extract_words(load_textgrid("en_ok.TextGrid"))
        starts = [w.start for w in words]
        assert starts == sorted(starts)


# ── extract_words convenience ─────────────────────────────────────────────────

class TestExtractWords:
    def test_returns_three_words_for_en_ok(self):
        words = extract_words(load_textgrid("en_ok.TextGrid"))
        assert len(words) == 3

    def test_words_are_hello_world_goodbye(self):
        words = extract_words(load_textgrid("en_ok.TextGrid"))
        assert [w.text for w in words] == ["Hello", "world", "goodbye"]

    def test_raises_on_empty_intervals(self):
        with pytest.raises(ValueError):
            extract_words(load_textgrid("empty_intervals.TextGrid"))
