"""How many pixels of motion does an effect actually deliver?

"Looks subtle" is an opinion. The top of the row's ink band is a number: with
\an2 the bottom edge is pinned, so a syllable that scales up pushes the band
top higher, and a syllable that rises off-baseline does the same. Sampling the
band top across the animation window gives the peak excursion in pixels.

Usage: peak.py <mp4> <t0> <t1> <frames> <y0> <y1>
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

mp4, t0, t1, n = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
y0, y1 = int(sys.argv[5]), int(sys.argv[6])
tmp = Path(mp4).parent / "_peak"
tmp.mkdir(exist_ok=True)

tops, bottoms = [], []
for i in range(n):
    t = t0 + (t1 - t0) * i / max(1, n - 1)
    f = tmp / f"f{i:02d}.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
                    "-i", mp4, "-frames:v", "1", str(f)], check=True)
    a = np.array(Image.open(f).convert("L"))[y0:y1]
    lit = np.where(a.max(axis=1) > 60)[0]
    if lit.size:
        tops.append(y0 + int(lit[0]))
        bottoms.append(y0 + int(lit[-1]))

rest_top, rest_bottom = max(tops), max(bottoms)
print(f"  band top   : min={min(tops)} rest={rest_top}  -> peak rise {rest_top - min(tops)}px")
print(f"  band bottom: min={min(bottoms)} rest={rest_bottom}")
print(f"  resting glyph height: {rest_bottom - rest_top + 1}px")
print(f"  peak excursion as a share of glyph height: "
      f"{(rest_top - min(tops)) / max(1, rest_bottom - rest_top + 1):.1%}")
