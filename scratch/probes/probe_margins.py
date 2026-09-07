r"""T0 GATE: can a Dialogue event be displaced WITHOUT \pos, using its own
MarginL/MarginR/MarginV fields?

A ghost layer needs displacement -- that is what chromatic aberration is made
of. On the layout path every syllable already carries \pos so it is free. On
the NON-layout path the line has no \pos at all: position comes from alignment
plus margins. If the event's own margin fields displace it, ghost/glitch is
cheap on both paths. If they do not, ghost becomes layout-exclusive.

Measured, not assumed: render the same text with different event margins and
locate the ink.

CONTROL FIRST. The instrument here is "where is the ink", and an instrument
that cannot see a shift would report every variant as "no offset" -- exactly
the failure mode every probe in this directory hit at least once. So a \pos
variant with a KNOWN displacement runs first, and if the measurement does not
report that known shift, no verdict below it is usable.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path("scratch/marginprobe")
W, H = 960, 400

HEADER = (
    "[Script Info]\nScriptType: v4.00+\n"
    f"PlayResX: {W}\nPlayResY: {H}\nScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
    "MarginR, MarginV, Encoding\n"
    # Alignment 2 = bottom-centre, the alignment every shipped preset uses.
    "Style: P,Segoe UI Bold,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
    "-1,0,0,0,100,100,0,0,1,3,0,2,100,100,100,1\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text\n"
)

TEXT = "GHOST"


def ink(name: str, *, ml: int, mr: int, mv: int, tags: str = "") -> tuple[int, int]:
    """(centroid x, top y) of the drawn glyphs, or (-1, -1) if nothing drew."""
    (OUT / f"{name}.ass").write_text(
        HEADER + f"Dialogue: 0,0:00:00.00,0:00:01.00,P,,{ml},{mr},{mv},,{tags}{TEXT}\n",
        encoding="utf-8-sig",
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", "1",
         "-i", f"color=c=black:s={W}x{H}:r=25", "-vf", f"ass={name}.ass",
         "-frames:v", "1", f"{name}.png"],
        cwd=OUT, check=True,
    )
    img = np.array(Image.open(OUT / f"{name}.png").convert("L")).astype(int)
    ys, xs = np.nonzero(img > 100)
    if xs.size == 0:
        return -1, -1
    return int(round(xs.mean())), int(ys.min())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- CONTROL: a displacement the renderer definitely applies. ----------
    base_x, base_y = ink("m_base", ml=100, mr=100, mv=100)
    if base_x < 0:
        print("!! nothing drew at all -- probe is broken, no verdict usable")
        return 1
    pos_x, pos_y = ink("m_pos", ml=100, mr=100, mv=100,
                       tags=r"{\pos(%d,%d)}" % (W // 2 + 120, H - 100))
    dx_ctl, dy_ctl = pos_x - base_x, pos_y - base_y
    print(f"baseline (L=100 R=100 V=100)      ink centre x={base_x}  top y={base_y}")
    print(f"CONTROL  \pos +120px right       x={pos_x} (dx={dx_ctl:+d})  "
          f"y={pos_y} (dy={dy_ctl:+d})")
    if abs(dx_ctl) < 60:
        print(f"\n!! CONTROL DID NOT MOVE (dx={dx_ctl}) -- the measurement cannot "
              "see a displacement it was handed. No verdict below is usable.")
        return 1
    print(f"   control moved {dx_ctl:+d}px horizontally, so the rows below are real\n")

    # ---- The gate itself. -------------------------------------------------
    rows = [
        ("MarginL 300 / MarginR 100 (asymmetric)", dict(ml=300, mr=100, mv=100)),
        ("MarginL 100 / MarginR 300 (asymmetric)", dict(ml=100, mr=300, mv=100)),
        ("MarginV 100 -> 220",                     dict(ml=100, mr=100, mv=220)),
    ]
    horiz = vert = False
    for label, kw in rows:
        x, y = ink("m_" + label[:6].replace(" ", "_").replace("/", "_"), **kw)
        dx, dy = x - base_x, y - base_y
        horiz |= abs(dx) > 5 and kw["mv"] == 100
        vert |= abs(dy) > 5 and kw["ml"] == 100 and kw["mr"] == 100
        print(f"  {label:<40} x={x:4d} (dx={dx:+5d})  y={y:4d} (dy={dy:+5d})")

    print()
    if horiz and vert:
        print("GATE: offsets on BOTH axes -> build T4 as written, ghost is cheap "
              "on both paths.")
    elif vert:
        print("GATE: VERTICAL ONLY -> off the layout path glitch gets vertical "
              "displacement only; horizontal becomes layout-exclusive.")
    elif horiz:
        print("GATE: HORIZONTAL ONLY -> vertical ghost displacement becomes "
              "layout-exclusive.")
    else:
        print("GATE: NO OFFSET -> ghost/glitch is layout-exclusive. T4 shrinks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
