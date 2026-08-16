"""
s03b_lyrics_align.py — Forced lyric alignment via CTC + MMS Wav2Vec2.

Bypasses Whisper entirely when lyrics.txt is available. Instead of
transcribing (asking "what is being sung?"), this script aligns (asking
"when is each known word being sung?") — the same paradigm used by
MyKaraoke Video, Youka, and Capify.

Why this beats Whisper for karaoke when lyrics exist:
    - Whisper was trained on speech, not singing. VAD removes sustained
      notes. Greedy beam=1 hallucinates on sparse/extended vocals.
    - Forced alignment takes the known lyrics as ground truth and finds
      the precise timestamp for each word. Zero hallucination possible.
    - For "Struggle"-type songs (long instrumental intro, sparse vocals,
      scream sections), forced alignment is the only reliable approach.

Model: MahmoudAshraf/mms-300m-1130-forced-aligner (~1.2 GB)
    - Downloaded automatically on first run to ~/.cache/huggingface/
    - Supports 1130+ languages via Meta's Massively Multilingual Speech
    - Runs on CPU (no DirectML/CUDA required — same constraint as Whisper)

Hardware note (Z13 AMD iGPU):
    ctc-forced-aligner uses PyTorch CPU path. The model runs efficiently
    on the Z13's CPU for songs up to ~10 minutes. DirectML is not needed
    here — HubertFA in Stage 04 handles the GPU-accelerated work.

Output schema: identical to s03_transcribe.py transcript.json so Stage 04
(HubertFA) and Stage 05 (Ollama) work without any modification.

Additional fields in transcript.json (not present in Whisper output):
    alignment_mode: "forced"           — signals downstream that lyrics
                                         are ground truth
    segments[*].section: "chorus"      — section label from lyrics.txt
                                         used by s05 to skip LLM style
                                         inference

Usage (auto — called by test_pipeline.py when lyrics.txt exists):
    python scripts/s03b_lyrics_align.py
        --job-dir jobs/my-job
        --lyrics  jobs/my-job/lyrics.txt

Usage (explicit language):
    python scripts/s03b_lyrics_align.py
        --job-dir jobs/my-job
        --lyrics  jobs/my-job/lyrics.txt
        --language jpn

Pitch-guided boundary correction (pYIN):
    After CTC alignment, pYIN (via librosa) detects note onsets in the
    vocals.wav. Each CTC word boundary is snapped to the nearest note
    onset within a ±1.5s window. This is the same technique used by
    Spotify Research to improve alignment accuracy on sustained notes
    and melismatic transitions — the main failure mode of generic CTC
    aligners on singing voice.

    The correction is conservative: if a snap would invert a word
    boundary relative to its neighbor, it is discarded. The original
    CTC timestamp is kept as fallback.

Reads:
    jobs/{job_id}/vocals.wav
    <lyrics_path>               (lyrics.txt with [Section] markers)

Writes:
    jobs/{job_id}/transcript.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root
sys.path.insert(0, str(Path(__file__).parent))                    # scripts/ dir
from hw_detect import detect
try:
    from scripts.common.observability import write_event
except ModuleNotFoundError:
    from common.observability import write_event
try:
    from scripts.common.config import load_app_config as _load_cfg
except ModuleNotFoundError:
    from common.config import load_app_config as _load_cfg
_cfg = _load_cfg()

# Fix Windows encoding issues for checkmark/cross symbols
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, io.UnsupportedOperation):
        pass

logger = logging.getLogger(__name__)

MERGE_GAP_SECONDS = 1.20
MIN_REGION_SECONDS = 0.80
MIN_VOCAL_PROB = 0.35
LONG_GAP_SECONDS = 8.0
WINDOW_PADDING_BEFORE = 0.30
WINDOW_PADDING_AFTER = 0.50
CTC_SAMPLE_RATE = 16000
CTC_MAX_CHARS_PER_SECOND = 35.0
MIN_WINDOW_VOCAL_OVERLAP_RATIO = 0.50
MAX_WINDOW_TO_ESTIMATED_DURATION_RATIO = 3.0
MIN_WINDOW_WORDS_PER_SECOND = 0.25

# ISO-639-3 language codes for the MMS model.
# Different from Whisper's ISO-639-1 codes (en → eng, ja → jpn, pt → por).
LANGUAGE_MAP = {
    "en": "eng", "ja": "jpn", "pt": "por", "zh": "zho",
    "es": "spa", "fr": "fra", "de": "deu", "ko": "kor",
    "ar": "ara", "ru": "rus", "it": "ita", "nl": "nld",
}

# Section label → style name (used by s05 to bypass LLM style inference)
# Canonical section label → ASS style name.
# Keys are lowercase, stripped. Add new genres / DAWs here as discovered.
SECTION_TO_STYLE: dict[str, str] = {
    # ── Intro / Outro ───────────────────────────────────────────────────
    "intro":            "intro",
    "introduction":     "intro",
    "opening":          "intro",
    "outro":            "outro",
    "outro chorus":     "outro",
    "outro hook":       "outro",
    "ending":           "outro",
    "fade out":         "outro",
    "fade-out":         "outro",
    "coda":             "outro",
    # ── Verse ───────────────────────────────────────────────────────────
    "verse":            "verse",
    "verse 1":          "verse",
    "verse 2":          "verse",
    "verse 3":          "verse",
    "estrofe":          "verse",   # Portuguese
    "estrofa":          "verse",   # Spanish
    "rap":              "rap",     # bare [Rap], common in Suno / pt-BR lyrics
    "rap verse":        "verse",
    "spoken":           "verse",
    "spoken word":      "verse",
    # ── Chorus / Hook ───────────────────────────────────────────────────
    "chorus":           "chorus",
    "chorus 2":         "chorus",
    "chorus 3":         "chorus",
    "refrao":           "chorus",  # Portuguese (no accent)
    "refrão":           "chorus",  # Portuguese (with accent)
    "refrán":           "chorus",  # Spanish
    "hook":             "chorus",
    "hook 2":           "chorus",
    "drop":             "chorus",  # EDM
    "drop 1":           "chorus",
    "drop 2":           "chorus",
    "big chorus":       "chorus",
    "final chorus":     "chorus",
    "climax":           "chorus",
    # ── Pre-Chorus ──────────────────────────────────────────────────────
    # Every preset defines a PreChorus style; mapping these to "verse" threw
    # that distinction away. The style library already said "prechorus" — this
    # map was the outlier, and s05 was quietly correcting it until s03b started
    # carrying the style itself.
    "pre-chorus":       "prechorus",
    "pre-chorus 2":     "prechorus",
    "pre chorus":       "prechorus",
    "pre-hook":         "prechorus",
    "lift":             "prechorus",   # some EDM / pop labels
    "build":            "prechorus",
    "build-up":         "prechorus",
    "buildup":          "prechorus",
    # ── Bridge / Breakdown ──────────────────────────────────────────────
    "bridge":           "bridge",
    "ponte":            "bridge",  # Portuguese/Spanish
    "breakdown":        "bridge",
    "break":            "bridge",
    "interlude":        "bridge",
    "guitar solo":      "bridge",
    "solo":             "bridge",
    "instrumental":     "bridge",
    "instrumental break":"bridge",
    "spoken bridge":    "bridge",
    "dialogue":         "bridge",
    "transition":       "bridge",
    "middle 8":         "bridge",
    "middle eight":     "bridge",
}

# Prefix-based fallback mapping (tried when exact label not found).
# If a label STARTS WITH a prefix, it maps to that style.
_SECTION_PREFIX_FALLBACK: dict[str, str] = {
    "verse":    "verse",
    "chorus":   "chorus",
    "refra":    "chorus",   # refrão / refrán
    "hook":     "chorus",
    "drop":     "chorus",
    "bridge":   "bridge",
    "pont":     "bridge",   # ponte
    "break":    "bridge",
    "pre":      "prechorus",  # pre-chorus / pre-hook
    "intro":    "intro",
    "outro":    "outro",
    "solo":     "bridge",
    "interl":   "bridge",
    "instru":   "bridge",
    "build":    "prechorus",
    "spoken":   "verse",
    "coda":     "outro",
}


# ---------------------------------------------------------------------------
# Lyrics parser
# ---------------------------------------------------------------------------

def _resolve_section(label: str) -> tuple[str, str]:
    """
    Map a raw section label to a canonical section key and ASS style.

    Resolution order:
    1. Exact match in SECTION_TO_STYLE
    2. Numbered suffix strip: "chorus 3" → "chorus"
    3. Prefix match in _SECTION_PREFIX_FALLBACK
    4. Default "verse" (logged as unknown)

    Returns (canonical_label, style_name).
    """
    # 1. Exact match
    if label in SECTION_TO_STYLE:
        return label, SECTION_TO_STYLE[label]

    # 2. Strip trailing number/parenthetical and retry
    # "chorus 3" → "chorus", "verse (2)" → "verse"
    stripped = re.sub(r"[\s\d\(\)]+$", "", label).strip()
    if stripped and stripped in SECTION_TO_STYLE:
        return stripped, SECTION_TO_STYLE[stripped]

    # 3. Prefix fallback
    for prefix, style in _SECTION_PREFIX_FALLBACK.items():
        if label.startswith(prefix):
            # Return a normalized label so downstream grouping works
            return label, style

    # 4. Unknown — return as-is with verse style; caller logs the marker
    return label, "verse"


def _is_stage_direction(label: str) -> bool:
    """
    Heuristic: is this [Label] a stage direction rather than a section marker?

    Stage directions tend to be verbose descriptive phrases:
    "Heavy Wall of Sound", "Drums kick in", "Raw Scream", etc.
    Section markers are short: "Chorus", "Verse", "Bridge".

    Rules (in order):
    1. If label is already a known section → NOT a stage direction.
    2. If label has more than 4 words → IS a stage direction.
    3. If label contains a stage-direction-specific keyword → IS a stage direction.
       Keywords are deliberately narrow to avoid false-positives on labels
       like "guitar solo" or "spoken word" that are valid section names.
    """
    # Rule 1: known sections are never stage directions
    if label in SECTION_TO_STYLE:
        return False
    stripped = re.sub(r"[\s\d\(\)]+$", "", label).strip()
    if stripped and stripped in SECTION_TO_STYLE:
        return False

    # Rule 2: word count threshold
    words = label.split()
    if len(words) > 4:
        return True

    # Rule 3: stage-specific keywords — deliberately narrow.
    # Excludes "guitar", "spoken", "bass", "solo" which are valid section names.
    direction_keywords = {
        # Percussion / instruments
        "drums", "kick", "snare", "hi-hat", "bass", "guitar",
        # Texture / dynamics
        "wall of", "riff", "melody", "tempo", "groove", "volume",
        "heavy", "loud", "soft", "slow", "fast", "staccato",
        # Vocal technique
        "scream", "whisper", "adlib", "ad lib", "backing", "vocal",
        "acapella", "a cappella", "monotone", "strain",
        # Production terms
        "instrumental only", "music only", "instrumental break",
        "ambient", "noise", "drone", "pad",
        "distortion", "feedback", "reverb", "echo",
        # Emotional/intensity descriptors (when NOT a section label)
        "tension", "energy", "build up", "climactic", "emotional",
        "chaotic", "explosion", "heavy groove",
        "cracks with", "maximum",
        "long instrumental", "long intro", "long outro",
        "short instrumental", "extended",
        "half time", "double time", "time signature",
    }
    return any(kw in label for kw in direction_keywords)


def _parse_lyrics(lyrics_path: Path) -> list[dict[str, str]]:
    """
    Parse lyrics.txt into a list of section-aware lyric line dicts.

    Returns:
        [{"text": "Cause I'm still here", "section": "chorus"}, ...]

    Resolution:
        - Pure [Label] lines: resolved via _resolve_section() with fallback chain
        - Verbose stage direction lines: skipped (do not update section)
        - Unknown markers: assigned "verse" style, original label preserved for
          s08_validate to report ("unknown section markers detected")
        - Inline [directions] stripped from text
        - Parentheticals are preserved unless the whole line is a stage direction
    """
    section_only_re = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    bracket_dir_re  = re.compile(r"\[[^\]]*\]")
    paren_only_re   = re.compile(r"^\(([^)]*)\)$")
    word_re         = re.compile(r"[a-zA-Z''\u00C0-\u024F]+")

    current_section  = "verse"
    current_style    = "verse"
    unknown_markers: list[str] = []
    lines: list[dict[str, str]] = []
    pending_blank = False
    pending_section_break = False

    for raw_line in lyrics_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            pending_blank = bool(lines)
            continue

        # Pure section marker line
        m = section_only_re.match(stripped)
        if m:
            raw_label = m.group(1).strip()
            label     = raw_label.lower()

            # Skip verbose stage directions (they don't change section)
            if _is_stage_direction(label):
                logger.debug("Stage direction skipped: [%s]", raw_label)
                continue

            canonical, style = _resolve_section(label)

            if style == "verse" and canonical not in SECTION_TO_STYLE:
                # Genuinely unknown — track for s08 reporting
                unknown_markers.append(raw_label)
                logger.warning(
                    "Unknown section marker [%s] — defaulting to 'verse'. "
                    "Add to SECTION_TO_STYLE if this is a real section.",
                    raw_label,
                )
            else:
                logger.debug("Section: [%s] → %s (%s)", raw_label, canonical, style)

            current_section = canonical
            # Keep the style s03b just resolved; s05 must not re-derive it from
            # its own smaller map, which disagrees on 31 of these 56 labels.
            current_style   = style
            pending_section_break = bool(lines)
            continue

        paren_match = paren_only_re.match(stripped)
        if paren_match and _is_stage_direction(paren_match.group(1).strip().lower()):
            continue
        if stripped.startswith("(") and ")" not in stripped:
            continue

        # Strip square-bracket stage directions from text lines.
        clean = bracket_dir_re.sub("", stripped).strip()
        # Must have at least one alphabetic word to be singable
        if not word_re.search(clean):
            continue

        line_id = f"L{len(lines) + 1:03d}"
        lines.append({
            "text":             clean,
            "section":          current_section,
            "style":            current_style,
            "unknown_markers":  unknown_markers.copy() if unknown_markers else [],
            "line_id":          line_id,
            "line_index":       len(lines),
            "blank_before":     pending_blank,
            "section_break_before": pending_section_break,
        })
        pending_blank = False
        pending_section_break = False

    if unknown_markers:
        logger.warning(
            "Encountered %d unknown section marker(s): %s. "
            "These were defaulted to 'verse'. "
            "s08_validate will report them.",
            len(set(unknown_markers)),
            sorted(set(unknown_markers)),
        )

    return lines


def _lyrics_observability_details(
    lyrics_path: Path,
    lyric_lines: list[dict[str, str]],
) -> dict[str, Any]:
    section_only_re = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    stage_direction_count = 0
    for raw_line in lyrics_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        match = section_only_re.match(stripped)
        if match and _is_stage_direction(match.group(1).strip().lower()):
            stage_direction_count += 1

    unknown_markers = sorted(set(
        marker
        for line in lyric_lines
        for marker in line.get("unknown_markers", [])
    ))
    sections = sorted({line.get("section", "verse") for line in lyric_lines})
    return {
        "line_count": len(lyric_lines),
        "section_count": len(sections),
        "sections": sections,
        "unknown_marker_count": len(unknown_markers),
        "unknown_markers": unknown_markers,
        "stage_direction_stripped_count": stage_direction_count,
    }


def _word_count(text: str) -> int:
    return len(re.findall(r"[a-zA-Z''\u00C0-\u024F]+", text))


def _repetition_signature(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _build_lyrics_blocks(lyric_lines: list[dict[str, Any]], max_lines: int = 6) -> list[dict[str, Any]]:
    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append(current)
            current = []

    for line in lyric_lines:
        if current and (line.get("blank_before") or line.get("section_break_before") or len(current) >= max_lines):
            flush()
        current.append(line)
    flush()

    result: list[dict[str, Any]] = []
    for index, block_lines in enumerate(blocks, start=1):
        text = " ".join(str(line["text"]) for line in block_lines)
        words = _word_count(text)
        sections = {str(line.get("section", "verse")) for line in block_lines}
        result.append({
            "block_id": f"B{index:03d}",
            "start_line_index": int(block_lines[0].get("line_index", index - 1)),
            "end_line_index": int(block_lines[-1].get("line_index", index - 1)),
            "line_ids": [str(line.get("line_id", f"L{i + 1:03d}")) for i, line in enumerate(block_lines)],
            "text": text,
            "word_count": words,
            "line_count": len(block_lines),
            "estimated_duration_min": round(max(0.5, words / 5.5), 3),
            "estimated_duration_max": round(max(1.5, words / 0.8), 3),
            "section_hint": next(iter(sections)) if len(sections) == 1 else "mixed",
            "language_hint": "mixed",
            "contains_parentheticals": "(" in text and ")" in text,
            "repetition_signature": _repetition_signature(text),
        })
    return result


def _region_start(region: dict[str, Any]) -> float:
    return float(region.get("start", region.get("start_s", 0.0)) or 0.0)


def _region_end(region: dict[str, Any]) -> float:
    return float(region.get("end", region.get("end_s", 0.0)) or 0.0)


def _region_prob(region: dict[str, Any]) -> float:
    return float(region.get("vocal_prob", region.get("voiced_ratio", 0.0)) or 0.0)


def _normalize_vocal_regions(
    regions: list[dict[str, Any]],
    merge_gap_s: float = MERGE_GAP_SECONDS,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for region in sorted(regions, key=_region_start):
        start = _region_start(region)
        end = _region_end(region)
        if end <= start:
            continue
        prob = _region_prob(region)
        if merged and start - merged[-1]["end"] <= merge_gap_s:
            prev = merged[-1]
            prev_duration = prev["end"] - prev["start"]
            duration = end - start
            total = max(0.001, prev_duration + duration)
            prev["end"] = max(prev["end"], end)
            prev["vocal_prob"] = round((prev["vocal_prob"] * prev_duration + prob * duration) / total, 4)
            prev["source_region_count"] += 1
            continue
        merged.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "vocal_prob": round(prob, 4),
            "source_region_count": 1,
        })

    for index, region in enumerate(merged, start=1):
        duration = region["end"] - region["start"]
        region["region_id"] = f"VR{index:03d}"
        region["duration"] = round(duration, 3)
        region["weak"] = duration < MIN_REGION_SECONDS or region["vocal_prob"] < MIN_VOCAL_PROB
    return merged


def _build_vocal_region_groups(
    vocal_regions: list[dict[str, Any]],
    max_group_size: int = 3,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for start_idx in range(len(vocal_regions)):
        for end_idx in range(start_idx, min(start_idx + max_group_size, len(vocal_regions))):
            group_regions = vocal_regions[start_idx : end_idx + 1]
            if any(
                group_regions[i + 1]["start"] - group_regions[i]["end"] >= LONG_GAP_SECONDS
                for i in range(len(group_regions) - 1)
            ):
                break
            duration = group_regions[-1]["end"] - group_regions[0]["start"]
            mean_prob = sum(region["vocal_prob"] for region in group_regions) / len(group_regions)
            groups.append({
                "region_ids": [region["region_id"] for region in group_regions],
                "start": group_regions[0]["start"],
                "end": group_regions[-1]["end"],
                "duration": round(duration, 3),
                "mean_vocal_prob": round(mean_prob, 4),
                "start_region_index": start_idx,
                "end_region_index": end_idx,
                "weak": any(region["weak"] for region in group_regions),
            })
    return groups


def _interval_overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _build_vocal_islands(vocal_regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    islands: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    for region in vocal_regions:
        if current and float(region["start"]) - float(current[-1]["end"]) >= LONG_GAP_SECONDS:
            islands.append(current)
            current = []
        current.append(region)
    if current:
        islands.append(current)

    result: list[dict[str, Any]] = []
    for index, island_regions in enumerate(islands, start=1):
        start = float(island_regions[0]["start"])
        end = float(island_regions[-1]["end"])
        result.append({
            "island_id": f"VI{index:03d}",
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "region_ids": [str(region["region_id"]) for region in island_regions],
            "region_count": len(island_regions),
            "internal_long_gaps": 0,
            "weak": all(bool(region.get("weak")) for region in island_regions),
        })
    return result


def _violation(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "severity": "fail", **details}


def _evaluate_ctc_window_safety(
    *,
    windows: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    vocal_regions: list[dict[str, Any]],
    non_vocal_gaps: list[dict[str, Any]],
    vocal_islands: list[dict[str, Any]],
    full_audio_duration: float | None = None,
) -> dict[str, Any]:
    blocks_by_id = {str(block.get("block_id")): block for block in blocks}
    assignments_by_id = {str(assignment.get("block_id")): assignment for assignment in assignments}
    report_windows: list[dict[str, Any]] = []

    for window in windows:
        block_id = str(window.get("block_id"))
        block = blocks_by_id.get(block_id, {})
        assignment = assignments_by_id.get(block_id, {})
        start = float(window.get("audio_start", 0.0) or 0.0)
        end = float(window.get("audio_end", start) or start)
        duration = max(0.0, end - start)
        word_count = int(block.get("word_count", 0) or 0)
        character_count = len(re.sub(r"\s+", "", str(block.get("text", ""))))
        estimated_max = float(block.get("estimated_duration_max", max(duration, 1.0)) or 1.0)
        vocal_overlap = sum(
            _interval_overlap_seconds(start, end, float(region["start"]), float(region["end"]))
            for region in vocal_regions
        )
        non_vocal_overlap = sum(
            _interval_overlap_seconds(
                start,
                end,
                float(gap.get("start", 0.0) or 0.0),
                float(gap.get("end", gap.get("start", 0.0)) or 0.0),
            )
            for gap in non_vocal_gaps
        )
        long_gap_overlaps = [
            {
                "gap_start": float(gap.get("start", 0.0) or 0.0),
                "gap_end": float(gap.get("end", gap.get("start", 0.0)) or 0.0),
                "gap_duration": float(gap.get("duration", 0.0) or 0.0),
                "overlap_seconds": round(_interval_overlap_seconds(
                    start,
                    end,
                    float(gap.get("start", 0.0) or 0.0),
                    float(gap.get("end", gap.get("start", 0.0)) or 0.0),
                ), 3),
            }
            for gap in non_vocal_gaps
            if float(gap.get("duration", 0.0) or 0.0) >= LONG_GAP_SECONDS
            and _interval_overlap_seconds(
                start,
                end,
                float(gap.get("start", 0.0) or 0.0),
                float(gap.get("end", gap.get("start", 0.0)) or 0.0),
            ) > 0
        ]
        touched_islands = [
            str(island["island_id"])
            for island in vocal_islands
            if _interval_overlap_seconds(start, end, float(island["start"]), float(island["end"])) > 0
        ]
        vocal_overlap_ratio = vocal_overlap / duration if duration else 0.0
        non_vocal_overlap_ratio = non_vocal_overlap / duration if duration else 0.0
        words_per_second = word_count / duration if duration else 0.0
        characters_per_second = character_count / duration if duration else 0.0
        duration_ratio = duration / max(estimated_max, 1.0)

        violations: list[dict[str, Any]] = []
        if not assignment or "unassigned" in assignment.get("flags", []) or not assignment.get("region_ids"):
            violations.append(_violation("block_unassigned"))
        elif float(assignment.get("confidence", 0.0) or 0.0) < 0.45:
            violations.append(_violation("block_assignment_low_confidence"))
        for gap in long_gap_overlaps:
            violations.append(_violation("crosses_long_non_vocal_gap", **gap))
        if len(touched_islands) > 1:
            violations.append(_violation("window_contains_multiple_vocal_islands", island_ids=touched_islands))
        if vocal_overlap_ratio < MIN_WINDOW_VOCAL_OVERLAP_RATIO:
            violations.append(_violation("window_low_vocal_overlap", vocal_overlap_ratio=round(vocal_overlap_ratio, 4)))
        if duration_ratio > MAX_WINDOW_TO_ESTIMATED_DURATION_RATIO or words_per_second < MIN_WINDOW_WORDS_PER_SECOND:
            violations.append(_violation(
                "window_too_wide_for_block",
                window_to_estimated_duration_ratio=round(duration_ratio, 4),
                words_per_second_if_full_window=round(words_per_second, 4),
            ))
        if characters_per_second > CTC_MAX_CHARS_PER_SECOND:
            violations.append(_violation(
                "ctc_target_too_dense_for_window",
                characters_per_second_if_full_window=round(characters_per_second, 4),
                max_characters_per_second=CTC_MAX_CHARS_PER_SECOND,
            ))
        if full_audio_duration and full_audio_duration > 0 and duration / full_audio_duration >= 0.90:
            violations.append(_violation("window_matches_full_audio_or_near_full_audio"))

        report_windows.append({
            "block_id": block_id,
            "line_ids": window.get("line_ids", []),
            "window_start": round(start, 3),
            "window_end": round(end, 3),
            "duration": round(duration, 3),
            "safe_for_ctc": not violations,
            "violations": violations,
            "warnings": [],
            "metrics": {
                "vocal_overlap_ratio": round(vocal_overlap_ratio, 4),
                "non_vocal_overlap_ratio": round(non_vocal_overlap_ratio, 4),
                "long_gap_overlap_seconds": round(sum(gap["overlap_seconds"] for gap in long_gap_overlaps), 3),
                "words_per_second_if_full_window": round(words_per_second, 4),
                "characters_per_second_if_full_window": round(characters_per_second, 4),
                "window_to_estimated_duration_ratio": round(duration_ratio, 4),
            },
            "recommendation": "use_window_for_ctc" if not violations else "split_block_or_reassign_to_single_vocal_island",
        })

    unsafe = [window for window in report_windows if not window["safe_for_ctc"]]
    return {
        "source": "ctc_window_safety_evaluator",
        "safe_for_ctc": not unsafe,
        "summary": {
            "total_windows": len(report_windows),
            "safe_windows": len(report_windows) - len(unsafe),
            "unsafe_windows": len(unsafe),
            "long_gap_crossing_windows": sum(
                any(v["code"] == "crosses_long_non_vocal_gap" for v in window["violations"])
                for window in report_windows
            ),
            "overwide_windows": sum(
                any(v["code"] == "window_too_wide_for_block" for v in window["violations"])
                for window in report_windows
            ),
            "multi_region_ambiguous_windows": sum(
                any(v["code"] == "window_contains_multiple_vocal_islands" for v in window["violations"])
                for window in report_windows
            ),
        },
        "windows": report_windows,
    }


def _score_block_region_pair(
    block: dict[str, Any],
    group: dict[str, Any],
    repeated_signatures: set[str] | None = None,
) -> dict[str, Any]:
    duration = max(0.001, float(group["duration"]))
    min_dur = float(block.get("estimated_duration_min", 0.5))
    max_dur = float(block.get("estimated_duration_max", max(min_dur, 1.5)))
    if min_dur <= duration <= max_dur:
        duration_mismatch = 0.0
    else:
        duration_mismatch = min(1.0, min(abs(duration - min_dur), abs(duration - max_dur)) / max(max_dur, 0.001))

    low_vocal_probability = 1.0 - max(0.0, min(1.0, float(group.get("mean_vocal_prob", 0.0))))
    density = int(block.get("word_count", 0)) / duration
    density_mismatch = 0.0 if 0.35 <= density <= 6.0 else min(1.0, abs(density - 3.0) / 6.0)
    repetition_ambiguity = 0.2 if repeated_signatures and block.get("repetition_signature") in repeated_signatures else 0.0
    gap_inconsistency = 0.0
    cost = (
        0.40 * duration_mismatch
        + 0.25 * low_vocal_probability
        + 0.15 * gap_inconsistency
        + 0.10 * density_mismatch
        + 0.10 * repetition_ambiguity
    )
    flags: list[str] = []
    if group.get("weak"):
        flags.append("weak_region")
        cost += 0.25
    return {
        "cost": round(cost, 4),
        "confidence": round(max(0.0, min(1.0, 1.0 - cost)), 4),
        "score_breakdown": {
            "duration_fit": round(1.0 - duration_mismatch, 4),
            "vocal_probability": round(1.0 - low_vocal_probability, 4),
            "order_consistency": 1.0,
            "gap_consistency": round(1.0 - gap_inconsistency, 4),
            "density_fit": round(1.0 - density_mismatch, 4),
            "repetition_penalty": round(repetition_ambiguity, 4),
        },
        "flags": flags,
    }


def _skip_region_penalty(group: dict[str, Any]) -> float:
    return 0.15 if group.get("weak") else 0.80


# Finer probe settings tried, in order, when the default gap merges a densely
# sung track into regions too coarse to place the blocks in.
REPROBE_STEPS: tuple[tuple[float, float], ...] = ((0.40, 0.35), (0.30, 0.30), (0.22, 0.25), (0.15, 0.20))


def _best_regions_for_blocks(
    candidates: list[list[dict[str, Any]]],
    blocks: list[dict[str, Any]],
    non_vocal_gaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pick the region granularity whose windows the safety evaluator likes best.

    Too coarse and every window is a mega-region ("too wide"); too fine and each
    window is a sliver its block cannot fit in ("too dense"). Rather than guess a
    merge gap per song, build the windows for each candidate and keep the safest.
    Equally safe candidates are separated by how many windows had to be subdivided:
    a subdivided window is a guess inside a region, a real region boundary is not.
    """
    best: list[dict[str, Any]] | None = None
    best_key = (-1, 0)
    for regions in candidates:
        if not regions:
            continue
        assignments = _assign_blocks_to_regions(blocks, _build_vocal_region_groups(regions))
        windows = _build_alignment_windows(assignments)
        report = _evaluate_ctc_window_safety(
            windows=windows,
            blocks=blocks,
            assignments=assignments,
            vocal_regions=regions,
            non_vocal_gaps=non_vocal_gaps,
            vocal_islands=_build_vocal_islands(regions),
            full_audio_duration=max([float(region.get("end", 0.0) or 0.0) for region in regions] + [0.0]),
        )
        guessed = sum(1 for item in assignments if "region_subdivided" in item.get("flags", []))
        key = (int(report["summary"]["safe_windows"]), -guessed)
        if key > best_key:
            best, best_key = regions, key
    return best if best is not None else (candidates[0] if candidates else [])


def _regions_for_blocks(
    job_dir: Path,
    regions: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    non_vocal_gaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the vocal regions to build windows from, re-probing finer if it helps.

    A track sung end to end merges into a couple of mega-regions at the default
    0.5s gap, so every block would share the same 100s window. Probing finer
    recovers the phrase structure that is actually there.
    """
    candidates = [regions]
    vocals_path = job_dir / "vocals.wav"
    if vocals_path.exists():
        try:
            from scripts.review_wizard.vocal_activity import VocalActivityProbe

            probe = VocalActivityProbe.from_wav(vocals_path)
            duration_s = float(probe.frame_times_s[-1]) if len(probe.frame_times_s) else 0.0
            for merge_gap_s, min_duration_s in REPROBE_STEPS:
                probed = probe.voiced_regions(
                    0.0, duration_s, min_duration_s=min_duration_s, merge_gap_s=merge_gap_s
                )
                candidates.append(_normalize_vocal_regions(
                    [
                        {
                            "start": region["start_s"],
                            "end": region["end_s"],
                            "vocal_prob": region["voiced_ratio"],
                            "type": "probable_vocal",
                        }
                        for region in probed
                    ],
                    merge_gap_s=merge_gap_s,
                ))
        except Exception as exc:  # probing is best-effort; the coarse regions still work
            logging.getLogger(__name__).warning("Region re-probe failed: %s", exc)
    return _best_regions_for_blocks(candidates, blocks, non_vocal_gaps)


def _block_duration_weight(block: dict[str, Any]) -> float:
    """How much of a shared region this block should get: its expected duration."""
    low = float(block.get("estimated_duration_min", 0.0) or 0.0)
    high = float(block.get("estimated_duration_max", 0.0) or 0.0)
    weight = (low + high) / 2.0 if high else low
    return weight if weight > 0 else 1.0


def _subdivide_shared_windows(
    assignments: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Give each block its own slice of a region several blocks were sent to.

    Both assignment paths can land consecutive blocks on the same region (the
    distributed reuse branch, and the DP's ``must_reuse`` rewind). Identical
    windows carry no information and are rejected downstream as too wide, so the
    shared span is split between them by expected duration.
    """
    weights_by_id = {str(block["block_id"]): _block_duration_weight(block) for block in blocks}
    result: list[dict[str, Any]] = []
    index = 0
    while index < len(assignments):
        run = [assignments[index]]
        while index + len(run) < len(assignments):
            candidate = assignments[index + len(run)]
            if (
                candidate.get("window_start") != run[0].get("window_start")
                or candidate.get("window_end") != run[0].get("window_end")
                or candidate.get("window_start") is None
            ):
                break
            run.append(candidate)
        if len(run) > 1:
            spans = _subdivide_span(
                float(run[0]["window_start"]),
                float(run[0]["window_end"]),
                [weights_by_id.get(str(item["block_id"]), 1.0) for item in run],
            )
            for item, (span_start, span_end) in zip(run, spans):
                item["window_start"] = span_start
                item["window_end"] = span_end
                item["flags"] = list(item.get("flags", [])) + ["region_subdivided"]
        result.extend(run)
        index += len(run)
    return result


def _subdivide_span(start: float, end: float, weights: list[float]) -> list[tuple[float, float]]:
    """Split ``[start, end]`` into consecutive slices proportional to ``weights``."""
    if len(weights) <= 1:
        return [(round(start, 3), round(end, 3))]
    total = sum(weights)
    if total <= 0:
        weights = [1.0] * len(weights)
        total = float(len(weights))
    spans: list[tuple[float, float]] = []
    cursor = start
    for index, weight in enumerate(weights):
        slice_end = end if index == len(weights) - 1 else cursor + (end - start) * weight / total
        spans.append((round(cursor, 3), round(slice_end, 3)))
        cursor = slice_end
    return spans


def _assign_blocks_to_regions(
    blocks: list[dict[str, Any]],
    region_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not blocks:
        return []
    if not region_groups:
        return [
            {
                "block_id": block["block_id"],
                "line_ids": block["line_ids"],
                "region_ids": [],
                "window_start": None,
                "window_end": None,
                "confidence": 0.0,
                "score_breakdown": {},
                "flags": ["unassigned"],
            }
            for block in blocks
        ]

    signature_counts: dict[str, int] = {}
    for block in blocks:
        signature = str(block.get("repetition_signature", ""))
        signature_counts[signature] = signature_counts.get(signature, 0) + 1
    repeated = {signature for signature, count in signature_counts.items() if signature and count > 1}

    dp: dict[tuple[int, int], float] = {(0, 0): 0.0}
    back: dict[tuple[int, int], tuple[tuple[int, int], dict[str, Any], dict[str, Any]]] = {}
    groups_by_start: dict[int, list[dict[str, Any]]] = {}
    for group in region_groups:
        groups_by_start.setdefault(int(group["start_region_index"]), []).append(group)
    region_count = max(int(group["end_region_index"]) for group in region_groups) + 1
    if len(blocks) > region_count:
        assignments: list[dict[str, Any]] = []
        for block_index, block in enumerate(blocks):
            target = round(block_index * (region_count - 1) / max(1, len(blocks) - 1))
            candidates = groups_by_start.get(target, [])
            single_region = [
                group
                for group in candidates
                if int(group["start_region_index"]) == int(group["end_region_index"])
            ]
            group = (single_region or candidates)[0]
            score = _score_block_region_pair(block, group, repeated)
            assignments.append({
                "block_id": block["block_id"],
                "line_ids": block["line_ids"],
                "region_ids": group["region_ids"],
                "window_start": group["start"],
                "window_end": group["end"],
                "confidence": score["confidence"],
                "score_breakdown": score["score_breakdown"],
                "flags": score["flags"] + ["distributed_region_reuse"],
            })
        return _subdivide_shared_windows(assignments, blocks)

    for block_index, block in enumerate(blocks):
        states = [(state, cost) for state, cost in dp.items() if state[0] == block_index]
        for (state_block_index, cursor), state_cost in states:
            if state_block_index != block_index:
                continue
            skipped_cost = 0.0
            for start_idx in range(cursor, len(region_groups)):
                for group in groups_by_start.get(start_idx, []):
                    score = _score_block_region_pair(block, group, repeated)
                    remaining_blocks = len(blocks) - block_index - 1
                    remaining_regions = region_count - int(group["end_region_index"]) - 1
                    must_reuse = remaining_blocks > remaining_regions
                    next_cursor = int(group["start_region_index"]) if must_reuse else int(group["end_region_index"]) + 1
                    next_state = (block_index + 1, next_cursor)
                    new_cost = state_cost + skipped_cost + float(score["cost"]) + (0.2 if must_reuse else 0.0)
                    if new_cost < dp.get(next_state, float("inf")):
                        dp[next_state] = new_cost
                        back[next_state] = ((block_index, cursor), group, score)
                skipped = groups_by_start.get(start_idx, [])
                if skipped:
                    skipped_cost += min(_skip_region_penalty(group) for group in skipped)

    end_states = [state for state in dp if state[0] == len(blocks)]
    if not end_states:
        return [
            {
                "block_id": block["block_id"],
                "line_ids": block["line_ids"],
                "region_ids": [],
                "window_start": None,
                "window_end": None,
                "confidence": 0.0,
                "score_breakdown": {},
                "flags": ["unassigned"],
            }
            for block in blocks
        ]

    best = min(end_states, key=lambda state: dp[state])
    chosen: list[tuple[dict[str, Any], dict[str, Any]]] = []
    state = best
    while state in back:
        prev, group, score = back[state]
        chosen.append((group, score))
        state = prev
    chosen.reverse()

    assignments: list[dict[str, Any]] = []
    for block, (group, score) in zip(blocks, chosen):
        assignments.append({
            "block_id": block["block_id"],
            "line_ids": block["line_ids"],
            "region_ids": group["region_ids"],
            "window_start": group["start"],
            "window_end": group["end"],
            "confidence": score["confidence"],
            "score_breakdown": score["score_breakdown"],
            "flags": score["flags"],
        })
    if len(assignments) < len(blocks):
        for block in blocks[len(assignments):]:
            assignments.append({
                "block_id": block["block_id"],
                "line_ids": block["line_ids"],
                "region_ids": [],
                "window_start": None,
                "window_end": None,
                "confidence": 0.0,
                "score_breakdown": {},
                "flags": ["unassigned"],
            })
    return _subdivide_shared_windows(assignments, blocks)


def _build_alignment_windows(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for assignment in assignments:
        if not assignment.get("region_ids"):
            continue
        start = float(assignment["window_start"])
        end = float(assignment["window_end"])
        windows.append({
            "block_id": assignment["block_id"],
            "line_ids": assignment["line_ids"],
            "audio_start": round(max(0.0, start - WINDOW_PADDING_BEFORE), 3),
            "audio_end": round(end + WINDOW_PADDING_AFTER, 3),
            "padding_before": WINDOW_PADDING_BEFORE,
            "padding_after": WINDOW_PADDING_AFTER,
            "alignment_required": True,
        })
    return windows


def _write_alignment_window_artifacts(job_dir: Path, lyric_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = _build_lyrics_blocks(lyric_lines)
    blocks_path = job_dir / "lyrics_blocks.json"
    blocks_path.write_text(
        json.dumps({"source": "lyrics_parser", "blocks": blocks}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    regions_path = job_dir / "vocal_regions.json"
    regions: list[dict[str, Any]] = []
    non_vocal_gaps: list[dict[str, Any]] = []
    if regions_path.exists():
        payload = json.loads(regions_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("regions"), list):
            regions = _normalize_vocal_regions(payload["regions"])
        if isinstance(payload, dict) and isinstance(payload.get("non_vocal_gaps"), list):
            non_vocal_gaps = payload["non_vocal_gaps"]

    regions = _regions_for_blocks(job_dir, regions, blocks, non_vocal_gaps)
    groups = _build_vocal_region_groups(regions)
    assignments = _assign_blocks_to_regions(blocks, groups)
    windows = _build_alignment_windows(assignments)
    vocal_islands = _build_vocal_islands(regions)
    max_audio_end = max(
        [float(region.get("end", 0.0) or 0.0) for region in regions]
        + [float(gap.get("end", 0.0) or 0.0) for gap in non_vocal_gaps]
        + [0.0]
    )
    safety_report = _evaluate_ctc_window_safety(
        windows=windows,
        blocks=blocks,
        assignments=assignments,
        vocal_regions=regions,
        non_vocal_gaps=non_vocal_gaps,
        vocal_islands=vocal_islands,
        full_audio_duration=max_audio_end,
    )

    assignments_path = job_dir / "block_region_assignments.json"
    assignments_path.write_text(
        json.dumps({"source": "auto_block_region_matcher", "assignments": assignments}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    islands_path = job_dir / "vocal_islands.json"
    islands_path.write_text(
        json.dumps({"source": "vocal_activity_probe", "vocal_islands": vocal_islands}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    windows_path = job_dir / "alignment_windows.json"
    windows_path.write_text(
        json.dumps({"source": "auto_block_region_matcher", "windows": windows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    safety_path = job_dir / "ctc_window_safety_report.json"
    safety_path.write_text(json.dumps(safety_report, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_event(
        job_dir,
        "stage03b.alignment_windows_written",
        message="Alignment windows written",
        artifact=windows_path.name,
        details={
            "block_count": len(blocks),
            "assignment_count": len(assignments),
            "window_count": len(windows),
            "ctc_safe_windows": safety_report["summary"]["safe_windows"],
            "ctc_unsafe_windows": safety_report["summary"]["unsafe_windows"],
        },
    )
    return windows


def _windows_cover_all_lines(windows: list[dict[str, Any]], lyric_lines: list[dict[str, Any]]) -> bool:
    expected = {str(line.get("line_id")) for line in lyric_lines}
    actual = {
        str(line_id)
        for window in windows
        for line_id in window.get("line_ids", [])
    }
    return bool(expected) and expected == actual


def _windows_safe_for_ctc(windows: list[dict[str, Any]], lyric_lines: list[dict[str, Any]]) -> bool:
    lines_by_id = {str(line.get("line_id")): line for line in lyric_lines}
    for window in windows:
        duration = float(window.get("audio_end", 0.0) or 0.0) - float(window.get("audio_start", 0.0) or 0.0)
        window_lines = [
            lines_by_id[str(line_id)]
            for line_id in window.get("line_ids", [])
            if str(line_id) in lines_by_id
        ]
        text = _build_full_text(window_lines, expand=True)
        char_count = len(re.sub(r"\s+", "", text))
        if duration <= 0 or char_count > duration * CTC_MAX_CHARS_PER_SECOND:
            return False
    return True


# Backward overlap tolerated between consecutive words before the windowed
# alignment is considered damaged (CTC routinely leaves a few ms at phrase ends).
GUARD_OVERLAP_TOLERANCE_S = 0.05


def _alignment_with_quality_guard(
    windowed_words: list[dict[str, Any]],
    align_full_audio: Callable[[], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], bool, dict[str, Any]]:
    """Keep the windowed alignment only while it measures at least as clean.

    Windows constrain CTC to a slice; when the slice is off, the text is squeezed
    into it and words start overlapping each other. That is measurable, so measure
    it: a damaged windowed result buys a full-audio pass, and the one with fewer
    timestamp errors wins. A clean windowed result costs nothing extra.
    """
    from scripts.common.validation import find_timestamp_errors

    windowed_errors = len(find_timestamp_errors(windowed_words, overlap_tolerance_s=GUARD_OVERLAP_TOLERANCE_S))
    details: dict[str, Any] = {
        "windowed_timestamp_errors": windowed_errors,
        "full_audio_timestamp_errors": None,
        "fallback_used": False,
    }
    if not windowed_errors:
        return windowed_words, True, details

    full_words = align_full_audio()
    full_errors = len(find_timestamp_errors(full_words, overlap_tolerance_s=GUARD_OVERLAP_TOLERANCE_S))
    details["full_audio_timestamp_errors"] = full_errors
    details["fallback_used"] = True
    if full_errors < windowed_errors:
        return full_words, False, details
    return windowed_words, True, details


def _ctc_safety_report_safe(job_dir: Path) -> bool:
    report_path = job_dir / "ctc_window_safety_report.json"
    if not report_path.exists():
        return False
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(isinstance(report, dict) and report.get("safe_for_ctc"))


def _slice_audio_waveform(audio_waveform: Any, start_s: float, end_s: float) -> Any:
    start_sample = max(0, int(start_s * CTC_SAMPLE_RATE))
    end_sample = max(start_sample + 1, int(end_s * CTC_SAMPLE_RATE))
    end_sample = min(end_sample, int(audio_waveform.size(0)))
    return audio_waveform[start_sample:end_sample]


def _shift_word_results(word_results: list[dict[str, Any]], offset_s: float) -> list[dict[str, Any]]:
    shifted: list[dict[str, Any]] = []
    for word in word_results:
        copy = dict(word)
        copy["start"] = float(copy.get("start", 0.0)) + offset_s
        copy["end"] = float(copy.get("end", copy["start"])) + offset_s
        shifted.append(copy)
    return shifted


def _align_ctc_text(
    *,
    text: str,
    language: str,
    audio_waveform: Any,
    alignment_model: Any,
    alignment_tokenizer: Any,
    batch_size: int,
    generate_emissions: Any,
    preprocess_text: Any,
    get_alignments: Any,
    get_spans: Any,
    postprocess_results: Any,
) -> list[dict[str, Any]]:
    emissions, stride = generate_emissions(
        alignment_model,
        audio_waveform,
        batch_size=batch_size,
    )
    tokens_starred, text_starred = preprocess_text(
        text,
        romanize=True,
        language=language,
    )
    segments_raw, scores, blank_token = get_alignments(
        emissions,
        tokens_starred,
        alignment_tokenizer,
    )
    spans = get_spans(tokens_starred, segments_raw, blank_token)
    return postprocess_results(text_starred, spans, stride, scores)


def _align_ctc_by_windows(
    *,
    lyric_lines: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    language: str,
    audio_waveform: Any,
    alignment_model: Any,
    alignment_tokenizer: Any,
    batch_size: int,
    generate_emissions: Any,
    preprocess_text: Any,
    get_alignments: Any,
    get_spans: Any,
    postprocess_results: Any,
) -> list[dict[str, Any]]:
    lines_by_id = {str(line.get("line_id")): line for line in lyric_lines}
    word_results: list[dict[str, Any]] = []
    for window in windows:
        window_lines = [
            lines_by_id[str(line_id)]
            for line_id in window.get("line_ids", [])
            if str(line_id) in lines_by_id
        ]
        if not window_lines:
            continue
        window_text = _build_full_text(window_lines, expand=True)
        start = float(window["audio_start"])
        end = float(window["audio_end"])
        chunk = _slice_audio_waveform(audio_waveform, start, end)
        aligned = _align_ctc_text(
            text=window_text,
            language=language,
            audio_waveform=chunk,
            alignment_model=alignment_model,
            alignment_tokenizer=alignment_tokenizer,
            batch_size=batch_size,
            generate_emissions=generate_emissions,
            preprocess_text=preprocess_text,
            get_alignments=get_alignments,
            get_spans=get_spans,
            postprocess_results=postprocess_results,
        )
        word_results.extend(_shift_word_results(aligned, start))
    return word_results


def _expand_contractions(text: str) -> str:
    """
    Normalize common singing contractions to improve model alignment confidence.
    This preserves word count to avoid desyncing the alignment results.
    """
    # Simply remove apostrophes from common contractions and normalize
    # This avoids the "I'm" -> "I am" (1 word -> 2 words) desync issue.
    contractions = {
        r"\b'cause\b": "cause",
        r"\bcause\b":  "cause",
        r"\b'til\b":   "til",
        r"\btil\b":    "til",
        r"\b'em\b":    "em",
        r"\b'bout\b":  "bout",
        r"\bgonna\b":  "gonna",
        r"\bwanna\b":  "wanna",
        r"\bgotta\b":  "gotta",
        r"\bi'm\b":    "im",
        r"\bi've\b":   "ive",
        r"\bi'll\b":   "ill",
        r"\bi'd\b":    "id",
        r"\bit's\b":   "its",
        r"\bcan't\b":  "cant",
        r"\bwon't\b":  "wont",
        r"\bdon't\b":  "dont",
        r"\bdidn't\b": "didnt",
        r"\bcouldn't\b":"couldnt",
        r"\bshouldn't\b":"shouldnt",
        r"\bwouldn't\b":"wouldnt",
        r"\bain't\b":  "aint",
    }
    
    expanded = text.lower()
    for pattern, replacement in contractions.items():
        expanded = re.sub(pattern, replacement, expanded)
    
    # Also strip any remaining apostrophes that might confuse tokenization
    expanded = expanded.replace("'", "")
    
    return expanded


def _build_full_text(lyric_lines: list[dict], expand: bool = False) -> str:
    """Flatten all lyric lines into a single space-separated string."""
    if expand:
        return " ".join(_expand_contractions(line["text"]) for line in lyric_lines)
    return " ".join(line["text"] for line in lyric_lines)


def _split_words_by_lines(
    lyric_lines: list[dict],
    word_results: list[dict],
) -> list[dict[str, Any]]:
    """
    Re-group flat word results back into lyric-line segments.

    The CTC aligner returns a flat list of word timestamps. We re-assign
    each word to its original lyric line by consuming words in order and
    matching against each line's expected word count.

    Returns a list of segment dicts matching the transcript.json schema,
    with an extra 'section' field for s05 to consume.
    """
    word_re = re.compile(r"[a-zA-Z''\u00C0-\u024F]+")
    segments: list[dict[str, Any]] = []
    word_idx = 0
    total_words = len(word_results)

    for lyric_line in lyric_lines:
        # Count words expected in this lyric line
        lyric_line_words = word_re.findall(lyric_line["text"])
        n = len(lyric_line_words)

        if word_idx >= total_words:
            # Ran out of aligned words — create a dummy segment
            logger.warning(
                "Ran out of aligned words at lyric line: '%s'",
                lyric_line["text"][:60],
            )
            break

        # Take the next n words from the flat result list
        chunk = word_results[word_idx : word_idx + n]
        word_idx += n

        if not chunk:
            continue

        # Enforce minimum word duration and non-overlap
        min_dur = 0.050  # 50ms
        for i in range(len(chunk)):
            w = chunk[i]
            if w["end"] <= w["start"]:
                w["end"] = w["start"] + min_dur
            
            # Prevent overlap with next word in chunk
            if i < len(chunk) - 1:
                next_w = chunk[i+1]
                if w["end"] > next_w["start"]:
                    # Split the gap or push back?
                    # Push back is safer for CTC
                    mid = (w["start"] + next_w["end"]) / 2
                    w["end"] = mid
                    next_w["start"] = mid
            
            # Final sanity check for duration
            if w["end"] - w["start"] < min_dur:
                w["end"] = w["start"] + min_dur

        seg_start = chunk[0]["start"]
        seg_end   = chunk[-1]["end"]

        segments.append({
            "text":    lyric_line["text"],
            "section": lyric_line["section"],
            "style":   lyric_line.get("style", "verse"),
            "line_id": lyric_line.get("line_id", f"L{len(segments) + 1:03d}"),
            "start":   round(seg_start, 4),
            "end":     round(seg_end,   4),
            "words": [
                {
                    "word":        lyric_line_words[i],  # Preserve original text
                    "start":       round(chunk[i]["start"], 4),
                    "end":         round(chunk[i]["end"],   4),
                    "probability": round(chunk[i].get("score", 1.0), 4),
                }
                for i in range(len(chunk))
            ],
        })

    if word_idx < total_words:
        logger.warning(
            "%d aligned words were not assigned to any lyric line "
            "(lyric line count may differ from lyrics.txt word count)",
            total_words - word_idx,
        )

    return segments


def _normalized_line_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def _load_reference_line_starts(job_dir: Path, lyric_lines: list[dict]) -> list[float] | None:
    reference_path = job_dir / "reference_timestamps.json"
    if not reference_path.exists():
        return None

    try:
        payload = json.loads(reference_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("reference_timestamps.json could not be read: %s", exc)
        return None

    reference_lines = payload.get("lines", payload) if isinstance(payload, dict) else payload
    if not isinstance(reference_lines, list):
        logger.warning("reference_timestamps.json ignored: expected a list or {lines: [...]}")
        return None
    if len(reference_lines) != len(lyric_lines):
        logger.warning(
            "reference_timestamps.json ignored: %d lines but lyrics has %d",
            len(reference_lines),
            len(lyric_lines),
        )
        return None

    starts: list[float] = []
    for index, (reference_line, lyric_line) in enumerate(zip(reference_lines, lyric_lines)):
        if not isinstance(reference_line, dict):
            logger.warning("reference_timestamps.json ignored: line %d is not an object", index)
            return None
        if _normalized_line_text(str(reference_line.get("text", ""))) != _normalized_line_text(lyric_line["text"]):
            logger.warning("reference_timestamps.json ignored: text mismatch at line %d", index)
            return None
        try:
            starts.append(float(reference_line.get("reference_start_sec", reference_line.get("start_sec"))))
        except (TypeError, ValueError):
            logger.warning("reference_timestamps.json ignored: missing start time at line %d", index)
            return None

    return starts


def _retime_segments_to_reference_starts(
    segments: list[dict[str, Any]],
    reference_starts: list[float],
    *,
    min_word_dur: float = 0.05,
) -> list[dict[str, Any]]:
    retimed: list[dict[str, Any]] = []

    for index, (segment, line_start) in enumerate(zip(segments, reference_starts)):
        copy = {**segment}
        words = [{**word} for word in segment.get("words", [])]
        if not words:
            copy["start"] = round(line_start, 4)
            copy["end"] = round(line_start + min_word_dur, 4)
            retimed.append(copy)
            continue

        original_start = min(float(word["start"]) for word in words)
        original_end = max(float(word["end"]) for word in words)
        original_duration = max(min_word_dur, original_end - original_start)
        next_start = reference_starts[index + 1] if index + 1 < len(reference_starts) else None
        line_end = line_start + original_duration if next_start is None else max(
            line_start + min_word_dur * len(words),
            next_start - 0.001,
        )
        available_duration = max(min_word_dur * len(words), line_end - line_start)
        original_durations = [
            max(min_word_dur, float(word["end"]) - float(word["start"]))
            for word in words
        ]
        duration_scale = available_duration / max(min_word_dur, sum(original_durations))
        new_durations = [max(min_word_dur, duration * duration_scale) for duration in original_durations]
        if sum(new_durations) > available_duration:
            even_duration = available_duration / len(words)
            new_durations = [even_duration for _ in words]

        cursor = line_start
        new_words: list[dict[str, Any]] = []
        for word, duration in zip(words, new_durations):
            start = cursor
            end = start + duration
            start = max(start, cursor)
            end = max(end, start + min_word_dur)
            cursor = end
            new_words.append({
                **word,
                "start": round(start, 4),
                "end": round(end, 4),
            })

        copy["words"] = new_words
        copy["start"] = round(line_start, 4)
        copy["end"] = round(max(float(word["end"]) for word in new_words), 4)
        retimed.append(copy)

    return retimed


def _build_vocal_regions_artifact(vocals_path: Path) -> dict[str, Any]:
    from scripts.review_wizard.vocal_activity import VocalActivityProbe

    probe = VocalActivityProbe.from_wav(vocals_path)
    duration_s = float(probe.frame_times_s[-1]) if len(probe.frame_times_s) else 0.0
    regions = probe.voiced_regions(0.0, duration_s, min_duration_s=0.50, merge_gap_s=0.50)

    gaps: list[dict[str, Any]] = []
    cursor = 0.0
    for region in regions:
        start = float(region["start_s"])
        if start - cursor >= 1.0:
            gaps.append({
                "start": round(cursor, 3),
                "end": round(start, 3),
                "duration": round(start - cursor, 3),
                "type": "instrumental_or_silence",
            })
        cursor = max(cursor, float(region["end_s"]))
    if duration_s - cursor >= 1.0:
        gaps.append({
            "start": round(cursor, 3),
            "end": round(duration_s, 3),
            "duration": round(duration_s - cursor, 3),
            "type": "instrumental_or_silence",
        })

    return {
        "source": "vocal_activity_probe",
        "regions": [
            {
                "start": region["start_s"],
                "end": region["end_s"],
                "vocal_prob": region["voiced_ratio"],
                "type": "probable_vocal",
                "detectors": {
                    "stem_energy": region["rms"],
                    "threshold": region["threshold"],
                },
            }
            for region in regions
        ],
        "non_vocal_gaps": gaps,
    }


def _write_vocal_regions_artifact(job_dir: Path, vocals_path: Path) -> bool:
    try:
        payload = _build_vocal_regions_artifact(vocals_path)
    except Exception as exc:
        logger.warning("Vocal activity artifact skipped: %s", exc)
        _write_event(
            job_dir,
            "stage03b.vocal_regions_skipped",
            level="warning",
            message=str(exc),
        )
        return False

    output_path = job_dir / "vocal_regions.json"
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_event(
        job_dir,
        "stage03b.vocal_regions_written",
        message="Vocal regions written",
        artifact=output_path.name,
        details={
            "region_count": len(payload["regions"]),
            "non_vocal_gap_count": len(payload["non_vocal_gaps"]),
        },
    )
    return True



# ---------------------------------------------------------------------------
# Pitch-guided boundary correction
# ---------------------------------------------------------------------------

def _extract_note_onsets_crepe(
    vocals_path: Path,
    sr_target: int = 16000,
) -> tuple[list[float], Any, Any]:
    """
    Extract note onsets and voiced frames using torchcrepe.

    Returns:
        (onsets, times, voiced)
    """
    import torchcrepe
    import torch
    import numpy as np

    logger.info("Loading audio for CREPE pitch detection...")
    # torchcrepe expects float32 tensor at 16kHz
    import soundfile as sf
    import resampy
    audio_raw, sr = sf.read(str(vocals_path), always_2d=False)
    if audio_raw.ndim > 1:
        audio_raw = audio_raw.mean(axis=1)  # stereo → mono
    if sr != sr_target:
        audio_raw = resampy.resample(audio_raw, sr, sr_target)
        sr = sr_target

    audio_tensor = torch.tensor(audio_raw, dtype=torch.float32).unsqueeze(0)
    hop_length = 160  # 10ms at 16kHz — CREPE default

    # Predict pitch with Viterbi decoding (smoother, fewer octave errors)
    frequency, periodicity = torchcrepe.predict(
        audio_tensor,
        sr,
        hop_length=hop_length,
        fmin=50.0,
        fmax=2006.0,
        model="full",
        decoder=torchcrepe.decode.viterbi,
        return_periodicity=True,
        device="cpu",
        batch_size=_cfg.crepe_batch_size,
    )

    frequency   = frequency.squeeze().numpy()
    periodicity = periodicity.squeeze().numpy()
    times = np.arange(len(frequency)) * (hop_length / sr)

    # Voiced = periodicity > 0.21 (torchcrepe recommended threshold)
    voiced = periodicity > 0.21

    onsets: list[float] = []

    # Onset type 1: unvoiced → voiced transitions
    for i in range(1, len(voiced)):
        if not voiced[i - 1] and voiced[i]:
            onsets.append(float(times[i]))

    # Onset type 2: large pitch jumps (>2 semitones) within voiced regions
    prev_f0 = None
    for i in range(len(voiced)):
        if voiced[i] and frequency[i] > 0:
            if prev_f0 is not None and prev_f0 > 0:
                semitones = abs(12 * np.log2(frequency[i] / prev_f0))
                if semitones > 2.0:
                    onsets.append(float(times[i]))
            prev_f0 = float(frequency[i])
        else:
            prev_f0 = None

    onsets_sorted = sorted(set(round(t, 3) for t in onsets))
    logger.info(
        "CREPE detected %d note onsets in %.1fs of audio",
        len(onsets_sorted), len(audio_raw) / sr,
    )
    return onsets_sorted, times, voiced


def _extract_note_onsets_pyin(
    vocals_path: Path,
    sr_target: int = 22050,
) -> tuple[list[float], Any, Any]:
    """
    Extract note onsets using pYIN (librosa). 

    Returns:
        (onsets, times, voiced)
    """
    import librosa
    import numpy as np

    logger.info("Loading audio for pYIN pitch detection (fallback)...")
    y, sr = librosa.load(str(vocals_path), sr=sr_target, mono=True)

    hop_length = 512  # ~23ms at 22050Hz
    f0, voiced_flag, _ = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C6"),
        sr=sr,
        hop_length=hop_length,
        fill_na=None,
    )
    times = librosa.frames_to_time(range(len(voiced_flag)), sr=sr, hop_length=hop_length)

    onsets: list[float] = []

    for i in range(1, len(voiced_flag)):
        if not voiced_flag[i - 1] and voiced_flag[i]:
            onsets.append(float(times[i]))

    prev_f0 = None
    for t, v, f in zip(times, voiced_flag, f0):
        if v and f is not None and not np.isnan(f):
            if prev_f0 is not None and prev_f0 > 0:
                semitones = abs(12 * np.log2(f / prev_f0))
                if semitones > 2.0:
                    onsets.append(float(t))
            prev_f0 = f
        else:
            prev_f0 = None

    onsets_sorted = sorted(set(round(t, 3) for t in onsets))
    logger.info(
        "pYIN detected %d note onsets in %.1fs of audio",
        len(onsets_sorted), len(y) / sr,
    )
    return onsets_sorted, np.array(times), np.array(voiced_flag, dtype=bool)


def _extract_note_onsets(
    vocals_path: Path,
    sr_target: int = 16000,
    onset_window: float = 1.5,
) -> tuple[list[float], str, Any, Any]:
    """
    Extract note onset times with automatic engine selection.

    Priority chain:
        1. torchcrepe  — neural, Viterbi decoded, ~50MB model download
        2. pYIN        — DSP-based, in librosa (already installed), no download
        3. []          — empty list (pitch correction skipped gracefully)

    Returns:
        (onsets, engine_name, frames_times, voiced_frames_bool)
    """
    import numpy as np
    
    # Try torchcrepe first
    try:
        import torchcrepe  # noqa: F401
        logger.info("Pitch engine: torchcrepe (primary)")
        onsets, times, voiced = _extract_note_onsets_crepe(vocals_path, sr_target)
        return onsets, "torchcrepe", times, voiced
    except ImportError:
        logger.info(
            "torchcrepe not installed — falling back to pYIN. "
            "For better accuracy: pip install torchcrepe"
        )
    except Exception as e:
        logger.warning("torchcrepe failed (%s) — falling back to pYIN", e)

    # Fall back to pYIN
    try:
        import librosa  # noqa: F401
        logger.info("Pitch engine: pYIN/librosa (fallback)")
        onsets, times, voiced = _extract_note_onsets_pyin(vocals_path, sr_target=22050)
        return onsets, "pYIN", times, voiced
    except ImportError:
        logger.warning("librosa not installed — pitch correction disabled")
    except Exception as e:
        logger.warning("pYIN failed (%s) — pitch correction disabled", e)

    return [], "none", np.array([]), np.array([], dtype=bool)


def _snap_to_onsets(
    segments:       list[dict],
    onsets:         list[float],
    snap_window:    float = 1.5,
    min_word_dur:   float = 0.05,
) -> tuple[list[dict], int]:
    """
    Snap CTC word boundaries to the nearest pitch-detected note onset.
    Applied primarily to word STARTS. 
    """
    if not onsets:
        return segments, 0

    import bisect

    corrections = 0

    for seg in segments:
        words = seg.get("words", [])
        for w_i, word in enumerate(words):
            original_start = word["start"]
            original_end   = word["end"]
            prev_end = words[w_i - 1]["end"] if w_i > 0 else 0.0

            # Find nearest onset within window
            idx = bisect.bisect_left(onsets, original_start)
            candidates = []
            for oi in [idx - 1, idx, idx + 1]:
                if 0 <= oi < len(onsets):
                    delta = abs(onsets[oi] - original_start)
                    if delta <= snap_window:
                        candidates.append((delta, onsets[oi]))

            if not candidates:
                continue

            _, best_onset = min(candidates)

            # Safety checks before applying snap
            if best_onset >= original_end:
                continue   # would collapse or invert the word
            if best_onset < prev_end + min_word_dur:
                continue   # would overlap with previous word

            delta = best_onset - original_start
            if abs(delta) < 0.01:
                continue   # negligible correction, skip

            word["start"] = round(best_onset, 4)
            corrections += 1

            logger.debug(
                "Snap '%s': %.4f → %.4f (Δ%.3fs, onset=%.4f)",
                word["word"], original_start, best_onset, delta, best_onset,
            )

        # Update segment start/end from words after snapping
        if words:
            seg["start"] = words[0]["start"]
            seg["end"]   = words[-1]["end"]

    return segments, corrections


# ---------------------------------------------------------------------------
# Melisma / phrase-end extension
# ---------------------------------------------------------------------------

def _find_voiced_end(
    times:             Any,         # np.ndarray of frame times (seconds)
    voiced:            Any,         # np.ndarray of bool, same length as times
    search_start:      float,
    search_end:        float,
    silence_tolerance: float = 0.20,
) -> float | None:
    """
    Find the last time in [search_start, search_end] where the voice is active,
    allowing brief unvoiced gaps up to silence_tolerance seconds.
    """
    import bisect

    if len(times) == 0 or search_end <= search_start:
        return None

    i0 = bisect.bisect_left(times, search_start)
    i1 = min(bisect.bisect_right(times, search_end), len(times))

    if i0 >= i1:
        return None

    last_voiced_t: float | None = None
    gap_start: float | None = None   # when unvoiced region began

    for i in range(i0, i1):
        t = float(times[i])
        if voiced[i]:
            last_voiced_t = t
            gap_start = None   # reset gap clock
        else:
            if gap_start is None:
                gap_start = t
            elif (t - gap_start) > silence_tolerance:
                # Silence exceeded tolerance — voice is genuinely off
                break

    return last_voiced_t


def _extend_phrase_ends_voiced(
    segments:          list[dict],
    times:             Any,        # np.ndarray from pitch detection
    voiced:            Any,        # np.ndarray[bool]
    min_tail_gap:      float = 0.40,  # only extend when gap to next seg > this
    silence_tolerance: float = 0.20,  # tolerance for brief gaps inside a hold
    min_extension:     float = 0.10,  # skip if extension would be trivially small
    max_extension:     float = 8.0,   # cap — no single word hold should be >8s
    end_margin:        float = 0.05,  # stop this far before next segment start
) -> tuple[list[dict], int]:
    """
    Extend the last word of each phrase to cover melismatic holds.
    """
    if len(times) == 0:
        return segments, 0

    n = len(segments)
    extensions = 0

    for i, seg in enumerate(segments):
        words = seg.get("words", [])
        if not words:
            continue

        last_w = words[-1]
        word_end = last_w["end"]

        # Cap: don't extend past start of next segment (with margin)
        if i + 1 < n:
            cap = segments[i + 1]["start"] - end_margin
        else:
            cap = word_end + max_extension

        # Only consider extending when there's a meaningful gap
        tail_gap = cap - word_end
        if tail_gap < min_tail_gap:
            continue

        # Query voiced array for last active frame in the gap
        voiced_end = _find_voiced_end(
            times, voiced,
            search_start=word_end,
            search_end=min(cap, word_end + max_extension),
            silence_tolerance=silence_tolerance,
        )

        if voiced_end is None:
            continue

        extension_amount = voiced_end - word_end
        if extension_amount < min_extension:
            continue

        # Apply extension
        old_end = round(word_end, 4)
        new_end = round(voiced_end, 4)
        last_w["end"] = new_end
        seg["end"]    = new_end
        extensions   += 1

        logger.debug(
            "Phrase end extended: '%s' … '%s' %.4f → %.4f (+%.2fs, gap was %.2fs)",
            seg["text"][:30], last_w["word"],
            old_end, new_end, extension_amount, tail_gap,
        )

    return segments, extensions


def _vocal_gate_boundaries(
    segments:          list[dict],
    times:             Any,        # np.ndarray from pitch detection
    voiced:            Any,        # np.ndarray[bool]
    max_seek:          float = 2.0,  # how far to look for voice activity
) -> tuple[list[dict], int]:
    """
    Ensure word boundaries don't start/end in silence by snapping them 
    to the nearest voiced frame. Prevents stretching over instrumentals.
    """
    if len(times) == 0:
        return segments, 0

    import bisect
    import numpy as np
    
    corrections = 0
    
    for seg in segments:
        words = seg.get("words", [])
        for word in words:
            # ── Trim Start ──
            # If CTC says word starts in silence, look forward for voice
            idx_start = bisect.bisect_left(times, word["start"])
            if idx_start < len(voiced) and not voiced[idx_start]:
                # Search forward for first voiced frame
                search_limit = bisect.bisect_right(times, word["start"] + max_seek)
                voiced_indices = np.where(voiced[idx_start:search_limit])[0]
                if len(voiced_indices) > 0:
                    new_start = float(times[idx_start + voiced_indices[0]])
                    if new_start < word["end"]:
                        word["start"] = round(new_start, 4)
                        corrections += 1

            # ── Trim End ──
            # If word ends in silence, look backward for last voice
            idx_end = min(bisect.bisect_right(times, word["end"]), len(voiced) - 1)
            if idx_end >= 0 and not voiced[idx_end]:
                # Search backward for last voiced frame
                search_limit = max(0, bisect.bisect_left(times, word["end"] - max_seek))
                voiced_indices = np.where(voiced[search_limit:idx_end])[0]
                if len(voiced_indices) > 0:
                    new_end = float(times[search_limit + voiced_indices[-1]])
                    if new_end > word["start"]:
                        word["end"] = round(new_end, 4)
                        corrections += 1
        
        # Sync segment boundaries
        if words:
            seg["start"] = words[0]["start"]
            seg["end"]   = words[-1]["end"]

    return segments, corrections


# ---------------------------------------------------------------------------
# Status helper
# ---------------------------------------------------------------------------

def _update_status(job_dir: Path, stage: str, progress: int, error: str = "") -> None:
    status_path = job_dir / "status.json"
    existing: dict[str, Any] = {}
    if status_path.exists():
        try:
            existing = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            pass
    existing.update({
        "stage":      stage,
        "progress":   progress,
        "error":      error,
        "updated_at": time.time(),
    })
    status_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _write_event(
    job_dir: Path,
    event: str,
    level: str = "info",
    message: str = "",
    details: dict[str, Any] | None = None,
    artifact: str | None = None,
) -> None:
    try:
        write_event(
            job_dir,
            event,
            "stage03b",
            level=level,
            message=message,
            details=details,
            artifact=artifact,
        )
    except Exception:
        logger.debug("Failed to write observability event %s", event, exc_info=True)


def _write_missing_job_event(job_dir: Path, message: str) -> None:
    parent = job_dir.parent if job_dir.parent != job_dir else Path.cwd()
    write_event(
        parent / "_stage03b",
        "stage03b.failed",
        "stage03b",
        level="error",
        message=message,
        details={"reason": "job_dir_missing", "missing_job_dir": str(job_dir)},
    )


def _fail(job_dir: Path, event: str, message: str, details: dict[str, Any] | None = None) -> int:
    _write_event(job_dir, event, level="error", message=message, details=details)
    if event != "stage03b.failed":
        _write_event(job_dir, "stage03b.failed", level="error", message=message, details=details)
    return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    hw = detect()

    parser = argparse.ArgumentParser(
        description=(
            "Stage 03b — Forced lyric alignment via CTC + MMS Wav2Vec2. "
            "Requires lyrics.txt. Bypasses Whisper transcription entirely."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--job-dir",  required=True, type=Path,
                        help="Path to the job directory.")
    parser.add_argument("--lyrics",   required=True, type=Path,
                        help="Path to lyrics.txt with [Section] markers.")
    parser.add_argument("--language", default="eng",
                        metavar="ISO639-3",
                        help=(
                            "ISO-639-3 language code for the MMS model. "
                            "eng=English, jpn=Japanese, por=Portuguese. "
                            "Auto-converts ISO-639-1 codes (en→eng, etc.)."
                        ))
    parser.add_argument("--batch-size", type=int, default=8,
                        help="Batch size for emission generation. Reduce if OOM.")
    parser.add_argument("--snap-window", type=float, default=0.75,
                        metavar="SECONDS",
                        help=(
                            "Maximum distance (seconds) to snap a CTC word boundary "
                            "to a pitch-detected note onset. Default: 1.5."
                        ))
    parser.add_argument("--no-pitch", action="store_true",
                        help="Disable pitch correction entirely (use raw CTC timestamps).")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    job_dir: Path = args.job_dir.resolve()
    lyrics_path: Path = args.lyrics.resolve()

    log_handlers: list[logging.Handler] = [logging.StreamHandler()]
    if job_dir.exists():
        log_handlers.append(logging.FileHandler(job_dir / "pipeline.log", mode="a"))
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
        handlers=log_handlers,
    )

    # Auto-convert ISO-639-1 → ISO-639-3 if needed
    language = args.language
    if len(language) == 2 and language in LANGUAGE_MAP:
        language = LANGUAGE_MAP[language]
        logger.info("Language code converted: %s → %s", args.language, language)

    if not job_dir.exists():
        logger.error("Job directory does not exist: %s", job_dir)
        _write_missing_job_event(job_dir, f"Job directory does not exist: {job_dir}")
        return 1

    logger.info(
        "Stage 03b · Forced Align  language=%s  batch=%d",
        language, args.batch_size,
    )
    _write_event(
        job_dir,
        "stage03b.started",
        message="Stage 03b forced lyric alignment started",
        details={
            "language": language,
            "batch_size": args.batch_size,
            "snap_window": args.snap_window,
            "pitch_enabled": not args.no_pitch,
        },
    )

    # ── Validate inputs ────────────────────────────────────────────────────
    vocals_path = job_dir / "vocals.wav"
    if not vocals_path.exists() or vocals_path.stat().st_size == 0:
        message = "vocals.wav missing or empty. Run Stage 02 first."
        logger.error(message)
        return _fail(
            job_dir,
            "stage03b.input_missing",
            message,
            {"artifact": "vocals.wav", "path": str(vocals_path)},
        )

    if not lyrics_path.exists():
        message = f"lyrics.txt not found at {lyrics_path}"
        logger.error(message)
        return _fail(
            job_dir,
            "stage03b.input_missing",
            message,
            {"artifact": "lyrics.txt", "path": str(lyrics_path)},
        )

    logger.info("Audio:  %s (%.1f MB)", vocals_path.name, vocals_path.stat().st_size / 1e6)
    logger.info("Lyrics: %s", lyrics_path)
    vocal_regions_written = _write_vocal_regions_artifact(job_dir, vocals_path)

    # ── Parse lyrics ───────────────────────────────────────────────────────
    lyric_lines = _parse_lyrics(lyrics_path)
    if not lyric_lines:
        message = "No singable lines found in lyrics.txt"
        logger.error(message)
        return _fail(job_dir, "stage03b.input_missing", message, {"artifact": "lyrics.txt"})

    full_text = _build_full_text(lyric_lines, expand=True)
    total_lyric_words = sum(
        len(re.findall(r"[a-zA-Z''\u00C0-\u024F]+", line["text"]))
        for line in lyric_lines
    )

    logger.info(
        "Parsed %d lyric lines, %d words across %d sections",
        len(lyric_lines),
        total_lyric_words,
        len({l["section"] for l in lyric_lines}),
    )
    lyrics_details = _lyrics_observability_details(lyrics_path, lyric_lines)
    _write_event(
        job_dir,
        "stage03b.lyrics_reference_loaded",
        message="Lyrics reference loaded",
        details={**lyrics_details, "word_count": total_lyric_words},
        artifact=lyrics_path.name,
    )
    _write_event(
        job_dir,
        "stage03b.forced_alignment_text_built",
        message="Forced alignment text built",
        details={"word_count": total_lyric_words, "character_count": len(full_text)},
    )
    _write_event(
        job_dir,
        "stage03b.alignment_path_selected",
        message="CTC forced alignment path selected",
        details={"aligner": "ctc-forced-aligner/mms-300m-1130", "language": language},
    )
    alignment_windows = _write_alignment_window_artifacts(job_dir, lyric_lines)

    _update_status(job_dir, "aligning_lyrics", 0)

    # ── Import ctc-forced-aligner ─────────────────────────────────────────
    try:
        import torch
        from ctc_forced_aligner import (
            load_audio,
            load_alignment_model,
            generate_emissions,
            preprocess_text,
            get_alignments,
            get_spans,
            postprocess_results,
        )
    except ImportError:
        message = (
            "ctc-forced-aligner is not installed.\n"
            "Run: pip install git+https://github.com/MahmoudAshraf97/ctc-forced-aligner.git"
        )
        logger.error(message)
        return _fail(job_dir, "stage03b.failed", message)

    # ── Load model ─────────────────────────────────────────────────────────
    logger.info("Loading MMS alignment model...")
    _update_status(job_dir, "aligning_lyrics", 10)

    try:
        alignment_model, alignment_tokenizer = load_alignment_model(
            device="cpu",
            dtype=torch.float32,
        )
    except Exception as e:
        logger.error("Failed to load alignment model: %s", e)
        _update_status(job_dir, "failed", 0, str(e))
        return _fail(job_dir, "stage03b.failed", f"Failed to load alignment model: {e}")

    logger.info("Model loaded.")
    _update_status(job_dir, "aligning_lyrics", 20)

    # ── Load audio ─────────────────────────────────────────────────────────
    try:
        audio_waveform = load_audio(
            str(vocals_path),
            alignment_model.dtype,
            alignment_model.device,
        )
    except Exception as e:
        logger.error("Failed to load audio: %s", e)
        _update_status(job_dir, "failed", 0, str(e))
        return _fail(job_dir, "stage03b.failed", f"Failed to load audio: {e}")

    # ── Generate emissions ────────────────────────────────────────────────
    ctc_windows_cover_lines = _windows_cover_all_lines(alignment_windows, lyric_lines)
    ctc_windows_safe = (
        ctc_windows_cover_lines
        and _windows_safe_for_ctc(alignment_windows, lyric_lines)
        and _ctc_safety_report_safe(job_dir)
    )
    ctc_windowed_alignment = ctc_windows_cover_lines and ctc_windows_safe
    if ctc_windowed_alignment:
        logger.info("Aligning %d words inside %d vocal windows...", total_lyric_words, len(alignment_windows))
    else:
        logger.info("Aligning %d words against full audio...", total_lyric_words)
    _update_status(job_dir, "aligning_lyrics", 35)

    # ── Preprocess text and align ─────────────────────────────────────────
    _update_status(job_dir, "aligning_lyrics", 55)
    _write_event(
        job_dir,
        "stage03b.ctc_alignment_started",
        message="CTC forced alignment started",
        details={
            "word_count": total_lyric_words,
            "language": language,
            "windowed_alignment": ctc_windowed_alignment,
            "window_count": len(alignment_windows),
            "windows_cover_lines": ctc_windows_cover_lines,
            "windows_safe_for_ctc": ctc_windows_safe,
        },
    )

    guard_details: dict[str, Any] = {}
    try:
        def align_full_audio() -> list[dict[str, Any]]:
            return _align_ctc_text(
                text=full_text,
                language=language,
                audio_waveform=audio_waveform,
                alignment_model=alignment_model,
                alignment_tokenizer=alignment_tokenizer,
                batch_size=args.batch_size,
                generate_emissions=generate_emissions,
                preprocess_text=preprocess_text,
                get_alignments=get_alignments,
                get_spans=get_spans,
                postprocess_results=postprocess_results,
            )

        if ctc_windowed_alignment:
            word_results = _align_ctc_by_windows(
                lyric_lines=lyric_lines,
                windows=alignment_windows,
                language=language,
                audio_waveform=audio_waveform,
                alignment_model=alignment_model,
                alignment_tokenizer=alignment_tokenizer,
                batch_size=args.batch_size,
                generate_emissions=generate_emissions,
                preprocess_text=preprocess_text,
                get_alignments=get_alignments,
                get_spans=get_spans,
                postprocess_results=postprocess_results,
            )
            word_results, ctc_windowed_alignment, guard_details = _alignment_with_quality_guard(
                word_results, align_full_audio
            )
            if guard_details["fallback_used"]:
                logger.info(
                    "Quality guard: windowed alignment had %d timestamp error(s), full audio had %d - keeping %s.",
                    guard_details["windowed_timestamp_errors"],
                    guard_details["full_audio_timestamp_errors"],
                    "windows" if ctc_windowed_alignment else "full audio",
                )
        else:
            word_results = align_full_audio()
    except Exception as e:
        logger.error("Alignment failed: %s", e)
        _update_status(job_dir, "failed", 0, str(e))
        return _fail(job_dir, "stage03b.failed", f"Alignment failed: {e}")

    logger.info("Raw alignment returned %d word entries", len(word_results))
    _write_event(
        job_dir,
        "stage03b.ctc_alignment_finished",
        message="CTC forced alignment finished",
        details={
            "word_count": len(word_results),
            "language": language,
            "windowed_alignment": ctc_windowed_alignment,
            **guard_details,
        },
    )
    _update_status(job_dir, "aligning_lyrics", 75)

    # ── Re-group into lyric-line segments ─────────────────────────────────
    segments = _split_words_by_lines(lyric_lines, word_results)

    if not segments:
        logger.error("No segments produced after grouping.")
        _update_status(job_dir, "failed", 0, "No segments after grouping")
        return _fail(job_dir, "stage03b.failed", "No segments after grouping")

    # ── Pitch-guided boundary correction ───────────────────────────────────
    # Step 1 — Snap CTC word STARTS to note onsets (existing).
    # Step 2 — Extend last word ENDS to voiced audio end (new: melisma fix).
    pitch_engine = "none"
    n_snapped = 0
    n_extended = 0
    if not args.no_pitch and args.snap_window > 0:
        logger.info(
            "Running pitch detection (snap_window=%.1fs)...",
            args.snap_window,
        )
        _update_status(job_dir, "aligning_lyrics", 80)

        onsets, pitch_engine, pitch_times, pitch_voiced = _extract_note_onsets(
            vocals_path, onset_window=args.snap_window,
        )

        if onsets:
            segments, n_snapped = _snap_to_onsets(
                segments,
                onsets,
                snap_window=args.snap_window,
            )
            logger.info("Step 1 — onset snap: %d word starts corrected", n_snapped)
        else:
            logger.info("No note onsets detected — onset snap skipped")

        if len(pitch_times) > 0:
            segments, n_extended = _extend_phrase_ends_voiced(
                segments,
                pitch_times,
                pitch_voiced,
            )
            logger.info("Step 2 — phrase end extension: %d phrase ends extended", n_extended)

        # Step 3 — Vocal Gating: Trim words that start/end in non-voiced regions
        if len(pitch_times) > 0:
            segments, n_gated = _vocal_gate_boundaries(
                segments,
                pitch_times,
                pitch_voiced,
            )
            logger.info("Step 3 — vocal gating: %d boundaries trimmed to voice activity", n_gated)
    else:
        logger.info("Pitch correction disabled")

    reference_timing_applied = False
    reference_starts = _load_reference_line_starts(job_dir, lyric_lines)
    if reference_starts is not None:
        segments = _retime_segments_to_reference_starts(segments, reference_starts)
        reference_timing_applied = True
        logger.info(
            "Applied reference_timestamps.json timing to %d lyric lines",
            len(reference_starts),
        )

    _write_event(
        job_dir,
        "stage03b.correction_path_selected",
        message="Pitch/onset correction path selected",
        details={
            "pitch_engine": pitch_engine,
            "pitch_enabled": not args.no_pitch and args.snap_window > 0,
            "snap_window": args.snap_window,
            "onset_snaps": n_snapped,
            "phrase_extensions": n_extended,
            "reference_timing_applied": reference_timing_applied,
        },
    )

    # ── Validate timestamps ────────────────────────────────────────────────
    inverted = 0
    for seg in segments:
        for w in seg.get("words", []):
            if w["start"] >= w["end"]:
                inverted += 1
                logger.warning(
                    "Inverted word timestamp: '%s' start=%.4f end=%.4f",
                    w["word"], w["start"], w["end"],
                )

    if inverted:
        logger.warning(
            "%d word timestamps are inverted after alignment. "
            "HubertFA (Stage 04) will apply min/max correction.",
            inverted,
        )

    # ── Build transcript.json ──────────────────────────────────────────────
    total_words_aligned = sum(len(s["words"]) for s in segments)
    section_distribution = {}
    for seg in segments:
        sec = seg.get("section", "verse")
        section_distribution[sec] = section_distribution.get(sec, 0) + 1

    # Collect unknown section markers logged by _parse_lyrics
    all_unknown = sorted(set(
        m for line in lyric_lines
        for m in line.get("unknown_markers", [])
    ))

    transcript: dict[str, Any] = {
        "language":                "en",
        "language_probability":    1.0,
        "alignment_mode":          "forced",
        "aligner":                 "ctc-forced-aligner/mms-300m-1130",
        "forced_language":         language,
        "pitch_engine":            pitch_engine,
        "vocal_regions_artifact":  vocal_regions_written,
        "alignment_windows_artifact": bool(alignment_windows),
        "ctc_windowed_alignment":  ctc_windowed_alignment,
        "ctc_window_quality_guard": guard_details or None,
        "ctc_windows_cover_lines": ctc_windows_cover_lines,
        "ctc_windows_safe_for_ctc": ctc_windows_safe,
        "alignment_window_count":  len(alignment_windows),
        "onset_snaps":             n_snapped,
        "phrase_extensions":       n_extended,
        "reference_timing_applied": reference_timing_applied,
        "segment_count":           len(segments),
        "word_count":              total_words_aligned,
        "section_distribution":    section_distribution,
        "unknown_section_markers": all_unknown,
        "segments":                segments,
    }

    logger.info(
        "Alignment complete: %d/%d words in %d segments",
        total_words_aligned, total_lyric_words, len(segments),
    )

    # ── Write output ───────────────────────────────────────────────────────
    output_path = job_dir / "transcript.json"
    output_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "Written: %s (%.1f KB, alignment_mode=forced)",
        output_path.name, output_path.stat().st_size / 1e3,
    )
    _write_event(
        job_dir,
        "stage03b.transcript_written",
        message="Forced alignment transcript written",
        artifact=output_path.name,
        details={
            "segment_count": len(segments),
            "word_count": total_words_aligned,
            "section_count": len(section_distribution),
            "unknown_marker_count": len(all_unknown),
            "unknown_markers": all_unknown,
            "pitch_engine": pitch_engine,
            "alignment_mode": "forced",
            "size_bytes": output_path.stat().st_size,
        },
    )

    _update_status(job_dir, "aligning_lyrics", 100)
    logger.info("Stage 03b complete.")
    _write_event(
        job_dir,
        "stage03b.completed",
        message="Stage 03b forced lyric alignment completed",
        details={
            "segment_count": len(segments),
            "word_count": total_words_aligned,
            "section_count": len(section_distribution),
            "unknown_marker_count": len(all_unknown),
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
