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

status = 0
for preset in ("fly-in", "swing", "punch"):
    path = ROOT / preset / "output.ass"
    texts, chars = visible(path)
    ok = chars == base_chars
    status |= 0 if ok else 1
    print(f"{preset:>10} : {len(texts)} Dialogue events, {len(chars)} non-space chars"
          f"  -> {'IDENTICAL to baseline' if ok else 'DIFFERS'}")
    if not ok:
        for i, (a, b) in enumerate(zip(base_chars, chars)):
            if a != b:
                print(f"             first divergence at char {i}: "
                      f"baseline {base_chars[i:i+40]!r} vs {chars[i:i+40]!r}")
                break
        else:
            print(f"             length differs: {len(base_chars)} vs {len(chars)}")

# The events-per-syllable claim, checked rather than asserted.
for preset in ("fly-in", "swing", "punch"):
    events = dialogues(ROOT / preset / "output.ass")
    positioned = sum(1 for e in events if "\\pos(" in e or "\\move(" in e)
    print(f"{preset:>10} : {positioned} of {len(events)} events carry \\pos or \\move")
    if positioned != len(events):
        status = 1

sys.exit(status)
