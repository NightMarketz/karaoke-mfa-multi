r"""Keyframe tracks -> libass override tags.

The one rule that governs this file: \t times are milliseconds from the START
OF THE DIALOGUE LINE, not from the syllable. Callers pass attack_ms already
measured from the line start, and keyframes.resolve() keeps it that way.

Only IN_PLACE_PROPS are compiled here. LAYOUT_PROPS need the syllable's own
\pos and are handled by the layout path; FUTURE_PROPS are refused by name
through unsupported_props(), never silently ignored.
"""

from __future__ import annotations

from .keyframes import IN_PLACE_PROPS, Effect, resolve


def _fmt(value: float) -> str:
    """Trim a float to the shortest form libass parses the same way."""
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def _alpha_tag(value: float) -> str:
    # Neutral 1.0 = fully visible; ASS alpha is transparency, so invert.
    visible = min(1.0, max(0.0, value))
    return f"\\alpha&H{255 - round(visible * 255):02X}&"


PROP_TAG = {
    "scale_y": lambda v: f"\\fscy{_fmt(v * 100)}",
    "alpha": _alpha_tag,
    "blur": lambda v: f"\\blur{_fmt(v)}",
    "outline": lambda v: f"\\bord{_fmt(v)}",
}

ASS_SUPPORTED = frozenset(PROP_TAG)
assert ASS_SUPPORTED == IN_PLACE_PROPS, "PROP_TAG and IN_PLACE_PROPS drifted apart"


def unsupported_props(effect: Effect) -> set[str]:
    """Properties this effect asks for that the ASS compiler cannot deliver."""
    return {t.prop for t in effect.tracks} - ASS_SUPPORTED


def compile_syllable(
    effect: Effect,
    *,
    text: str,
    duration_cs: int,
    attack_ms: int,
) -> str:
    r"""Render one syllable as "{tags}text".

    duration_cs is the syllable's karaoke time and is emitted verbatim as \kf:
    the sum of these across a line is the line's clock and must not change.
    """
    duration_cs = max(1, int(duration_cs))
    duration_ms = duration_cs * 10
    statics: list[str] = []
    transforms: list[str] = []

    for track in effect.tracks:
        if track.prop not in ASS_SUPPORTED:
            continue
        tag = PROP_TAG[track.prop]
        keys = resolve(track, attack_ms=attack_ms, duration_ms=duration_ms)
        statics.append(tag(keys[0][1]))
        for (t0, _), (t1, v1) in zip(keys, keys[1:]):
            if t1 <= t0:
                continue
            accel = "" if track.accel == 1.0 else f"{_fmt(track.accel)},"
            transforms.append(f"\\t({t0},{t1},{accel}{tag(v1)})")

    return f"{{{''.join(statics)}{''.join(transforms)}\\kf{duration_cs}}}{text}"
