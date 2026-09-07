r"""Font file lookup and text measurement for the layout path.

libass substitutes a missing family silently. We refuse to: once we place
syllables ourselves, a substituted face makes every measurement a lie, so an
unresolvable family raises instead.

Measurement is Pillow/FreeType, and it has to agree with libass in the
ABSOLUTE, not merely be self-consistent -- a syllable placed by us sits next to
glyphs libass laid out itself. Two things make that work, both of them found by
measuring real renders in the Task 0 gate rather than by reading docs:

  1. An ASS Fontsize is not an em size. libass sizes a face so that
     ascender + descender equals the Fontsize; ImageFont.truetype(path, S)
     treats S as the em size. For Segoe UI that is a flat 0.752x.

  2. Read that ratio, and every advance, at a high reference ppem. getmetrics()
     rounds ascent and descent to whole pixels and FreeType hinting quantises
     each glyph advance at the target ppem; both errors are systematic and
     accumulate along a word, worth 5px by the last syllable at 84ppem.

With both applied the measured intra-word error against libass was <=1px over
30 of 30 syllable placements across two faces and three words.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

# High enough that hinting quantisation is worth ~0.05% of an advance.
REF_PPEM = 1024

# Subfamily words that may be glued onto a family name the ASS way.
_WEIGHT_WORDS = frozenset({"thin", "light", "regular", "medium", "semibold",
                           "demibold", "bold", "semilight", "black", "heavy"})
_SLANT_WORDS = frozenset({"italic", "oblique"})
_STYLE_WORDS = _WEIGHT_WORDS | _SLANT_WORDS
# What counts as "bold enough" when the name carries the weight itself.
_BOLD_WORDS = frozenset({"bold", "black", "heavy"})


class FontNotFound(RuntimeError):
    pass


def _font_dirs() -> list[Path]:
    dirs = []
    windir = os.environ.get("WINDIR")
    if windir:
        dirs.append(Path(windir) / "Fonts")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    dirs += [Path("/usr/share/fonts"), Path.home() / ".fonts"]
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=1)
def _font_index() -> dict[str, tuple[tuple[Path, frozenset[str]], ...]]:
    """lowercase family name -> the faces in it, with their subfamily words.

    Built once. Opening every file in the system font directory is the
    expensive part, and the resolver needs two passes over it (exact name, then
    name-minus-style-words), so it must not be a scan per lookup.
    """
    index: dict[str, list[tuple[Path, frozenset[str]]]] = {}
    for directory in _font_dirs():
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() not in (".ttf", ".otf"):
                continue
            try:
                family, subfamily = ImageFont.truetype(str(path), 12).getname()
            except (OSError, ValueError):
                continue
            key = (family or "").strip().lower()
            if not key:
                continue
            words = frozenset((subfamily or "regular").strip().lower().split())
            index.setdefault(key, []).append((path, words))
    return {k: tuple(v) for k, v in index.items()}


def _pick(family: str, want: frozenset[str]) -> Path | None:
    """Best face inside one family for a set of wanted subfamily words.

    Weight is matched by WORD, not by a bold flag. On Windows `seguibl.ttf`
    reports family "Segoe UI" with subfamily "Black" -- there is no "Segoe UI
    Black" family at all -- so folding Black into a boolean bold hands back
    `segoeuib.ttf`, a real face that is simply the wrong weight and measurably
    narrower. Every advance downstream would then be wrong by ~7%.

    Slant is compared first so it is never traded away for weight: asking for
    upright Black must not return Black Italic just because the weight agrees.
    """
    faces = _font_index().get(family.strip().lower())
    if not faces:
        return None
    want_slant = bool(want & _SLANT_WORDS)
    best, best_score = None, None
    for path, words in faces:
        score = (
            bool(words & _SLANT_WORDS) == want_slant,
            words == want,
            len(words & want),
            -len(words ^ want),
        )
        if best_score is None or score > best_score:
            best, best_score = path, score
    return best


def _wanted_words(trailing: list[str], *, bold: bool, italic: bool) -> frozenset[str]:
    r"""Subfamily words to look for, given a name's own words plus the flags.

    The NAME wins over the flags. A preset that says "Segoe UI Black" also
    carries bold=True in its Style row -- ASS's way of asking for weight -- and
    OR-ing "bold" into the request would stop {"black"} matching exactly. The
    flags only fill in what the name left unsaid.
    """
    want = set(trailing)
    if italic and not (want & _SLANT_WORDS):
        want.add("italic")
    if bold and not (want & _WEIGHT_WORDS):
        want.add("bold")
    return frozenset(want or {"regular"})


@lru_cache(maxsize=256)
def resolve_font_path(fontname: str, *, bold: bool, italic: bool) -> Path:
    r"""Best TTF/OTF for a style's (fontname, bold, italic).

    Two passes, in this order:

      1. Exact family, with the style taken from the flags. Some systems do
         expose "Segoe UI Black" as a family of its own; that must win before
         any name-splitting happens.
      2. Family with trailing style words peeled off and folded into the
         request. Every shipped preset says fontname="Segoe UI Bold", which is
         a family plus a subfamily and resolves to nothing in pass 1.
    """
    hit = _pick(fontname, _wanted_words([], bold=bold, italic=italic))
    if hit is not None:
        return hit

    words = fontname.split()
    trailing: list[str] = []
    while len(words) > 1 and words[-1].lower() in _STYLE_WORDS:
        trailing.insert(0, words.pop().lower())
    if trailing:
        hit = _pick(" ".join(words), _wanted_words(trailing, bold=bold, italic=italic))
        if hit is not None:
            return hit

    raise FontNotFound(
        f"no font file for family {fontname!r} "
        f"(bold={bold}, italic={italic}) under {[str(d) for d in _font_dirs()]}"
    )


@lru_cache(maxsize=64)
def _ref_face(font_path: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path, REF_PPEM)


@lru_cache(maxsize=64)
def px_per_ass_unit(font_path: str) -> float:
    r"""How many pixels one unit of ASS Fontsize is worth in this face.

    upem / (hhea_ascender - hhea_descender), read through Pillow rather than by
    parsing the font tables: getmetrics() at REF_PPEM returns the ascent and
    descent already scaled, so REF_PPEM / (asc + desc) is the same ratio.
    """
    ascent, descent = _ref_face(font_path).getmetrics()
    return REF_PPEM / (ascent + descent)


def measure(text: str, *, font_path: Path, size_px: int, spacing: float = 0.0) -> float:
    r"""Advance width in pixels for text drawn at ASS Fontsize `size_px`.

    `size_px` is an ASS Fontsize -- the number the Style row carries after
    scaling to the render height -- NOT a FreeType em size. See the module
    docstring; handing this a raw em size makes every advance ~33% too wide.

    `spacing` mirrors the ASS Style Spacing column: libass adds it after every
    character, including the last, which is why it is len(text) and not
    len(text) - 1.
    """
    if not text:
        return 0.0
    key = str(font_path)
    px = size_px * px_per_ass_unit(key)
    width = _ref_face(key).getlength(text) * px / REF_PPEM
    return width + spacing * len(text)
