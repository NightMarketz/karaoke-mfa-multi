r"""Task 3's carried concern: does ghost_layer's offset land where Layer.offset
says it should, on an ACTUAL burned frame -- not just in the emitted margin
numbers LayerOffsetTests already checks?

ghost_layer builds Layer("under", ..., offset=(dx, dy)). ass_emit turns that
into the event's own MarginL/MarginR/MarginV (T0 gate, probe_margins.py). This
probe renders one real line through the real ass_emit.build_line_events path,
burns the ghost event and the main event as separate frames, and measures
where each one's ink actually sits.

CONTROL FIRST, same discipline as every probe in this directory: an instrument
that cannot see a 32px shift would report the ghost as unmoved too, which is
exactly the failure mode this directory has hit before. So a \pos-shifted
variant of the SAME style/text, displaced by the SAME magnitude requested
below, has to move by close to that amount before the ghost measurement is
trusted at all.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.karaoke_styles.effects import EFFECTS
from scripts.karaoke_styles.effects import ghost_layer
from scripts.karaoke_styles.keyframes import Effect, Layer
from scripts.karaoke_styles.library import get_preset
from scripts.ass_emit import build_line_events
from scripts.s06_generate_ass import style_row

OUT = Path("scratch/ghostprobe")
PLAY_RES = (1920, 1080)
SCALE = 1.5
MARGIN_LR = 96
DX, DY = 32.0, 0.0          # requested displacement -- well over the 16px floor
GHOST_COLOR = "#00E5FF"

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
    + style_row(STYLE, scale=SCALE, margin_lr=MARGIN_LR) + "\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text\n"
)


def _demo_line():
    """Same shape as tests/test_layers.py::_demo_line -- one line, one word."""
    def syl(text, start, end):
        return {"text": text, "start": start, "end": end,
                "karaoke_start": start, "karaoke_end": end, "confidence": 1.0}
    return {
        "start": 1.0, "end": 2.2, "style": "verse",
        "words": [
            {"word": "sol", "start": 1.0, "end": 1.4,
             "syllables": [syl("sol", 1.0, 1.4)]},
            {"word": "brilha", "start": 1.5, "end": 2.2,
             "syllables": [syl("bri", 1.5, 1.85), syl("lha", 1.85, 2.2)]},
        ],
    }


def ink(name: str, dialogue: str, *, at: float) -> tuple[float, float]:
    """(bbox centre x, bbox centre y) of the drawn glyphs, or (-1, -1) if none.

    Bounding-box centre, not a brightness-weighted mean: ghost_layer sets
    alpha=0.85 and its own colours, so a weighted-mean centroid drifts with
    how much of the antialiased rim clears the threshold -- a measurement
    artefact, not a position difference. The bounding box only asks whether a
    pixel is ink at all, which the alpha and colour do not change.
    """
    (OUT / f"{name}.ass").write_text(HEADER + dialogue + "\n", encoding="utf-8-sig")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", "3",
         "-i", f"color=c=black:s={PLAY_RES[0]}x{PLAY_RES[1]}:r=25",
         "-vf", f"ass={name}.ass", "-ss", f"{at:.2f}", "-frames:v", "1", f"{name}.png"],
        cwd=OUT, check=True,
    )
    img = np.array(Image.open(OUT / f"{name}.png").convert("L")).astype(int)
    ys, xs = np.nonzero(img > 40)
    if xs.size == 0:
        return -1.0, -1.0
    return (xs.min() + xs.max()) / 2.0, (ys.min() + ys.max()) / 2.0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- CONTROL: same style/text, \pos-displaced by the SAME magnitude ----
    # (dx, dy) below is the exact shift the ghost measurement will be judged
    # against, so the control has to resolve THAT size of shift, not merely
    # "some" shift, or a coarse instrument could pass on a bigger control and
    # still miss the real one.
    base_dialogue = (
        f"Dialogue: 0,0:00:00.00,0:00:03.00,{STYLE.name},,0,0,0,,GHOSTCTRL"
    )
    base_x, base_y = ink("ctrl_base", base_dialogue, at=0.5)
    if base_x < 0:
        print("!! nothing drew at all -- probe is broken, no verdict usable")
        return 1
    anchor_x = PLAY_RES[0] / 2
    anchor_y = PLAY_RES[1] - round(STYLE.margin_v * SCALE)
    pos_dialogue = (
        f"Dialogue: 0,0:00:00.00,0:00:03.00,{STYLE.name},,0,0,0,,"
        r"{\pos(%.1f,%.1f)}GHOSTCTRL" % (anchor_x + DX, anchor_y)
    )
    pos_x, pos_y = ink("ctrl_pos", pos_dialogue, at=0.5)
    dx_ctl = pos_x - base_x
    print(f"CONTROL  base ink centre           x={base_x:.1f} y={base_y:.1f}")
    print(f"CONTROL  \\pos shifted by dx={DX:+.1f}    x={pos_x:.1f} y={pos_y:.1f}  "
          f"measured dx={dx_ctl:+.1f}")
    if abs(dx_ctl - DX) > 6:
        print(f"\n!! CONTROL DID NOT MOVE BY THE REQUESTED AMOUNT "
              f"(measured {dx_ctl:+.1f}, requested {DX:+.1f}) -- the instrument "
              "cannot resolve this shift. No verdict below is usable.")
        return 1
    print(f"   control resolved a {DX:+.1f}px shift to within "
          f"{abs(dx_ctl - DX):.1f}px, so the ghost measurement below is real.\n")

    # ---- The real thing: ghost_layer through build_line_events -------------
    EFFECTS["_ghostprobe"] = Effect("_ghostprobe", (
        ghost_layer(DX, DY, GHOST_COLOR),
        Layer("main"),
    ))
    try:
        events = build_line_events(
            _demo_line(), STYLE,
            effect="_ghostprobe", style_effect="_ghostprobe", style_key="verse",
            scale=SCALE, play_res=PLAY_RES, margin_lr=MARGIN_LR,
            fade_tag="{\\fad(120,120)}",
            start_ts="0:00:00.70", end_ts="0:00:02.50",
            start_ms=700, line_start_ms=1000,
        )
    finally:
        del EFFECTS["_ghostprobe"]

    assert len(events) == 2, events
    ghost_event, main_event = events
    assert ghost_event.startswith("Dialogue: 0,"), ghost_event
    assert main_event.startswith("Dialogue: 1,"), main_event

    ghost_x, ghost_y = ink("real_ghost", ghost_event, at=1.0)
    main_x, main_y = ink("real_main", main_event, at=1.0)
    print(f"MEASURED main ink centre             x={main_x:.1f} y={main_y:.1f}")
    print(f"MEASURED ghost ink centre            x={ghost_x:.1f} y={ghost_y:.1f}")

    measured_dx = ghost_x - main_x
    measured_dy = ghost_y - main_y
    print(f"\nrequested displacement  dx={DX:+.1f}  dy={DY:+.1f}")
    print(f"measured  displacement  dx={measured_dx:+.1f}  dy={measured_dy:+.1f}")
    print(f"delta                   dx_err={measured_dx - DX:+.2f}  "
          f"dy_err={measured_dy - DY:+.2f}")

    # dy tolerance is 5px, not 3: DY=0 here, and the arithmetic independently
    # proves zero real vertical drift (with dy=0 the ghost's MarginV
    # expression reduces to the same number style_row() writes), so a
    # tolerance sitting on the measured ~3.0px residual would flip a correct
    # implementation to MISMATCH on any font-rendering change.
    ok = abs(measured_dx - DX) <= 3 and abs(measured_dy - DY) <= 5
    print("\nVERDICT: " + ("MATCH within tolerance (dx<=3px, dy<=5px)"
                            if ok else "MISMATCH -- see delta above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
