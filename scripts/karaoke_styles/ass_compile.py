r"""Keyframe tracks -> libass override tags.

The one rule that governs this file: \t times are milliseconds from the START
OF THE DIALOGUE LINE, not from the syllable. Callers pass attack_ms already
measured from the line start, and keyframes.resolve() keeps it that way.

Only IN_PLACE_PROPS are compiled here. LAYOUT_PROPS need the syllable's own
\pos and are handled by the layout path; FUTURE_PROPS are refused by name
through unsupported_props(), never silently ignored.
"""

from __future__ import annotations

from .keyframes import IN_PLACE_PROPS, Effect, Layer, resolve


def _fmt(value: float) -> str:
    """Trim a float to the shortest form libass parses the same way."""
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def _ass_colour(value: str) -> str:
    r"""#RRGGBB -> &HBBGGRR&.

    Authored in the web hex every designer already has, stored in ASS's
    reversed byte order. Refused rather than truncated when it is not six hex
    digits: a silently wrong colour is invisible until someone watches the
    video, which is exactly the class of bug this vocabulary exists to remove.
    """
    text = str(value).lstrip("#")
    if len(text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in text):
        raise ValueError(f"colour must be #RRGGBB, got {value!r}")
    return f"&H{text[4:6]}{text[2:4]}{text[0:2]}&".upper()


def _alpha_of(tag: str):
    """Builder for one alpha register. Neutral 1.0 = fully visible."""
    def build(value: float) -> str:
        # ASS alpha is transparency, so invert.
        visible = min(1.0, max(0.0, float(value)))
        return f"\\{tag}&H{255 - round(visible * 255):02X}&"
    return build


PROP_TAG = {
    "scale_y": lambda v: f"\\fscy{_fmt(v * 100)}",
    "alpha": _alpha_of("alpha"),
    "blur": lambda v: f"\\blur{_fmt(v)}",
    "outline": lambda v: f"\\bord{_fmt(v)}",
    "fill_color": lambda v: f"\\1c{_ass_colour(v)}",
    "unsung_color": lambda v: f"\\2c{_ass_colour(v)}",
    "outline_color": lambda v: f"\\3c{_ass_colour(v)}",
    "shadow_color": lambda v: f"\\4c{_ass_colour(v)}",
    "fill_alpha": _alpha_of("1a"),
    "outline_alpha": _alpha_of("3a"),
    "shadow_alpha": _alpha_of("4a"),
}

ASS_SUPPORTED = frozenset(PROP_TAG)
assert ASS_SUPPORTED == IN_PLACE_PROPS, "PROP_TAG and IN_PLACE_PROPS drifted apart"

# Only reachable when the caller owns the syllable's origin and passes an
# anchor -- i.e. on the one-Dialogue-per-syllable path.
LAYOUT_TAG = {
    "scale": lambda v: f"\\fscx{_fmt(v * 100)}\\fscy{_fmt(v * 100)}",
    "scale_x": lambda v: f"\\fscx{_fmt(v * 100)}",
    "rotate": lambda v: f"\\frz{_fmt(v)}",
}
# offset_x/offset_y are not in LAYOUT_TAG: \pos is not animatable, so they
# compile to a single \move instead of a \t chain.
MOVE_PROPS = ("offset_x", "offset_y")


def unsupported_props(effect: Effect, *, anchored: bool = False) -> set[str]:
    """Properties this effect asks for that the ASS compiler cannot deliver.

    `anchored` is whether the caller will hand compile_syllable an anchor. Off
    the positioned path, scale/rotate/offset are just as undeliverable as glow.
    """
    usable = set(ASS_SUPPORTED)
    if anchored:
        usable |= set(LAYOUT_TAG) | set(MOVE_PROPS)
    return {t.prop for t in effect.tracks} - usable


def _move_tag(
    layer: Layer,
    anchor: tuple[float, float],
    *,
    attack_ms: int,
    duration_ms: int,
) -> str:
    r"""The single \move for this effect's offset tracks, or "".

    ponytail: one linear segment, first key to last. \move is all libass gives
    for animating a position, so an offset track with three keys loses its
    middle one. Two axes with different key times are covered by taking the
    union of their spans. If a preset ever needs a real position curve, that is
    the GPU compiler's job, not another tag here.
    """
    tracks = {
        prop: next((t for t in layer.tracks if t.prop == prop), None)
        for prop in MOVE_PROPS
    }
    if not any(tracks.values()):
        return ""

    resolved = {
        prop: resolve(track, attack_ms=attack_ms, duration_ms=duration_ms)
        for prop, track in tracks.items()
        if track is not None
    }
    t0 = min(keys[0][0] for keys in resolved.values())
    t1 = max(keys[-1][0] for keys in resolved.values())

    def at(prop: str, index: int) -> float:
        keys = resolved.get(prop)
        return keys[index][1] if keys else 0.0

    x0 = anchor[0] + at("offset_x", 0)
    y0 = anchor[1] + at("offset_y", 0)
    x1 = anchor[0] + at("offset_x", -1)
    y1 = anchor[1] + at("offset_y", -1)
    return f"\\move({_fmt(x0)},{_fmt(y0)},{_fmt(x1)},{_fmt(y1)},{t0},{t1})"


def compile_layer(
    layer: Layer,
    *,
    text: str,
    duration_cs: int,
    attack_ms: int,
    anchor: tuple[float, float] | None = None,
    frame: tuple[int, int] | None = None,
    karaoke: str = "kf",
) -> str:
    r"""Render one layer of one syllable as "{tags}text".

    `karaoke` is "kf" for the main layer and "k" for every other one: karaoke
    tags draw no glyph, they only advance the clock, so a non-main layer needs
    the same clock and no sweep. That is exactly why the fill-colour
    prohibition does not reach them -- the two rules compose instead of
    fighting.

    duration_cs is the syllable's karaoke time and is emitted verbatim: the sum
    of these across a line is the line's clock and must not change, on ANY
    layer.

    `anchor` is the (x, y) the caller placed this syllable at. Passing it
    unlocks LAYOUT_PROPS; without it those tracks are silently absent from the
    output and loudly present in unsupported_props(). When the returned token
    contains a \move, the caller must NOT also emit its own \pos -- libass
    keeps whichever positioning tag it parses first and drops the other.
    `frame` is the (width, height) a mask sweeps across.
    """
    duration_cs = max(1, int(duration_cs))
    duration_ms = duration_cs * 10
    statics: list[str] = []
    transforms: list[str] = []

    usable = dict(PROP_TAG)
    if anchor is not None:
        usable.update(LAYOUT_TAG)

    for track in layer.tracks:
        if track.prop in MOVE_PROPS or track.prop not in usable:
            continue
        tag = usable[track.prop]
        keys = resolve(track, attack_ms=attack_ms, duration_ms=duration_ms)
        # The first key is the RESTING pose, not just the start of the ramp:
        # libass shows this static tag from the Dialogue's first frame until
        # keys[0][0], which for a syllable late in the line is most of the time
        # it is on screen. An effect that opens on its animated extreme leaves
        # the whole not-yet-sung tail of the line sitting in that extreme.
        if track.prop == "rotate" and anchor is not None:
            # \frz without \org spins around the frame centre, which throws a
            # syllable near the edge clean off screen. Once per token.
            org = f"\\org({_fmt(anchor[0])},{_fmt(anchor[1])})"
            if org not in statics:
                statics.append(org)
        statics.append(tag(keys[0][1]))
        for (t0, _), (t1, v1) in zip(keys, keys[1:]):
            if t1 <= t0:
                continue
            accel = "" if track.accel == 1.0 else f"{_fmt(track.accel)},"
            transforms.append(f"\\t({t0},{t1},{accel}{tag(v1)})")

    if anchor is not None:
        move = _move_tag(layer, anchor, attack_ms=attack_ms, duration_ms=duration_ms)
        if move:
            statics.append(move)

    return f"{{{''.join(statics)}{''.join(transforms)}\\{karaoke}{duration_cs}}}{text}"


def compile_syllable(
    effect: Effect,
    *,
    text: str,
    duration_cs: int,
    attack_ms: int,
    anchor: tuple[float, float] | None = None,
    frame: tuple[int, int] | None = None,
) -> str:
    r"""The effect's MAIN layer, which is the one that carries \kf."""
    return compile_layer(
        effect.main,
        text=text,
        duration_cs=duration_cs,
        attack_ms=attack_ms,
        anchor=anchor,
        frame=frame,
        karaoke="kf",
    )
