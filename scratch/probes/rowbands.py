"""Find the ink row bands in a burned frame, so line spacing is measured.

Reports the bottom edge of each band and the gap between consecutive bottoms:
that gap IS the renderer's line height, and comparing mine to libass's is the
only way to know whether line_height = ass_size * 1.2 was a good guess.
"""
import sys

import numpy as np
from PIL import Image

for path in sys.argv[1:]:
    arr = np.array(Image.open(path).convert("L"))
    lit = arr.max(axis=1) > 60
    bands, start = [], None
    for y, on in enumerate(lit):
        if on and start is None:
            start = y
        elif not on and start is not None:
            if y - start > 8:          # ignore the small label band
                bands.append((start, y - 1))
            start = None
    if start is not None:
        bands.append((start, len(lit) - 1))
    lyric = [b for b in bands if b[1] - b[0] > 40]
    print(f"{path}")
    for top, bot in lyric:
        print(f"   band top={top} bottom={bot} height={bot - top + 1}")
    for (t0, b0), (t1, b1) in zip(lyric, lyric[1:]):
        print(f"   -> line height (bottom to bottom): {b1 - b0}px")
