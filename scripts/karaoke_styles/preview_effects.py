r"""Render a visual preview of every karaoke effect in effects.py.

Builds a throwaway ASS that plays each effect on its own line, then burns it
over a dark background with ffmpeg (libass) — the same render path s07 uses,
so what you see here is what burns into the real video. No media input needed.

    python scripts/karaoke_styles/preview_effects.py

Output: scratch/effects_preview.mp4  (+ the .ass beside it)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.karaoke_styles.effects import EFFECTS, syllable_ass  # noqa: E402

# Fake syllables just to show the left-to-right fill and the per-syllable motion.
DEMO_WORDS = ["Bri", "lha", " es", "tre", "la", " a", "cor", "da"]
SYL_CS = 20          # centiseconds of \kf fill per syllable (~0.20s)
HOLD_CS = 70         # hold after the sweep completes so the line is readable
GAP_CS = 25          # blank gap between effects

# Everything effects.py can render. Order = play order.
SHOWCASE = sorted(EFFECTS)

WIDTH, HEIGHT = 1280, 720


def _ts(cs: int) -> str:
    s, cs = divmod(cs, 100)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass() -> tuple[str, int]:
    line_cs = len(DEMO_WORDS) * SYL_CS + HOLD_CS
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {WIDTH}\nPlayResY: {HEIGHT}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # &H AABBGGRR — gray waiting text, gold sung fill.
        "Style: Demo,Segoe UI Bold,74,&H00E0E0E0,&H0028C8FF,&H00000000,&H50000000,-1,0,0,0,"
        "100,100,0,0,1,3,1.5,5,60,60,0,1\n"
        "Style: Label,Segoe UI Bold,36,&H00FF9664,&H00FF9664,&H00000000,&H50000000,-1,0,0,0,"
        "100,100,0,0,1,2,1,8,60,60,70,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events: list[str] = []
    t = 20
    for name in SHOWCASE:
        start, end = t, t + line_cs
        syllables = "".join(syllable_ass(name, SYL_CS, w) for w in DEMO_WORDS)
        events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Demo,,0,0,0,,{{\\fad(200,200)}}{syllables}")
        events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Label,,0,0,0,,{{\\fad(200,200)}}{name}")
        t = end + GAP_CS
    return header + "\n".join(events) + "\n", t


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found on PATH", file=sys.stderr)
        return 2

    out_dir = Path(__file__).resolve().parents[2] / "scratch"
    out_dir.mkdir(exist_ok=True)
    ass_content, total_cs = build_ass()
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
    print(f"ok -> {out_dir / 'effects_preview.mp4'}  ({duration_s:.1f}s, {len(SHOWCASE)} effects)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
