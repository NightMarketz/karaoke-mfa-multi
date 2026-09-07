r"""Line wrapping and per-syllable placement for the \pos path.

Pure geometry: callers pass widths, this returns coordinates. No font handle
and no ASS tag crosses this boundary, which is what makes it testable without
a renderer.

Wrapping reproduces WrapStyle 0's INTENT (balanced lines), not its algorithm:
fill greedily to learn how many lines the text needs, then even them out to
that count. Matching libass exactly is neither possible nor needed — once we
emit \pos, libass does no wrapping at all and ours is the only one that runs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Placed:
    text: str
    x: float      # LEFT edge of the syllable
    y: float      # baseline row the syllable sits on
    width: float


def _greedy(widths: list[float], gaps: list[float], max_width: float) -> list[list[int]]:
    lines: list[list[int]] = [[]]
    used = 0.0
    for i, w in enumerate(widths):
        extra = w if not lines[-1] else gaps[i - 1] + w
        if lines[-1] and used + extra > max_width:
            lines.append([i])
            used = w
        else:
            lines[-1].append(i)
            used += extra
    return [line for line in lines if line]


def _unbreakable(gaps: list[float]) -> list[list[int]]:
    r"""Index groups that must share a row: split only where a gap actually is.

    gaps[i] == 0 means token i is glued to i + 1, which is how a word's
    syllables are handed to us. Wrapping over raw syllables puts a row break
    wherever the margin happens to fall, and the lyrics come apart mid-word --
    "dorme" drawn as "dor" closing one row and "me" opening the next.
    """
    groups: list[list[int]] = []
    current: list[int] = []
    for index, gap in enumerate(gaps):
        current.append(index)
        if gap > 0:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _wrap(widths: list[float], gaps: list[float], max_width: float) -> list[list[int]]:
    """Balanced line breaking. gaps[i] is the gap that FOLLOWS token i."""
    if not widths:
        return []
    groups = _unbreakable(gaps)
    # Wrap over whole words; each word's own width is the sum of its syllables,
    # and the gap after a word is the one following its last syllable.
    group_widths = [sum(widths[i] for i in g) for g in groups]
    group_gaps = [gaps[g[-1]] for g in groups]

    def rows(budget: float) -> list[list[int]]:
        return [
            [i for g in row for i in groups[g]]
            for row in _greedy(group_widths, group_gaps, budget)
        ]

    lines = rows(max_width)
    if len(lines) <= 1:
        return lines

    # Balance by squeezing the budget: the narrowest budget that still fits in
    # the row count greedy found is the one whose longest row is shortest, which
    # is what "balanced" means. Found by bisection over whole pixels.
    #
    # The obvious cheaper move -- try total / row_count once and keep it if the
    # row count happens to match -- is what this replaced. That budget usually
    # does NOT hold the count, so it fell back to the greedy fill and rendered a
    # full row followed by one stranded word.
    lo, hi = int(max(group_widths)), int(max_width)
    target = hi
    while lo <= hi:
        mid = (lo + hi) // 2
        if len(rows(mid)) <= len(lines):
            target, hi = mid, mid - 1
        else:
            lo = mid + 1
    return rows(target)


def wrap(
    tokens: list[str],
    widths: list[float],
    space_width: float,
    max_width: float,
) -> list[list[int]]:
    """Token indices per visual line, balanced, with one uniform gap between."""
    if not tokens:
        return []
    return _wrap(widths, [space_width] * len(tokens), max_width)


def place(
    syllables: list[str],
    *,
    widths: list[float],
    space_after: list[float],
    max_width: float,
    centre_x: float,
    bottom_y: float,
    line_height: float,
) -> list[Placed]:
    r"""Coordinates for every syllable, centred per line, stacked upward.

    space_after[i] is the gap that follows syllable i — non-zero only at word
    boundaries, which is how a word's syllables stay glued together. Those real
    gaps go straight into the wrapper: collapsing them to one scalar would
    charge a space between every syllable and break lines far too early.
    """
    if not syllables:
        return []
    lines = _wrap(widths, space_after, max_width)
    placed: list[Placed] = []
    for row, line in enumerate(lines):
        run = sum(widths[i] for i in line)
        run += sum(space_after[i] for i in line[:-1])
        x = centre_x - run / 2
        y = bottom_y - (len(lines) - 1 - row) * line_height
        for i in line:
            placed.append(Placed(syllables[i], x, y, widths[i]))
            x += widths[i] + space_after[i]
    return placed
