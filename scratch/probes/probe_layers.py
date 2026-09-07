r"""What does stacking layers per syllable cost to burn?

Rich karaoke effects are built by drawing the same syllable several times on
different Layer values -- a blurred copy underneath for glow, offset coloured
copies for chromatic aberration, a trail of fading copies behind a moving one.
So the real ceiling on "more complex" is not what libass can express, it is
what the burn can afford.

Takes a real generated .ass and multiplies every lyric event into N layered
copies, then times the burn. Reports events, wall time and the multiple over
the single-layer baseline.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "scratch/preset-preview/punch/output.ass")
SECONDS = 60
W, H = 1920, 1080
OUT = Path("scratch/layerprobe")


def layered(text: str, copies: int) -> str:
    """Multiply each Dialogue into `copies` layers: a blurred glow stack."""
    head, events = [], []
    for raw in text.splitlines():
        if raw.startswith("Dialogue:"):
            events.append(raw)
        else:
            head.append(raw)
    out = list(head)
    for raw in events:
        prefix, _, body = raw.partition(",,")
        fields = prefix.split(",", 1)
        for layer in range(copies):
            if layer == copies - 1:
                out.append(raw)                       # the real one, on top
            else:
                # Underneath: progressively wider and softer, as a glow stack.
                blur = 2 + 4 * (copies - 1 - layer)
                tint = f"{{\\blur{blur}\\bord{2 + layer}\\alpha&H60&}}"
                out.append(f"Dialogue: {layer},{fields[1]},,{tint}{body}")
    return "\n".join(out) + "\n"


def burn(path: Path) -> tuple[float, int]:
    n = sum(1 for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.startswith("Dialogue:"))
    start = time.time()
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", str(SECONDS),
         "-i", f"color=c=black:s={W}x{H}:r=30", "-vf", f"ass={path.name}",
         "-c:v", "libx264", "-preset", "ultrafast", "-f", "null", "-"],
        cwd=path.parent, check=True,
    )
    return time.time() - start, n


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    src = SRC.read_text(encoding="utf-8-sig")
    print(f"source: {SRC}   burn: {SECONDS}s of {W}x{H} @30\n")
    base = None
    for copies in (1, 2, 4, 8, 16):
        target = OUT / f"L{copies:02d}.ass"
        target.write_text(layered(src, copies), encoding="utf-8-sig")
        secs, n = burn(target)
        base = base or secs
        print(f"  {copies:2d} layer(s)  {n:5d} events  {secs:6.2f}s  "
              f"{secs / base:4.2f}x baseline  "
              f"({SECONDS / secs:5.1f}x realtime)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
