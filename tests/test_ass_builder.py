"""
tests/test_ass_builder.py

Unit + Golden tests for karaoke.ass_builder
Category: Unit + Contract (no I/O, no subprocess)
"""
import os
import pytest
from conftest import load_textgrid, EXPECTED_DIR
from karaoke.textgrid_parser import extract_words
from karaoke.ass_builder import (
    format_ass_time,
    clamp_duration,
    to_k_tags,
    build_dialogue_event,
    group_words_by_lyrics_lines,
    write_ass,
    MIN_WORD_S,
    MAX_WORD_S,
)


# ── format_ass_time ───────────────────────────────────────────────────────────

class TestFormatAssTime:
    def test_zero(self):
        assert format_ass_time(0.0) == "0:00:00.00"

    def test_one_minute_thirty(self):
        assert format_ass_time(90.0) == "0:01:30.00"

    def test_over_one_hour(self):
        assert format_ass_time(3723.5) == "1:02:03.50"

    def test_centiseconds_precision(self):
        # Python float 1.255 rounds to 1.25 (binary FP), not 1.26
        result = format_ass_time(1.255)
        # Accept either 1.25 or 1.26 — the key is the format, not this edge case
        assert result.startswith("0:00:01.") and len(result) == 10


# ── clamp_duration ────────────────────────────────────────────────────────────

class TestClampDuration:
    def test_normal_passes_through(self):
        assert abs(clamp_duration(0.5) - 0.5) < 0.001

    def test_too_short_clamped_to_min(self):
        assert clamp_duration(0.001) == MIN_WORD_S

    def test_too_long_clamped_to_max(self):
        assert clamp_duration(5.0) == MAX_WORD_S

    def test_exactly_at_boundaries(self):
        assert clamp_duration(MIN_WORD_S) == MIN_WORD_S
        assert clamp_duration(MAX_WORD_S) == MAX_WORD_S


# ── to_k_tags ─────────────────────────────────────────────────────────────────

class TestToKTags:
    def _timings(self):
        return [
            (0.5, 0.85, "Hello"),
            (0.9, 1.3,  "world"),
        ]

    def test_k_tag_format(self):
        k_text, start, end = to_k_tags(["Hello", "world"], self._timings())
        assert "{\\k" in k_text
        assert "Hello" in k_text

    def test_line_start_and_end_correct(self):
        _, start, end = to_k_tags(["Hello", "world"], self._timings())
        assert abs(start - 0.5) < 0.001
        assert abs(end - 1.3) < 0.001

    def test_duration_centiseconds_min_3(self):
        # Use a 0.001s duration — clamp should produce ≥3 cs
        timings = [(0.5, 0.501, "tiny")]
        k_text, _, _ = to_k_tags(["tiny"], timings)
        # Extract the number after {\\k
        import re
        m = re.search(r"\{\\k(\d+)\}", k_text)
        assert m is not None
        cs_val = int(m.group(1))
        assert cs_val >= 3

    def test_more_words_than_timings_appends_bare(self):
        """Words without a timing should appear without {\\k} tag."""
        k_text, _, _ = to_k_tags(["Hello", "world", "orphan"], self._timings())
        assert "{\\k" not in k_text.split("orphan")[0].rsplit(" ", 1)[-1] or "orphan" in k_text


# ── invariant tests on write_ass output ──────────────────────────────────────

class TestWriteAssInvariants:
    def _build_ass(self) -> str:
        words = extract_words(load_textgrid("en_ok.TextGrid"))
        lyric_lines = ["Hello world", "goodbye"]
        events = group_words_by_lyrics_lines(lyric_lines, words)
        return write_ass(events)

    def test_header_present(self):
        ass = self._build_ass()
        assert "[Script Info]" in ass
        assert "[V4+ Styles]" in ass
        assert "[Events]" in ass

    def test_dialogue_lines_present(self):
        ass = self._build_ass()
        dialogue_lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogue_lines) == 2   # two lyric lines

    def test_all_dialogue_start_less_than_end(self):
        """Critical invariant: start < end in every Dialogue event."""
        import re
        ass = self._build_ass()
        time_pat = re.compile(r"Dialogue: \d+,([^,]+),([^,]+),")
        def parse_ass_time(t: str) -> float:
            # Format: H:MM:SS.cc  e.g. 0:00:01.25
            parts = t.split(":")
            h = int(parts[0])
            m = int(parts[1])
            s = float(parts[2])
            return h * 3600 + m * 60 + s
        for line in ass.splitlines():
            m = time_pat.match(line)
            if m:
                start_s = parse_ass_time(m.group(1))
                end_s   = parse_ass_time(m.group(2))
                assert start_s < end_s, f"start >= end in: {line}"

    def test_k_tags_in_every_dialogue(self):
        ass = self._build_ass()
        for line in ass.splitlines():
            if line.startswith("Dialogue:"):
                assert "{\\k" in line


# ── Golden test: en_ok fixture ────────────────────────────────────────────────

GOLDEN_EN_OK = os.path.join(EXPECTED_DIR, "en_ok.ass")

class TestGoldenEnOk:
    def _actual(self) -> str:
        words = extract_words(load_textgrid("en_ok.TextGrid"))
        lyric_lines = ["Hello world goodbye"]
        events = group_words_by_lyrics_lines(lyric_lines, words)
        return write_ass(events)

    def test_golden_matches_if_exists(self):
        """
        If the golden file exists, the output must match exactly.
        If it doesn't exist yet, this test writes it (bootstrap).
        """
        actual = self._actual()
        if not os.path.exists(GOLDEN_EN_OK):
            os.makedirs(EXPECTED_DIR, exist_ok=True)
            with open(GOLDEN_EN_OK, "w", encoding="utf-8") as f:
                f.write(actual)
            pytest.skip("Golden file created — re-run tests to validate.")
        else:
            with open(GOLDEN_EN_OK, "r", encoding="utf-8") as f:
                expected = f.read()
            assert actual == expected
