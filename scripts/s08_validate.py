r"""
s08_validate.py — Pipeline contract tests and quality metrics.

Runs after a complete pipeline execution to verify correctness of every
intermediate artifact. Designed to catch regressions when any stage changes.

Contract tests (hard failures):
    Stage 03/03b  transcript.json schema and word timestamps
    Stage 04      aligned.json — no overlaps, monotonic timestamps
    Stage 05      analysis.json — all words accounted for, valid styles
    Stage 06      output.ass  — no inverted/overlapping dialogue lines, \kf present

Quality metrics (warnings, not failures):
    Drift p50/p95 vs reference_mapping.json (if present)
    Word coverage: aligned words vs lyrics.txt word count
    Low-confidence word rate (if alignment_mode == "whisper")
    HubertFA alignment rate (hubertfa vs whisper_fallback)

Exit codes:
    0 — all contract tests pass (warnings may be present)
    1 — one or more contract tests failed

Usage:
    python scripts/s08_validate.py --job-dir jobs/struggle_test
    python scripts/s08_validate.py --job-dir jobs/struggle_test --reference reference_mapping.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.common.observability import build_observability_summary, write_event
from scripts.common.provenance import ProvenanceError, file_sha256, load_manifest, validate_file_hash
from scripts.common.validation import find_timestamp_errors, find_word_coverage_errors

logger = logging.getLogger(__name__)

# ── ANSI colours ─────────────────────────────────────────────────────────────
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_RESET  = "\033[0m"

_failures: list[str] = []
_warnings: list[str] = []
_current_job_dir: Path | None = None


def _ok(msg: str) -> None:
    print(f"  {_GREEN}[OK]{_RESET} {msg}")


def _warn(msg: str) -> None:
    _warnings.append(msg)
    if _current_job_dir is not None:
        write_event(_current_job_dir, "validation_warning", "validating", level="warning", message=msg)
    print(f"  {_YELLOW}[WARN]{_RESET}  {msg}")


def _fail(msg: str) -> None:
    _failures.append(msg)
    if _current_job_dir is not None:
        write_event(_current_job_dir, "validation_failure", "validating", level="error", message=msg)
    print(f"  {_RED}[FAIL]{_RESET}  {msg}")


def _section(title: str) -> None:
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        _fail(f"Missing file: {path.name}")
        return None
    if path.stat().st_size == 0:
        _fail(f"Empty file: {path.name}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        _fail(f"{path.name} is not valid JSON: {e}")
        return None


def _ts_to_ms(ass_ts: str) -> int:
    """Convert ASS timestamp H:MM:SS.cc to milliseconds."""
    h, m, rest = ass_ts.split(":")
    sec, cs = rest.split(".")
    return int(h) * 3_600_000 + int(m) * 60_000 + int(sec) * 1_000 + int(cs) * 10


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_v) - 1)
    return sorted_v[lo] + (sorted_v[hi] - sorted_v[lo]) * (k - lo)


def _manifest_sha(manifest: dict[str, Any], section: str, artifact: str) -> str:
    entries = manifest.get(section)
    if not isinstance(entries, dict):
        raise ProvenanceError(f"manifest missing {section}")
    details = entries.get(artifact)
    if not isinstance(details, dict):
        raise ProvenanceError(f"manifest missing {artifact} entry")
    sha256 = details.get("sha256")
    if not isinstance(sha256, str) or not sha256:
        raise ProvenanceError(f"manifest missing {artifact} sha256")
    return sha256


def _ass_dialogue_count(path: Path) -> int:
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    return content.count("\nDialogue:")


# ---------------------------------------------------------------------------
# Stage 03 / 03b — transcript.json
# ---------------------------------------------------------------------------
def validate_job_contracts(job_dir: Path) -> None:
    _section("Job Contracts - meta/status")

    meta_path = job_dir / "meta.json"
    meta = _load_json(meta_path) if meta_path.exists() else None
    legacy = _load_json(job_dir / "metadata.json") if (job_dir / "metadata.json").exists() else None

    if meta is None:
        if legacy is not None:
            _warn("metadata.json found without meta.json - legacy contract only")
        else:
            _fail("Missing required meta.json")
    elif isinstance(meta, dict):
        required_meta = {
            "job_id",
            "song_name",
            "preset",
            "created_at",
            "duration_s",
            "has_lyrics",
            "source",
        }
        missing = required_meta - set(meta.keys())
        if missing:
            _fail(f"meta.json missing keys: {missing}")
        else:
            _ok("meta.json contract OK")

    if isinstance(meta, dict) and isinstance(legacy, dict):
        meta_id = meta.get("job_id")
        legacy_id = legacy.get("job_id") or legacy.get("id")
        if meta_id and legacy_id and meta_id != legacy_id:
            _fail("meta.json and metadata.json have conflicting job identifiers")
        else:
            _warn("metadata.json is present as legacy metadata")

    status = _load_json(job_dir / "status.json")
    if not isinstance(status, dict):
        _fail("status.json must be an object")
        return

    required_status = {"stage", "progress", "error", "updated_at"}
    missing_status = required_status - set(status.keys())
    if missing_status:
        _fail(f"status.json missing keys: {missing_status}")
    else:
        _ok("status.json contract OK")


def validate_transcript(job_dir: Path) -> dict[str, Any] | None:
    _section("Stage 03/03b — transcript.json")
    data = _load_json(job_dir / "transcript.json")
    if data is None:
        return None

    mode = data.get("alignment_mode", "whisper")
    _ok(f"alignment_mode: {mode}")

    segs = data.get("segments", [])
    if not segs:
        _fail("No segments found")
        return data
    _ok(f"Segments: {len(segs)}")

    # Schema check
    required_word_keys = {"word", "start", "end", "probability"}
    zero_dur = 0
    inverted = 0
    total_words = 0

    for i, seg in enumerate(segs):
        for key in ("text", "start", "end", "words"):
            if key not in seg:
                _fail(f"Segment {i} missing key '{key}'")

        if seg.get("start", 0) >= seg.get("end", 0):
            inverted += 1

        for w in seg.get("words", []):
            total_words += 1
            missing = required_word_keys - set(w.keys())
            if missing:
                _fail(f"Word '{w.get('word')}' missing keys: {missing}")
            if w.get("start", 0) >= w.get("end", 0):
                zero_dur += 1

    _ok(f"Total words: {total_words}")
    if inverted:
        _fail(f"{inverted} segment(s) with start >= end")
    else:
        _ok("All segment timestamps: start < end")

    if zero_dur:
        _warn(f"{zero_dur}/{total_words} words have start >= end (zero-duration — floor applied in s06)")
    else:
        _ok("All word timestamps: start < end")

    # Low-confidence report
    if mode == "whisper":
        all_words = [w for s in segs for w in s.get("words", [])]
        lc = [w for w in all_words if w.get("low_confidence")]
        if lc:
            pct = 100 * len(lc) / len(all_words)
            msg = f"Low-confidence words: {len(lc)}/{len(all_words)} ({pct:.0f}%)"
            if pct > 20:
                _warn(msg + " — consider using --lyrics")
            else:
                _ok(msg)

    # Section distribution (forced mode)
    if mode == "forced":
        dist = data.get("section_distribution", {})
        if len(dist) > 1:
            _ok(f"Section distribution: {dist}")
        else:
            _warn(f"Only 1 section type in transcript: {dist} — lyrics.txt may lack markers")

        # Unknown markers report (set by _parse_lyrics when a [Label] is unrecognized)
        unknown = data.get("unknown_section_markers", [])
        if unknown:
            _warn(
                f"Unknown section markers defaulted to 'verse': {sorted(set(unknown))} "
                f"— add to SECTION_TO_STYLE in s03b if these are real sections"
            )

    return data


# ---------------------------------------------------------------------------
# Stage 04 — aligned.json
# ---------------------------------------------------------------------------

def validate_aligned(job_dir: Path) -> dict[str, Any] | None:
    _section("Stage 04 — aligned.json")
    data = _load_json(job_dir / "aligned.json")
    if data is None:
        return None

    words = data.get("words", [])
    if not words:
        _fail("No words in aligned.json")
        return data
    _ok(f"Words: {len(words)}")

    # Source distribution
    sources: dict[str, int] = {}
    hfa = 0
    for w in words:
        s = w.get("source", "unknown")
        sources[s] = sources.get(s, 0) + 1
        if "hubertfa" in s:
            hfa += 1

    _ok(f"Source distribution: {sources}")

    total = len(words)
    if hfa == 0:
        fallback_sources = {"ctc_forced", "whisper_fallback"}
        if any("fallback" in str(source) or source in fallback_sources for source in sources):
            _warn("0% HubertFA alignment - using fallback timings")
        else:
            _fail("0% HubertFA alignment - no fallback source was recorded")
    elif hfa / total < 0.6:
        _warn(f"HubertFA rate {hfa}/{total} ({100*hfa//total}%) < 60% — many fallbacks")
    else:
        _ok(f"HubertFA alignment rate: {hfa}/{total} ({100*hfa//total}%)")

    # Timestamp monotonicity
    timestamp_errors = find_timestamp_errors(words)
    if not timestamp_errors:
        _ok("All word timestamps: start < end and monotonic")
    else:
        for error in timestamp_errors:
            _fail(error)

    # low_confidence propagation check
    lc_words = [w for w in words if w.get("low_confidence")]
    if lc_words:
        _ok(f"low_confidence propagated: {len(lc_words)} word(s) flagged")

    return data


# ---------------------------------------------------------------------------
# Stage 05 — analysis.json
# ---------------------------------------------------------------------------

def validate_analysis(job_dir: Path, transcript: dict | None, aligned: dict | None) -> dict | None:
    _section("Stage 05 — analysis.json")
    data = _load_json(job_dir / "analysis.json")
    if data is None:
        return None

    lines = data.get("lines", [])
    if not lines:
        _fail("No lines in analysis.json")
        return data
    _ok(f"Lines: {len(lines)}")

    # Schema check
    required = {"text", "start", "end", "style", "words"}
    valid_styles = {"verse", "prechorus", "chorus", "bridge", "drop", "intro", "outro", "ad_lib"}
    bad_styles = []

    for i, line in enumerate(lines):
        missing = required - set(line.keys())
        if missing:
            _fail(f"Line {i} missing keys: {missing}")
        style = line.get("style")
        if style not in valid_styles:
            bad_styles.append(style)
        if line.get("end", 0) <= line.get("start", 0):
            _fail(f"Line {i} '{line.get('text','')[:40]}' inverted timestamps")

    if bad_styles:
        _fail(f"Unknown styles: {set(bad_styles)}")
    else:
        _ok("All styles valid")

    # Style distribution
    style_dist: dict[str, int] = {}
    for line in lines:
        s = line.get("style", "verse")
        style_dist[s] = style_dist.get(s, 0) + 1
    _ok(f"Style distribution: {style_dist}")

    if len(style_dist) == 1 and aligned:
        _warn("Only 1 style in analysis — section detection may have failed")

    # Word coverage: every aligned word should appear in analysis
    if aligned:
        aligned_words = aligned.get("words", [])
        analysis_words = [
            w
            for line in lines
            for w in line.get("words", [])
        ]
        coverage_errors = find_word_coverage_errors(aligned_words, analysis_words)
        if coverage_errors:
            for error in coverage_errors:
                _fail(error)
        else:
            _ok(f"Word coverage: all {len(aligned_words)} aligned words present")

    # Check 1:1 mapping if alignment_mode == forced
    if transcript and transcript.get("alignment_mode") == "forced":
        n_segs = len(transcript.get("segments", []))
        if len(lines) < n_segs:
            _warn(
                f"analysis.json has {len(lines)} lines but transcript has {n_segs} segments "
                f"(LLM may have merged lines)"
            )
        elif len(lines) == n_segs:
            _ok(f"1:1 segment->line mapping: {n_segs} segments = {len(lines)} lines")

    return data


# ---------------------------------------------------------------------------
# Stage 06 — output.ass
# ---------------------------------------------------------------------------

def validate_ass(job_dir: Path) -> None:
    _section("Stage 06 — output.ass")
    ass_path = job_dir / "output.ass"
    if not ass_path.exists():
        _fail("output.ass not found")
        return

    content = ass_path.read_text(encoding="utf-8-sig", errors="replace")

    # Required sections
    for section in ("[Script Info]", "[V4+ Styles]", "[Events]"):
        if section not in content:
            _fail(f"Missing ASS section: {section}")
        else:
            _ok(f"Section present: {section}")

    # \kf tags
    if "\\kf" not in content:
        _fail("No \\kf tags — karaoke highlighting not applied")
    else:
        kf_count = content.count("\\kf")
        _ok(f"\\kf tags: {kf_count}")

    # Dialogue lines
    dialogues = [l for l in content.splitlines() if l.startswith("Dialogue")]
    n_lines = len(dialogues)
    if n_lines == 0:
        _fail("No Dialogue lines in ASS")
        return

    _ok(f"Dialogue lines: {n_lines}")

    # Timestamp checks
    inverted_ts = 0

    timestamps: list[tuple[int, int]] = []
    timestamps_by_layer: dict[int, list[tuple[int, int]]] = {}
    for d in dialogues:
        parts = d.split(",")
        if len(parts) < 3:
            continue
        try:
            layer = int(parts[0].split(":", 1)[1].strip())
            s_ms = _ts_to_ms(parts[1].strip())
            e_ms = _ts_to_ms(parts[2].strip())
        except (ValueError, IndexError):
            continue
        if e_ms <= s_ms:
            inverted_ts += 1
        timestamps.append((s_ms, e_ms))
        timestamps_by_layer.setdefault(layer, []).append((s_ms, e_ms))

    if inverted_ts:
        _fail(f"{inverted_ts} Dialogue lines with end ≤ start")
    else:
        _ok("All Dialogue timestamps: end > start")

    # Check overlaps within each ASS layer. Single-layer karaoke is the
    # default, but this keeps validation correct for imported/editable ASS.
    layer_overlaps: dict[int, int] = {}
    for layer, layer_timestamps in timestamps_by_layer.items():
        ordered = sorted(layer_timestamps)
        overlap_count = sum(
            1 for i in range(len(ordered) - 1)
            if ordered[i][1] > ordered[i + 1][0]
        )
        if overlap_count:
            layer_overlaps[layer] = overlap_count

    if layer_overlaps:
        details = ", ".join(
            f"layer {layer}: {count}" for layer, count in sorted(layer_overlaps.items())
        )
        _fail(f"display window overlap(s): {details}")
    else:
        _ok("No display window overlaps within ASS layers")


# ---------------------------------------------------------------------------
# Drift metrics — compare transcript.json vs reference_mapping.json
# ---------------------------------------------------------------------------

def validate_provenance(job_dir: Path) -> None:
    _section("Artifact Provenance Graph")

    ass_path = job_dir / "output.ass"
    current_ass_sha256: str | None = None
    if ass_path.exists():
        try:
            manifest = load_manifest(job_dir / "output.ass.manifest.json")
            validate_file_hash(ass_path, _manifest_sha(manifest, "outputs", "output.ass"))
            current_ass_sha256 = file_sha256(ass_path)
            _ok("output.ass hash matches output.ass.manifest.json")

            renderer_mode = manifest.get("renderer_mode")
            if renderer_mode != "single_layer_kf":
                _fail(f"output.ass renderer_mode must be single_layer_kf, got {renderer_mode!r}")
            else:
                _ok("renderer_mode: single_layer_kf")

            metrics = manifest.get("metrics")
            if not isinstance(metrics, dict):
                _fail("output.ass.manifest.json missing metrics")
            else:
                dialogue_count = _ass_dialogue_count(ass_path)
                if metrics.get("dialogue_count") != dialogue_count:
                    _fail(
                        "output.ass.manifest.json dialogue_count mismatch: "
                        f"{metrics.get('dialogue_count')} != {dialogue_count}"
                    )
                else:
                    _ok(f"ASS dialogue_count provenance OK: {dialogue_count}")

                analysis_path = job_dir / "analysis.json"
                if analysis_path.exists():
                    analysis = _load_json(analysis_path)
                    if isinstance(analysis, dict):
                        lines = analysis.get("lines", [])
                        if metrics.get("analysis_line_count") != len(lines):
                            _fail(
                                "output.ass.manifest.json analysis_line_count mismatch: "
                                f"{metrics.get('analysis_line_count')} != {len(lines)}"
                            )
                        else:
                            _ok(f"analysis_line_count provenance OK: {len(lines)}")

            inputs = manifest.get("inputs")
            if isinstance(inputs, dict) and "analysis.json" in inputs and (job_dir / "analysis.json").exists():
                validate_file_hash(job_dir / "analysis.json", _manifest_sha(manifest, "inputs", "analysis.json"))
                _ok("analysis.json hash matches output.ass.manifest.json")
        except ProvenanceError as exc:
            _fail(f"output.ass.manifest.json invalid: {exc}")
    else:
        _warn("output.ass absent - ASS provenance skipped")

    mp4_path = job_dir / "output.mp4"
    if not mp4_path.exists():
        _warn("output.mp4 absent - MP4 provenance skipped")
        return

    try:
        manifest = load_manifest(job_dir / "output.mp4.manifest.json")
        validate_file_hash(mp4_path, _manifest_sha(manifest, "outputs", "output.mp4"))
        _ok("output.mp4 hash matches output.mp4.manifest.json")

        expected_ass_sha256 = _manifest_sha(manifest, "inputs", "output.ass")
        if current_ass_sha256 is None:
            if not ass_path.exists():
                raise ProvenanceError("output.mp4.manifest.json declares output.ass but output.ass is missing")
            current_ass_sha256 = file_sha256(ass_path)
        if expected_ass_sha256 != current_ass_sha256:
            raise ProvenanceError(
                "output.mp4.manifest.json output.ass input hash mismatch: "
                f"{expected_ass_sha256} != {current_ass_sha256}"
            )
        _ok("output.mp4 input output.ass hash matches current output.ass")
    except ProvenanceError as exc:
        _fail(f"output.mp4.manifest.json invalid: {exc}")


def validate_drift(job_dir: Path, ref_path: Path | None, transcript: dict | None) -> None:
    _section("Drift Metrics — CTC vs Ground Truth")

    if transcript is None:
        _warn("No transcript data — skipping drift analysis")
        return

    # Auto-discover reference
    if ref_path is None:
        candidates = [
            job_dir / "reference_mapping.json",
            job_dir / "reference_timestamps.json",
        ]
        for c in candidates:
            if c.exists():
                ref_path = c
                break

    if ref_path is None or not ref_path.exists():
        _warn("No reference_mapping.json found — drift metrics skipped")
        _warn("To enable: pass --reference <path> or place reference_mapping.json in job_dir")
        return

    ref_data = _load_json(ref_path)
    if ref_data is None:
        return

    ref_lines = ref_data.get("lines", ref_data) if isinstance(ref_data, dict) else ref_data
    segs = transcript.get("segments", [])

    matched = min(len(segs), len(ref_lines))
    if matched == 0:
        _warn("No lines to compare")
        return

    drifts: list[float] = []
    outliers: list[tuple[int, str, float, float, float]] = []
    TOLERANCE = 3.0

    for i in range(matched):
        seg = segs[i]
        ref = ref_lines[i]
        ctc_start = seg.get("start", 0)
        ref_start = ref.get("reference_start_sec", ref.get("start_sec", 0))
        drift = abs(ctc_start - ref_start)
        drifts.append(drift)
        if drift > TOLERANCE:
            outliers.append((i, seg.get("text", "")[:40], ref_start, ctc_start, drift))

    p50  = _percentile(drifts, 50)
    p95  = _percentile(drifts, 95)
    mean = sum(drifts) / len(drifts)
    within = sum(1 for d in drifts if d <= TOLERANCE)

    _ok(f"Lines compared: {matched}")
    _ok(f"Mean drift:   {mean:.2f}s")
    _ok(f"Median (p50): {p50:.2f}s")

    if p95 > 5.0:
        _warn(f"p95 drift: {p95:.2f}s  (>5s — tail is heavy, pitch correction may not be enough)")
    elif p95 > 2.0:
        _warn(f"p95 drift: {p95:.2f}s  (>2s — acceptable but noticeable at outliers)")
    else:
        _ok(f"p95 drift: {p95:.2f}s  (excellent)")

    pct = 100 * within / matched
    if pct >= 95:
        _ok(f"Within {TOLERANCE}s tolerance: {within}/{matched} ({pct:.0f}%)")
    elif pct >= 85:
        _warn(f"Within {TOLERANCE}s tolerance: {within}/{matched} ({pct:.0f}%)")
    else:
        _fail(f"Within {TOLERANCE}s tolerance: {within}/{matched} ({pct:.0f}%) — below 85%")

    if outliers:
        print(f"\n  Outliers (drift > {TOLERANCE}s):")
        for idx, text, ref_s, ctc_s, d in outliers:
            annotation = ref_lines[idx].get("annotation", "")
            ann_str = f" [{annotation}]" if annotation else ""
            print(f"    [{idx:2d}] '{text}'{ann_str}")
            print(f"          ref={ref_s:.1f}s  ctc={ctc_s:.1f}s  diff{d:.1f}s")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    global _current_job_dir
    _failures.clear()
    _warnings.clear()
    parser = argparse.ArgumentParser(
        description="Stage 08 — Pipeline contract tests and quality metrics.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--job-dir",   required=True, type=Path)
    parser.add_argument("--reference", type=Path, default=None,
                        help="Path to reference_mapping.json for drift metrics.")
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    job_dir = args.job_dir.resolve()
    _current_job_dir = job_dir
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    print(f"\n{'=' * 60}")
    print(f"  Pipeline Validation — {job_dir.name}")
    print(f"{'=' * 60}")

    write_event(job_dir, "validation_started", "validating")
    unexpected_error = ""
    try:
        validate_job_contracts(job_dir)
        transcript = validate_transcript(job_dir)
        aligned    = validate_aligned(job_dir)
        validate_analysis(job_dir, transcript, aligned)
        validate_ass(job_dir)
        validate_provenance(job_dir)
        validate_drift(job_dir, args.reference, transcript)
    except Exception as exc:
        unexpected_error = str(exc)
        _fail(f"Unexpected validation error: {unexpected_error}")
    finally:
        _current_job_dir = None

    # -- Summary -----------------------------------------------------------
    print(f"\n{'=' * 60}")
    if _failures:
        print(f"  {_RED}FAILED{_RESET} — {len(_failures)} contract violation(s):")
        for f in _failures:
            print(f"    {_RED}[FAIL]{_RESET}  {f}")
    else:
        print(f"  {_GREEN}PASSED{_RESET} — all contract tests OK")

    if _warnings:
        print(f"\n  {_YELLOW}{len(_warnings)} warning(s):{_RESET}")
        for w in _warnings:
            print(f"    {_YELLOW}[WARN]{_RESET}  {w}")
    print(f"{'=' * 60}\n")

    exit_code = 1 if _failures else 0
    write_event(
        job_dir,
        "validation_finished",
        "validating",
        level="error" if _failures else "info",
        message="validation failed" if _failures else "validation passed",
        details={
            "exit_code": exit_code,
            "failure_count": len(_failures),
            "warning_count": len(_warnings),
            "failures": list(_failures),
            "warnings": list(_warnings),
        },
    )
    build_observability_summary(job_dir)
    if unexpected_error:
        raise RuntimeError(unexpected_error)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
