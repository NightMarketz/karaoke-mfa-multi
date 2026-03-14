"""
tests/test_music_gap_corrector.py

Golden tests for the MusicGapCorrector + VAD voice_overlap_ratio.
Category: Unit (no I/O, no subprocess, runs in <1s)
"""
import pytest
from conftest import load_textgrid

from karaoke.textgrid_parser import parse_textgrid, select_word_tier, Interval
from karaoke.vad import VADSegment, voice_overlap_ratio
from karaoke.corrector_config import CorrectorConfig
from karaoke.music_gap_corrector import correct_alignment, CorrectedAlignment


# ── Helpers ──────────────────────────────────────────────────────────────────

def _words(fixture_name: str):
    """Load words from a TextGrid fixture."""
    tiers = parse_textgrid(load_textgrid(fixture_name))
    tier = select_word_tier(tiers)
    return sorted(tier.speech_intervals, key=lambda i: i.start)


# ── VAD fixtures (in-memory, no WAV needed) ─────────────────────────────────

# drift_instrumental.TextGrid:
#   Words: So(0.5–0.85), burn(0.85–1.2), it(1.2–1.5), all(1.5–1.9), Blinded(1.9–30.0)
#   Voice is at [0.3, 2.1] only — the rest is instrumental silence
DRIFT_VAD = [VADSegment(start=0.3, end=2.1)]

# sustained_note.TextGrid:
#   Words: I'm(0.3–0.7), still(0.7–1.1), here(1.1–3.4)
#   Voice covers entire range
SUSTAINED_VAD = [VADSegment(start=0.0, end=4.0)]

# gap_split.TextGrid:
#   Words: Let(0.2–0.6), it(0.6–1.0), burn(1.0–1.3), No(3.5–3.9), return(3.9–4.4)
#   Voice at [0.1, 1.5] and [3.3, 4.6] — gap in between
GAP_VAD = [VADSegment(start=0.1, end=1.5), VADSegment(start=3.3, end=4.6)]

DEFAULT_CONFIG = CorrectorConfig()


# ── Test 1: Drift across instrumental is clamped ────────────────────────────

class TestDriftClamped:
    def test_blinded_word_is_clamped(self):
        """'Blinded' spans 1.9→30.0 (28.1s) but voice ends at 2.1s.
        It should be clamped to MAX_WORD_SEC_SILENCE (1.2s) since
        voice_overlap_ratio < 0.5."""
        words = _words("drift_instrumental.TextGrid")
        result = correct_alignment(words, DRIFT_VAD, DEFAULT_CONFIG)

        blinded = [w for w in result.words if w.text == "Blinded"][0]
        assert blinded.duration <= DEFAULT_CONFIG.max_word_sec_silence + 0.01
        assert blinded.duration < 2.0  # definitely not 28s anymore

    def test_report_has_clamped_count(self):
        words = _words("drift_instrumental.TextGrid")
        result = correct_alignment(words, DRIFT_VAD, DEFAULT_CONFIG)
        assert result.report.words_clamped >= 1

    def test_max_duration_reduced(self):
        words = _words("drift_instrumental.TextGrid")
        result = correct_alignment(words, DRIFT_VAD, DEFAULT_CONFIG)
        assert result.report.max_duration_before > 20.0  # was 28.1s
        assert result.report.max_duration_after <= DEFAULT_CONFIG.max_word_sec_voice


# ── Test 2: Sustained note inside voice is preserved ────────────────────────

class TestSustainedPreserved:
    def test_here_word_not_clamped(self):
        """'here' is 2.3s but FULLY inside voice activity.
        It should NOT be clamped (2.3 < MAX_WORD_SEC_VOICE=2.5)."""
        words = _words("sustained_note.TextGrid")
        result = correct_alignment(words, SUSTAINED_VAD, DEFAULT_CONFIG)

        here = [w for w in result.words if w.text == "here"][0]
        assert abs(here.duration - 2.3) < 0.01  # preserved

    def test_no_words_clamped(self):
        words = _words("sustained_note.TextGrid")
        result = correct_alignment(words, SUSTAINED_VAD, DEFAULT_CONFIG)
        assert result.report.words_clamped == 0


# ── Test 3: Gap triggers line break ─────────────────────────────────────────

class TestGapSplit:
    def test_line_break_inserted(self):
        """Gap between 'burn'(ends 1.3) and 'No'(starts 3.5) is 2.2s.
        This exceeds MAX_GAP_SEC=1.5 → line break after 'burn'."""
        words = _words("gap_split.TextGrid")
        result = correct_alignment(words, GAP_VAD, DEFAULT_CONFIG)

        # Line break set contains the index of the word BEFORE the break
        assert len(result.line_breaks) >= 1
        assert result.report.lines_split >= 1

    def test_line_break_at_correct_position(self):
        """The break should be after index 2 ('burn'), before index 3 ('No')."""
        words = _words("gap_split.TextGrid")
        result = correct_alignment(words, GAP_VAD, DEFAULT_CONFIG)
        # 'burn' is at index 2 (Let=0, it=1, burn=2)
        assert 2 in result.line_breaks


# ── Test 4: Voice overlap ratio computation ─────────────────────────────────

class TestVoiceOverlapRatio:
    def test_fully_inside_voice(self):
        # We don't actually call detect_voice_activity here because we use manual segments
        # but if we did, it would be: segments, stats = detect_voice_activity(...)
        ratio = voice_overlap_ratio(0.5, 1.0, [VADSegment(0.0, 2.0)])
        assert abs(ratio - 1.0) < 0.001

    def test_fully_outside_voice(self):
        ratio = voice_overlap_ratio(5.0, 10.0, [VADSegment(0.0, 2.0)])
        assert ratio == 0.0

    def test_partial_overlap(self):
        # Word 0.0–2.0, voice 1.0–3.0 → overlap 1.0–2.0 = 1.0s / 2.0s = 0.5
        ratio = voice_overlap_ratio(0.0, 2.0, [VADSegment(1.0, 3.0)])
        assert abs(ratio - 0.5) < 0.001

    def test_drift_word_mostly_silence(self):
        """'Blinded' at 1.9–30.0, voice at 0.3–2.1.
        Overlap = 2.1–1.9 = 0.2s / 28.1s ≈ 0.007 → mostly silence."""
        ratio = voice_overlap_ratio(1.9, 30.0, DRIFT_VAD)
        assert ratio < 0.05  # way below threshold

    def test_sustained_word_mostly_voice(self):
        """'here' at 1.1–3.4, voice at 0.0–4.0.
        Overlap = 2.3s / 2.3s = 1.0 → fully in voice."""
        ratio = voice_overlap_ratio(1.1, 3.4, SUSTAINED_VAD)
        assert abs(ratio - 1.0) < 0.001


# ── Test 5: Report metrics ──────────────────────────────────────────────────

class TestCorrectionReport:
    def test_drift_report_complete(self):
        words = _words("drift_instrumental.TextGrid")
        result = correct_alignment(words, DRIFT_VAD, DEFAULT_CONFIG)

        r = result.report
        assert r.words_clamped >= 1
        assert r.max_duration_before > 20.0
        assert r.max_duration_after <= DEFAULT_CONFIG.max_word_sec_voice
        # huge_gaps_after should be <= huge_gaps_before
        # (clamping Blinded creates a gap but it was already huge)

    def test_sustained_report_clean(self):
        words = _words("sustained_note.TextGrid")
        result = correct_alignment(words, SUSTAINED_VAD, DEFAULT_CONFIG)
        assert result.report.words_clamped == 0
        assert result.report.lines_split == 0
