"""
tests/test_qc.py

Unit tests for karaoke.qc
Category: Unit (no I/O, no subprocess)
"""
import pytest
from karaoke.textgrid_parser import extract_words
from karaoke.qc import qc_words, should_fail, QCReport
from conftest import load_textgrid


# ── qc_words with fixture data ────────────────────────────────────────────────

class TestQcWords:
    def test_en_ok_no_outliers(self):
        words = extract_words(load_textgrid("en_ok.TextGrid"))
        report = qc_words(words)
        # Hello=0.35s, world=0.4s, goodbye=0.45s — all within 0.03–1.2s
        assert report.total_words == 3
        assert report.too_short == 0
        assert report.too_long == 0

    def test_buggy_durations_detected(self):
        """
        buggy_durations.TextGrid has:
          - 'looooong': 12s  → too_long
          - 'tiny':  0.01s → too_short
          - 'ok': 0.99s   → fine
        """
        words = extract_words(load_textgrid("buggy_durations.TextGrid"))
        report = qc_words(words)
        assert report.too_long == 1
        assert report.too_short == 1
        assert report.total_words == 3

    def test_pct_long_formula(self):
        words = extract_words(load_textgrid("buggy_durations.TextGrid"))
        report = qc_words(words)
        expected_pct = (1 / 3) * 100
        assert abs(report.pct_long - expected_pct) < 0.01

    def test_top_durations_sorted_descending(self):
        words = extract_words(load_textgrid("buggy_durations.TextGrid"))
        report = qc_words(words)
        durations_only = [d for d, _ in report.top_durations]
        assert durations_only == sorted(durations_only, reverse=True)

    def test_huge_gap_detected(self):
        """
        In buggy_durations, gap between 'tiny' (ends 12.51) and
        the silence end is internal — but between 'looooong' end (12.5)
        and 'tiny' start (12.5) gap = 0 → no gap.
        The fixture doesn't have an explicit huge gap, so we test zero.
        """
        words = extract_words(load_textgrid("buggy_durations.TextGrid"))
        report = qc_words(words, max_gap_s=0.5)
        # All words are contiguous in this fixture
        assert report.huge_gaps == 0

    def test_empty_words_zero_report(self):
        report = qc_words([])
        assert report.total_words == 0
        assert report.pct_long == 0.0
        assert report.pct_short == 0.0


# ── should_fail gate ──────────────────────────────────────────────────────────

class TestShouldFail:
    def test_passes_clean_fixture(self):
        words = extract_words(load_textgrid("en_ok.TextGrid"))
        report = qc_words(words)
        failed, _ = should_fail(report, pct_thresh=5.0)
        assert not failed

    def test_fails_buggy_fixture(self):
        words = extract_words(load_textgrid("buggy_durations.TextGrid"))
        report = qc_words(words)
        failed, reason = should_fail(report, pct_thresh=5.0)
        assert failed
        assert "duration" in reason.lower()

    def test_fails_when_zero_words(self):
        report = QCReport(total_words=0)
        failed, reason = should_fail(report)
        assert failed
        assert "Zero" in reason

    def test_reason_is_string(self):
        words = extract_words(load_textgrid("en_ok.TextGrid"))
        report = qc_words(words)
        _, reason = should_fail(report)
        assert isinstance(reason, str)

    def test_threshold_sensitivity(self):
        """At 0% tolerance every outlier fails."""
        words = extract_words(load_textgrid("buggy_durations.TextGrid"))
        report = qc_words(words)
        failed_strict, _ = should_fail(report, pct_thresh=0.0)
        assert failed_strict

        # At 100% tolerance nothing should fail
        failed_lenient, _ = should_fail(report, pct_thresh=100.0)
        assert not failed_lenient
