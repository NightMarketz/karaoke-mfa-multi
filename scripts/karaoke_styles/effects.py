r"""ASS per-syllable karaoke effect registry.

An effect is DATA — a set of keyframe tracks over neutral properties (see
keyframes.py) — and ass_compile.py turns those tracks into libass override
tags. This module is the registry that names them and the dispatcher s06 calls.

Everything still compiles to plain libass tags, so the same output previews
live in JASSUB and burns identically through ffmpeg's ass= filter — one
representation, both render paths.

Add an effect = add one Effect() to EFFECTS. Nothing here writes a tag by hand
any more, with one deliberate exception documented on TextEffect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .ass_compile import compile_syllable, unsupported_props  # noqa: F401
from .keyframes import Effect, Track

DEFAULT_EFFECT = "highlight"

# The soft edge every lyric effect carries. Kept as a literal prefix rather than
# a track: \be is a render-quality switch, not something anyone animates.
SOFT_EDGE = "\\be1"

REVEAL_FADE_MS = 140
POP_RISE_MS = 90
POP_FALL_MS = 150
POP_SCALE_Y = 1.24
TYPE_FADE_MS = 60


def _in_place(effect: Effect, d: int, t: str, off: int) -> str:
    """Compile an effect and splice the soft edge in just before the karaoke tag."""
    token = compile_syllable(effect, text=t, duration_cs=d, attack_ms=off)
    return token.replace("\\kf", f"{SOFT_EDGE}\\kf", 1)


REVEAL = Effect("reveal", (Track("alpha", ((0, 0.0), (REVEAL_FADE_MS, 1.0))),))


@dataclass(frozen=True)
class TextEffect:
    r"""An effect that rewrites the syllable's TEXT, not just its properties.

    typewriter is the only one: it splits a syllable across its characters and
    divides the karaoke time between them. The keyframe model animates
    properties of a fixed token and cannot express that, so this stays a
    function. needs_layout is always False.
    """

    id: str
    render: Callable[[int, str, int], str]
    needs_layout: bool = False

    def props(self) -> set[str]:
        return set()


def _typewriter(d: int, t: str, off: int) -> str:
    # Character-by-character typing. Unlike every other effect this one emits
    # SEVERAL tag groups — one per character — because the syllable's karaoke
    # time has to be split across its letters.
    # The split must sum back to d exactly: \k durations are the line's clock,
    # so a rounding leak here drifts the whole line against the audio.
    chars = list(t)
    if len(chars) <= 1:
        return _in_place(REVEAL, d, t, off)
    per, extra = divmod(d, len(chars))
    durations = [per + (1 if i < extra else 0) for i in range(len(chars))]
    parts = []
    at = off
    for char, dur in zip(chars, durations):
        # ponytail: written by hand, NOT through compile_syllable, and that is
        # load-bearing. The compiler floors every token at 1cs, which is right
        # for a whole syllable and wrong here: a 2cs syllable split across 3
        # characters legitimately gives one of them \kf0, and flooring it would
        # add centiseconds to the line's clock. The one invariant no effect may
        # touch is the one that would break.
        parts.append(
            f"{{\\alpha&HFF&\\t({at},{at + TYPE_FADE_MS},\\alpha&H00&)"
            f"{SOFT_EDGE}\\kf{dur}}}{char}"
        )
        at += dur * 10
    return "".join(parts)


EFFECTS: dict[str, Effect | TextEffect] = {
    # No tracks: the plain left-to-right fill, softened edge, nothing animated.
    "highlight": Effect("highlight", ()),
    # Also no tracks; syllable_ass downgrades its \kf to \k for the hard switch.
    "none": Effect("none", ()),
    # Glitch pop: thick border snaps down to normal on this syllable's attack.
    "flash": Effect("flash", (Track("outline", ((0, 8.0), (200, 2.0))),)),
    # Focus pull: each syllable sharpens across its OWN sung window, so the key
    # times are fractions of the duration rather than fixed milliseconds.
    "focus": Effect("focus", (Track("blur", ((0.0, 3.0), (1.0, 0.0)), time="frac"),)),
    # Bounce on the attack — the "word pop" caption look.
    # scale_y ONLY, deliberately: vertical scale leaves the glyph's horizontal
    # advance untouched, so the line never reflows under the bounce. Uniform
    # scale is the "punch" effect, which can afford it because it owns its \pos.
    "pop": Effect("pop", (
        Track("scale_y", ((0, 1.0), (POP_RISE_MS, POP_SCALE_Y),
                          (POP_RISE_MS + POP_FALL_MS, 1.0))),
    )),
    # Word-by-word appear — nothing exists ahead of the voice. A lyric-video
    # look, not a sing-along one: pair it with a preset, never default to it.
    "reveal": REVEAL,
    "typewriter": TextEffect("typewriter", _typewriter),

    # ── Motion. These need LAYOUT_PROPS, so s06 gives each syllable its own
    # Dialogue and \pos before the compiler will emit anything for them.
    #
    # ponytail: the numbers below (80px, -9 degrees, 1.12x) are first guesses,
    # authored without watching a frame. They are structurally right -- the
    # tracks say what moves and when -- but nobody should call the VALUES
    # finished until they have been through preview_effects.py.

    # Rises into place from 80px below, arriving exactly on the attack, fading
    # up on the way so it does not slide in as a solid block.
    "fly-in": Effect("fly-in", (
        Track("offset_y", ((-260, 80.0), (0, 0.0)), accel=0.6),
        Track("alpha", ((-260, 0.0), (-60, 1.0))),
    )),
    # Tips in from -9 degrees and settles level. \org keeps the pivot on the
    # syllable, so a word at the frame edge does not swing off screen.
    # The leading 0.0 is the RESTING pose (see below) -- without it the whole
    # not-yet-sung tail of the line sat permanently at -9 and read as italic.
    "swing": Effect("swing", (
        Track("rotate", ((-200, 0.0), (-120, -9.0), (0, 0.0)), accel=0.5),
    )),
    # Uniform overshoot — the scale the old \fscy pop could not do without
    # reflowing, now safe because each syllable owns its position.
    # Rests at 1.0 for the same reason, and one sharper than swing's: a
    # syllable drawn narrower than the width we measured shrinks toward its own
    # \pos, so every unsung word visibly came apart ("i lu são").
    "punch": Effect("punch", (
        Track("scale", ((-80, 1.0), (0, 0.92), (110, 1.12), (260, 1.0)), accel=0.7),
    )),
}

# Effects that used to live here and are gone: fade_in prefixed a per-syllable
# \fad, which libass drops because the event already carries one and the first
# \fad wins — 158 of 652 shipped Dialogue lines asked for it and rendered
# identically to the sweep. scale_pop, outline_pop and glow_pulse were only
# reachable through effect_profile_id, which nothing read. Unknown names still
# fall back to the sweep, so old analysis.json files keep rendering.


def resolve_effect(effect: str, style_effect: str = DEFAULT_EFFECT) -> str:
    r"""Which effect a line actually gets, given its own choice and its style's.

    One implementation on purpose. s06 has to answer this question a second
    time -- before rendering, to decide whether the line needs the per-syllable
    \pos path -- and a second copy of the rule is a second thing to keep in
    step. It already has a subtlety worth not re-deriving: a retired or unknown
    name (shipped analysis.json still carries "fade_in") means "no opinion",
    not "plain sweep", so it normalises to the default BEFORE the style upgrade
    or a preset's animation never reaches those lines.
    """
    name = effect if effect in EFFECTS else DEFAULT_EFFECT
    if name == DEFAULT_EFFECT and style_effect in EFFECTS:
        name = style_effect
    return name


def syllable_ass(
    effect: str,
    duration_cs: int,
    text: str,
    *,
    offset_ms: int = 0,
    style_effect: str = DEFAULT_EFFECT,
) -> str:
    r"""Render one syllable token. Unknown effect falls back to the sweep.

    offset_ms anchors any \t this effect emits (see SyllableEffect).

    style_effect is the animation the STYLE asks for, which a plain "highlight"
    line upgrades to — cyberpunk's \bord8 glitch pulse, focus-pull's blur ramp.
    A line that explicitly picked something else keeps its own choice.
    """
    name = resolve_effect(effect, style_effect)
    chosen = EFFECTS[name]
    attack_ms = max(0, int(offset_ms))
    if isinstance(chosen, TextEffect):
        return chosen.render(max(1, int(duration_cs)), text, attack_ms)
    token = _in_place(chosen, duration_cs, text, attack_ms)
    if name == "none":
        # The hard switch: no sweep, and no soft edge either.
        return token.replace(SOFT_EDGE + "\\kf", "\\k", 1)
    return token


def available_effects() -> list[str]:
    return sorted(EFFECTS)


if __name__ == "__main__":
    import re

    # Self-check: every effect emits balanced brace groups, preserves the
    # visible text, carries a karaoke tag, and — most important — spends
    # exactly the karaoke time it was given. No renderer needed.
    for _name in EFFECTS:
        out = syllable_ass(_name, 42, "lá")
        assert out.count("{") == out.count("}") >= 1, (_name, out)
        assert out.endswith("á"), (_name, out)          # typewriter splits "lá"
        assert "".join(re.sub(r"\{[^}]*\}", "", out)) == "lá", (_name, out)
        assert ("\\kf" in out) or ("\\k" in out), (_name, out)
        # The karaoke clock must survive any effect, however many groups it emits.
        assert sum(int(n) for n in re.findall(r"\\k[fo]?(\d+)", out)) == 42, (_name, out)
    assert syllable_ass("nope", 10, "x") == syllable_ass("highlight", 10, "x")
    assert (syllable_ass("highlight", 10, "x", style_effect="flash")
            == syllable_ass("flash", 10, "x"))
    assert syllable_ass("none", 0, "x") == "{\\k1}x"  # duration floored to 1cs
    # A line that picked its own effect is not overridden by the style.
    assert syllable_ass("none", 10, "x", style_effect="focus") == "{\\k10}x"
    # "none" is the ONE effect without the soft edge; every other one has it.
    assert SOFT_EDGE not in syllable_ass("none", 10, "x")
    for _name in EFFECTS:
        if _name != "none":
            assert SOFT_EDGE in syllable_ass(_name, 10, "x"), _name
    # Every \t an effect emits must be anchored at the offset it was handed —
    # the whole point of the argument. Effects without \t are exempt.
    for _name in EFFECTS:
        _out = syllable_ass(_name, 30, "x", offset_ms=1234)
        assert "\\t(" not in _out or "\\t(1234," in _out, (_name, _out)
    # Retired names must keep rendering, not vanish, on old analysis.json.
    for _retired in ("fade_in", "bounce", "scale_pop", "outline_pop", "glow_pulse", "soft_glow"):
        assert syllable_ass(_retired, 10, "x") == syllable_ass("highlight", 10, "x"), _retired
    print(f"ok: {len(EFFECTS)} effects ->", available_effects())
