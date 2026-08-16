r"""ASS per-syllable karaoke effect registry.

Each effect turns one syllable (its visible text + its \kf fill duration in
centiseconds) into a single ASS override-tag token: "{...}text".

Everything compiles to plain libass tags, so the same output previews live in
JASSUB and burns identically through ffmpeg's ass= filter — one representation,
both render paths. This is the single source of truth that replaces the
hardcoded if/elif chain that used to live inline in
s06_generate_ass._build_karaoke_text.

Add an effect = add one entry to EFFECTS. Every effect is a pure string
function, so the whole thing is testable without a renderer (see __main__).
"""

from __future__ import annotations

from typing import Callable

# An effect maps (duration_cs, text) -> "{tags}text".
SyllableEffect = Callable[[int, str], str]

DEFAULT_EFFECT = "highlight"


def _sweep(d: int, t: str) -> str:
    # Readable left-to-right fill (secondary -> primary), softened edge.
    return f"{{\\be1\\kf{d}}}{t}"


def _instant(d: int, t: str) -> str:
    # Classic hard color switch, no sweep.
    return f"{{\\k{d}}}{t}"


def _fade_in(d: int, t: str) -> str:
    return f"{{\\fad(500,0)\\be1\\kf{d}}}{t}"


def _flash(d: int, t: str) -> str:
    # Glitch pop: thick border snaps down to normal on the vocal attack.
    return f"{{\\bord8\\t(0,200,\\bord2)\\be1\\kf{d}}}{t}"


def _scale_pop(d: int, t: str) -> str:
    # Real bounce: quick scale up then settle. The old "bounce" used untimed
    # \t tags that just eased to 100% over the whole syllable (no pop) — these
    # \t windows are in ms and fire on the attack, so it actually bounces.
    return f"{{\\be1\\t(0,120,\\fscx118\\fscy118)\\t(120,280,\\fscx100\\fscy100)\\kf{d}}}{t}"


def _outline_pop(d: int, t: str) -> str:
    # Outline grows in at the attack for a crisp edge.
    return f"{{\\bord0\\t(0,120,\\bord3.2)\\be1\\kf{d}}}{t}"


def _glow_pulse(d: int, t: str) -> str:
    # Soft glow: blur blooms then relaxes as the syllable lights up.
    return f"{{\\be1\\t(0,140,\\blur5)\\t(140,420,\\blur1)\\kf{d}}}{t}"


EFFECTS: dict[str, SyllableEffect] = {
    "highlight": _sweep,
    "sweep": _sweep,
    "none": _instant,
    "instant": _instant,
    "fade_in": _fade_in,
    "flash": _flash,
    "bounce": _scale_pop,
    "scale_pop": _scale_pop,
    "outline_pop": _outline_pop,
    "glow_pulse": _glow_pulse,
    "soft_glow": _glow_pulse,
}

# ponytail: clip_reveal (typewriter) and float need per-syllable x/y layout
# metrics that libass only knows at render time. They want a measurement pass
# before we can emit \clip / \move — deferred until an effect actually needs
# positioning, not stubbed now.


def syllable_ass(
    effect: str,
    duration_cs: int,
    text: str,
    *,
    flash_default: bool = False,
) -> str:
    r"""Render one syllable token. Unknown effect falls back to the sweep.

    flash_default preserves the old "highlight + style.flash_on_highlight"
    behaviour: a plain highlight upgrades to the flash effect when the style
    asks for it (cyberpunk preset, \bord8 glitch pulse).
    """
    name = effect or DEFAULT_EFFECT
    if name in ("highlight", "sweep") and flash_default:
        name = "flash"
    render = EFFECTS.get(name, EFFECTS[DEFAULT_EFFECT])
    return render(max(1, int(duration_cs)), text)


def available_effects() -> list[str]:
    return sorted(EFFECTS)


if __name__ == "__main__":
    # Self-check: every effect emits a single balanced brace group, ends with
    # the visible text, and carries a karaoke tag — the invariants s06 relies
    # on. No renderer needed.
    for _name in EFFECTS:
        out = syllable_ass(_name, 42, "lá")
        assert out.count("{") == out.count("}") == 1, (_name, out)
        assert out.endswith("lá"), (_name, out)
        assert ("\\kf" in out) or ("\\k" in out), (_name, out)
    assert syllable_ass("nope", 10, "x") == _sweep(10, "x")
    assert syllable_ass("highlight", 10, "x", flash_default=True) == _flash(10, "x")
    assert syllable_ass("none", 0, "x") == "{\\k1}x"  # duration floored to 1cs
    print(f"ok: {len(EFFECTS)} effects ->", available_effects())
