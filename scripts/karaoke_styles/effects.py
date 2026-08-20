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

from .ass_compile import compile_layer, compile_syllable, unsupported_props  # noqa: F401
from .keyframes import Effect, Layer, Track

DEFAULT_EFFECT = "highlight"

# The soft edge every lyric effect carries. Kept as a literal prefix rather than
# a track: \be is a render-quality switch, not something anyone animates.
SOFT_EDGE = "\\be1"

REVEAL_FADE_MS = 140
POP_RISE_MS = 90
POP_FALL_MS = 150
POP_SCALE_Y = 1.24
TYPE_FADE_MS = 60


def _in_place(layer, d: int, t: str, off: int, *, karaoke: str, frame=None) -> str:
    """Compile a layer and splice the soft edge in just before the karaoke tag."""
    token = compile_layer(
        layer, text=t, duration_cs=d, attack_ms=off, frame=frame, karaoke=karaoke
    )
    return token.replace(f"\\{karaoke}", f"{SOFT_EDGE}\\{karaoke}", 1)


REVEAL = Effect("reveal", (Layer("main", (Track("alpha", ((0, 0.0), (REVEAL_FADE_MS, 1.0))),)),))


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
        return _in_place(REVEAL.main, d, t, off, karaoke="kf")
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
    "highlight": Effect("highlight", (Layer("main"),)),
    # Also no tracks; syllable_ass downgrades its \kf to \k for the hard switch.
    "none": Effect("none", (Layer("main"),)),
    # Glitch pop: thick border snaps down to normal on this syllable's attack.
    "flash": Effect("flash", (Layer("main", (Track("outline", ((0, 8.0), (200, 2.0))),)),)),
    # Focus pull: each syllable sharpens across its OWN sung window, so the key
    # times are fractions of the duration rather than fixed milliseconds.
    "focus": Effect("focus", (Layer("main", (Track("blur", ((0.0, 3.0), (1.0, 0.0)), time="frac"),)),)),
    # Bounce on the attack — the "word pop" caption look.
    # scale_y ONLY, deliberately: vertical scale leaves the glyph's horizontal
    # advance untouched, so the line never reflows under the bounce. Uniform
    # scale is the "punch" effect, which can afford it because it owns its \pos.
    "pop": Effect("pop", (Layer("main", (
        Track("scale_y", ((0, 1.0), (POP_RISE_MS, POP_SCALE_Y),
                          (POP_RISE_MS + POP_FALL_MS, 1.0))),
    )),)),
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
    #
    # The 160ms lead is the load-bearing number, not the 80px. Syllables land
    # roughly 200ms apart, so the first draft's 260ms lead had a syllable
    # already in flight while the one before it was still being sung: the word
    # visibly tore in half for the duration ("mun" seated, "do" still below).
    # Keeping the flight shorter than a syllable's own gap keeps a word whole.
    "fly-in": Effect("fly-in", (Layer("main", (
        Track("offset_y", ((-160, 80.0), (0, 0.0)), accel=0.6),
        Track("alpha", ((-160, 0.0), (-40, 1.0))),
    )),)),
    # Tips in from -9 degrees and settles level. \org keeps the pivot on the
    # syllable, so a word at the frame edge does not swing off screen.
    # The leading 0.0 is the RESTING pose (see below) -- without it the whole
    # not-yet-sung tail of the line sat permanently at -9 and read as italic.
    # -14, not the -9 of the first draft: measured on a burned frame, -9 moved
    # the glyph's top corner 2px on a 44px cap height and read as a rendering
    # artefact rather than as motion.
    "swing": Effect("swing", (Layer("main", (
        Track("rotate", ((-200, 0.0), (-110, -14.0), (0, 0.0)), accel=0.5),
    )),)),
    # Uniform overshoot — the scale the old \fscy pop could not do without
    # reflowing, now safe because each syllable owns its position.
    # Rests at 1.0 for the same reason, and one sharper than swing's: a
    # syllable drawn narrower than the width we measured shrinks toward its own
    # \pos, so every unsung word visibly came apart ("i lu são").
    # 0.88 -> 1.22, not the first draft's 0.92 -> 1.12: that delivered 6px of
    # excursion on a 43px cap height, measured off a burned frame. Present, but
    # small enough to pass for a compression artefact.
    "punch": Effect("punch", (Layer("main", (
        Track("scale", ((-80, 1.0), (0, 0.88), (110, 1.22), (280, 1.0)), accel=0.7),
    )),)),
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
    layer_index: int = 0,
    frame: tuple[int, int] | None = None,
) -> str:
    r"""Render one LAYER of one syllable. Unknown effect falls back to the sweep.

    offset_ms anchors any \t this effect emits.

    style_effect is the animation the STYLE asks for, which a plain "highlight"
    line upgrades to. A line that explicitly picked something else keeps it.

    layer_index selects which of the effect's layers to draw; the caller emits
    one Dialogue per layer. Only the main layer gets \kf -- the others carry
    \k, so they advance the same clock without a sweep of their own.
    """
    name = resolve_effect(effect, style_effect)
    chosen = EFFECTS[name]
    attack_ms = max(0, int(offset_ms))
    if isinstance(chosen, TextEffect):
        if layer_index:
            raise IndexError(f"{name!r} is a TextEffect and has one layer only")
        return chosen.render(max(1, int(duration_cs)), text, attack_ms)
    layer = chosen.layers[layer_index]
    karaoke = "kf" if layer.role == "main" else "k"
    token = _in_place(layer, duration_cs, text, attack_ms, karaoke=karaoke, frame=frame)
    if name == "none":
        # The hard switch: no sweep, and no soft edge either.
        return token.replace(SOFT_EDGE + "\\kf", "\\k", 1)
    return token


def available_effects() -> list[str]:
    return sorted(EFFECTS)


if __name__ == "__main__":
    import re

    # Self-check: every LAYER of every effect emits balanced brace groups,
    # preserves the visible text, carries a karaoke tag, and -- most important
    # -- spends exactly the karaoke time it was given.
    _layers_checked = 0
    for _name, _fx in EFFECTS.items():
        _count = 1 if isinstance(_fx, TextEffect) else len(_fx.layers)
        for _li in range(_count):
            out = syllable_ass(_name, 42, "lá", layer_index=_li, frame=(1280, 720))
            assert out.count("{") == out.count("}") >= 1, (_name, _li, out)
            assert out.endswith("á"), (_name, _li, out)      # typewriter splits "lá"
            assert "".join(re.sub(r"\{[^}]*\}", "", out)) == "lá", (_name, _li, out)
            assert ("\\kf" in out) or ("\\k" in out), (_name, _li, out)
            # The karaoke clock must survive any effect, on any layer, however
            # many groups it emits.
            assert sum(int(n) for n in re.findall(r"\\k[fo]?(\d+)", out)) == 42, (_name, _li, out)
            _layers_checked += 1
    # Cardinality: at least one layer per effect, or the loop proved nothing.
    assert _layers_checked >= len(EFFECTS) >= 10, (_layers_checked, len(EFFECTS))
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
    # Every time an effect emits is anchored on the offset it was handed — the
    # whole point of the argument. Checked as a SHIFT rather than as "the first
    # \t starts at the offset": an effect with a lead-in legitimately starts
    # before its own attack (fly-in emits \t(974,..) for offset 1234), and the
    # older form declared that a bug. Both offsets are far from zero so
    # resolve()'s clamp never bites.
    def _times(out: str) -> list[int]:
        return [int(n) for pair in re.findall(r"\\t\((\d+),(\d+)", out) for n in pair]

    _animated = 0
    for _name in EFFECTS:
        _lo = _times(syllable_ass(_name, 30, "x", offset_ms=1000))
        _hi = _times(syllable_ass(_name, 30, "x", offset_ms=2000))
        assert len(_lo) == len(_hi), (_name, _lo, _hi)
        assert all(h - l == 1000 for l, h in zip(_lo, _hi)), (_name, _lo, _hi)
        _animated += bool(_lo)
    # Cardinality: if nothing emitted a \t the loop above proved nothing.
    assert _animated >= 5, _animated
    # Retired names must keep rendering, not vanish, on old analysis.json.
    for _retired in ("fade_in", "bounce", "scale_pop", "outline_pop", "glow_pulse", "soft_glow"):
        assert syllable_ass(_retired, 10, "x") == syllable_ass("highlight", 10, "x"), _retired
    print(f"ok: {len(EFFECTS)} effects, {_layers_checked} layers ->", available_effects())
