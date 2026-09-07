r"""Does libass actually ANIMATE the \clip band via \t, on THIS tag shape?

The band's GEOMETRY is pinned by tests/test_shine.py (rectangle, full-frame
height, marches right, leaves the frame at both ends) -- all computed in
Python, none of it proves libass draws the animation. This probe burns the
REAL production stack -- shine_layer() through compile_layer(), clipping a
full-frame white rectangle -- and measures whether the visible ink actually
moves between sampled instants.

HISTORY: the first version of `_shine_clip` drew a skewed four-point VECTOR
drawing (`\clip(m x y l ...)`), and this probe is the reason it no longer
does. Burned with the same three-instant, two-control discipline below, that
form never moved: DIAG-B (a plain \clip(x1,y1,x2,y2) rectangle animated via
\t, both endpoints on-frame) swept correctly, but the same test rewritten as
a vector drawing stayed frozen at its resting shape for the full 3s duration
of the event -- confirmed with a static-endpoint control so "frozen" wasn't
just "always off-frame" (the two static endpoint shapes drew 407px apart, so
a working \t would have shown motion). `_shine_clip` was rewritten as the
plain rectangle DIAG-B already proved works, and SHINE_SKEW was deleted.
DIAG-B below now runs the CURRENT `_shine_clip` directly (decoupled from the
compile_layer/shine_layer plumbing DIAG for cross-check), so it is expected
to move too now that the function it calls has changed shape.

CONTROL FIRST, same discipline as every probe in this directory (see
scratch/probes/README.md): a plain \move on an unrelated block, over the same
900ms window, must resolve to the requested slope before anything below it is
trusted. A single frame cannot tell a moving clip from a stuck one, and
(as this probe found out the hard way, back when the band was a vector
drawing) neither can 3 samples that are all off-frame the whole time -- a
resting value that starts off-frame stays invisible whether it is animating
off-frame -> off-frame or just stuck. So DIAG-B deliberately uses two
ON-FRAME `_shine_clip` outputs as the \t endpoints: if the render never
leaves the resting footprint, the band is not animating, full stop,
independent of where the real shine track's own endpoints happen to sit.
DIAG-C is the same test written as a bare rectangular (4-number) \clip
literal, to tell "\t is broken here" apart from "\t works, this particular
call site does not".
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.karaoke_styles.ass_compile import compile_layer, _shine_clip
from scripts.karaoke_styles.effects import shine_layer
from scripts.karaoke_styles.library import get_preset
from scripts.s06_generate_ass import style_row

OUT = Path("scratch/shineprobe")
PLAY_RES = (1920, 1080)
TRAVEL_MS = 900          # matches shine_layer's default travel_ms
INSTANTS_MS = (100, 450, 800)   # 3+ instants inside the travel window

STYLE = get_preset("pill").styles["verse"]

HEADER = (
    "[Script Info]\nScriptType: v4.00+\n"
    f"PlayResX: {PLAY_RES[0]}\nPlayResY: {PLAY_RES[1]}\n"
    "ScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
    "MarginR, MarginV, Encoding\n"
    + style_row(STYLE, scale=1.0, margin_lr=0) + "\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text\n"
)

# A rectangle drawn via \p1 that covers the WHOLE frame -- so what the burned
# frame shows is exactly whatever the clip (or \move, for the control) lets
# through, nothing about glyph shapes or antialiasing in the way.
RECT = f"m 0 0 l {PLAY_RES[0]} 0 {PLAY_RES[0]} {PLAY_RES[1]} 0 {PLAY_RES[1]}"


def ink_bounds(name: str, dialogue: str, *, at_ms: int) -> tuple[float, float, float]:
    """(min_x, max_x, centre_x) of drawn ink at the given instant, or (-1,-1,-1)."""
    (OUT / f"{name}.ass").write_text(HEADER + dialogue + "\n", encoding="utf-8-sig")
    at_s = at_ms / 1000.0
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", "3",
         "-i", f"color=c=black:s={PLAY_RES[0]}x{PLAY_RES[1]}:r=30",
         "-vf", f"ass={name}.ass", "-ss", f"{at_s:.3f}", "-frames:v", "1", f"{name}.png"],
        cwd=OUT, check=True,
    )
    img = np.array(Image.open(OUT / f"{name}.png").convert("L")).astype(int)
    ys, xs = np.nonzero(img > 40)
    if xs.size == 0:
        return -1.0, -1.0, -1.0
    return float(xs.min()), float(xs.max()), (xs.min() + xs.max()) / 2.0


def dialogue_for(tags: str) -> str:
    return f"Dialogue: 0,0:00:00.00,0:00:03.00,{STYLE.name},,0,0,0,,{tags}"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- CONTROL: plain \move on an unrelated block, same 900ms window -----
    # What matters is whether the instrument (ffmpeg burn + ink-bounds
    # measurement) resolves the REQUESTED SLOPE between sampled instants.
    move_dx = 600.0
    ctrl_tags = (
        r"{\p1\bord0\shad0\1c&HFFFFFF&"
        rf"\move(200,440,{200 + move_dx:.0f},440,0,{TRAVEL_MS})}}"
        "m 0 0 l 200 0 200 200 0 200"
    )
    print("-- CONTROL: \\move on a 200x200 block, 0->%dms --" % TRAVEL_MS)
    ctrl_samples = []
    for t in INSTANTS_MS:
        lo, hi, centre = ink_bounds("ctrl", dialogue_for(ctrl_tags), at_ms=t)
        ctrl_samples.append((t, lo, hi, centre))
        print(f"   t={t:4d}ms  ink x=[{lo:.1f}, {hi:.1f}]  centre={centre:.1f}")
    if any(c[3] < 0 for c in ctrl_samples):
        print("\n!! CONTROL DREW NOTHING at some instant -- probe is broken, no verdict usable")
        return 1
    ctrl_measured = [c[3] for c in ctrl_samples]
    monotonic = all(b > a for a, b in zip(ctrl_measured, ctrl_measured[1:]))
    slope_errs = []
    for (t_a, *_), (t_b, *_), c_a, c_b in zip(
        ctrl_samples, ctrl_samples[1:], ctrl_measured, ctrl_measured[1:]
    ):
        expected_delta = move_dx * (t_b - t_a) / TRAVEL_MS
        measured_delta = c_b - c_a
        slope_errs.append(abs(measured_delta - expected_delta))
        print(f"   {t_a}ms->{t_b}ms  expected delta={expected_delta:.1f}px  "
              f"measured delta={measured_delta:.1f}px")
    max_err = max(slope_errs)
    print(f"   monotonic={monotonic}, max slope error={max_err:.1f}px")
    if not monotonic or max_err > 30:
        print("\n!! CONTROL DID NOT MOVE AS REQUESTED -- the instrument cannot "
              "resolve this shift. No verdict below is usable.")
        return 1
    print("   control's measured slope matches the requested \\move -- "
          "the burn+measure pipeline is trusted.\n")

    # ---- DIAG-C: rectangular (4-number) \clip animated via \t, ON-FRAME ----
    # Isolates whether \t(...,\clip(...)) works AT ALL on this libass build,
    # independent of the drawing-vector question.
    rect_tags = (
        r"{\p1\bord0\shad0\1c&HFFFFFF&\clip(0,0,400,1080)"
        rf"\t(0,{TRAVEL_MS},\clip(1520,0,1920,1080))}}" + RECT
    )
    print("-- DIAG-C: rectangular \\clip(x1,y1,x2,y2) animated via \\t, on-frame -> on-frame --")
    diagc = []
    for t in INSTANTS_MS:
        lo, hi, centre = ink_bounds("diagc", dialogue_for(rect_tags), at_ms=t)
        diagc.append((t, lo, hi, centre))
        print(f"   t={t:4d}ms  ink x=[{lo:.1f}, {hi:.1f}]  centre={centre:.1f}")
    diagc_moved = all(b[3] > a[3] for a, b in zip(diagc, diagc[1:]))
    print(f"   rectangular \\clip via \\t moves: {diagc_moved}\n")

    # ---- DIAG-B: the real _shine_clip() called directly, both ends ON-FRAME -
    # v=0.3 and v=0.7 are both comfortably on-frame (unlike the real shine
    # track's own 0.0 -> 1.0, which starts and ends off-frame by design).
    # This is the test that actually distinguishes "animating, currently
    # off-frame" from "not animating at all, frozen at the resting value" --
    # and it is exactly this diagnostic that caught the original vector-drawing
    # `_shine_clip` frozen (see the module docstring's HISTORY section). It is
    # decoupled from compile_layer/shine_layer, unlike EXPERIMENT below.
    clip_a = _shine_clip(0.3, PLAY_RES)
    clip_b = _shine_clip(0.7, PLAY_RES)
    diagb_tags = (
        r"{\p1\bord0\shad0\1c&HFFFFFF&" + clip_a + rf"\t(0,{TRAVEL_MS},{clip_b})}}" + RECT
    )
    print("-- DIAG-B: _shine_clip() directly via \\t, on-frame -> on-frame --")
    print(f"   resting (v=0.3): {clip_a}")
    print(f"   target  (v=0.7): {clip_b}")
    diagb = []
    for t in INSTANTS_MS:
        lo, hi, centre = ink_bounds("diagb", dialogue_for(diagb_tags), at_ms=t)
        diagb.append((t, lo, hi, centre))
        print(f"   t={t:4d}ms  ink x=[{lo:.1f}, {hi:.1f}]  centre={centre:.1f}")
    diagb_moved = any(abs(b[3] - diagb[0][3]) > 5 for b in diagb[1:])
    print(f"   _shine_clip() via \\t moves: {diagb_moved}\n")

    # ---- EXPERIMENT: the real shine_layer stack through compile_layer ------
    layer = shine_layer(start_ms=0, travel_ms=TRAVEL_MS)
    token = compile_layer(
        layer, text="", duration_cs=300, attack_ms=0, frame=PLAY_RES, karaoke="k",
    )
    shine_tags = token + r"{\p1\bord0\shad0}" + RECT
    print("-- EXPERIMENT: compile_layer(shine_layer()) clipping a full-frame rect --")
    print(f"   tags: {token}\n")
    exp_samples = []
    for t in INSTANTS_MS:
        lo, hi, centre = ink_bounds("shine", dialogue_for(shine_tags), at_ms=t)
        exp_samples.append((t, lo, hi, centre))
        visible = "nothing visible" if centre < 0 else f"x=[{lo:.1f}, {hi:.1f}] centre={centre:.1f}"
        print(f"   t={t:4d}ms  {visible}")

    print(f"\nDIAG-C (bare rectangular \\clip literal via \\t) moves: {diagc_moved}")
    print(f"DIAG-B (_shine_clip() via \\t, on-frame endpoints) moves: {diagb_moved}")

    if not diagb_moved:
        print(
            "\nVERDICT: BAND DID NOT MOVE. _shine_clip()'s output, animated via "
            "\\t with both endpoints deliberately on-frame, never left its "
            "resting footprint (DIAG-B) even though DIAG-C shows a bare "
            "rectangular \\clip literal animates fine on this libass build -- "
            "so \\t itself is not broken, this specific call site is. Do not "
            "paper over this by adjusting the test."
        )
        return 1

    moved = any(s[3] != exp_samples[0][3] for s in exp_samples[1:] if s[3] >= 0)
    print("\nVERDICT: " + ("BAND MOVES across sampled instants" if moved
                            else "BAND DID NOT MOVE -- real finding, do not paper over it"))
    return 0 if moved else 1


if __name__ == "__main__":
    sys.exit(main())
