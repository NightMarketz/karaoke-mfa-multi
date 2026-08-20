"""One frame per effect, stacked, label band kept above each lyric band.

Usage: montage.py <mp4> <out.png> <t0> <t1> ...
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

mp4, out = sys.argv[1], sys.argv[2]
times = [float(v) for v in sys.argv[3:]]
tmp = Path(out).parent / "_montage"
tmp.mkdir(exist_ok=True)

LABEL = (62, 120)     # y band carrying the effect name
LYRIC = (480, 700)    # each preset keeps its own MarginV, so the band is wide
X0, X1 = 90, 1190
SCALE = 0.55

rows = []
for i, t in enumerate(times):
    f = tmp / f"m{i:02d}.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
                    "-i", mp4, "-frames:v", "1", str(f)], check=True)
    a = np.array(Image.open(f).convert("RGB"))
    tile = np.concatenate([a[LABEL[0]:LABEL[1], X0:X1], a[LYRIC[0]:LYRIC[1], X0:X1]])
    rows.append(tile)
    rows.append(np.full((2, tile.shape[1], 3), 100, dtype=np.uint8))

sheet = np.concatenate(rows[:-1])
img = Image.fromarray(sheet)
img = img.resize((int(img.width * SCALE), int(img.height * SCALE)), Image.LANCZOS)
img.save(out)
print(f"{out}: {len(times)} effects, {img.width}x{img.height}")
