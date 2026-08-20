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
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dataclasses import replace  # noqa: E402

from scripts.karaoke_styles.effects import EFFECTS  # noqa: E402
from scripts.karaoke_styles.library import KaraokeStyle, get_preset  # noqa: E402
from scripts.ass_emit import SIDE_MARGIN_RATIO, build_line_events  # noqa: E402
from scripts.s06_generate_ass import style_row  # noqa: E402

# Which preset's LOOK each effect is shown in. Eight of the ten are the preset
# that actually ships the effect, so what you see is what that preset burns.
#
# Two are not, and the difference matters when reading the result:
#   highlight  18 presets select it; pill is the flagship modern one.
#   none       NO preset selects it. The style here is borrowed, so this block
#              shows the effect faithfully and the pairing not at all.
PRESET_FOR_EFFECT = {
    "flash": "cyberpunk",
    "fly-in": "fly-in",
    "focus": "focus-pull",
    "highlight": "pill",
    "none": "bold-highlight",     # borrowed: bold-highlight itself selects highlight
    "pop": "word-pop",
    "punch": "punch",
    "reveal": "word-reveal",
    "swing": "swing",
    "typewriter": "typewriter",
}
BORROWED_STYLE = {"none"}

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
# Head and tail around a real line's own window. The head is not decoration:
# a lead-in effect resolves its keys against the DIALOGUE start, and with no
# head at all resolve() clamps them and the motion collapses.
PREROLL_CS = 30
POSTROLL_CS = 30

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


def _style_for(effect: str, style_key: str, *, one_style: bool) -> KaraokeStyle:
    r"""The KaraokeStyle this effect's block is drawn in, with a unique name.

    Each effect gets its own preset's look by default, taken at the LINE's own
    section key -- so a chorus line is drawn in the preset's chorus style, not
    in some stand-in. The ASS Style name has to be unique per (effect, section)
    or the ten blocks would all collide on one row named "Verse".
    """
    if one_style:
        return DEMO_STYLE
    preset = get_preset(PRESET_FOR_EFFECT.get(effect, "pill"))
    style = preset.styles.get(style_key) or preset.styles["verse"]
    return replace(style, name=f"{effect}~{style_key}")


def _shift_line(line: dict, delta_s: float) -> dict:
    """A copy of an analysis line with every timestamp moved by delta_s."""
    out = copy.deepcopy(line)
    out["start"] = float(out["start"]) + delta_s
    out["end"] = float(out["end"]) + delta_s
    for word in out.get("words", []):
        for key in ("start", "end", "start_s", "end_s"):
            if key in word:
                word[key] = float(word[key]) + delta_s
        for syllable in word.get("syllables") or []:
            for key in ("start", "end", "karaoke_start", "karaoke_end"):
                if key in syllable:
                    syllable[key] = float(syllable[key]) + delta_s
    return out


def job_lines(job_dir: str | Path, *, first: int = 0, count: int | None = None) -> list[dict]:
    r"""Real lyric lines from a job's analysis.json, for previewing on real material.

    The fake demo phrase is built to stress layout (it wraps, it has short and
    long words). Real lyrics stress something else entirely -- syllables of
    wildly uneven duration, lines that start on a beat, words the aligner split
    oddly -- and an effect can read perfectly on the demo and badly on a song.
    """
    data = json.loads((Path(job_dir) / "analysis.json").read_text(encoding="utf-8"))
    lines = data["lines"][first:]
    return lines[:count] if count else lines


def build_ass(
    effect_ids: list[str] | None = None,
    *,
    lines: list[dict] | None = None,
    one_style: bool = False,
) -> tuple[str, int]:
    """(ass text, total centiseconds). Unknown effect ids raise KeyError.

    `lines` are analysis.json-shaped lyric lines to play once per effect; the
    built-in demo phrase is used when they are not given.

    Each effect is drawn in its own preset's look. `one_style` puts every one
    of them in the same style instead, which isolates the effect as the only
    variable -- useful for judging motion, useless for judging what ships.
    """
    showcase = sorted(EFFECTS) if effect_ids is None else list(effect_ids)
    unknown = [name for name in showcase if name not in EFFECTS]
    if unknown:
        raise KeyError(
            f"unknown effect(s): {', '.join(unknown)} "
            f"(known: {', '.join(sorted(EFFECTS))})"
        )

    if lines:
        span_cs = round((float(lines[-1]["end"]) - float(lines[0]["start"])) * 100)
        block_cs = PREROLL_CS + span_cs + POSTROLL_CS + HOLD_CS
    else:
        block_cs = LEAD_CS + SYL_COUNT * SYL_CS + HOLD_CS
    # Every (effect, section) pair in play needs its own Style row. Collected
    # first so the header can be written before the events that reference it.
    section_keys = sorted({str(ln.get("style") or "verse") for ln in lines}) if lines \
        else ["verse"]
    used: dict[str, KaraokeStyle] = {}
    for name in showcase:
        for key in section_keys:
            s = _style_for(name, key, one_style=one_style)
            used[s.name] = s

    scale = HEIGHT / DESIGN_HEIGHT
    style_rows = "\n".join(
        style_row(s, scale=scale, margin_lr=MARGIN_LR) for s in used.values()
    )
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {WIDTH}\nPlayResY: {HEIGHT}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style_rows}\n"
        "Style: Label,Segoe UI Bold,36,&H00FF9664,&H00FF9664,&H00000000,&H50000000,-1,0,0,0,"
        f"100,100,0,0,1,2,1,8,{MARGIN_LR},{MARGIN_LR},70,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events: list[str] = []
    fade = "{\\fad(200,200)}"
    t = 20
    for name in showcase:
        block_start, block_end = t, t + block_cs

        # (line, its own Dialogue window) pairs for this effect's block.
        if lines:
            base = float(lines[0]["start"]) - PREROLL_CS / 100
            shifted = [_shift_line(ln, block_start / 100 - base) for ln in lines]
            windows = [
                (ln,
                 round(float(ln["start"]) * 100) - PREROLL_CS,
                 round(float(ln["end"]) * 100) + POSTROLL_CS)
                for ln in shifted
            ]
        else:
            windows = [(_demo_line(block_start + LEAD_CS), block_start, block_end)]

        for line, win_start, win_end in windows:
            style = _style_for(
                name, str(line.get("style") or "verse"), one_style=one_style
            )
            # s06's own builder, not a second copy of it: this is what burns,
            # gap absorption, \kf quantisation and every layer included.
            events += build_line_events(
                line, style,
                effect=name,
                style_effect=name,
                style_key=str(line.get("style") or "verse"),
                scale=scale,
                play_res=(WIDTH, HEIGHT),
                margin_lr=MARGIN_LR,
                fade_tag=fade,
                start_ts=_ts(win_start), end_ts=_ts(win_end),
                start_ms=win_start * 10,
                line_start_ms=round(float(line["start"]) * 1000),
            )

        events.append(
            f"Dialogue: 0,{_ts(block_start)},{_ts(block_end)},Label,,0,0,0,,{fade}{name}"
        )
        t = block_end + GAP_CS
    return header + "\n".join(events) + "\n", t


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "effects", nargs="*",
        help=f"effect ids to preview (default: all). Known: {', '.join(sorted(EFFECTS))}",
    )
    parser.add_argument(
        "--job", metavar="DIR",
        help="play real lyrics from this job's analysis.json instead of the demo phrase",
    )
    parser.add_argument("--first", type=int, default=0, metavar="N",
                        help="index of the first --job line to play (default 0)")
    parser.add_argument("--lines", type=int, default=4, metavar="N",
                        help="how many --job lines to play, 0 for all (default 4)")
    parser.add_argument("--one-style", action="store_true",
                        help="draw every effect in the same style, isolating the "
                             "effect as the only variable")
    parser.add_argument("-o", "--out", default="effects_preview", metavar="NAME",
                        help="output basename under scratch/ (default effects_preview)")
    args = parser.parse_args(argv)

    if not shutil.which("ffmpeg"):
        print("ffmpeg not found on PATH", file=sys.stderr)
        return 2

    try:
        lines = (
            job_lines(args.job, first=args.first, count=args.lines or None)
            if args.job else None
        )
        ass_content, total_cs = build_ass(
            args.effects or None, lines=lines, one_style=args.one_style
        )
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"could not read job lines: {exc}", file=sys.stderr)
        return 2
    count = len(args.effects) if args.effects else len(EFFECTS)

    out_dir = Path(__file__).resolve().parents[2] / "scratch"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{args.out}.ass").write_bytes(ass_content.encode("utf-8-sig"))

    duration_s = total_cs / 100 + 0.5
    # Run from out_dir so the ass= filter gets a bare relative filename and we
    # dodge the Windows "C:\..." colon-escaping trap entirely.
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x14141C:s={WIDTH}x{HEIGHT}:r=30:d={duration_s:.2f}",
        "-vf", f"ass={args.out}.ass",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        f"{args.out}.mp4",
    ]
    proc = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-2000:])
        return proc.returncode
    where = f" on {len(lines)} lines of {args.job}" if lines else ""
    print(f"ok -> {out_dir / (args.out + '.mp4')}  "
          f"({duration_s:.1f}s, {count} effects{where})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
