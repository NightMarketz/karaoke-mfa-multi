"""
Audio alignment constraint snapshot tests.

These tests verify that alignment-critical default values have not drifted
from the documented spec in AGENTS.md. When you change a default, update
both the code and AGENTS.md — these tests enforce the contract.
"""

import ast
import inspect
import pathlib
import re

from scripts.common.config import (
    DEFAULT_GENERATE_ASS_PREROLL_MS,
    DEFAULT_GENERATE_ASS_POSTROLL_MS,
    DEFAULT_GENERATE_ASS_GAP_MS,
    DEFAULT_VALIDATE_OVERLAP_TOLERANCE_S,
    DEFAULT_TRANSCRIBE_LOW_CONFIDENCE_THRESHOLD,
    DEFAULT_TRANSCRIBE_LC_WARNING_PCT,
)
from scripts.common.validation import find_timestamp_errors


def _extract_constant(filepath, name):
    tree = ast.parse(pathlib.Path(filepath).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if isinstance(node.value, ast.Constant):
                        return node.value.value
    return None


class TestAppConfigAlignmentDefaults:
    def test_generate_ass_preroll_ms_default_is_200(self):
        assert DEFAULT_GENERATE_ASS_PREROLL_MS == 200

    def test_generate_ass_postroll_ms_default_is_300(self):
        assert DEFAULT_GENERATE_ASS_POSTROLL_MS == 300

    def test_generate_ass_gap_ms_default_is_50(self):
        assert DEFAULT_GENERATE_ASS_GAP_MS == 50

    def test_validate_overlap_tolerance_s_default_is_0_05(self):
        assert DEFAULT_VALIDATE_OVERLAP_TOLERANCE_S == 0.05

    def test_transcribe_low_confidence_threshold_default_is_0_25(self):
        assert DEFAULT_TRANSCRIBE_LOW_CONFIDENCE_THRESHOLD == 0.25

    def test_transcribe_lc_warning_pct_default_is_20(self):
        assert DEFAULT_TRANSCRIBE_LC_WARNING_PCT == 20


class TestHardcodedAlignmentFloors:
    def test_min_word_ms_is_80(self):
        # MIN_WORD_MS lives inside _build_karaoke_text, which moved from
        # s06_generate_ass.py to ass_emit.py (pure code move, task 1 of the
        # 2026-08-20-camadas-cor-e-mascara plan).
        value = _extract_constant("scripts/ass_emit.py", "MIN_WORD_MS")
        assert value == 80

    def test_s03b_alignment_min_dur_is_50ms(self):
        value = _extract_constant("scripts/s03b_lyrics_align.py", "min_dur")
        assert value == 0.050

    def test_s04_alignment_min_dur_is_50ms(self):
        value = _extract_constant("scripts/s04_align.py", "min_dur")
        assert value == 0.050


class TestValidationDefaults:
    def test_find_timestamp_errors_min_duration_default(self):
        sig = inspect.signature(find_timestamp_errors)
        assert sig.parameters["min_duration"].default == 0.001

    def test_find_timestamp_errors_overlap_tolerance_default(self):
        sig = inspect.signature(find_timestamp_errors)
        assert sig.parameters["overlap_tolerance_s"].default == 0.0


class TestSnapWindowDefaults:
    def test_snap_window_cli_default_is_0_75(self):
        content = pathlib.Path("scripts/s03b_lyrics_align.py").read_text(encoding="utf-8")
        m = re.search(r'"--snap-window".*?default=([\d.]+)', content, re.DOTALL)
        assert m is not None, "--snap-window argument not found in s03b_lyrics_align.py"
        assert float(m.group(1)) == 0.75
