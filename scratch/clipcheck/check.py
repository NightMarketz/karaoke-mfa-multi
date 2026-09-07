r"""Independent check: does THIS libass interpolate a VECTOR \clip through \t?

Three variants, each burned at three instants, each measuring the same thing:
the horizontal centre of the ink that survives the mask.

  A. CONTROL -- animated RECTANGULAR \clip(x1,y1,x2,y2). Known-good shape.
  B. animated VECTOR \clip(m ... l ...). The shape `shine` uses.
  C. STATIC vector clip at two different fixed values, rendered as two files.
     This is the control for B: it proves the vector form draws AT ALL and
     that the two endpoint shapes are distinguishable by this measurement.
     Without C, "B did not move" could equally mean "B never drew".
"""
import subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image

OUT = Path("scratch/clipcheck"); W, H = 960, 200
HEAD = ("[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: P,Segoe UI Bold,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
        "-1,0,0,0,100,100,0,0,1,0,0,5,10,10,10,1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
TEXT = "MMMMMMMMMMMMMMMM"

def centre(name, tags, at):
    (OUT / f"{name}.ass").write_text(
        HEAD + f"Dialogue: 0,0:00:00.00,0:00:01.00,P,,0,0,0,,{tags}{TEXT}\n", encoding="utf-8-sig")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-f","lavfi","-t","1",
                    "-i",f"color=c=black:s={W}x{H}:r=50","-vf",f"ass={name}.ass",
                    "-ss",f"{at:.2f}","-frames:v","1",f"{name}.png"], cwd=OUT, check=True)
    img = np.array(Image.open(OUT / f"{name}.png").convert("L")).astype(int)
    xs = np.nonzero((img > 100).any(axis=0))[0]
    return -1 if xs.size == 0 else int(round(xs.mean()))

def rect(v):   # a 200px-wide axis-aligned window sweeping left to right
    x = int(-200 + v * (W + 400))
    return f"\clip({x},0,{x+200},{H})"
def vec(v):    # the same window as a 4-point vector drawing, no skew
    x = int(-200 + v * (W + 400))
    return f"\clip(m {x} 0 l {x+200} 0 {x+200} {H} {x} {H})"

times = (0.10, 0.50, 0.90)
print(f"ink centre at t={times}\n")
a = [centre(f"a{i}", r"{\clip(-200,0,0,200)\t(0,1000," + rect(1.0) + ")}", t) for i, t in enumerate(times)]
b = [centre(f"b{i}", r"{" + vec(0.0) + r"\t(0,1000," + vec(1.0) + ")}", t) for i, t in enumerate(times)]
print(f"  A CONTROL animated RECT   \clip  {a}  span={max(a)-min(a):+5d}")
print(f"  B         animated VECTOR \clip  {b}  span={max(b)-min(b):+5d}")
if max(a) - min(a) < 100:
    print("\n!! CONTROL DID NOT MOVE -- the measurement cannot see a sweep. Verdict void.")
    sys.exit(1)
# C: the control for B. Two STATIC vector clips at the endpoints B animates
# between. If these two do not differ, B could not have shown motion either
# way and 'B is frozen' would be a verdict over a situation that cannot occur.
c0 = centre("c0", "{" + vec(0.35) + "}", 0.5)
c1 = centre("c1", "{" + vec(0.65) + "}", 0.5)
print(f"  C static VECTOR clip at v=0.35 / v=0.65 -> {c0} / {c1}  (delta={c1-c0:+d})")
if c0 < 0 or c1 < 0 or abs(c1 - c0) < 50:
    print("\n!! static vector clip does not draw, or its two endpoints are "
          "indistinguishable -- no verdict on B is usable.")
    sys.exit(1)
print(f"\ncontrol swept {max(a)-min(a)}px and the static vector form draws and "
      f"differs by {c1-c0}px, so the B row is real.")
print("VERDICT:", "vector clip ANIMATES" if max(b)-min(b) > 100 else
      "vector clip is FROZEN through \t (rectangular form animates, vector does not)")
