r"""Engine-neutral keyframe model for karaoke syllable effects.

An effect is DATA, not a tag string: a set of tracks, each animating one
neutral property over keyframes. Nothing here knows about ASS. The ASS
compiler lives in ass_compile.py; a GPU compiler can read the same tracks.

Time reference: every key is stated relative to the SYLLABLE's attack, which
is the natural way to author. resolve() converts to absolute line-relative
milliseconds, because that is the only clock \t and \move actually run on.
"""

from __future__ import annotations

from dataclasses import dataclass

# Properties libass can animate on a syllable without owning its position.
IN_PLACE_PROPS = frozenset({"scale_y", "alpha", "blur", "outline"})
# Properties that need us to place the syllable ourselves (one Dialogue each
# with \pos), because they change the glyph's advance or its origin.
LAYOUT_PROPS = frozenset({"scale", "scale_x", "rotate", "offset_x", "offset_y"})
# Named on purpose so the ASS compiler can refuse them by name rather than
# ignore them. Delivered by the GPU compiler, which is not part of this plan.
FUTURE_PROPS = frozenset({"glow", "gradient", "motion_blur", "audio"})
ALL_PROPS = IN_PLACE_PROPS | LAYOUT_PROPS | FUTURE_PROPS

TIME_MODES = ("ms", "frac")


@dataclass(frozen=True)
class Track:
    prop: str
    keys: tuple[tuple[float, float], ...]
    time: str = "ms"
    accel: float = 1.0

    def __post_init__(self) -> None:
        if self.prop not in ALL_PROPS:
            raise ValueError(
                f"unknown effect property: {self.prop!r} "
                f"(known: {', '.join(sorted(ALL_PROPS))})"
            )
        if not self.keys:
            raise ValueError(f"track {self.prop!r} has no keys")
        if self.time not in TIME_MODES:
            raise ValueError(
                f"track {self.prop!r} has time={self.time!r}, expected one of {TIME_MODES}"
            )


@dataclass(frozen=True)
class Effect:
    id: str
    tracks: tuple[Track, ...]

    @property
    def needs_layout(self) -> bool:
        return any(track.prop in LAYOUT_PROPS for track in self.tracks)

    def props(self) -> set[str]:
        return {track.prop for track in self.tracks}


def resolve(track: Track, *, attack_ms: int, duration_ms: int) -> list[tuple[int, float]]:
    r"""Keys as (absolute_ms_from_line_start, value), sorted and de-duplicated.

    Clamped at 0: a lead-in longer than the line's own head would ask libass to
    animate before the Dialogue exists.
    """
    scale = duration_ms if track.time == "frac" else 1
    resolved: dict[int, float] = {}
    for at, value in track.keys:
        ms = max(0, int(round(attack_ms + at * scale)))
        resolved[ms] = float(value)
    return sorted(resolved.items())
