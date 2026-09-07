r"""Does animating a colour break the \kf karaoke fill?

\kf sweeps SecondaryColour -> PrimaryColour across the syllable. A colour
track that animates \1c is therefore writing to the same register the fill is
reading, and which one wins is not something to guess at -- it decides whether
colour tracks may touch the fill colour at all, or only the outline and shadow.

For each variant the sweep front is located directly: scan the text row and
find the rightmost column still showing the UNSUNG colour. If the fill works
that column marches right over time; if the fill is broken it does not move.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path("scratch/colourprobe")
W, H = 960, 200
SUNG = np.array([255, 255, 255])      # PrimaryColour   &H00FFFFFF -> white
UNSUNG = np.array([255, 128, 0])      # SecondaryColour &H000080FF -> orange

HEADER = (
    "[Script Info]\nScriptType: v4.00+\n"
    f"PlayResX: {W}\nPlayResY: {H}\nScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
    "MarginR, MarginV, Encoding\n"
    "Style: P,Segoe UI Bold,72,&H00FFFFFF,&H000080FF,&H00101010,&H00000000,"
    "-1,0,0,0,100,100,0,0,1,3,0,5,10,10,10,1\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text\n"
)

TEXT = "AAAAAAAAAAAA"

VARIANTS = [
    ("plain sweep (control)", r"{\kf100}" + TEXT),
    (r"sweep + \t on \1c (fill colour)", r"{\kf100\t(0,1000,\1c&H0000FF&)}" + TEXT),
    (r"sweep + static \1c override", r"{\1c&H0000FF&\kf100}" + TEXT),
    (r"sweep + \t on \3c (outline)", r"{\kf100\t(0,1000,\3c&H0000FF&)}" + TEXT),
    (r"sweep + \t on \2c (unsung)", r"{\kf100\t(0,1000,\2c&H00FF00&)}" + TEXT),
    (r"sweep + \t on \1a (fill alpha)", r"{\kf100\t(0,1000,\1a&HA0&)}" + TEXT),
]


def frame(name: str, text: str, at: float) -> np.ndarray:
    (OUT / f"{name}.ass").write_text(
        HEADER + f"Dialogue: 0,0:00:00.00,0:00:01.00,P,,0,0,0,,{text}\n",
        encoding="utf-8-sig",
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", "1",
         "-i", f"color=c=black:s={W}x{H}:r=50", "-vf", f"ass={name}.ass",
         "-ss", f"{at:.2f}", "-frames:v", "1", f"{name}.png"],
        cwd=OUT, check=True,
    )
    return np.array(Image.open(OUT / f"{name}.png").convert("RGB")).astype(int)


def front(img: np.ndarray) -> int:
    r"""Rightmost column whose brightest pixel is nearer SUNG than UNSUNG.

    The SUNG edge, not the unsung one. \kf fills left to right, so the last
    unsung column sits at the text's right edge from the first frame to the
    last and never moves -- measuring it reported the control itself as a dead
    fill, which is how this probe was wrong the first time.
    """
    best = -1
    for x in range(img.shape[1]):
        col = img[:, x]
        lit = col[col.sum(axis=1) > 150]
        if lit.size == 0:
            continue
        px = lit[lit.sum(axis=1).argmax()]
        if np.abs(px - SUNG).sum() < np.abs(px - UNSUNG).sum():
            best = x
    return best


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    times = (0.15, 0.45, 0.75)
    print(f"sweep front (rightmost unsung column) at t={times}\n")
    results = []
    for i, (label, text) in enumerate(VARIANTS):
        fronts = [front(frame(f"c{i}_{j}", text, t)) for j, t in enumerate(times)]
        moved = fronts[-1] - fronts[0]
        results.append((label, fronts, moved))
        verdict = "fill ALIVE" if moved > 50 else "fill DEAD"
        print(f"  {label:<34} {fronts}  moved={moved:+5d}  {verdict}")

    # The control has to move, or every verdict below it is meaningless. This
    # probe already reported a working fill as dead once by measuring the wrong
    # edge; a control that cannot fail would have let that stand.
    _, control_fronts, control_moved = results[0]
    if control_moved <= 50:
        print(f"\n!! CONTROL DID NOT SWEEP ({control_fronts}) -- probe is broken, "
              "no verdict above is usable")
        return 1
    print(f"\ncontrol swept {control_moved}px, so the verdicts above are real")
    return 0


if __name__ == "__main__":
    sys.exit(main())
