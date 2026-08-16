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


def _flash(d: int, t: str) -> str:
    # Glitch pop: thick border snaps down to normal on the vocal attack.
    # Not selectable per line — a style opts in via flash_on_highlight.
    return f"{{\\bord8\\t(0,200,\\bord2)\\be1\\kf{d}}}{t}"


EFFECTS: dict[str, SyllableEffect] = {
    "highlight": _sweep,
    "none": _instant,
    "flash": _flash,
}

# Effects that used to live here and are gone: fade_in prefixed a per-syllable
# \fad, which libass drops because the event already carries one and the first
# \fad wins — 158 of 652 shipped Dialogue lines asked for it and rendered
# identically to the sweep. scale_pop, outline_pop and glow_pulse were only
# reachable through effect_profile_id, which nothing read. Unknown names still
# fall back to the sweep, so old analysis.json files keep rendering.


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
    if name == "highlight" and flash_default:
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
    # Retired names must keep rendering, not vanish, on old analysis.json.
    for _retired in ("fade_in", "bounce", "scale_pop", "outline_pop", "glow_pulse", "soft_glow"):
        assert syllable_ass(_retired, 10, "x") == _sweep(10, "x"), _retired
    print(f"ok: {len(EFFECTS)} effects ->", available_effects())
