"""
test_critical_pipeline.py — Comprehensive tests for every critical failure point
identified in the karaoke pipeline.

Covers:
  1. lyrics_cleaner: adlib extraction, stage-direction filtering, edge cases
  2. 03_prepare_corpus: the LyricsParseResult unpacking bug + adlib_hints.json
  3. server lyrics flow: pre-cleaned text loses adlibs
  4. state_store: thread-safety, atomic writes, API name mismatch
  5. resume_planner: preview/full job_id parity, missing output resilience
  6. music_gap_corrector: clamping, unmapped regions, negative-duration guard
  7. vad: adaptive threshold for bass-heavy tracks, edge cases
  8. ass_builder: MAX_WORD_S clamp, \kf tags, format_ass_time
"""
import json
import os
import sys
import logging
import threading
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from conftest import stdout_protegido

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from karaoke.lyrics_cleaner import (
    clean_lyrics,
    clean_lyrics_strict,
    clean_lyrics_with_adlibs,
    LyricsParseResult,
    _is_stage_direction,
)
from karaoke import state_store, resume_planner
from karaoke.music_gap_corrector import (
    correct_alignment,
    CorrectorConfig,
    CorrectedAlignment,
    _find_last_voice_boundary,
)
from karaoke.textgrid_parser import Interval
from karaoke.vad import (
    VADSegment,
    voice_overlap_ratio,
    _smooth_mask,
    _mask_to_segments,
    VADConfig,
)
from karaoke.ass_builder import (
    format_ass_time,
    to_k_tags,
    build_dialogue_event,
    group_words_by_lyrics_lines,
    write_ass,
    MIN_WORD_S,
    MAX_WORD_S,
)

logger = logging.getLogger("test_critical")
logging.basicConfig(level=logging.DEBUG, format="%(name)s | %(levelname)s | %(message)s")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LYRICS CLEANER — adlib/stage-direction classification
# ═══════════════════════════════════════════════════════════════════════════════
class TestLyricsCleanerAdlibs:
    """Tests for clean_lyrics_with_adlibs() — the source of adlib_hints."""

    def test_return_type_is_dataclass(self):
        """CRITICAL: clean_lyrics_with_adlibs returns LyricsParseResult, NOT a tuple.
        03_prepare_corpus.py L152 used to do `a, b = clean_lyrics_with_adlibs(...)` — crashes."""
        result = clean_lyrics_with_adlibs("Hello (Yeah!) world")
        assert isinstance(result, LyricsParseResult), (
            f"Expected LyricsParseResult, got {type(result).__name__}. "
            "This confirms the bug: tuple unpacking will raise ValueError."
        )
        logger.info(
            "✓ Return type is LyricsParseResult — tuple unpacking would crash"
        )

    def test_cannot_tuple_unpack(self):
        """Verify that tuple-unpacking raises — proving the 03_prepare_corpus.py bug."""
        result = clean_lyrics_with_adlibs("Hello (Yeah!) world")
        with pytest.raises((ValueError, TypeError)):
            # This is exactly what 03_prepare_corpus.py L152 does:
            cleaned, hints = result  # type: ignore
        logger.info(
            "✓ Tuple unpack of LyricsParseResult raises as expected"
        )

    def test_adlib_extraction_basic(self):
        """Parentheticals that are sung backing vocals should be captured."""
        raw = "I won't fall... (For that!)\nI must carry on!"
        result = clean_lyrics_with_adlibs(raw)
        logger.info(f"  lyrics  = {result.lyrics!r}")
        logger.info(f"  hints   = {result.adlib_hints}")
        assert len(result.adlib_hints) == 1, (
            f"Expected 1 adlib hint, got {len(result.adlib_hints)}"
        )
        assert result.adlib_hints[0][1] == "For that!"
        assert "For that" not in result.lyrics, "Adlib text should be removed from lyrics"

    def test_stage_direction_removed_not_captured(self):
        """Parentheticals with stage keywords should be stripped, NOT captured as adlibs."""
        raw = "(whisper) Hello world\n(instrumental interlude)"
        result = clean_lyrics_with_adlibs(raw)
        logger.info(f"  lyrics = {result.lyrics!r}")
        logger.info(f"  hints  = {result.adlib_hints}")
        assert result.adlib_hints == [], (
            f"Stage directions leaked into adlib_hints: {result.adlib_hints}"
        )
        assert "whisper" not in result.lyrics
        assert "instrumental" not in result.lyrics

    def test_suno_bracket_lines_removed(self):
        """Lines that are entirely [bracketed] should be stripped entirely."""
        raw = "[Verse 1]\nSome lyrics here\n[Chorus]\nMore lyrics"
        result = clean_lyrics_with_adlibs(raw)
        assert "Verse" not in result.lyrics
        assert "Chorus" not in result.lyrics
        assert "Some lyrics here" in result.lyrics
        logger.info("✓ Bracket-only lines correctly stripped")

    def test_inline_brackets_removed(self):
        """Inline [tags] within a line should be stripped but not the rest."""
        raw = "Hello [Explosion] world"
        result = clean_lyrics_with_adlibs(raw)
        assert "Explosion" not in result.lyrics
        assert "Hello" in result.lyrics
        assert "world" in result.lyrics

    def test_truncated_adlib_marker(self):
        """Unclosed parens like '(adbl' should be silently removed."""
        raw = "Some lyrics here\n(adbl"
        result = clean_lyrics_with_adlibs(raw)
        assert "adbl" not in result.lyrics
        assert result.adlib_hints == []

    def test_multiple_adlibs_same_line(self):
        """Multiple parentheticals on one line should each be captured."""
        raw = "Yeah (oh!) I'm here (woo!)"
        result = clean_lyrics_with_adlibs(raw)
        logger.info(f"  hints = {result.adlib_hints}")
        assert len(result.adlib_hints) == 2
        adlib_texts = [h[1] for h in result.adlib_hints]
        assert "oh!" in adlib_texts
        assert "woo!" in adlib_texts

    def test_empty_parens_ignored(self):
        """Empty parentheticals '()' should be silently removed."""
        raw = "Hello () world"
        result = clean_lyrics_with_adlibs(raw)
        assert result.adlib_hints == []
        # Should still have the lyrics around it
        assert "Hello" in result.lyrics

    def test_multi_exclamation_normalized(self):
        """Multiple '!!!!!' should collapse to single '!'."""
        raw = "Oh, Fuck!!!!!"
        result = clean_lyrics_with_adlibs(raw)
        assert "!!!!!" not in result.lyrics
        assert "!" in result.lyrics
        logger.info(f"  normalized = {result.lyrics!r}")

    def test_clean_lyrics_strict_removes_punctuation_lines(self):
        """Lines that are only punctuation/ellipsis should be removed by strict mode."""
        raw = "Hello\n...\n!!!\nWorld"
        result = clean_lyrics_strict(raw)
        logger.info(f"  strict = {result!r}")
        assert "..." not in result.split("\n")
        assert "Hello" in result
        assert "World" in result


class TestStageDirectionClassifier:
    """Tests for _is_stage_direction() — the gatekeeper for adlib vs stage."""

    @pytest.mark.parametrize("text,expected", [
        ("whisper", True),
        ("instrumental", True),
        ("guitar solo", True),
        ("heavy breakdown", True),
        ("adbl", True),
        ("adlibs", True),
        ("", True),  # empty = stage direction
        ("Yeah!", False),
        ("Oh oh oh", False),
        ("For that!", False),
        ("Woo!", False),
        ("Na na na", False),
    ])
    def test_classification(self, text, expected):
        result = _is_stage_direction(text)
        label = "stage" if expected else "adlib"
        assert result == expected, f"'{text}' should be {label}, got {'stage' if result else 'adlib'}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PREPARE CORPUS — the LyricsParseResult unpacking bug
# ═══════════════════════════════════════════════════════════════════════════════
class TestPrepareCorpusBug:
    """Tests that validate the 03_prepare_corpus.py integration."""

    def test_correct_unpacking_pattern(self):
        """Demonstrate the CORRECT way to use clean_lyrics_with_adlibs().
        03_prepare_corpus.py should use: result = clean_lyrics_with_adlibs(raw)
        then result.lyrics and result.adlib_hints — NOT tuple unpacking."""
        raw = "Hello (Yeah!) world\n[Verse 2]\nAnother line (oh!)"
        result = clean_lyrics_with_adlibs(raw)

        # Correct access pattern:
        clean_text = result.lyrics
        hints = result.adlib_hints

        logger.info(f"  clean_text = {clean_text!r}")
        logger.info(f"  hints      = {hints}")

        assert isinstance(clean_text, str)
        assert isinstance(hints, list)
        assert len(hints) == 2

    def test_adlib_hints_json_serializable(self):
        """adlib_hints must be JSON-serializable for saving to adlib_hints.json."""
        raw = "I'm here (oh yeah!) standing tall (woo!)"
        result = clean_lyrics_with_adlibs(raw)
        # This is what 03_prepare_corpus.py does:
        serialized = json.dumps(result.adlib_hints, indent=2, ensure_ascii=False)
        logger.info(f"  JSON = {serialized}")
        deserialized = json.loads(serialized)
        # JSON round-trip converts tuples to lists — compare structurally
        expected = [list(h) for h in result.adlib_hints]
        assert deserialized == expected

    @pytest.mark.xfail(
        reason="BUG: server.py saves pre-cleaned lyrics → adlib hints are lost. "
               "Frontend sends cleaned text to /api/generate, so 03_prepare_corpus "
               "never sees parentheticals. Fix: preserve raw lyrics.",
        strict=True,
    )
    def test_adlib_hints_survive_server_flow(self):
        """CORRECT BEHAVIOR: even after the server pipeline, adlib hints should
        be extracted from the ORIGINAL lyrics (with parentheticals).
        
        Bug chain:
          1. Frontend btn-clean-lyrics calls /api/clean_lyrics → strips parens
          2. Frontend replaces textarea value with cleaned text
          3. btn-generate sends cleaned text to /api/generate
          4. server.py L314 saves cleaned text as lyrics.txt
          5. 03_prepare_corpus reads lyrics.txt → 0 adlib hints
          
        This test asserts the EXPECTED correct behavior (hints found),
        which currently fails → xfail documents the bug."""
        raw_with_adlibs = "Hello (Yeah!) world\nI'm here (oh!) now"
        pre_cleaned = clean_lyrics_strict(raw_with_adlibs)
        
        logger.info(f"  Raw lyrics:     {raw_with_adlibs!r}")
        logger.info(f"  After clean_lyrics_strict: {pre_cleaned!r}")
        
        # Simulate what 03_prepare_corpus.py receives (pre-cleaned):
        result = clean_lyrics_with_adlibs(pre_cleaned)
        logger.info(f"  Adlib hints from pre-cleaned: {result.adlib_hints}")
        
        # This SHOULD find hints, but won't because parens were already stripped
        assert len(result.adlib_hints) > 0, (
            "Adlib hints lost! clean_lyrics_strict removed parentheticals before "
            "clean_lyrics_with_adlibs could extract them."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SERVER LYRICS FLOW — API name mismatch bug
# ═══════════════════════════════════════════════════════════════════════════════
class TestStateStoreApiSurface:
    """Tests for state_store public API — catching server.py call mismatches."""

    def test_public_api_has_update_function(self):
        """state_store must expose update_step (alias) for server.py L697/721/732."""
        has_update_step = hasattr(state_store, "update_step")
        has_update_step_status = hasattr(state_store, "update_step_status")
        logger.info(f"  update_step: {has_update_step}")
        logger.info(f"  update_step_status: {has_update_step_status}")
        
        assert has_update_step, "update_step alias must exist for server.py compatibility"
        assert has_update_step_status, "update_step_status (canonical) must exist"
        assert state_store.update_step is state_store.update_step_status, (
            "update_step should be an alias for update_step_status"
        )

    def test_update_function_signature(self):
        """Whichever update function exists must accept the args server.py passes."""
        import inspect
        # Use whichever function exists
        fn = getattr(state_store, "update_step", None) or state_store.update_step_status
        sig = inspect.signature(fn)
        params = list(sig.parameters.keys())
        logger.info(f"  {fn.__name__} params: {params}")
        
        assert "job_id" in params
        assert "step_name" in params
        assert "status" in params


# ═══════════════════════════════════════════════════════════════════════════════
# 4. STATE STORE — Thread safety and atomic writes
# ═══════════════════════════════════════════════════════════════════════════════
class TestStateStoreThreadSafety:
    """Tests for concurrent access to state.json."""

    def test_atomic_write_survives_crash(self, tmp_path, monkeypatch):
        """save_state uses os.replace for atomicity. Verify no corruption."""
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(state_store, "get_state_path", lambda: str(state_file))

        state = {"schema_version": 1, "jobs": {"j1": {"id": "j1", "steps": {}}}}
        state_store.save_state(state)

        loaded = state_store.load_state()
        assert loaded["jobs"]["j1"]["id"] == "j1"
        logger.info("✓ Atomic write + load round-trip succeeded")

    def test_concurrent_upsert_no_corruption(self, tmp_path, monkeypatch):
        """Multiple threads upserting jobs simultaneously should not corrupt state."""
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(state_store, "get_state_path", lambda: str(state_file))

        errors = []

        def worker(job_id):
            try:
                state_store.upsert_job(
                    job_id, f"audio_{job_id}.mp3", "hash_a", "hash_l",
                    "hash_c", "en", {"v": "1.0"}
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"job_{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent upsert errors: {errors}"
        state = state_store.load_state()
        n_jobs = len(state["jobs"])
        logger.info(f"  Jobs after concurrent upsert: {n_jobs}/10 — {list(state['jobs'].keys())}")

        assert n_jobs == 10, f"Expected all 10 jobs to survive, got {n_jobs}"

    def test_corrupt_state_file_recovers(self, tmp_path, monkeypatch):
        """If state.json is corrupted, load_state should return empty state."""
        state_file = tmp_path / "state.json"
        state_file.write_text("{broken json!!!", encoding="utf-8")
        monkeypatch.setattr(state_store, "get_state_path", lambda: str(state_file))

        state = state_store.load_state()
        assert state == {"schema_version": 1, "jobs": {}}
        logger.info("✓ Corrupt state file gracefully recovered")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. RESUME PLANNER — preview/full job ID parity
# ═══════════════════════════════════════════════════════════════════════════════
class TestResumePlannerPreviewParity:
    """Preview and full jobs MUST share the same job_id for promote workflow."""

    def test_preview_and_full_share_job_id(self, tmp_path):
        """CRITICAL: preview_mode/preview_duration must NOT affect job_id hash."""
        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"fake audio data for hashing")
        lyrics = "Some test lyrics"
        lang = "en"

        config_preview = {
            "mfa_lang": "en",
            "pipeline_version": "1.2.0",
            "preview_mode": True,
            "preview_duration": 60,
            "preview_start": 10,
        }
        config_full = {
            "mfa_lang": "en",
            "pipeline_version": "1.2.0",
            "preview_mode": False,
            "preview_duration": None,
        }

        id_preview = resume_planner.calculate_job_id(
            str(audio), lyrics, lang, config_preview
        )
        id_full = resume_planner.calculate_job_id(
            str(audio), lyrics, lang, config_full
        )

        logger.info(f"  Preview ID: {id_preview[:16]}...")
        logger.info(f"  Full ID:    {id_full[:16]}...")
        assert id_preview == id_full, (
            "Preview and full job IDs differ! Promote workflow will fail. "
            "Check that calculate_job_id strips preview_mode, preview_duration, preview_start."
        )

    def test_different_audio_different_id(self, tmp_path):
        """Different audio files must produce different job IDs."""
        a1 = tmp_path / "a.mp3"
        a2 = tmp_path / "b.mp3"
        a1.write_bytes(b"audio one")
        a2.write_bytes(b"audio two")

        id1 = resume_planner.calculate_job_id(str(a1), "lyrics", "en", {})
        id2 = resume_planner.calculate_job_id(str(a2), "lyrics", "en", {})
        assert id1 != id2

    def test_resume_plan_independent_step_evaluation(self, tmp_path):
        """Steps should be evaluated independently — a missing step 2 should NOT
        force re-run of step 3 if step 3's outputs are intact."""
        f1 = tmp_path / "out1.wav"
        f3 = tmp_path / "out3.ass"
        f1.write_bytes(b"step1 output")
        f3.write_bytes(b"step3 output")

        job_data = {
            "steps": {
                "Step 1": {"status": "ok", "outputs": {"wav": str(f1)}},
                "Step 2": {"status": "ok", "outputs": {"wav": str(tmp_path / "missing.wav")}},
                "Step 3": {"status": "ok", "outputs": {"ass": str(f3)}},
            }
        }
        current_steps = [
            {"name": "Step 1"},
            {"name": "Step 2"},
            {"name": "Step 3"},
        ]

        skips = resume_planner.get_resume_plan(job_data, current_steps)
        logger.info(f"  Skippable steps: {skips}")

        assert "Step 1" in skips, "Step 1 has outputs and is ok — should skip"
        assert "Step 2" not in skips, "Step 2 outputs are missing — must re-run"
        assert "Step 3" in skips, "Step 3 outputs exist — should skip independently"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MUSIC GAP CORRECTOR — clamping, unmapped regions, edge cases
# ═══════════════════════════════════════════════════════════════════════════════
class TestMusicGapCorrector:
    """Tests for correct_alignment() — the core alignment post-processor."""

    def test_empty_words_returns_empty(self):
        """No words → empty result, no crash."""
        vad = [VADSegment(1.0, 5.0)]
        result = correct_alignment([], vad)
        assert result.words == []
        assert result.report.unmapped_vocal_regions == [(1.0, 5.0)]
        logger.info("✓ Empty words handled, VAD reported as unmapped")

    def test_word_clamped_in_silence(self):
        """A word spanning silence should be clamped to max_word_sec_silence."""
        config = CorrectorConfig(max_word_sec_silence=1.0)
        words = [Interval(start=0.0, end=5.0, text="hello")]
        vad = []  # no voice at all

        result = correct_alignment(words, vad, config)
        clamped = result.words[0]
        logger.info(f"  Original: 0.0-5.0, Clamped: {clamped.start}-{clamped.end}")
        assert clamped.end - clamped.start <= 1.0 + 0.01, (
            f"Word should be clamped to ≤1.0s in silence, got {clamped.end - clamped.start}"
        )
        assert result.report.words_clamped >= 1

    def test_word_clamped_in_voice(self):
        """A word spanning voice should be clamped to max_word_sec_voice (4.0s)."""
        config = CorrectorConfig(max_word_sec_voice=4.0)
        words = [Interval(start=0.0, end=10.0, text="heeeeere")]
        vad = [VADSegment(0.0, 10.0)]  # voice the whole time

        result = correct_alignment(words, vad, config)
        clamped = result.words[0]
        dur = clamped.end - clamped.start
        logger.info(f"  Clamped duration: {dur:.2f}s (max={config.max_word_sec_voice})")
        assert dur <= config.max_word_sec_voice + 0.01

    def test_no_negative_duration_after_drift_correction(self):
        """CRITICAL: When first word starts before first voice, drift correction
        must shift BOTH start AND end to avoid negative duration.
        Previous bug: only shifted start → end < start → crash in ASS builder."""
        words = [Interval(start=0.0, end=0.5, text="the")]
        vad = [VADSegment(5.0, 10.0)]  # voice starts way later

        result = correct_alignment(words, vad)
        w = result.words[0]
        dur = w.end - w.start
        logger.info(f"  Drift-corrected: start={w.start:.2f} end={w.end:.2f} dur={dur:.2f}")
        assert dur > 0, f"Negative duration after drift correction: {dur}"

    def test_unmapped_vocal_regions_detected(self):
        """Vocal segments with no aligned words should appear in unmapped_vocal_regions."""
        words = [Interval(start=0.0, end=1.0, text="hello")]
        vad = [
            VADSegment(0.0, 1.0),   # mapped
            VADSegment(5.0, 7.0),   # unmapped — potential adlib
            VADSegment(10.0, 12.0), # unmapped — potential adlib
        ]
        result = correct_alignment(words, vad)
        logger.info(f"  Unmapped regions: {result.report.unmapped_vocal_regions}")
        assert len(result.report.unmapped_vocal_regions) == 2
        assert (5.0, 7.0) in result.report.unmapped_vocal_regions
        assert (10.0, 12.0) in result.report.unmapped_vocal_regions

    def test_line_breaks_on_large_gaps(self):
        """Gaps > max_gap_sec between words should trigger line breaks."""
        config = CorrectorConfig(max_gap_sec=2.0)
        words = [
            Interval(start=0.0, end=0.5, text="hello"),
            Interval(start=5.0, end=5.5, text="world"),  # 4.5s gap > 2.0
        ]
        vad = [VADSegment(0.0, 0.5), VADSegment(5.0, 5.5)]

        result = correct_alignment(words, vad, config)
        logger.info(f"  Line breaks at indices: {result.line_breaks}")
        assert 0 in result.line_breaks, "Should have line break after first word (gap=4.5s)"

    def test_find_last_voice_boundary_clamps(self):
        """_find_last_voice_boundary must return ≤ word_end, not seg.end."""
        # VAD segment extends far beyond word boundary
        boundary = _find_last_voice_boundary(0.0, 1.0, [VADSegment(0.5, 50.0)])
        logger.info(f"  Boundary: {boundary} (word_end=1.0)")
        assert boundary is not None
        assert boundary <= 1.0, f"Boundary {boundary} exceeds word_end 1.0"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. VAD — adaptive threshold, edge cases
# ═══════════════════════════════════════════════════════════════════════════════
class TestVAD:
    """Tests for voice_overlap_ratio and VAD helpers."""

    def test_voice_overlap_full_coverage(self):
        """Word fully inside a VAD segment → ratio = 1.0."""
        ratio = voice_overlap_ratio(1.0, 2.0, [VADSegment(0.0, 5.0)])
        assert abs(ratio - 1.0) < 0.01

    def test_voice_overlap_no_coverage(self):
        """Word outside all VAD segments → ratio = 0.0."""
        ratio = voice_overlap_ratio(10.0, 11.0, [VADSegment(0.0, 5.0)])
        assert ratio == 0.0

    def test_voice_overlap_partial(self):
        """Word partially overlaps VAD → correct ratio."""
        # Word: 4.0-6.0 (2s), VAD: 0-5 → overlap = 1s → ratio = 0.5
        ratio = voice_overlap_ratio(4.0, 6.0, [VADSegment(0.0, 5.0)])
        logger.info(f"  Partial overlap ratio: {ratio}")
        assert abs(ratio - 0.5) < 0.01

    def test_voice_overlap_zero_duration(self):
        """Zero-duration word → ratio = 0.0, no ZeroDivisionError."""
        ratio = voice_overlap_ratio(1.0, 1.0, [VADSegment(0.0, 5.0)])
        assert ratio == 0.0

    def test_smooth_mask_removes_spikes(self):
        """Short True spikes should be removed."""
        # 1 frame spike with min_speech_ms=150 (15 frames at 10ms hop)
        mask = [False] * 50 + [True] + [False] * 50
        smoothed = _smooth_mask(mask, hop_ms=10, min_speech_ms=150, min_silence_ms=200)
        assert not any(smoothed), "Single-frame spike should be removed"

    def test_smooth_mask_fills_gaps(self):
        """Short False gaps between True regions should be filled."""
        mask = [True] * 20 + [False] * 5 + [True] * 20
        smoothed = _smooth_mask(mask, hop_ms=10, min_speech_ms=50, min_silence_ms=200)
        # Gap is 5 frames = 50ms < min_silence 200ms → should be filled
        assert all(smoothed[20:25]), "Short gap should be filled"

    def test_mask_to_segments_merges_overlapping(self):
        """Adjacent segments after padding should merge."""
        mask = [True] * 10 + [False] * 2 + [True] * 10
        segments = _mask_to_segments(mask, hop_ms=10, pad_ms=100, total_duration=1.0)
        logger.info(f"  Segments: {[(s.start, s.end) for s in segments]}")
        # With 100ms padding, the 20ms gap should cause overlap → merge
        assert len(segments) == 1, "Should merge into single segment after padding"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ASS BUILDER — timing, \kf tags, MAX_WORD_S
# ═══════════════════════════════════════════════════════════════════════════════
class TestAssBuilder:
    """Tests for ASS subtitle generation."""

    def test_format_ass_time_basic(self):
        """Standard time formatting."""
        assert format_ass_time(0) == "0:00:00.00"
        assert format_ass_time(61.5) == "0:01:01.50"
        assert format_ass_time(3661.99) == "1:01:01.99"

    def test_format_ass_time_negative_clamped(self):
        """Negative timestamps should clamp to 0."""
        assert format_ass_time(-5) == "0:00:00.00"

    def test_max_word_s_matches_corrector(self):
        """MAX_WORD_S in ass_builder must match CorrectorConfig.max_word_sec_voice."""
        config = CorrectorConfig()
        logger.info(f"  ASS MAX_WORD_S = {MAX_WORD_S}")
        logger.info(f"  Corrector max_word_sec_voice = {config.max_word_sec_voice}")
        assert MAX_WORD_S == config.max_word_sec_voice, (
            f"Mismatch: ASS MAX_WORD_S={MAX_WORD_S} vs CorrectorConfig={config.max_word_sec_voice}. "
            "This causes double-clamping or highlights extending past word boundaries."
        )

    def test_to_k_tags_uses_kf(self):
        """Karaoke tags must use \\kf (progressive fill), not \\k (hard jump)."""
        words = ["Hello", "World"]
        timings = [(0.0, 0.5, "hello"), (0.5, 1.0, "world")]
        k_text, start, end = to_k_tags(words, timings)
        logger.info(f"  k_text = {k_text!r}")
        assert "\\kf" in k_text, f"Expected \\kf tags, got: {k_text}"
        assert "\\k " not in k_text.replace("\\kf", ""), "Should NOT have plain \\k tags"

    def test_to_k_tags_clamps_duration(self):
        """Word durations should be clamped between MIN_WORD_S and MAX_WORD_S."""
        # Tiny duration (0.01s < MIN_WORD_S=0.03)
        words = ["Hi"]
        timings = [(0.0, 0.01, "hi")]
        k_text, _, _ = to_k_tags(words, timings)
        # MIN_WORD_S=0.03 → 3 centiseconds minimum
        assert "\\kf3}" in k_text, f"Expected minimum 3cs, got: {k_text}"

        # Huge duration (10s > MAX_WORD_S=4.0)
        timings_long = [(0.0, 10.0, "heeeere")]
        k_text_long, _, _ = to_k_tags(["Heeeere"], timings_long)
        # MAX_WORD_S=4.0 → 400 centiseconds maximum
        assert "\\kf400}" in k_text_long, f"Expected max 400cs, got: {k_text_long}"

    def test_to_k_tags_empty_returns_empty(self):
        """No timings → empty string, no crash."""
        k_text, start, end = to_k_tags(["hello"], [])
        assert k_text == ""
        assert start == 0
        assert end == 0

    def test_build_dialogue_event_format(self):
        """Dialogue line should have correct ASS format."""
        words = ["Hello", "World"]
        timings = [(1.0, 1.5, "hello"), (1.5, 2.0, "world")]
        event = build_dialogue_event(words, timings)
        logger.info(f"  event = {event[:100]}...")
        assert event.startswith("Dialogue: 0,")
        assert "\\an2" in event
        assert "\\pos(" in event

    def test_build_dialogue_event_adlib_style(self):
        """Adlib lines should use 'Adlib' style."""
        words = ["Yeah"]
        timings = [(5.0, 5.5, "yeah")]
        event = build_dialogue_event(words, timings, style="Adlib", layer=1)
        assert ",Adlib," in event
        assert event.startswith("Dialogue: 1,")

    def test_group_words_by_lyrics_lines(self):
        """Each lyric line should consume the correct number of word timings."""
        lyrics_lines = ["Hello World", "Goodbye Moon"]
        words = [
            Interval(0.0, 0.5, "hello"),
            Interval(0.5, 1.0, "world"),
            Interval(2.0, 2.5, "goodbye"),
            Interval(2.5, 3.0, "moon"),
        ]
        events = group_words_by_lyrics_lines(lyrics_lines, words)
        logger.info(f"  Events generated: {len(events)}")
        assert len(events) == 2, f"Expected 2 events (one per line), got {len(events)}"

    def test_write_ass_has_required_sections(self):
        """Complete ASS file must have [Script Info], [V4+ Styles], [Events]."""
        events = ["Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hello"]
        content = write_ass(events)
        assert "[Script Info]" in content
        assert "[V4+ Styles]" in content
        assert "[Events]" in content
        assert "Dialogue:" in content
        logger.info("✓ ASS file has all required sections")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. NORMALISE LYRICS (from 03_prepare_corpus.py)
# ═══════════════════════════════════════════════════════════════════════════════
class TestNormaliseLyrics:
    """Tests for the normalise_lyrics function used to create song.lab."""

    def test_contractions_expanded(self):
        """Import and test contraction expansion."""
        # We import from the script directly
        spec_path = Path(__file__).parent.parent / "scripts" / "03_prepare_corpus.py"
        if not spec_path.exists():
            pytest.skip("03_prepare_corpus.py not found")

        # Import dynamically
        import importlib.util
        spec = importlib.util.spec_from_file_location("prepare_corpus", str(spec_path))
        mod = importlib.util.module_from_spec(spec)
        # Mock argparse to avoid sys.argv issues
        sys.modules["prepare_corpus"] = mod
        with stdout_protegido():          # ver conftest: o script
            spec.loader.exec_module(mod)   # sequestra o stdout do pytest

        result = mod.normalise_lyrics("I'm still here, won't fall!")
        logger.info(f"  normalised = {result!r}")
        assert "i am still here" in result
        assert "will not fall" in result
        assert "'" not in result  # all apostrophes removed

    def test_punctuation_removed(self):
        """Ensure all punctuation is stripped for MFA alignment."""
        spec_path = Path(__file__).parent.parent / "scripts" / "03_prepare_corpus.py"
        if not spec_path.exists():
            pytest.skip("03_prepare_corpus.py not found")

        import importlib.util
        spec = importlib.util.spec_from_file_location("prepare_corpus2", str(spec_path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["prepare_corpus2"] = mod
        with stdout_protegido():          # ver conftest: o script
            spec.loader.exec_module(mod)   # sequestra o stdout do pytest

        result = mod.normalise_lyrics("Hello, World! How's it going?")
        logger.info(f"  normalised = {result!r}")
        assert "," not in result
        assert "!" not in result
        assert "?" not in result
