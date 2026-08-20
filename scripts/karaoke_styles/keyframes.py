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
from typing import Any

# Colour, authored as "#RRGGBB" and converted at emission. NOT interpolated
# here: \t interpolates colour itself, so only the endpoints are ever emitted.
COLOR_PROPS = frozenset({"fill_color", "outline_color", "shadow_color", "unsung_color"})
# Per-register transparency. Neutral 1.0 = fully visible, like `alpha`.
ALPHA_PROPS = frozenset({"fill_alpha", "outline_alpha", "shadow_alpha"})
# Properties libass can animate on a syllable without owning its position.
IN_PLACE_PROPS = (
    frozenset({"scale_y", "alpha", "blur", "outline"}) | COLOR_PROPS | ALPHA_PROPS
)
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


# Draw order, and the only axis the compiler needs in order to REFUSE. glow and
# ghost are constructors (see effects.py), not roles: role is engine, the rest
# is authoring convenience and convenience should not become an engine concept.
ROLE_Z = {"under": -1, "main": 0, "over": 1}

# Measured, 60s of 1920x1080 @30 from a real 538-event file: 1 layer 4.5s,
# 2 layers 7.4s, 4 layers 13.4s, 8 layers 25.7s, 16 layers 49.4s. No knee --
# cost is linear -- so the ceiling is a budget decision, not a cliff. 4 keeps a
# 3-minute song at roughly 40s of burn; 16 is where "seconds, not minutes"
# breaks.
MAX_LAYERS = 4

# \kf sweeps SecondaryColour -> PrimaryColour, so a track writing the FILL
# register writes the register the sweep reads from. Measured on a burned
# frame by locating the sweep front: animating \1c, setting \1c statically and
# animating \1a all kill the fill; \3c and \2c leave it alone. Refused by NAME
# on a main layer -- never silently dropped.
#
# ponytail: the generic `alpha` prop also touches \1a, and `reveal` ships on
# it. It stays allowed because it is golden-pinned shipped behaviour; refusing
# it would be a behaviour change wearing a fence's clothes.
MAIN_REFUSED = frozenset({"fill_color", "fill_alpha"})


@dataclass(frozen=True)
class Layer:
    r"""One drawn copy of the line: one more Dialogue on the path that exists.

    `offset` is a STATIC displacement in pixels, (dx, dy), positive dy = down.
    Static on purpose: off the layout path it becomes the event's own
    MarginL/MarginR/MarginV (measured -- centre_x = W/2 + (L - R)/2, and
    MarginV is the distance from the bottom), which is what keeps a ghost cheap
    on a preset that never measures its line. An ANIMATED offset is still
    offset_x/offset_y, still a LAYOUT_PROP, and still needs \pos.
    """

    role: str
    tracks: tuple[Track, ...] = ()
    offset: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        if self.role not in ROLE_Z:
            raise ValueError(
                f"unknown layer role: {self.role!r} "
                f"(known: {', '.join(sorted(ROLE_Z))})"
            )
        if self.role != "main":
            return
        refused = sorted({track.prop for track in self.tracks} & MAIN_REFUSED)
        if refused:
            raise ValueError(
                f"a main layer may not animate {', '.join(refused)}: \\kf sweeps "
                "SecondaryColour -> PrimaryColour, so writing the fill register "
                "kills the karaoke sweep. Put it on an under or over layer, "
                "which carry \\k and have no sweep to kill."
            )
        if self.offset != (0.0, 0.0):
            raise ValueError(
                "a main layer may not be offset: it is where the line is"
            )


@dataclass(frozen=True)
class Effect:
    id: str
    layers: tuple[Layer, ...]

    def __post_init__(self) -> None:
        mains = sum(1 for layer in self.layers if layer.role == "main")
        if mains != 1:
            raise ValueError(
                f"effect {self.id!r} has {mains} main layers, needs exactly 1: "
                "the main layer is the one that carries \\kf"
            )
        if len(self.layers) > MAX_LAYERS:
            raise ValueError(
                f"effect {self.id!r} has {len(self.layers)} layers; the ceiling "
                f"is {MAX_LAYERS}. Layer cost is linear in burn time and 4 keeps "
                "a 3-minute song at roughly 40s."
            )

    @property
    def main(self) -> Layer:
        return next(layer for layer in self.layers if layer.role == "main")

    @property
    def tracks(self) -> tuple[Track, ...]:
        """Every track on every layer. What capability reporting asks about."""
        return tuple(track for layer in self.layers for track in layer.tracks)

    @property
    def layer_numbers(self) -> tuple[int, ...]:
        r"""The ASS Layer field per layer, in self.layers order.

        Roles carry offsets under=-1, main=0, over=+1 and the whole set is
        translated so its minimum is 0. A main-only effect therefore yields
        (0,) -- byte for byte what ships today, so the golden needs no
        hand-written exception.
        """
        zs = [ROLE_Z[layer.role] for layer in self.layers]
        base = min(zs)
        return tuple(z - base for z in zs)

    @property
    def needs_layout(self) -> bool:
        return any(track.prop in LAYOUT_PROPS for track in self.tracks)

    def props(self) -> set[str]:
        return {track.prop for track in self.tracks}


def resolve(track: Track, *, attack_ms: int, duration_ms: int) -> list[tuple[int, Any]]:
    r"""Keys as (absolute_ms_from_line_start, value), sorted and de-duplicated.

    Clamped at 0: a lead-in longer than the line's own head would ask libass to
    animate before the Dialogue exists.

    The VALUE is preserved, not coerced -- a colour key is a "#RRGGBB" string
    and float() would throw on it. Only the time is arithmetic.
    """
    scale = duration_ms if track.time == "frac" else 1
    resolved: dict[int, Any] = {}
    for at, value in track.keys:
        ms = max(0, int(round(attack_ms + at * scale)))
        resolved[ms] = value if isinstance(value, str) else float(value)
    # Sorted by TIME only. The default tuple sort falls through to the value on
    # a tie, and comparing a str to a float raises -- unreachable today because
    # dict keys are unique, but one line is cheaper than the landmine.
    return sorted(resolved.items(), key=lambda item: item[0])
