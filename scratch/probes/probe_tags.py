r"""Which ASS override tags does THIS libass actually draw?

Docs describe a format; a binary renders one. Every tag below is burned
through the same ffmpeg/libass path the pipeline uses and compared against an
untagged baseline frame. A tag that changes no pixel is one libass ignored --
and an effect language that emits it would be lying to whoever authored it.

Each probe uses a value chosen to be unmissable if honoured (45 degrees, not
2), so "no change" means "not supported", not "too subtle to see".
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path("scratch/tagprobe")
W, H = 960, 540
AT = "0.50"          # sampled mid-event, so \t and \move are underway

HEADER = (
    "[Script Info]\nScriptType: v4.00+\n"
    f"PlayResX: {W}\nPlayResY: {H}\nScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
    "MarginR, MarginV, Encoding\n"
    # BackColour is YELLOW on purpose: it is the shadow's colour, and with the
    # usual black-on-black every \shad/\4a probe reads as "libass ignored it".
    "Style: P,Segoe UI Bold,64,&H00FFFFFF,&H000080FF,&H00202020,&H0000FFFF,"
    "-1,0,0,0,100,100,0,0,1,3,2,5,20,20,20,1\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text\n"
)

# (group, label, text-with-tags). "" == the untagged baseline.
# (group, label, text[, baseline_text]) -- a 4th item overrides the baseline
# for probes where the untagged frame is not the right comparison.
PROBES: list[tuple] = [
    ("baseline", "no tags", "Arrasta"),

    ("transform 3D", r"\frx", r"{\frx60}Arrasta"),
    ("transform 3D", r"\fry", r"{\fry60}Arrasta"),
    ("transform 3D", r"\frz", r"{\frz30}Arrasta"),
    ("transform 3D", r"\fax shear", r"{\fax0.6}Arrasta"),
    ("transform 3D", r"\fay shear", r"{\fay0.4}Arrasta"),
    ("transform 3D", r"\org + \frz", r"{\org(0,0)\frz30}Arrasta"),

    ("geometry", r"\fscx", r"{\fscx220}Arrasta"),
    ("geometry", r"\fscy", r"{\fscy220}Arrasta"),
    ("geometry", r"\fsp letter spacing", r"{\fsp18}Arrasta"),
    ("geometry", r"\fs size override", r"{\fs110}Arrasta"),
    ("geometry", r"\fn font override", r"{\fnCourier New}Arrasta"),
    ("geometry", r"\b \i \u \s", r"{\i1\u1\s1}Arrasta"),
    ("geometry", r"\r style reset", r"{\fscx220}Arr{\r}asta"),

    ("colour", r"\1c primary", r"{\1c&H0000FF&}Arrasta"),
    ("colour", r"\3c outline", r"{\3c&H00FF00&}Arrasta"),
    ("colour", r"\4c shadow", r"{\4c&H00FFFF&\shad6}Arrasta"),
    ("colour", r"\2c secondary", r"{\2c&H00FF00&\kf200}Arrasta"),
    ("colour", r"\1a primary alpha", r"{\1a&H90&}Arrasta"),
    ("colour", r"\3a outline alpha", r"{\3a&H90&}Arrasta"),
    ("colour", r"\4a shadow alpha", r"{\4a&HE0&}Arrasta"),
    ("colour", r"\alpha all", r"{\alpha&H90&}Arrasta"),

    ("edge", r"\bord", r"{\bord9}Arrasta"),
    ("edge", r"\xbord only", r"{\xbord9}Arrasta"),
    ("edge", r"\ybord only", r"{\ybord9}Arrasta"),
    ("edge", r"\shad", r"{\shad12}Arrasta"),
    ("edge", r"\xshad only", r"{\xshad12}Arrasta"),
    ("edge", r"\yshad only", r"{\yshad12}Arrasta"),
    ("edge", r"\blur gaussian", r"{\blur6}Arrasta"),
    ("edge", r"\be box blur", r"{\be6}Arrasta"),

    ("mask", r"\clip rect", r"{\clip(0,0,300,540)}Arrasta"),
    ("mask", r"\iclip rect", r"{\iclip(300,0,700,540)}Arrasta"),
    ("mask", r"\clip vector", r"{\clip(m 0 0 l 300 0 300 540 0 540)}Arrasta"),
    ("mask", r"\clip animated by \t", r"{\clip(0,0,1,540)\t(0,900,\clip(0,0,960,540))}Arrasta"),

    ("drawing", r"\p1 vector drawing", r"{\p1}m 0 0 l 200 0 200 90 0 90{\p0}"),
    ("drawing", r"\pbo baseline offset", r"{\p1\pbo40}m 0 0 l 200 0 200 90 0 90{\p0}"),

    ("timing", r"\t animate", r"{\t(0,900,\fscx220)}Arrasta"),
    ("timing", r"\t with accel", r"{\t(0,900,3.0,\fscx220)}Arrasta"),
    ("timing", r"\move", r"{\move(100,270,800,270)}Arrasta"),
    ("timing", r"\move timed", r"{\move(100,270,800,270,0,900)}Arrasta"),
    ("timing", r"\fad", r"{\fad(900,0)}Arrasta"),
    # t1..t2 must STRADDLE the sample instant or the tag is fully opaque there
    # and reads as ignored -- which is what the first run of this probe said.
    ("timing", r"\fade 7-arg", r"{\fade(255,0,255,0,900,950,1000)}Arrasta"),

    ("karaoke", r"\k", r"{\k50}Arr{\k50}asta"),
    ("karaoke", r"\kf sweep", r"{\kf50}Arr{\kf50}asta"),
    ("karaoke", r"\ko outline", r"{\ko50}Arr{\ko50}asta"),
    ("karaoke", r"\kt absolute", r"{\kt100\kf50}Arr{\kt0\kf50}asta"),

    ("layout", r"\an alignment", r"{\an1}Arrasta"),
    ("layout", r"\pos", r"{\pos(200,150)}Arrasta"),
    ("layout", r"\q0 vs \q2 (long line)",
     r"{\q0}Arrasta pra cima cai na cilada dinheiro facil mente comprada",
     r"{\q2}Arrasta pra cima cai na cilada dinheiro facil mente comprada"),
]


def render(name: str, text: str) -> np.ndarray:
    (OUT / f"{name}.ass").write_text(
        HEADER + f"Dialogue: 0,0:00:00.00,0:00:01.00,P,,0,0,0,,{text}\n",
        encoding="utf-8-sig",
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", "1",
         "-i", f"color=c=black:s={W}x{H}:r=30", "-vf", f"ass={name}.ass",
         "-ss", AT, "-frames:v", "1", f"{name}.png"],
        cwd=OUT, check=True,
    )
    return np.array(Image.open(OUT / f"{name}.png").convert("RGB")).astype(int)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    base = render("p000", PROBES[0][2])

    supported, ignored = [], []
    group = None
    for i, probe in enumerate(PROBES[1:], start=1):
        grp, label, text = probe[0], probe[1], probe[2]
        frame = render(f"p{i:03d}", text)
        ref = render(f"b{i:03d}", probe[3]) if len(probe) > 3 else base
        diff = int(np.abs(frame - ref).sum())
        changed = diff > 20000        # well above codec noise on a still frame
        (supported if changed else ignored).append((grp, label, diff))
        if grp != group:
            print(f"\n-- {grp}")
            group = grp
        print(f"   {'OK ' if changed else 'IGNORED'}  {label:<26} diff={diff}")

    total = len(PROBES) - 1
    print(f"\n=== {len(supported)} of {total} probed tags changed the render")
    if ignored:
        print("=== ignored by this libass:")
        for grp, label, diff in ignored:
            print(f"      {grp}/{label} (diff={diff})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
