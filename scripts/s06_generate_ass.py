r"""
s06_generate_ass.py — Generate ASS karaoke subtitles via pysubs2.

Produces Aegisub-quality karaoke using a single visible dialogue layer:
    Layer 0 — line with \kf tags and progressive fill

The \kf tag fills left-to-right using the style's secondary color (\2c).
Primary color (\1c) = not-yet-sung text. Secondary color (\2c) = sung fill.
This is how professional Aegisub karaoke templates work.

Style map (from analysis.json → ASS style):
    verse   → medium size, white/cyan
    chorus  → large, bold, white/yellow — visually dominant
    bridge  → italic, white/magenta
    intro   → small, gray/white — understated
    outro   → small, gray/white — understated
    ad_lib  → small, italic, white/green — differentiated

Each line gets:
    - \an8 positioning (top center) or \an2 (bottom center, configurable)
    - \fad(300, 500) fade in/out
    - \pos override if --position=custom

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
import contextlib
import json
import logging
import sys
import time
from dataclasses import dataclass
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
# Style definitions
# ---------------------------------------------------------------------------

@dataclass
class KaraokeStyle:
    r"""
    One ASS style definition.
    primary_color   = not-yet-sung text color   (\1c)  &HBBGGRR& format
    secondary_color = progressive fill color    (\2c)  filled by \kf
    outline_color   = border                    (\3c)
    back_color      = shadow/background         (\4c)
    """
    name:            str
    fontname:        str
    fontsize:        int
    bold:            bool
    italic:          bool
    primary_color:   str   # &HBBGGRR&
    secondary_color: str
    outline_color:   str
    back_color:      str
    outline:         float
    shadow:          float
    alignment:       int   # 2=bottom-center, 8=top-center
    margin_v:        int   # vertical margin in pixels
    border_style:    int = 1  # 1=Outline+Shadow, 3=Opaque Box
    flash_on_highlight: bool = False  # True = \bord8 glitch pulse fires on each word


# ASS color format: &HAABBGGRR (alpha + BGR, not RGB)
# AA=00 means fully opaque

def _c(r: int, g: int, b: int, a: int = 0) -> str:
    """Convert RGBA to ASS &HAABBGGRR format."""
    return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


# ── Preset: default (clean professional) ──────────────────────────────────

DEFAULT_STYLES: dict[str, KaraokeStyle] = {
    "verse": KaraokeStyle(
        name            = "Verse",
        fontname        = "Segoe UI Bold",
        fontsize        = 52,
        bold            = True,
        italic          = False,
        primary_color   = _c(220, 220, 220),   # light gray — waiting
        secondary_color = _c(0,   220, 255),   # cyan  — sung fill
        outline_color   = _c(0,   0,   0),     # black border
        back_color      = _c(0,   0,   0, 80), # semi-transparent shadow
        outline         = 2.5,
        shadow          = 1.5,
        alignment       = 2,
        margin_v        = 40,
    ),
    "chorus": KaraokeStyle(
        name            = "Chorus",
        fontname        = "Segoe UI Bold",
        fontsize        = 64,
        bold            = True,
        italic          = False,
        primary_color   = _c(255, 255, 255),   # white — waiting
        secondary_color = _c(0,   200, 255),   # bright cyan — sung
        outline_color   = _c(0,   60,  120),   # deep blue border
        back_color      = _c(0,   0,   0, 60),
        outline         = 3.0,
        shadow          = 2.0,
        alignment       = 2,
        margin_v        = 40,
    ),
    "bridge": KaraokeStyle(
        name            = "Bridge",
        fontname        = "Segoe UI Bold",
        fontsize        = 50,
        bold            = True,
        italic          = True,
        primary_color   = _c(210, 210, 255),   # lavender — waiting
        secondary_color = _c(200, 100, 255),   # purple — sung
        outline_color   = _c(0,   0,   0),
        back_color      = _c(0,   0,   0, 80),
        outline         = 2.5,
        shadow          = 1.5,
        alignment       = 2,
        margin_v        = 40,
    ),
    "intro": KaraokeStyle(
        name            = "Intro",
        fontname        = "Segoe UI Bold",
        fontsize        = 40,
        bold            = False,
        italic          = False,
        primary_color   = _c(180, 180, 180),   # gray — understated
        secondary_color = _c(200, 200, 200),   # light gray
        outline_color   = _c(0,   0,   0),
        back_color      = _c(0,   0,   0, 100),
        outline         = 2.0,
        shadow          = 1.0,
        alignment       = 2,
        margin_v        = 40,
    ),
    "outro": KaraokeStyle(
        name            = "Outro",
        fontname        = "Segoe UI Bold",
        fontsize        = 40,
        bold            = False,
        italic          = False,
        primary_color   = _c(180, 180, 180),
        secondary_color = _c(200, 200, 200),
        outline_color   = _c(0,   0,   0),
        back_color      = _c(0,   0,   0, 100),
        outline         = 2.0,
        shadow          = 1.0,
        alignment       = 2,
        margin_v        = 40,
    ),
    "ad_lib": KaraokeStyle(
        name            = "AdLib",
        fontname        = "Segoe UI Bold",
        fontsize        = 38,
        bold            = True,
        italic          = True,
        primary_color   = _c(200, 255, 200),   # light green
        secondary_color = _c(50,  255, 100),   # bright green — sung
        outline_color   = _c(0,   60,  0),
        back_color      = _c(0,   0,   0, 100),
        outline         = 2.0,
        shadow          = 1.0,
        alignment       = 2,
        margin_v        = 40,
    ),
}

# ── Preset: neon (Original Neon) ───────────────────────────────────────────

NEON_STYLES: dict[str, KaraokeStyle] = {
    k: KaraokeStyle(
        name            = v.name,
        fontname        = "Segoe UI Bold",
        fontsize        = v.fontsize + 4,
        bold            = True,
        italic          = v.italic,
        primary_color   = _c(40, 40, 40),      # near-black — waiting
        secondary_color = _c(0, 255, 180),     # neon teal — sung
        outline_color   = _c(0, 200, 120),
        back_color      = _c(0, 0, 0, 60),
        outline         = 3.0,
        shadow          = 0.0,
        alignment       = v.alignment,
        margin_v        = v.margin_v,
    )
    for k, v in DEFAULT_STYLES.items()
}

# Chorus gets special neon treatment
NEON_STYLES["chorus"] = KaraokeStyle(
    name            = "Chorus",
    fontname        = "Segoe UI Bold",
    fontsize        = 68,
    bold            = True,
    italic          = False,
    primary_color   = _c(60, 60, 60),
    secondary_color = _c(255, 220, 0),     # neon yellow
    outline_color   = _c(180, 140, 0),
    back_color      = _c(0, 0, 0, 60),
    outline         = 3.5,
    shadow          = 0.0,
    alignment       = 2,
    margin_v        = 40,
)

# ── Preset: cyberpunk (Premium Synthwave) ───────────────────────────────────

CYBERPUNK_STYLES: dict[str, KaraokeStyle] = {
    "verse": KaraokeStyle(
        name               = "Verse",
        fontname           = "Segoe UI Bold",
        fontsize           = 52,
        bold               = True,
        italic             = False,
        primary_color      = _c(123, 47, 190),   # Deep Purple (#7B2FBE) — waiting
        secondary_color    = _c(0, 245, 255),     # Electric Cyan (#00F5FF) — sung
        outline_color      = _c(0, 0, 0),
        back_color         = _c(0, 0, 0, 150),
        outline            = 2.5,
        shadow             = 1.5,
        alignment          = 2,
        margin_v           = 50,
        border_style       = 3,                   # Opaque Box for HUD/Bar look
        flash_on_highlight = True,                # \bord8 glitch pulse per word
    ),
    "chorus": KaraokeStyle(
        name               = "Chorus",
        fontname           = "Segoe UI Bold",
        fontsize           = 64,
        bold               = True,
        italic             = False,
        primary_color      = _c(255, 255, 255),   # White — waiting
        secondary_color    = _c(0, 245, 255),     # Electric Cyan — sung
        outline_color      = _c(123, 47, 190),    # Purple border
        back_color         = _c(0, 0, 0, 150),
        outline            = 3.0,
        shadow             = 2.0,
        alignment          = 2,
        margin_v           = 50,
        border_style       = 3,                   # Opaque Box
        flash_on_highlight = True,                # \bord8 glitch pulse per word
    ),
    "bridge": KaraokeStyle(
        name               = "Bridge",
        fontname           = "Segoe UI Bold",
        fontsize           = 52,
        bold               = True,
        italic             = True,
        primary_color      = _c(180, 0, 180),
        secondary_color    = _c(255, 255, 255),   # \kf fill goes white — natural flash
        outline_color      = _c(0, 0, 0),
        back_color         = _c(0, 0, 0, 150),
        outline            = 2.0,
        shadow             = 1.0,
        alignment          = 2,
        margin_v           = 50,
        border_style       = 3,                   # Opaque Box
        flash_on_highlight = False,               # italic+bord8 fica pesado; \kf fill é suficiente
    ),
    "intro":  DEFAULT_STYLES["intro"],
    "outro":  DEFAULT_STYLES["outro"],
    "ad_lib": DEFAULT_STYLES["ad_lib"],
}

SECTION_CODED_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(190, 220, 220),
        secondary_color=_c(90, 210, 220),
        outline_color=_c(0, 40, 48),
        back_color=_c(0, 0, 0, 90),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=False,
        primary_color=_c(245, 245, 245),
        secondary_color=_c(255, 255, 255),
        outline_color=_c(20, 20, 20),
        back_color=_c(0, 0, 0, 80),
        outline=2.4,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Bold",
        fontsize=54,
        bold=True,
        italic=False,
        primary_color=_c(255, 245, 190),
        secondary_color=_c(255, 220, 40),
        outline_color=_c(70, 54, 0),
        back_color=_c(0, 0, 0, 80),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Bold",
        fontsize=64,
        bold=True,
        italic=False,
        primary_color=_c(255, 235, 248),
        secondary_color=_c(255, 70, 190),
        outline_color=_c(90, 0, 52),
        back_color=_c(0, 0, 0, 70),
        outline=3.0,
        shadow=1.6,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(220, 255, 225),
        secondary_color=_c(80, 220, 120),
        outline_color=_c(0, 55, 20),
        back_color=_c(0, 0, 0, 80),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Bold",
        fontsize=60,
        bold=True,
        italic=False,
        primary_color=_c(255, 235, 210),
        secondary_color=_c(255, 130, 40),
        outline_color=_c(80, 34, 0),
        back_color=_c(0, 0, 0, 80),
        outline=3.0,
        shadow=1.4,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(190, 205, 235),
        secondary_color=_c(110, 150, 220),
        outline_color=_c(0, 25, 70),
        back_color=_c(0, 0, 0, 90),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": DEFAULT_STYLES["ad_lib"],
}

from scripts.karaoke_styles.library import PRESETS
from scripts.karaoke_styles.backdrop import emit_backdrop_commands


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


def _build_karaoke_text(
    words: list[dict],
    line_start_ms: int,
    effect: str,
    use_flash_default: bool = False,
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

    def append_segment(
        target: list[str],
        *,
        duration_cs: int,
        visible_segment: str,
    ) -> None:
        if effect == "fade_in":
            target.append(f"{{\\fad(500,0)\\be1\\kf{duration_cs}}}{visible_segment}")
        elif effect == "bounce":
            target.append(f"{{\\be1\\t(\\fscx115\\fscy115)\\t(\\fscx100\\fscy100)\\kf{duration_cs}}}{visible_segment}")
        elif effect == "flash" or (effect == "highlight" and use_flash_default):
            target.append(f"{{\\bord8\\t(0,200,\\bord2)\\be1\\kf{duration_cs}}}{visible_segment}")
        elif effect == "none":
            target.append(f"{{\\k{duration_cs}}}{visible_segment}")
        else:
            target.append(f"{{\\be1\\kf{duration_cs}}}{visible_segment}")

    timing = classify_line_timing({"style": line_style or "", "words": words})
    gap_policies = timing["inter_word_gaps"]

    visual_parts = []
    prev_end_ms = line_start_ms
    for index, (segments, start_ms, end_ms) in enumerate(word_segment_groups):
        next_start_ms = word_segment_groups[index + 1][1] if index + 1 < len(word_segment_groups) else None
        gap_policy = gap_policies[index] if index < len(gap_policies) else None
        should_absorb_gap = gap_policy is not None and gap_should_be_absorbed(gap_policy)
        visual_end_ms = max(end_ms, next_start_ms) if next_start_ms is not None and should_absorb_gap else end_ms

        gap_cs = max(0, (start_ms - prev_end_ms) // 10)
        if gap_cs > 0:
            visual_parts.append(f"{{\\k{gap_cs}}}")

        word_parts = []
        segment_prev_end_ms = start_ms
        visible_segments = [segment for segment in segments if str(segment.get("text", ""))]
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
            if segment_gap_cs > 0:
                word_parts.append(f"{{\\k{segment_gap_cs}}}")
            append_segment(
                word_parts,
                duration_cs=max(1, (segment_end_ms - segment_start_ms) // 10),
                visible_segment=visible_segment,
            )
            segment_prev_end_ms = segment_end_ms

        if word_parts:
            visual_parts.append("".join(word_parts))
        prev_end_ms = visual_end_ms

    return " ".join(
        p if p.startswith("{") else p
        for p in visual_parts
    ).strip()

    parts = []
    prev_end_ms = line_start_ms

    for word in words:
        segments = build_word_highlight_segments(word)
        if not segments:
            continue

        start_ms = int(min(float(segment["start"]) for segment in segments) * 1000)
        end_ms = int(max(float(segment["end"]) for segment in segments) * 1000)

        # Apply minimum duration floor
        if end_ms - start_ms < MIN_WORD_MS:
            end_ms = start_ms + MIN_WORD_MS

        # Gap before this word — consume with \k0 (no visual change)
        gap_cs = max(0, (start_ms - prev_end_ms) // 10)
        if gap_cs > 0:
            parts.append(f"{{\\k{gap_cs}}}")

        word_parts = []
        segment_prev_end_ms = start_ms
        for segment in segments:
            visible_segment = _escape_ass_text(str(segment["text"]))
            if not visible_segment:
                continue
            segment_start_ms = int(float(segment["start"]) * 1000)
            segment_end_ms = int(float(segment["end"]) * 1000)
            if segment_end_ms - segment_start_ms < MIN_WORD_MS:
                segment_end_ms = segment_start_ms + MIN_WORD_MS
            segment_gap_cs = max(0, (segment_start_ms - segment_prev_end_ms) // 10)
            if segment_gap_cs > 0:
                word_parts.append(f"{{\\k{segment_gap_cs}}}")

            duration_cs = max(1, (segment_end_ms - segment_start_ms) // 10)

            if effect == "fade_in":
                word_parts.append(f"{{\\fad(500,0)\\be1\\kf{duration_cs}}}{visible_segment}")
            elif effect == "bounce":
                word_parts.append(f"{{\\be1\\t(\\fscx115\\fscy115)\\t(\\fscx100\\fscy100)\\kf{duration_cs}}}{visible_segment}")
            elif effect == "flash" or (effect == "highlight" and use_flash_default):
                # Glitch/Digital flash: large border shrinks fast to normal
                word_parts.append(f"{{\\bord8\\t(0,200,\\bord2)\\be1\\kf{duration_cs}}}{visible_segment}")
            elif effect == "none":
                word_parts.append(f"{{\\k{duration_cs}}}{visible_segment}")
            else:
                # Default: clean \kf fill, no flash
                # (flash branch above already handles effect=="flash" and use_flash_default)
                word_parts.append(f"{{\\be1\\kf{duration_cs}}}{visible_segment}")
            segment_prev_end_ms = segment_end_ms

        if word_parts:
            parts.append("".join(word_parts))

        prev_end_ms = end_ms

    return " ".join(
        p if p.startswith("{") else p
        for p in parts
    ).strip()


def _bool_to_ass(b: bool) -> str:
    return "-1" if b else "0"


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

    Uses dual-layer technique:
        Layer 0 — base layer: full line text, no \kf tags, always visible
        Layer 1 — kf layer:   \kf tagged text, progressive fill on top

    This produces the classic "light up as you sing" effect without
    the text disappearing between syllables.
    """
    _cfg = app_config if app_config is not None else load_app_config()
    width, height = resolution.split("x")

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
        style_lines.append(
            f"Style: {s.name},"
            f"{s.fontname},{s.fontsize},"
            f"{s.primary_color},{s.secondary_color},{s.outline_color},{s.back_color},"
            f"{_bool_to_ass(s.bold)},{_bool_to_ass(s.italic)},0,0,"
            f"100,100,0,0,{s.border_style},{s.outline},{s.shadow},"
            f"{s.alignment},20,20,{s.margin_v},1"
        )

    styles_section = "\n".join(style_lines)

    # ── Events ────────────────────────────────────────────────────────────
    event_lines = ["[Events]",
                   "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    # Pre-compute display windows to enable overlap prevention.
    # Each line's display_end is capped at the next line's display_start
    # minus a 50ms gap to prevent visual collisions.
    display_windows: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        start_ms = int(line["start"] * 1000)
        end_ms   = int(line["end"]   * 1000)
        dstart   = max(0, start_ms - _cfg.generate_ass_preroll_ms)
        dend     = end_ms + _cfg.generate_ass_postroll_ms
        display_windows.append((dstart, dend))

    # Clamp each display_end so it does not overlap the next display_start
    for i in range(len(display_windows) - 1):
        dstart_curr, dend_curr = display_windows[i]
        dstart_next, _         = display_windows[i + 1]
        GAP_MS = _cfg.generate_ass_gap_ms
        if dend_curr > dstart_next - GAP_MS:
            display_windows[i] = (dstart_curr, max(dstart_curr + 100, dstart_next - GAP_MS))

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
            use_flash_default=s.flash_on_highlight,
            line_style=style_key,
        )

        # Single visible karaoke layer. The \kf text itself keeps the
        # not-yet-sung text visible and applies the progressive fill.
        event_lines.append(
            f"Dialogue: 0,{start_ts},{end_ts},{s.name},,0,0,0,,"
            f"{fade_tag}{kf_text}"
        )

    events_section = "\n".join(event_lines)

    return f"{script_info}\n{styles_section}\n\n{events_section}\n"


def _parse_color(ass_color: str) -> tuple[int, int, int]:
    """Extract R, G, B from &HAABBGGRR string."""
    c = ass_color.lstrip("&H")
    # Format: AABBGGRR
    b = int(c[2:4], 16)
    g = int(c[4:6], 16)
    r = int(c[6:8], 16)
    return r, g, b


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


def _display_window_clamp_count(lines: list[dict]) -> int:
    display_windows: list[tuple[int, int]] = []
    for line in lines:
        start_ms = int(line["start"] * 1000)
        end_ms = int(line["end"] * 1000)
        display_windows.append((max(0, start_ms - 200), end_ms + 300))

    clamp_count = 0
    for i in range(len(display_windows) - 1):
        dstart_curr, dend_curr = display_windows[i]
        dstart_next, _ = display_windows[i + 1]
        if dend_curr > dstart_next - 50:
            clamped_end = max(dstart_curr + 100, dstart_next - 50)
            if clamped_end != dend_curr:
                clamp_count += 1
    return clamp_count


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
    status_path.write_text(json.dumps(existing, indent=2))


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

def _write_backdrop(job_dir: Path, lines: list[dict]) -> tuple[Path, int] | None:
    """
    Escreve backdrop.cmd a partir das cores de analysis.json.

    Cosmetico: qualquer falha devolve None e o s07 cai para canvas preto.
    Nunca levanta — um fundo ruim nao pode impedir um export. Devolve o
    path e a contagem de linhas de comando, para o chamador nao precisar
    reabrir o arquivo so' para contar (ver stage06.backdrop_written).

    Um backdrop.cmd antigo e' removido quando o conteudo atual da' invalido
    ou vazio — a analise mudou e o fundo anterior nao corresponde mais a
    ela; sem isso, um re-run com analise ruim deixaria o s07 renderizando
    com os timings da corrida anterior enquanto o manifesto diz que nao ha
    backdrop. Ja' uma falha de ESCRITA (I/O transiente, ex.: disco cheio)
    preserva o arquivo existente: o conteudo seria valido, so' nao foi
    possivel grava-lo, e um write nao-atomico nao pode corromper o que ja'
    estava bom.
    """
    path = job_dir / "backdrop.cmd"
    tmp_path = path.with_name(path.name + ".tmp")

    try:
        content = emit_backdrop_commands(lines)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        logger.warning("backdrop.cmd nao gerado: %s", exc)
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
        return None

    if not content:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
        return None

    try:
        tmp_path.write_text(content + "\n", encoding="utf-8")  # sem BOM
        tmp_path.replace(path)  # atomic: nunca deixa um arquivo parcial em backdrop.cmd
    except OSError as exc:
        logger.warning("backdrop.cmd nao gravado: %s", exc)
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        return None

    return path, content.count("\n") + 1


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
        display_window_clamp_count=_display_window_clamp_count(lines),
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
    backdrop_result = _write_backdrop(job_dir, lines)
    backdrop_path, backdrop_cmd_count = backdrop_result if backdrop_result else (None, 0)
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
                },
                **({"backdrop.cmd": {"path": "backdrop.cmd"}} if backdrop_path else {}),
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
        output_paths={
            "output.ass": output_path,
            **({"backdrop.cmd": backdrop_path} if backdrop_path else {}),
        },
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
    _stage06_event(
        job_dir,
        "stage06.backdrop_written" if backdrop_path else "stage06.backdrop_skipped",
        path=str(backdrop_path) if backdrop_path else "",
        command_count=backdrop_cmd_count,
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
