r"""
s06_generate_ass.py — Generate ASS karaoke subtitles via pysubs2.

Produces Aegisub-quality karaoke using a single visible dialogue layer:
    Layer 0 — line with \kf tags and progressive fill

The \kf tag fills left-to-right. In libass the sweep goes from SecondaryColour
to PrimaryColour, so PrimaryColour (\1c) = already-sung fill and SecondaryColour
(\2c) = not-yet-sung text. KaraokeStyle keeps designer-intuitive field names
(primary_color = waiting, secondary_color = sung fill); _generate_ass swaps
them onto the ASS Style line so the sweep lands the intended color.

Every style definition lives in scripts/karaoke_styles/library.py; this stage
only maps analysis.json's per-line style key onto the preset and writes the
file. line["style"] that the preset does not define falls back to "verse".

Placement comes from the style itself — Alignment (2 = bottom centre in every
shipped preset) plus MarginV. No \an or \pos override is emitted, so a player
honouring the style's own margins renders what the preset asked for.

The exception is an effect that animates position, rotation or uniform scale:
libass cannot do those without owning the syllable's origin, so such a line
becomes one Dialogue per syllable, each carrying its own \an2\pos computed from
real font metrics. See _build_layout_events and Effect.needs_layout.

Each line gets one \fad(fade_in, fade_out) and the \kf run built from its
words.

Usage:
    python scripts/s06_generate_ass.py --job-dir jobs/my-job

Usage (custom style preset):
    python scripts/s06_generate_ass.py --job-dir jobs/my-job --preset neon

Reads:
    jobs/{job_id}/analysis.json

Writes:
    jobs/{job_id}/output.ass
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from scripts.common.observability import record_artifact, write_event
from scripts.common.config import load_app_config
from scripts.common.provenance import file_sha256, write_manifest
from scripts.review_wizard.highlight_velocity import build_word_highlight_segments
from scripts.review_wizard.timing_layers import (
    SAFE_EXTENSION_CLASSES,
    apply_audio_backed_tail_extensions,
    build_audio_activity_map,
    build_audio_backed_timing,
    build_timing_diagnostics,
    classify_line_timing,
    gap_should_be_absorbed,
    is_review_only_audio_timing,
    summarize_audio_backed_timing,
    summarize_timing_layers,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Style library (single source of truth — scripts/karaoke_styles/)
# ---------------------------------------------------------------------------

from scripts.karaoke_styles.library import PRESETS, KaraokeStyle
from scripts.karaoke_styles.ass_compile import compile_syllable, unsupported_props
from scripts.karaoke_styles.effects import (
    DEFAULT_EFFECT,
    EFFECTS,
    TextEffect,
    resolve_effect,
    syllable_ass,
)
from scripts.karaoke_styles.fonts import measure, resolve_font_path
from scripts.karaoke_styles.layout import place

# Preset pixel values (fontsize, outline, shadow, margin_v) are authored
# against this canvas height and scaled to whatever the render asks for.
DESIGN_HEIGHT = 720
# Side margin as a share of frame width, so a long line wraps before the edge
# instead of at the flat 20px the style line used to carry.
SIDE_MARGIN_RATIO = 0.05


# ---------------------------------------------------------------------------
# ASS file builder (manual — pysubs2 for reading, direct write for control)
# ---------------------------------------------------------------------------

def _ms_to_ass(ms: int) -> str:
    """Convert milliseconds to ASS timestamp H:MM:SS.cc"""
    cs = ms // 10
    s  = cs // 100;  cs  %= 100
    m  = s  // 60;   s   %= 60
    h  = m  // 60;   m   %= 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass_text(text: str) -> str:
    return (
        text.replace("{", "")
        .replace("}", "")
        .replace("\\", "")
        .replace("\n", " ")
        .strip()
    )


def _quantize_kf_durations_to_centiseconds(
    durations_ms: list[int],
    *,
    target_ms: int,
    gap_cs: int = 0,
) -> list[int]:
    if not durations_ms:
        return []
    target_cs = max(len(durations_ms), int(round(target_ms / 10.0)) - gap_cs)
    durations = [max(1, int(round(duration_ms / 10.0))) for duration_ms in durations_ms]
    residual = target_cs - sum(durations)
    durations[-1] += residual
    if durations[-1] < 1:
        deficit = 1 - durations[-1]
        durations[-1] = 1
        for index in range(len(durations) - 2, -1, -1):
            if deficit <= 0:
                break
            available = max(0, durations[index] - 1)
            take = min(available, deficit)
            durations[index] -= take
            deficit -= take
    return durations


def _build_karaoke_text(
    words: list[dict],
    line_start_ms: int,
    effect: str,
    style_effect: str = "highlight",
    line_style: str | None = None,
) -> str:
    r"""
    Build the \kf tagged text for one karaoke line.

    Format: {\kf<duration_cs>}word {\kf<duration_cs>}word2 ...
    duration = word end - word start in centiseconds.

    A leading \k0 consumes time before the first word starts
    (silence/intro gap within the line).
    """
    # Minimum word highlight duration: 80ms = 8 centiseconds.
    # CTC forced alignment compresses function words (I, a, the) to zero
    # duration. A floor of 80ms ensures the highlight is visible even on
    # the fastest syllables without distorting the timing of longer words.
    MIN_WORD_MS = 80

    word_segment_groups = []
    for word in words:
        segments = build_word_highlight_segments(word)
        if not segments:
            continue
        start_ms = int(min(float(segment["start"]) for segment in segments) * 1000)
        end_ms = int(max(float(segment["end"]) for segment in segments) * 1000)
        if end_ms - start_ms < MIN_WORD_MS:
            end_ms = start_ms + MIN_WORD_MS
        word_segment_groups.append((segments, start_ms, end_ms))

    # Karaoke time consumed so far in this line, in centiseconds. ASS times \t
    # from the Dialogue start, so this is what lets an effect animate on the
    # syllable's own attack instead of on the line's first frame.
    elapsed_cs = 0

    def append_segment(
        target: list[str],
        *,
        duration_cs: int,
        visible_segment: str,
        offset_cs: int,
    ) -> None:
        target.append(
            syllable_ass(
                effect,
                duration_cs,
                visible_segment,
                offset_ms=offset_cs * 10,
                style_effect=style_effect,
            )
        )

    timing = classify_line_timing({"style": line_style or "", "words": words})
    gap_policies = timing["inter_word_gaps"]

    visual_parts = []
    prev_end_ms = line_start_ms
    for index, (segments, start_ms, end_ms) in enumerate(word_segment_groups):
        next_start_ms = word_segment_groups[index + 1][1] if index + 1 < len(word_segment_groups) else None
        gap_policy = gap_policies[index] if index < len(gap_policies) else None
        should_absorb_gap = gap_policy is not None and gap_should_be_absorbed(gap_policy)
        visual_end_ms = max(end_ms, next_start_ms) if next_start_ms is not None and should_absorb_gap else end_ms

        # The inter-word gap rides with the word that follows it. As its own
        # part it picked up a space on each side from the join below and burned
        # as "the  tomb" — the tag carries no glyph, so the second space was
        # pure padding that widened with the pause.
        word_parts = []
        gap_cs = max(0, (start_ms - prev_end_ms) // 10)
        if gap_cs > 0:
            word_parts.append(f"{{\\k{gap_cs}}}")
            elapsed_cs += gap_cs

        segment_prev_end_ms = start_ms
        visible_segments = [segment for segment in segments if str(segment.get("text", ""))]
        segment_runs = []
        for segment_index, segment in enumerate(visible_segments):
            visible_segment = _escape_ass_text(str(segment["text"]))
            if not visible_segment:
                continue
            segment_start_ms = int(float(segment["start"]) * 1000)
            segment_end_ms = int(float(segment["end"]) * 1000)
            if segment_index == len(visible_segments) - 1:
                segment_end_ms = max(segment_end_ms, visual_end_ms)
            if segment_end_ms - segment_start_ms < MIN_WORD_MS:
                segment_end_ms = segment_start_ms + MIN_WORD_MS
            segment_gap_cs = max(0, (segment_start_ms - segment_prev_end_ms) // 10)
            segment_runs.append(
                {
                    "gap_cs": segment_gap_cs,
                    "duration_ms": max(1, segment_end_ms - segment_start_ms),
                    "visible_segment": visible_segment,
                }
            )
            segment_prev_end_ms = segment_end_ms
        duration_cs_values = _quantize_kf_durations_to_centiseconds(
            [run["duration_ms"] for run in segment_runs],
            target_ms=max(1, visual_end_ms - start_ms),
            gap_cs=sum(run["gap_cs"] for run in segment_runs),
        )
        for run, duration_cs in zip(segment_runs, duration_cs_values):
            if run["gap_cs"] > 0:
                word_parts.append(f"{{\\k{run['gap_cs']}}}")
                elapsed_cs += run["gap_cs"]
            append_segment(
                word_parts,
                duration_cs=duration_cs,
                visible_segment=run["visible_segment"],
                offset_cs=elapsed_cs,
            )
            elapsed_cs += duration_cs

        if word_parts:
            chunk = "".join(word_parts)
            if segment_runs or not visual_parts:
                visual_parts.append(chunk)
            else:
                # Timing-only chunk (word had no visible text): glue it to the
                # previous word so it never becomes a space-padded part.
                visual_parts[-1] += chunk
        prev_end_ms = visual_end_ms

    return " ".join(visual_parts).strip()


def _effect_capability_gaps(
    lines: list[dict],
    styles: dict[str, KaraokeStyle],
) -> dict[str, list[str]]:
    r"""Effect id -> properties the ASS compiler dropped, for every effect in use.

    Resolved through resolve_effect, not read off line["effect"]: a plain
    "highlight" line is upgraded to its preset's highlight_effect, so a preset
    asking for something undeliverable renders as a bare sweep on every line
    while line["effect"] still says "highlight". That is exactly the case this
    report exists to catch.
    """
    gaps: dict[str, list[str]] = {}
    for line in lines:
        style = styles.get(line.get("style", "verse")) or styles.get("verse")
        style_effect = style.highlight_effect if style is not None else DEFAULT_EFFECT
        name = resolve_effect(line.get("effect", DEFAULT_EFFECT), style_effect)
        chosen = EFFECTS[name]
        if isinstance(chosen, TextEffect):
            continue
        missing = unsupported_props(chosen, anchored=chosen.needs_layout)
        if missing:
            gaps[name] = sorted(missing)
    return gaps


def _build_layout_events(
    line: dict,
    style: KaraokeStyle,
    *,
    scale: float,
    play_res: tuple[int, int],
    fade_tag: str,
    start_ts: str,
    end_ts: str,
    start_ms: int,
    effect: str,
) -> list[str]:
    r"""One Dialogue per syllable, each positioned with \pos.

    Every event spans the whole line window, so each syllable holds its fill
    back with a leading \k of the time elapsed before its own attack. That
    leading \k is the same number compile_syllable() anchors \t on, which is
    what keeps motion and fill agreed.

    `start_ms` is the DIALOGUE's start, which is the line's start minus the
    preroll — not line["start"]. \k, \t and \move all run on the Dialogue's
    clock, so measuring attacks from the line instead throws every animation
    early by the preroll AND leaves a lead-in effect with nowhere to come from:
    resolve() clamps at 0, so the first syllable's fly-in collapsed to
    \move(x,y,x,y,0,0) — a syllable that does not move, on every line.

    Anchoring is \an2, bottom-centre. MarginV means "distance from the bottom
    of the frame to the bottom of the text", so with \an2 the y we compute IS
    that edge and a layout preset lands on exactly the baseline every other
    preset in the library uses.
    """
    width_px, height_px = play_res
    font_path = resolve_font_path(style.fontname, bold=style.bold, italic=style.italic)
    # The ASS Fontsize this line's Style row carries. measure() converts it to
    # a FreeType size itself -- see fonts.py; they are not the same number.
    ass_size = round(style.fontsize * scale)

    texts: list[str] = []
    widths: list[float] = []
    space_after: list[float] = []
    attacks: list[int] = []
    durations: list[int] = []

    space_px = measure(" ", font_path=font_path, size_px=ass_size)
    for word in line["words"]:
        segments = [s for s in build_word_highlight_segments(word) if str(s.get("text", ""))]
        for i, segment in enumerate(segments):
            text = _escape_ass_text(str(segment["text"]))
            if not text:
                continue
            texts.append(text)
            widths.append(measure(text, font_path=font_path, size_px=ass_size))
            space_after.append(space_px if i == len(segments) - 1 else 0.0)
            seg_start_ms = int(float(segment["start"]) * 1000)
            seg_end_ms = int(float(segment["end"]) * 1000)
            attacks.append(max(0, seg_start_ms - start_ms))
            durations.append(max(1, (seg_end_ms - seg_start_ms) // 10))

    if not texts:
        return []

    placed = place(
        texts,
        widths=widths,
        space_after=space_after,
        max_width=width_px * (1 - 2 * SIDE_MARGIN_RATIO),
        centre_x=width_px / 2,
        bottom_y=height_px - round(style.margin_v * scale),
        # Exactly the ASS Fontsize, which is what libass stacks rows by. Not a
        # coincidence and not a guess: a Fontsize IS ascender + descender (the
        # same fact fonts.py derives measure() from), so it already is the
        # face's natural line height. Measured against a libass-wrapped render
        # of the same text: libass 74px, and the 1.2x this replaced gave 89.
        line_height=ass_size,
    )

    chosen = EFFECTS[effect] if effect in EFFECTS else EFFECTS[DEFAULT_EFFECT]
    events = []
    for spot, attack_ms, duration_cs in zip(placed, attacks, durations):
        anchor = (spot.x + spot.width / 2, spot.y)
        token = compile_syllable(
            chosen,
            text=spot.text,
            duration_cs=duration_cs,
            attack_ms=attack_ms,
            anchor=anchor,
        )
        # An effect that animates offset compiles to \move, which already
        # carries the destination. Emitting \pos as well leaves libass with two
        # positioning tags; it keeps the first and drops the other, so the
        # motion would silently vanish (or the placement would).
        placement = "" if "\\move(" in token else f"\\pos({anchor[0]:.1f},{anchor[1]:.1f})"
        lead_cs = attack_ms // 10
        lead = f"{{\\k{lead_cs}}}" if lead_cs > 0 else ""
        events.append(
            f"Dialogue: 0,{start_ts},{end_ts},{style.name},,0,0,0,,"
            f"{fade_tag}{{\\an2{placement}}}{lead}{token}"
        )
    return events


def _raw_display_window(line: dict, cfg) -> tuple[int, int]:
    """Pre-roll/post-roll window for one line, before overlap clamping."""
    start_ms = int(line["start"] * 1000)
    end_ms = int(line["end"] * 1000)
    return max(0, start_ms - cfg.generate_ass_preroll_ms), end_ms + cfg.generate_ass_postroll_ms


def _display_windows(lines: list[dict], cfg) -> list[tuple[int, int]]:
    """Display window per line, each end clamped so it cannot reach the next
    line's start. One implementation, so the manifest metric below cannot
    drift from what actually gets written."""
    windows = [_raw_display_window(line, cfg) for line in lines]
    for i in range(len(windows) - 1):
        start_curr, end_curr = windows[i]
        start_next, _ = windows[i + 1]
        limit = start_next - cfg.generate_ass_gap_ms
        if end_curr > limit:
            windows[i] = (start_curr, max(start_curr + 100, limit))
    return windows


def _bool_to_ass(b: bool) -> str:
    return "-1" if b else "0"


def style_row(
    style: KaraokeStyle,
    *,
    scale: float,
    margin_lr: int,
    name: str | None = None,
) -> str:
    r"""One [V4+ Styles] row for a preset style.

    Its own function because it is written in two places -- here and in the
    effect preview -- and the two details it encodes are both easy to get
    silently wrong. libass \kf sweeps SecondaryColour -> PrimaryColour, so the
    designer-facing secondary_color ("sung fill") goes in the ASS PRIMARY
    field; a straight-through copy previews every effect filling backwards.
    And every preset pixel is authored at 720p, so it scales here or the render
    is the wrong size at any other height. The preview got both wrong while it
    kept its own copy.
    """
    return (
        f"Style: {name or style.name},"
        f"{style.fontname},{round(style.fontsize * scale)},"
        f"{style.secondary_color},{style.primary_color},"
        f"{style.outline_color},{style.back_color},"
        f"{_bool_to_ass(style.bold)},{_bool_to_ass(style.italic)},0,0,"
        f"100,100,0,0,{style.border_style},"
        f"{round(style.outline * scale, 1)},{round(style.shadow * scale, 1)},"
        f"{style.alignment},{margin_lr},{margin_lr},{round(style.margin_v * scale)},1"
    )


def _generate_ass(
    lines:   list[dict],
    styles:  dict[str, KaraokeStyle],
    resolution: str,
    fade_in_ms:  int,
    fade_out_ms: int,
    app_config=None,
) -> str:
    r"""
    Build complete ASS file content as a string.

    One visible layer per line: the \kf run keeps the not-yet-sung text on
    screen and fills it left to right.

    Every pixel value in a preset is authored against a 720p canvas, so they
    are scaled by height/720 on the way out. Without it a 1080p render put the
    verse at 4.8% of frame height instead of the 7.2% the presets were drawn
    for, and the side margins were a flat 20px — a line could run to 1880 of
    1920px before wrapping.
    """
    _cfg = app_config if app_config is not None else load_app_config()
    width, height = resolution.split("x")
    scale = int(height) / DESIGN_HEIGHT
    margin_lr = round(int(width) * SIDE_MARGIN_RATIO)

    # ── Script Info ────────────────────────────────────────────────────────
    script_info = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
"""

    # ── Styles ────────────────────────────────────────────────────────────
    # Include only the visible karaoke style. A previous dual-layer renderer
    # emitted a dim base line plus a kf line at the same coordinates, which
    # made burned-in previews look like duplicated lyrics.
    style_lines = ["[V4+ Styles]",
                   "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                   "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                   "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                   "Alignment, MarginL, MarginR, MarginV, Encoding"]

    for style_key, s in styles.items():
        style_lines.append(style_row(s, scale=scale, margin_lr=margin_lr))

    styles_section = "\n".join(style_lines)

    # ── Events ────────────────────────────────────────────────────────────
    event_lines = ["[Events]",
                   "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    display_windows = _display_windows(lines, _cfg)

    for i, line in enumerate(lines):
        style_key = line.get("style", "verse")
        if style_key not in styles:
            style_key = "verse"
        s = styles[style_key]

        start_ms  = int(line["start"] * 1000)
        display_start_ms, display_end_ms = display_windows[i]

        start_ts      = _ms_to_ass(display_start_ms)
        end_ts        = _ms_to_ass(display_end_ms)
        fade_tag      = f"{{\\fad({fade_in_ms},{fade_out_ms})}}"
        kf_text = _build_karaoke_text(
            line["words"],
            start_ms,
            line.get("effect", "highlight"),
            style_effect=s.highlight_effect,
            line_style=style_key,
        )

        # Single visible karaoke layer. The \kf text itself keeps the
        # not-yet-sung text visible and applies the progressive fill.
        #
        # Unless the effect animates something libass cannot do in place, in
        # which case the line becomes one positioned Dialogue per syllable.
        chosen_effect = resolve_effect(line.get("effect", DEFAULT_EFFECT), s.highlight_effect)
        if EFFECTS[chosen_effect].needs_layout:
            event_lines.extend(_build_layout_events(
                line, s, scale=scale, play_res=(int(width), int(height)),
                fade_tag=fade_tag, start_ts=start_ts, end_ts=end_ts,
                start_ms=display_start_ms, effect=chosen_effect,
            ))
        else:
            event_lines.append(
                f"Dialogue: 0,{start_ts},{end_ts},{s.name},,0,0,0,,"
                f"{fade_tag}{kf_text}"
            )

    events_section = "\n".join(event_lines)

    return f"{script_info}\n{styles_section}\n\n{events_section}\n"

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_ass(content: str) -> list[str]:
    errors = []
    if "[Script Info]" not in content:
        errors.append("Missing [Script Info] section")
    if "[V4+ Styles]" not in content:
        errors.append("Missing [V4+ Styles] section")
    if "[Events]" not in content:
        errors.append("Missing [Events] section")
    if "\\kf" not in content:
        errors.append("No \\kf tags found — karaoke timing not applied")
    dialogue_count = content.count("\nDialogue:")
    if dialogue_count == 0:
        errors.append("No Dialogue lines generated")
    else:
        logger.info("Generated %d Dialogue lines", dialogue_count)
    return errors


def _ass_metrics(content: str) -> dict[str, int]:
    return {
        "dialogue_count": content.count("\nDialogue:"),
        "kf_count": content.count("\\kf"),
    }


def _audio_timing_diagnostics(audio_timings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def compact_audio_evidence(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        compact: dict[str, Any] = {}
        for key in ("active", "start_s", "end_s", "duration_s", "voiced_ratio", "rms", "threshold"):
            if key not in value:
                continue
            item = value[key]
            if isinstance(item, float):
                compact[key] = round(item, 4)
            else:
                compact[key] = item
        return compact

    diagnostics: list[dict[str, Any]] = []
    for line_index, timing in enumerate(audio_timings):
        line_classification = timing.get("line_classification")
        diagnostic_tags = timing.get("diagnostic_tags")
        if line_classification or diagnostic_tags:
            diagnostic = {
                "line_index": line_index,
                "line_classification": line_classification,
                "diagnostic_tags": diagnostic_tags or [],
                "confidence": timing.get("confidence"),
                "recommended_fallback": timing.get("recommended_fallback"),
            }
            if timing.get("sound_suggestion"):
                diagnostic["sound_suggestion"] = timing.get("sound_suggestion")
            diagnostics.append(diagnostic)

        tail = timing.get("tail") or {}
        tail_classification = tail.get("classification")
        if is_review_only_audio_timing(timing):
            continue
        if tail_classification in {
            "possible_lost_tail",
            "unwritten_interline_melisma",
            "false_long_tail",
        } or tail.get("sound_suggestion"):
            diagnostic = {
                "line_index": line_index,
                "tail_classification": tail_classification,
                "confidence": tail.get("confidence"),
                "recommended_fallback": tail.get("recommended_fallback"),
            }
            if tail.get("sound_suggestion"):
                diagnostic["sound_suggestion"] = tail.get("sound_suggestion")
            if tail.get("structural_tail_classification"):
                diagnostic["structural_tail_classification"] = tail.get("structural_tail_classification")
            if tail.get("review_flags"):
                diagnostic["review_flags"] = tail.get("review_flags")
            audio_evidence = compact_audio_evidence(tail.get("audio_evidence"))
            if audio_evidence:
                diagnostic["audio_evidence"] = audio_evidence
            diagnostics.append(diagnostic)
    return diagnostics


def _display_window_clamp_count(lines: list[dict], cfg) -> int:
    """How many lines had their display end pulled in by the next line."""
    return sum(
        1
        for line, clamped in zip(lines, _display_windows(lines, cfg))
        if _raw_display_window(line, cfg)[1] != clamped[1]
    )


def _update_status(job_dir: Path, stage: str, progress: int, error: str = "") -> None:
    status_path = job_dir / "status.json"
    existing: dict[str, Any] = {}
    if status_path.exists():
        try:
            existing = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            pass
        if not isinstance(existing, dict):
            existing = {}
    existing.update({
        "stage": stage, "progress": progress,
        "error": error, "updated_at": time.time(),
    })
    status_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _load_run_id(job_dir: Path) -> str:
    status_path = job_dir / "status.json"
    if not status_path.exists():
        return "manual"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "manual"
    if not isinstance(status, dict):
        return "manual"
    run_id = status.get("run_id")
    return str(run_id) if run_id else "manual"


def _stage06_event(
    job_dir: Path,
    event: str,
    level: str = "info",
    message: str = "",
    **details: Any,
) -> None:
    write_event(
        job_dir,
        event,
        "generating",
        level=level,
        message=message,
        details=details,
    )


def _stage06_missing_job_event(
    job_dir: Path,
    level: str,
    message: str,
    **details: Any,
) -> None:
    parent = job_dir.parent if job_dir.parent != job_dir else Path.cwd()
    write_event(
        parent / "_stage06",
        "stage06.failed",
        "generating",
        level=level,
        message=message,
        details={"missing_job_dir": str(job_dir), **details},
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    app_config = load_app_config()
    parser = argparse.ArgumentParser(
        description="Stage 06 — Generate ASS karaoke subtitles.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--job-dir",     required=True, type=Path)
    parser.add_argument("--preset",      default=app_config.generate_style_preset_id,
                        choices=list(PRESETS.keys()),
                        help="Style preset.")
    parser.add_argument("--resolution",  default=app_config.generate_resolution,
                        help="Output resolution (must match s07).")
    parser.add_argument("--fade-in",     type=int, default=app_config.generate_fade_in_ms,
                        help="Fade-in duration per line in ms.")
    parser.add_argument("--fade-out",    type=int, default=app_config.generate_fade_out_ms,
                        help="Fade-out duration per line in ms.")
    parser.add_argument("--log-level",   default=app_config.log_level,
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    job_dir: Path = args.job_dir.resolve()
    log_handlers: list[logging.Handler] = [logging.StreamHandler()]
    if job_dir.exists():
        log_handlers.append(logging.FileHandler(job_dir / "pipeline.log", mode="a"))
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
        handlers=log_handlers,
    )

    if not job_dir.exists():
        message = f"Job directory does not exist: {job_dir}"
        logger.error(message)
        _stage06_missing_job_event(
            job_dir,
            level="error",
            message=message,
            reason="job_dir_missing",
            path=str(job_dir),
        )
        return 1

    logger.info("Stage 06 · Generate ASS  preset=%s  resolution=%s",
                args.preset, args.resolution)

    # ── Validate input ─────────────────────────────────────────────────────
    _stage06_event(
        job_dir,
        "stage06.started",
        preset=args.preset,
        resolution=args.resolution,
        fade_in_ms=args.fade_in,
        fade_out_ms=args.fade_out,
    )
    _stage06_event(
        job_dir,
        "stage06.preset_selected",
        preset=args.preset,
        style_count=len(PRESETS[args.preset]),
    )

    analysis_path = job_dir / "analysis.json"
    if not analysis_path.exists() or analysis_path.stat().st_size == 0:
        message = "analysis.json missing or empty. Run Stage 05 first."
        logger.error(message)
        _stage06_event(
            job_dir,
            "stage06.input_missing",
            level="error",
            message=message,
            reason="missing_input",
            artifact="analysis.json",
        )
        _stage06_event(
            job_dir,
            "stage06.failed",
            level="error",
            message=message,
            reason="missing_input",
            artifact="analysis.json",
        )
        return 1

    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        message = f"analysis.json is not valid JSON: {exc}"
        logger.error(message)
        _stage06_event(
            job_dir,
            "stage06.failed",
            level="error",
            message=message,
            reason="invalid_input_json",
            artifact="analysis.json",
        )
        return 1

    lines    = analysis.get("lines", [])
    if not lines:
        message = "analysis.json has no lines."
        logger.error(message)
        _stage06_event(
            job_dir,
            "stage06.failed",
            level="error",
            message=message,
            reason="no_lines",
            artifact="analysis.json",
        )
        return 1

    logger.info("Lines to render: %d", len(lines))
    
    # ── Sanitise timeline — guard against inverted timestamps ──────────────
    # Inverted lines (end <= start) crash ASS players and JASSUB.
    # They originate from LLM hallucination in s05 or timestamp corruption
    # in s04. We discard them with a WARNING so the issue is visible in logs.
    valid_lines = []
    skipped_inverted = []
    for line in lines:
        if line.get("end", 0) <= line.get("start", 0):
            logger.warning(
                "Skipping line with inverted timestamps: "
                "start=%.4f end=%.4f text='%s'",
                line.get("start", 0), line.get("end", 0),
                line.get("text", "")[:60],
            )
            skipped_inverted.append(
                {
                    "start": line.get("start", 0),
                    "end": line.get("end", 0),
                    "text": str(line.get("text", ""))[:60],
                }
            )
        else:
            valid_lines.append(line)

    if len(valid_lines) < len(lines):
        logger.warning(
            "%d/%d lines discarded due to inverted timestamps.",
            len(lines) - len(valid_lines), len(lines),
        )
        _stage06_event(
            job_dir,
            "stage06.inverted_lines_skipped",
            level="warning",
            skipped_count=len(skipped_inverted),
            input_line_count=len(lines),
            examples=skipped_inverted[:5],
        )
    lines = valid_lines

    if not lines:
        logger.error("All lines had inverted timestamps — nothing to render.")
        _stage06_event(
            job_dir,
            "stage06.failed",
            level="error",
            message="All lines had inverted timestamps - nothing to render.",
            reason="all_lines_inverted",
        )
        return 1

    _update_status(job_dir, "generating", 0)

    # ── Generate ───────────────────────────────────────────────────────────
    styles = PRESETS[args.preset]

    # An effect asking for something libass cannot draw must not render as a
    # plain sweep in silence — the preview would disagree with the burn and
    # nothing would say why.
    for effect_id, dropped in _effect_capability_gaps(lines, styles).items():
        logger.warning("effect %r: ASS cannot render %s", effect_id, ", ".join(dropped))
        _stage06_event(
            job_dir,
            "stage06.effect_capability_gap",
            level="warning",
            message=f"effect {effect_id!r}: ASS cannot render {', '.join(dropped)}",
            effect=effect_id,
            dropped=dropped,
        )

    # Log style distribution
    style_counts: dict[str, int] = {}
    for line in lines:
        s = line.get("style", "verse")
        style_counts[s] = style_counts.get(s, 0) + 1
    logger.info("Style distribution: %s", style_counts)
    timing_summary = summarize_timing_layers(lines)
    timing_diagnostics = build_timing_diagnostics(lines)
    render_lines = lines
    timing_audio_layers: dict[str, Any] = {"available": False}
    vocals_path = job_dir / "vocals.wav"
    if vocals_path.exists() and vocals_path.stat().st_size > 0:
        try:
            audio_activity = build_audio_activity_map(lines, vocals_path)
            audio_timings = build_audio_backed_timing(lines, audio_activity=audio_activity)
            render_lines = apply_audio_backed_tail_extensions(lines, audio_timings)
            timing_audio_layers = {
                "available": True,
                "summary": summarize_audio_backed_timing(audio_timings),
                "diagnostics": _audio_timing_diagnostics(audio_timings),
                "applied_tail_extensions": sum(
                    1
                    for timing in audio_timings
                    if not is_review_only_audio_timing(timing)
                    and timing.get("tail", {}).get("classification") in SAFE_EXTENSION_CLASSES
                ),
                "applied_tail_trims": sum(
                    1
                    for timing in audio_timings
                    if not is_review_only_audio_timing(timing)
                    and timing.get("tail", {}).get("classification") == "false_long_tail"
                ),
            }
        except Exception as exc:
            timing_audio_layers = {
                "available": False,
                "error": str(exc),
            }
    _stage06_event(
        job_dir,
        "stage06.style_distribution",
        style_distribution=style_counts,
        line_count=len(lines),
    )
    _stage06_event(
        job_dir,
        "stage06.timestamp_validation",
        display_window_clamp_count=_display_window_clamp_count(lines, app_config),
        line_count=len(lines),
        timing_layers=timing_summary,
        timing_diagnostics=timing_diagnostics["summary"],
        timing_audio_layers=timing_audio_layers,
    )

    ass_content = _generate_ass(
        lines        = render_lines,
        styles       = styles,
        resolution   = args.resolution,
        fade_in_ms   = args.fade_in,
        fade_out_ms  = args.fade_out,
        app_config   = app_config,
    )
    ass_metrics = _ass_metrics(ass_content)
    _stage06_event(job_dir, "stage06.ass_generated", **ass_metrics)

    _update_status(job_dir, "generating", 70)

    # ── Validate ───────────────────────────────────────────────────────────
    errors = _validate_ass(ass_content)
    if errors:
        for e in errors:
            logger.error("ASS validation: %s", e)
        _stage06_event(
            job_dir,
            "stage06.validation_failed",
            level="error",
            message=errors[0],
            error_count=len(errors),
            errors=errors,
        )
        _stage06_event(
            job_dir,
            "stage06.failed",
            level="error",
            message=errors[0],
            reason="validation_failed",
            error=errors[0],
        )
        _update_status(job_dir, "failed", 0, errors[0])
        return 1

    # ── Write ──────────────────────────────────────────────────────────────
    output_path = job_dir / "output.ass"
    # ASS files must be UTF-8 with BOM for maximum player compatibility
    output_path.write_bytes(ass_content.encode("utf-8-sig"))
    logger.info("Written: %s (%.1f KB)", output_path.name,
                output_path.stat().st_size / 1e3)
    manifest_path = write_manifest(
        job_dir / "output.ass.manifest.json",
        {
            "stage": "stage06",
            "run_id": _load_run_id(job_dir),
            "preset": args.preset,
            "renderer_mode": "single_layer_kf",
            "inputs": {
                "analysis.json": {
                    "path": "analysis.json",
                    "sha256": file_sha256(analysis_path),
                }
            },
            "outputs": {
                "output.ass": {
                    "path": "output.ass",
                }
            },
            "metrics": {
                "analysis_line_count": len(lines),
                "dialogue_count": ass_metrics["dialogue_count"],
                "kf_count": ass_metrics["kf_count"],
            },
            "style_distribution": style_counts,
            "timing_layers": timing_summary,
            "timing_diagnostics": timing_diagnostics,
            "timing_audio_layers": timing_audio_layers,
        },
        output_paths={"output.ass": output_path},
    )
    artifact_details = record_artifact(job_dir, "generating", output_path)
    _stage06_event(
        job_dir,
        "stage06.ass_written",
        path=str(output_path),
        size_bytes=artifact_details["size_bytes"],
        manifest_path=str(manifest_path),
        manifest_sha256=file_sha256(manifest_path),
    )

    _update_status(job_dir, "generating", 100)
    _stage06_event(
        job_dir,
        "stage06.completed",
        line_count=len(lines),
        dialogue_count=ass_metrics["dialogue_count"],
        kf_count=ass_metrics["kf_count"],
        output="output.ass",
    )
    logger.info("Stage 06 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
