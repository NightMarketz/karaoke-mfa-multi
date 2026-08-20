"""Contact sheet across one syllable's animation window.

Stills lie about motion: a preset can look fine frozen and read as nothing at
all in play. This crops a band around one syllable and stacks consecutive
frames top to bottom, so the trajectory is visible as a shape.

Usage: strip.py <mp4> <out.png> <start_s> <end_s> <frames> [x0 x1 y0 y1]
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

mp4, out, t0, t1, n = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5])
crop = [int(v) for v in sys.argv[6:10]] if len(sys.argv) > 9 else None

tmp = Path(out).parent / "_strip"
tmp.mkdir(exist_ok=True)
rows = []
for i in range(n):
    t = t0 + (t1 - t0) * i / max(1, n - 1)
    f = tmp / f"f{i:02d}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", mp4,
         "-frames:v", "1", str(f)], check=True)
    a = np.array(Image.open(f).convert("RGB"))
    if crop:
        a = a[crop[2]:crop[3], crop[0]:crop[1]]
    # A one-pixel rule between frames so the boundaries are unambiguous.
    rows.append(a)
    rows.append(np.full((1, a.shape[1], 3), 90, dtype=np.uint8))

sheet = np.concatenate(rows[:-1], axis=0)
Image.fromarray(sheet).save(out)
print(f"{out}: {n} frames, {t0:.2f}s to {t1:.2f}s, {sheet.shape[1]}x{sheet.shape[0]}")
