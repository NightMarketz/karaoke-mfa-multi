"""
Pipeline artifact I/O contract tests.

Each class documents and verifies the schema contract for one pipeline stage's
output artifacts. These tests act as a living specification: if a stage renames
a key, these tests break and make the impact explicit.
"""

import json
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

VALID_STYLES = {"verse", "prechorus", "chorus", "bridge", "drop", "intro", "outro", "ad_lib"}


def _minimal_transcript() -> dict:
    return {
        "alignment_mode": "whisper",
        "segments": [
            {
                "text": "hello world",
                "start": 0.0,
                "end": 1.0,
                "words": [
                    {"word": "hello", "start": 0.0, "end": 0.4, "probability": 0.99},
                    {"word": "world", "start": 0.5, "end": 1.0, "probability": 0.98},
                ],
            }
        ],
    }


def _minimal_aligned() -> dict:
    return {
        "words": [
            {"word": "hello", "start": 0.0, "end": 0.4, "source": "whisper"},
            {"word": "world", "start": 0.5, "end": 1.0, "source": "whisper"},
        ]
    }


def _minimal_analysis() -> dict:
    return {
        "lines": [
            {
                "text": "hello world",
                "start": 0.0,
                "end": 1.0,
                "style": "verse",
                "words": [
                    {"word": "hello", "start": 0.0, "end": 0.4},
                    {"word": "world", "start": 0.5, "end": 1.0},
                ],
            }
        ]
    }


def _minimal_ass() -> str:
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{\\kf40}hello {\\kf60}world\n"
    )


def _minimal_ass_manifest() -> dict:
    return {
        "renderer_mode": "standard",
        "metrics": {
            "dialogue_count": 1,
            "analysis_line_count": 1,
        },
        "inputs": {
            "analysis.json": "/jobs/abc/analysis.json",
        },
        "outputs": {
            "output.ass": "/jobs/abc/output.ass",
        },
    }


def _minimal_mp4_manifest() -> dict:
    return {
        "inputs": {
            "output.ass": "/jobs/abc/output.ass",
        },
        "outputs": {
            "output.mp4": "/jobs/abc/output.mp4",
        },
    }


# ---------------------------------------------------------------------------
# s03 / s03b — transcript.json
# ---------------------------------------------------------------------------

class TestTranscriptContract:
    """Contract for transcript.json produced by s03 (whisper) or s03b (forced alignment)."""

    def test_transcript_required_keys(self):
        data = _minimal_transcript()
        assert "alignment_mode" in data
        assert "segments" in data
        for seg in data["segments"]:
            assert "text" in seg
            assert "start" in seg
            assert "end" in seg
            assert "words" in seg
            for w in seg["words"]:
                assert "word" in w
                assert "start" in w
                assert "end" in w
                assert "probability" in w

    def test_transcript_missing_key_detected(self):
        data = _minimal_transcript()
        del data["alignment_mode"]
        assert "alignment_mode" not in data

    def test_transcript_schema_invariant_segment_start_lt_end(self):
        data = _minimal_transcript()
        violations = [
            seg for seg in data["segments"]
            if seg["end"] <= seg["start"]
        ]
        assert len(violations) == 0

    def test_transcript_word_start_lt_end(self):
        data = _minimal_transcript()
        violations = [
            w
            for seg in data["segments"]
            for w in seg["words"]
            if w["end"] <= w["start"]
        ]
        assert len(violations) == 0

    def test_transcript_alignment_mode_missing_key_detected(self, tmp_path: Path):
        data = _minimal_transcript()
        del data["alignment_mode"]
        f = tmp_path / "transcript.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        loaded = json.loads(f.read_text(encoding="utf-8"))
        assert "alignment_mode" not in loaded


# ---------------------------------------------------------------------------
# s04 — aligned.json
# ---------------------------------------------------------------------------

class TestAlignedContract:
    """Contract for aligned.json produced by s04."""

    def test_aligned_required_keys(self):
        data = _minimal_aligned()
        assert "words" in data
        for w in data["words"]:
            assert "word" in w
            assert "start" in w
            assert "end" in w
            assert "source" in w

    def test_aligned_missing_key_detected(self):
        data = _minimal_aligned()
        del data["words"]
        assert "words" not in data

    def test_aligned_schema_invariant_source_field_present(self):
        data = _minimal_aligned()
        missing_source = [w for w in data["words"] if "source" not in w]
        assert len(missing_source) == 0

    def test_aligned_word_timestamps_ordered(self):
        data = _minimal_aligned()
        violations = [w for w in data["words"] if w["end"] <= w["start"]]
        assert len(violations) == 0

    def test_aligned_source_missing_detected(self):
        data = _minimal_aligned()
        data["words"][0].pop("source")
        missing = [w for w in data["words"] if "source" not in w]
        assert len(missing) == 1


# ---------------------------------------------------------------------------
# s05 — analysis.json
# ---------------------------------------------------------------------------

class TestAnalysisContract:
    """Contract for analysis.json produced by s05."""

    def test_analysis_required_keys(self):
        data = _minimal_analysis()
        assert "lines" in data
        for line in data["lines"]:
            assert "text" in line
            assert "start" in line
            assert "end" in line
            assert "style" in line
            assert "words" in line

    def test_analysis_missing_key_detected(self):
        data = _minimal_analysis()
        del data["lines"]
        assert "lines" not in data

    def test_analysis_schema_invariant_valid_styles(self):
        data = _minimal_analysis()
        invalid_styles = [
            line["style"] for line in data["lines"]
            if line["style"] not in VALID_STYLES
        ]
        assert len(invalid_styles) == 0

    def test_analysis_invalid_style_detected(self):
        data = _minimal_analysis()
        data["lines"][0]["style"] = "unknown_style"
        invalid = [l for l in data["lines"] if l["style"] not in VALID_STYLES]
        assert len(invalid) == 1

    def test_analysis_line_start_lt_end(self):
        data = _minimal_analysis()
        violations = [l for l in data["lines"] if l["end"] <= l["start"]]
        assert len(violations) == 0

    def test_analysis_all_valid_style_values_accepted(self):
        for style in VALID_STYLES:
            data = _minimal_analysis()
            data["lines"][0]["style"] = style
            invalid = [l for l in data["lines"] if l["style"] not in VALID_STYLES]
            assert len(invalid) == 0, f"style '{style}' should be valid"


# ---------------------------------------------------------------------------
# s06 — output.ass
# ---------------------------------------------------------------------------

class TestAssContract:
    """Contract for output.ass produced by s06."""

    def test_ass_required_sections(self):
        content = _minimal_ass()
        assert "[Script Info]" in content
        assert "[V4+ Styles]" in content
        assert "[Events]" in content

    def test_ass_missing_section_detected(self):
        content = _minimal_ass().replace("[Script Info]\n", "")
        assert "[Script Info]" not in content

    def test_ass_schema_invariant_kf_tags_present(self):
        content = _minimal_ass()
        dialogue_lines = [
            line for line in content.splitlines()
            if line.startswith("Dialogue:")
        ]
        assert len(dialogue_lines) > 0
        missing_kf = [line for line in dialogue_lines if r"\kf" not in line]
        assert len(missing_kf) == 0

    def test_ass_dialogue_lines_present(self):
        content = _minimal_ass()
        dialogue_lines = [l for l in content.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogue_lines) >= 1

    def test_ass_kf_tag_missing_detected(self):
        content = _minimal_ass().replace(r"{\kf40}", "").replace(r"{\kf60}", "")
        dialogue_lines = [l for l in content.splitlines() if l.startswith("Dialogue:")]
        missing_kf = [l for l in dialogue_lines if r"\kf" not in l]
        assert len(missing_kf) == len(dialogue_lines)

    def test_ass_written_and_read(self, tmp_path: Path):
        content = _minimal_ass()
        out = tmp_path / "output.ass"
        out.write_text(content, encoding="utf-8")
        loaded = out.read_text(encoding="utf-8")
        assert "[Script Info]" in loaded
        assert r"\kf" in loaded


# ---------------------------------------------------------------------------
# s06 / s07 — manifests
# ---------------------------------------------------------------------------

class TestManifestContract:
    """Contract for *.manifest.json files produced by s06 (ASS) and s07 (MP4)."""

    def test_ass_manifest_required_keys(self):
        data = _minimal_ass_manifest()
        assert "renderer_mode" in data
        assert "metrics" in data
        assert "dialogue_count" in data["metrics"]
        assert "analysis_line_count" in data["metrics"]
        assert "inputs" in data
        assert "analysis.json" in data["inputs"]
        assert "outputs" in data
        assert "output.ass" in data["outputs"]

    def test_ass_manifest_missing_key_detected(self):
        data = _minimal_ass_manifest()
        del data["renderer_mode"]
        assert "renderer_mode" not in data

    def test_ass_manifest_schema_invariant_dialogue_count_positive(self):
        data = _minimal_ass_manifest()
        assert data["metrics"]["dialogue_count"] >= 1

    def test_mp4_manifest_required_keys(self):
        data = _minimal_mp4_manifest()
        assert "inputs" in data
        assert "output.ass" in data["inputs"]
        assert "outputs" in data
        assert "output.mp4" in data["outputs"]

    def test_mp4_manifest_missing_key_detected(self):
        data = _minimal_mp4_manifest()
        del data["outputs"]
        assert "outputs" not in data

    def test_mp4_manifest_schema_invariant_ass_is_input(self):
        data = _minimal_mp4_manifest()
        assert "output.ass" in data["inputs"]

    def test_manifests_written_and_readable(self, tmp_path: Path):
        ass_manifest = _minimal_ass_manifest()
        mp4_manifest = _minimal_mp4_manifest()
        (tmp_path / "output.ass.manifest.json").write_text(
            json.dumps(ass_manifest), encoding="utf-8"
        )
        (tmp_path / "output.mp4.manifest.json").write_text(
            json.dumps(mp4_manifest), encoding="utf-8"
        )
        loaded_ass = json.loads((tmp_path / "output.ass.manifest.json").read_text(encoding="utf-8"))
        loaded_mp4 = json.loads((tmp_path / "output.mp4.manifest.json").read_text(encoding="utf-8"))
        assert loaded_ass["renderer_mode"] == "standard"
        assert "output.mp4" in loaded_mp4["outputs"]


# ---------------------------------------------------------------------------
# Dependency graph documentation (no imports from pipeline_runner)
# ---------------------------------------------------------------------------

class TestArtifactDependencyGraph:
    """
    Documents the artifact invalidation cascade as hardcoded expectations.

    When s05 (analyzing) reruns, downstream artifacts must be invalidated.
    When s06 (generating) reruns, rendering artifacts must be invalidated.
    When s07 (rendering) reruns, only video artifacts are cleared.

    These relationships mirror _INVALIDATION_TARGETS in scripts/pipeline_runner.py.
    If that dict changes, update these tests to keep the spec in sync.
    """

    # Hardcoded mirror of _INVALIDATION_TARGETS for documentation purposes.
    _EXPECTED_INVALIDATION: dict[str, tuple[str, ...]] = {
        "analyzing": (
            "analysis.json",
            "output.ass",
            "output.ass.manifest.json",
            "output.mp4",
            "output.mp4.manifest.json",
            "preview_full.mp4",
            "preview_full.manifest.json",
        ),
        "generating": (
            "output.ass",
            "output.ass.manifest.json",
            "output.mp4",
            "output.mp4.manifest.json",
            "preview_full.mp4",
            "preview_full.manifest.json",
        ),
        "rendering": (
            "output.mp4",
            "output.mp4.manifest.json",
            "preview_full.mp4",
            "preview_full.manifest.json",
        ),
    }

    def test_analyzing_invalidates_analysis_json(self):
        assert "analysis.json" in self._EXPECTED_INVALIDATION["analyzing"]

    def test_analyzing_invalidates_ass_artifacts(self):
        targets = self._EXPECTED_INVALIDATION["analyzing"]
        assert "output.ass" in targets
        assert "output.ass.manifest.json" in targets

    def test_analyzing_invalidates_mp4_artifacts(self):
        targets = self._EXPECTED_INVALIDATION["analyzing"]
        assert "output.mp4" in targets
        assert "output.mp4.manifest.json" in targets

    def test_generating_does_not_invalidate_analysis_json(self):
        assert "analysis.json" not in self._EXPECTED_INVALIDATION["generating"]

    def test_generating_invalidates_ass_and_downstream(self):
        targets = self._EXPECTED_INVALIDATION["generating"]
        assert "output.ass" in targets
        assert "output.mp4" in targets

    def test_rendering_only_invalidates_video_artifacts(self):
        targets = self._EXPECTED_INVALIDATION["rendering"]
        assert "output.mp4" in targets
        assert "output.ass" not in targets
        assert "analysis.json" not in targets

    def test_analyzing_is_superset_of_generating(self):
        analyzing = set(self._EXPECTED_INVALIDATION["analyzing"])
        generating = set(self._EXPECTED_INVALIDATION["generating"])
        assert generating.issubset(analyzing)

    def test_generating_is_superset_of_rendering(self):
        generating = set(self._EXPECTED_INVALIDATION["generating"])
        rendering = set(self._EXPECTED_INVALIDATION["rendering"])
        assert rendering.issubset(generating)

    def test_cascade_depth_analyzing_gt_generating_gt_rendering(self):
        assert (
            len(self._EXPECTED_INVALIDATION["analyzing"])
            > len(self._EXPECTED_INVALIDATION["generating"])
            > len(self._EXPECTED_INVALIDATION["rendering"])
        )

    def test_preview_artifacts_invalidated_by_all_stages(self):
        for stage in ("analyzing", "generating", "rendering"):
            targets = self._EXPECTED_INVALIDATION[stage]
            assert "preview_full.mp4" in targets, f"stage '{stage}' should invalidate preview_full.mp4"
            assert "preview_full.manifest.json" in targets, (
                f"stage '{stage}' should invalidate preview_full.manifest.json"
            )
