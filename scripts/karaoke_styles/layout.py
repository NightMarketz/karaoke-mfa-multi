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


def _wrap(widths: list[float], gaps: list[float], max_width: float) -> list[list[int]]:
    """Balanced line breaking. gaps[i] is the gap that FOLLOWS token i."""
    if not widths:
        return []
    lines = _greedy(widths, gaps, max_width)
    if len(lines) <= 1:
        return lines
    # Re-fill against a narrower budget so the last line is not left stranded,
    # keeping the line count the greedy pass established.
    total = sum(widths) + sum(gaps[:-1])
    target = max(max(widths), total / len(lines))
    balanced = _greedy(widths, gaps, target)
    return balanced if len(balanced) == len(lines) else lines


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
