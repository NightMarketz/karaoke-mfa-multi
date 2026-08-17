r"""Render a visual preview of every karaoke effect in effects.py.

Builds a throwaway ASS that plays each effect on its own line, then burns it
over a dark background with ffmpeg (libass) — the same render path s07 uses,
so what you see here is what burns into the real video. No media input needed.

    python scripts/karaoke_styles/preview_effects.py            # everything
    python scripts/karaoke_styles/preview_effects.py punch swing

This is the loop the keyframe language exists for: edit six lines of track data
in effects.py, run this, watch it. It goes through s06's own
_build_layout_events for effects that need real positioning, so a motion preset
previews the way it burns rather than as a plain sweep.

Output: scratch/effects_preview.mp4  (+ the .ass beside it)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.karaoke_styles.effects import EFFECTS, syllable_ass  # noqa: E402
from scripts.karaoke_styles.library import KaraokeStyle  # noqa: E402
from scripts.s06_generate_ass import SIDE_MARGIN_RATIO, _build_layout_events  # noqa: E402

# Fake lyrics, grouped the way analysis.json groups them: words made of
# syllables. The layout path needs that grouping to know where a word ends and
# a space belongs; the in-place path just joins it back with spaces.
#
# Long enough to WRAP on purpose. Measured at 1162px against a 1152px margin --
# 1.01x, which is the most informative width there is: greedy filling strands a
# single word alone on the second row, so the balancing pass has to earn its
# place. It also puts a layout preset's own wrapping and libass's side by side
# in the same preview, which is the only way to see how far apart they land.
DEMO_WORDS: list[tuple[str, list[str]]] = [
    ("Brilha", ["Bri", "lha"]),
    ("estrela", ["es", "tre", "la"]),
    ("acorda", ["a", "cor", "da"]),
    ("o", ["o"]),
    ("mundo", ["mun", "do"]),
    ("inteiro", ["in", "tei", "ro"]),
    ("dorme", ["dor", "me"]),
]
SYL_COUNT = sum(len(s) for _, s in DEMO_WORDS)

SYL_CS = 20          # centiseconds of \kf fill per syllable (~0.20s)
HOLD_CS = 70         # hold after the sweep completes so the line is readable
GAP_CS = 25          # blank gap between effects
LEAD_CS = 40         # blank head, so a lead-in effect has room to lead in

WIDTH, HEIGHT = 1280, 720
DESIGN_HEIGHT = 720
MARGIN_V = 300       # both paths sit here, so the effects are comparable
# Must be the ratio _build_layout_events wraps against, or the two paths wrap
# at different widths and the preview compares them unfairly.
MARGIN_LR = round(WIDTH * SIDE_MARGIN_RATIO)

# The ASS Style below, as data, for the layout path. fontsize/margin_v/name
# must match the "Demo" Style row exactly or a positioned syllable lands
# somewhere the in-place lines never go.
DEMO_STYLE = KaraokeStyle(
    name="Demo",
    fontname="Segoe UI Bold",
    fontsize=74,
    bold=True,
    italic=False,
    primary_color="&H00E0E0E0",
    secondary_color="&H0028C8FF",
    outline_color="&H00000000",
    back_color="&H50000000",
    outline=3.0,
    shadow=1.5,
    alignment=2,
    margin_v=MARGIN_V,
)


def _ts(cs: int) -> str:
    s, cs = divmod(cs, 100)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _demo_line(attack_cs: int) -> dict:
    """One analysis.json-shaped line whose first syllable attacks at attack_cs."""
    words = []
    at = attack_cs
    for word, syllables in DEMO_WORDS:
        parts = []
        for text in syllables:
            parts.append({
                "text": text,
                "karaoke_start": at / 100,
                "karaoke_end": (at + SYL_CS) / 100,
                "confidence": 1.0,
            })
            at += SYL_CS
        words.append({
            "word": word,
            "start": parts[0]["karaoke_start"],
            "end": parts[-1]["karaoke_end"],
            "syllables": parts,
        })
    return {
        "start": attack_cs / 100,
        "end": at / 100,
        "style": "verse",
        "words": words,
    }


def build_ass(effect_ids: list[str] | None = None) -> tuple[str, int]:
    """(ass text, total centiseconds). Unknown effect ids raise KeyError."""
    showcase = sorted(EFFECTS) if effect_ids is None else list(effect_ids)
    unknown = [name for name in showcase if name not in EFFECTS]
    if unknown:
        raise KeyError(
            f"unknown effect(s): {', '.join(unknown)} "
            f"(known: {', '.join(sorted(EFFECTS))})"
        )

    line_cs = LEAD_CS + SYL_COUNT * SYL_CS + HOLD_CS
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {WIDTH}\nPlayResY: {HEIGHT}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # \kf sweeps ASS SecondaryColour -> PrimaryColour, so the sung fill goes
        # in the Primary field. Swapped here exactly as s06 swaps it: the old
        # preview wrote the fields straight through and previewed every effect
        # filling the opposite way from how it burns.
        f"Style: Demo,{DEMO_STYLE.fontname},{DEMO_STYLE.fontsize},"
        f"{DEMO_STYLE.secondary_color},{DEMO_STYLE.primary_color},"
        f"{DEMO_STYLE.outline_color},{DEMO_STYLE.back_color},-1,0,0,0,"
        f"100,100,0,0,1,{DEMO_STYLE.outline},{DEMO_STYLE.shadow},"
        f"{DEMO_STYLE.alignment},{MARGIN_LR},{MARGIN_LR},{MARGIN_V},1\n"
        "Style: Label,Segoe UI Bold,36,&H00FF9664,&H00FF9664,&H00000000,&H50000000,-1,0,0,0,"
        f"100,100,0,0,1,2,1,8,{MARGIN_LR},{MARGIN_LR},70,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events: list[str] = []
    fade = "{\\fad(200,200)}"
    t = 20
    for name in showcase:
        start, end = t, t + line_cs
        line = _demo_line(start + LEAD_CS)
        if EFFECTS[name].needs_layout:
            events += _build_layout_events(
                line, DEMO_STYLE,
                scale=HEIGHT / DESIGN_HEIGHT,
                play_res=(WIDTH, HEIGHT),
                fade_tag=fade,
                start_ts=_ts(start), end_ts=_ts(end),
                start_ms=start * 10,
                effect=name,
            )
        else:
            parts = [f"{{\\k{LEAD_CS}}}"]
            elapsed = LEAD_CS
            for index, (_, syllables) in enumerate(DEMO_WORDS):
                if index:
                    parts.append(" ")
                for text in syllables:
                    parts.append(
                        syllable_ass(name, SYL_CS, text, offset_ms=elapsed * 10)
                    )
                    elapsed += SYL_CS
            events.append(
                f"Dialogue: 0,{_ts(start)},{_ts(end)},Demo,,0,0,0,,{fade}{''.join(parts)}"
            )
        events.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},Label,,0,0,0,,{fade}{name}"
        )
        t = end + GAP_CS
    return header + "\n".join(events) + "\n", t


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "effects", nargs="*",
        help=f"effect ids to preview (default: all). Known: {', '.join(sorted(EFFECTS))}",
    )
    args = parser.parse_args(argv)

    if not shutil.which("ffmpeg"):
        print("ffmpeg not found on PATH", file=sys.stderr)
        return 2

    try:
        ass_content, total_cs = build_ass(args.effects or None)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2
    count = len(args.effects) if args.effects else len(EFFECTS)

    out_dir = Path(__file__).resolve().parents[2] / "scratch"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "effects_preview.ass").write_bytes(ass_content.encode("utf-8-sig"))

    duration_s = total_cs / 100 + 0.5
    # Run from out_dir so the ass= filter gets a bare relative filename and we
    # dodge the Windows "C:\..." colon-escaping trap entirely.
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x14141C:s={WIDTH}x{HEIGHT}:r=30:d={duration_s:.2f}",
        "-vf", "ass=effects_preview.ass",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "effects_preview.mp4",
    ]
    proc = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-2000:])
        return proc.returncode
    print(f"ok -> {out_dir / 'effects_preview.mp4'}  ({duration_s:.1f}s, {count} effects)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
