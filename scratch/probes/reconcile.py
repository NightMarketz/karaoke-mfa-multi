r"""Reconcile the visible lyrics of each motion preset against the pill baseline.

Strip every {...} override group from the Dialogue text and compare what is
left. A layout preset that drops a syllable, or splits a word across a row it
should not, shows up HERE and nowhere else -- the file sizes differ by design
(one Dialogue per syllable), so nothing about the raw file tells you the words
survived.

Reports counts with denominators, and re-derives the total two ways so a wrong
denominator cannot pass as a right one.
"""
import re
import sys
from pathlib import Path

ROOT = Path("scratch/preset-preview")
TAGS = re.compile(r"\{[^}]*\}")


def dialogues(path: Path) -> list[str]:
    out = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        if raw.startswith("Dialogue:"):
            out.append(raw.split(",", 9)[9])
    return out


def visible(path: Path) -> tuple[list[str], str]:
    """(one string per Dialogue, all visible text concatenated with no spaces)."""
    texts = [TAGS.sub("", d) for d in dialogues(path)]
    return texts, "".join(texts).replace(" ", "")


base_texts, base_chars = visible(ROOT / "pill" / "output.ass")
# Re-derivation: the concatenation must agree with the per-line sum.
per_line = sum(len(t.replace(" ", "")) for t in base_texts)
print(f"baseline  pill : {len(base_texts)} Dialogue lines, "
      f"{len(base_chars)} non-space chars (per-line sum: {per_line})")
assert per_line == len(base_chars), "baseline character count does not reconcile"

PRESETS = ("fly-in", "swing", "punch", "glow", "aberration", "flare", "sweep")

# How many Dialogue events each preset draws per LINE. A layer preset repeats
# the same visible text once per layer, so its concatenation is L x the
# baseline and comparing it raw would be a guaranteed DIFFERS.
LAYERS = {"fly-in": 1, "swing": 1, "punch": 1,
          "flare": 1, "glow": 2, "sweep": 2, "aberration": 3}

# The four built from layers ride the single-event-per-line path by design --
# that is what the T0 gate bought -- so they carry no \pos or \move at all.
NON_LAYOUT = ("glow", "aberration", "flare", "sweep")

assert set(PRESETS) == set(LAYERS), "every preset needs its layer count"

# MEASURED, not assumed: ass_emit writes a line's layers consecutively
# (line 1 layer 0, line 1 layer 1, line 2 layer 0, ...), NOT n whole copies of
# the file one after another. So event j belongs to layer j % n, and slicing
# off the first len/n characters does NOT reproduce the baseline. The first
# draft of this probe did exactly that and called three working presets
# DIFFERS -- the classic probe failure: a verdict over a population that could
# not have matched.

status = 0
for preset in PRESETS:
    path = ROOT / preset / "output.ass"
    texts, chars = visible(path)
    n = LAYERS[preset]
    # Re-derivation on two independent axes, not a looser assertion:
    #   (a) EVERY layer's own text, taken alone, must equal the baseline --
    #       so a syllable lost from one layer only is still caught;
    #   (b) the total must be exactly n x the baseline -- so a layer that
    #       duplicated a syllable in all copies is caught too.
    # Either check alone would pass a file the other rejects.
    per_layer = ["".join(texts[k::n]).replace(" ", "") for k in range(n)]
    assert len(per_layer) == n
    layers_ok = sum(1 for c in per_layer if c == base_chars)
    ok = layers_ok == n and len(chars) == n * len(base_chars)
    status |= 0 if ok else 1
    print(f"{preset:>11} : {len(texts)} Dialogue events, {len(chars)} non-space "
          f"chars = {n} x {len(base_chars)}; {layers_ok} of {n} layers match "
          f"the {len(base_chars)}-char baseline  -> "
          f"{'IDENTICAL to baseline' if ok else 'DIFFERS'}")
    if not ok:
        for k, c in enumerate(per_layer):
            if c == base_chars:
                continue
            for i, (a, b) in enumerate(zip(base_chars, c)):
                if a != b:
                    print(f"              layer {k}: first divergence at char "
                          f"{i}: baseline {base_chars[i:i+40]!r} vs {c[i:i+40]!r}")
                    break
            else:
                print(f"              layer {k}: length differs, "
                      f"{len(c)} chars vs baseline {len(base_chars)}")

# The events-per-syllable claim, checked rather than asserted.
for preset in PRESETS:
    events = dialogues(ROOT / preset / "output.ass")
    positioned = sum(1 for e in events if "\pos(" in e or "\move(" in e)
    if preset in NON_LAYOUT:
        # Off the layout path by design -- that is what the T0 gate bought.
        print(f"{preset:>11} : {positioned} of {len(events)} positioned "
              f"(expected 0 -- non-layout path)")
        if positioned != 0:
            status = 1
        continue
    print(f"{preset:>11} : {positioned} of {len(events)} events carry "
          f"\pos or \move")
    if positioned != len(events):
        status = 1

sys.exit(status)
