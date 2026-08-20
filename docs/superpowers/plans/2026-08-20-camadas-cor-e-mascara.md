# Layers, colour and mask — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** give the keyframe effect language colour, layers and a mask, so glow,
chromatic aberration, colour flare and a light sweep become expressible as data.

**Architecture:** `Effect(id, tracks)` becomes `Effect(id, layers)` with exactly
three roles (`under`/`main`/`over`) and a ceiling of 4 layers. A layer is one
more Dialogue on the path that already exists — one per line off the layout
path, one per syllable on it. The emitter moves out of `s06_generate_ass.py`
into a new `scripts/ass_emit.py` **before** anything new is added, so every
later task lands in a file that fits in one head.

**Tech Stack:** Python 3.11 (SYSTEM python — the repo `.venv` has no pytest),
pytest + pytest-subtests, PIL + numpy for the pixel probes, system `ffmpeg`
with libass for burns.

## Global Constraints

Copied from the spec; every task's requirements implicitly include these.

- **Branch `mvp-pipeline-runner` in the MAIN checkout**
  `C:\Users\Katz\OneDrive\Desktop\Meus projetos\karaoke-mfa-multi`. Never the
  `.claude/worktrees/*` worktrees — they are on the `main` lineage, which
  shares no ancestor with this one and has no `scripts/karaoke_styles/`.
- **Pre-existing uncommitted WIP that is NOT ours:** `scripts/s06b_render_gpu.py`,
  `spike/gpu-karaoke/src/*.tsx`, `tests/test_gpu_palette.py`,
  `tests/test_s06_style_contracts.py`. Leave alone, never `git add` them, never
  `git add -A` / `git commit -a`. Stage by explicit path only.
- **Use the SYSTEM `python`** (3.11, has pytest/PIL/pysubs2/numpy).
- **Suite baseline measured at plan time: `760 passed, 165 subtests, 0 failed`
  in 55.9s.** (The brief said 700; the tree as it stands measures 760 — the
  denominator is what the tree reports, and every later count reconciles
  against 760, not 700.) Every task ends green, and the final count must
  reconcile as `760 + tests added`.
- **An ASS Fontsize is NOT a FreeType em size.** libass fits ascender+descender
  to it (0.752x for Segoe UI). `fonts.py` derives this. Do not "fix" it.
- **`\t` and `\move` times are milliseconds from the DIALOGUE start**, which is
  one preroll before `line["start"]`. Measuring from the line collapses lead-in
  effects to `\move(x,y,x,y,0,0)`.
- **A track's first key is its RESTING pose**, held from the Dialogue's first
  frame. An effect opening on its animated extreme leaves the whole unsung tail
  of the line sitting in that extreme.
- **Row breaks may only fall where a space does**, and rows stack by exactly
  the ASS Fontsize.
- **Colour is not interpolated in Python.** `\t` interpolates it; only the
  endpoints are emitted.
- **The karaoke clock is untouchable.** The sum of `\k`/`\kf` durations across
  a line is the line's clock. No task here may change it — on any layer.
- **Every fence gets a prescribed sabotage and must be SEEN RED before it
  counts.** A green run of a sabotaged target means the fence is wrong, not
  that the code is right. Harness: `python scratch/probes/sabotage.py <src>
  "<test files>" <cases.json>`; it treats "no tests ran" as a void verdict.
- **Report counts with denominators.** `[].every(...)` passes; a check over an
  empty set is a universal green. State how many items were examined.
- **Numbers interpolated between measurements must say so.**

---

## File structure

| file | now | after |
|---|---|---|
| `scripts/karaoke_styles/keyframes.py` | 74 | `Layer`, `ROLE_Z`, `MAX_LAYERS`, `MAIN_REFUSED`, colour/alpha/mask props, `time="abs"`, value-preserving `resolve` |
| `scripts/karaoke_styles/ass_compile.py` | 161 | colour table, `\clip` band, `compile_layer()`; `compile_syllable()` stays as the main-layer entry point |
| `scripts/karaoke_styles/effects.py` | 260 | 10 effects gain `(Layer("main", ...),)`; `glow_layer`/`ghost_layer`/`shine_layer`; 4 new effects |
| `scripts/ass_emit.py` | *(new)* | `_build_karaoke_text`, `_build_layout_events`, `_effect_capability_gaps`, `_escape_ass_text`, `_quantize_kf_durations_to_centiseconds`, `SIDE_MARGIN_RATIO`, `DESIGN_HEIGHT`, then `build_line_events` |
| `scripts/s06_generate_ass.py` | 1055 | shrinks; imports the five names back so its public surface is unchanged |
| `scripts/karaoke_styles/library.py` | 2538 | 4 new presets, data only |
| `scripts/karaoke_styles/preview_effects.py` | 376 | import source changes; 4 new `PRESET_FOR_EFFECT` entries |

New test files: `tests/test_layers.py`, `tests/test_ass_colour.py`,
`tests/test_shine.py`. Existing files extended: `tests/test_keyframes.py`,
`tests/test_ass_compile.py`, `tests/test_karaoke_style_library.py`,
`tests/test_preview_effects.py`, `tests/test_ass_generation.py`.

---

## Task 0: GATE — displace a layer without `\pos` — **ALREADY RUN, GO**

Run before the plan was written, because half of Task 4 depends on the answer
and it costs one render to find out. Recorded here so Task 4 does not re-derive
it. Probe: `scratch/probes/probe_margins.py` (committed with Task 1).

```
baseline (L=100 R=100 V=100)      ink centre x=478  top y=254
CONTROL  \pos +120px right        x=598 (dx=+120)  y=254 (dy=+0)
   control moved +120px horizontally, so the rows below are real

  MarginL 300 / MarginR 100       x= 578 (dx= +100)  y= 254 (dy=   +0)
  MarginL 100 / MarginR 300       x= 378 (dx= -100)  y= 254 (dy=   +0)
  MarginV 100 -> 220              x= 478 (dx=   +0)  y= 134 (dy= -120)

GATE: offsets on BOTH axes -> build T4 as written, ghost is cheap on both paths.
```

The control moved by exactly the +120px it was handed, so the instrument can
see a displacement; only then are the three rows below it meaningful.

**The exact mapping, which Task 4 uses verbatim.** With alignment 2 the text is
centred between the event's own MarginL and MarginR, and MarginV is the
distance from the bottom of the frame:

```
centre_x = W/2 + (MarginL - MarginR) / 2      ->  dx  needs  L = m + dx,  R = m - dx
top_y    shifts by -MarginV                   ->  dy  needs  V = v - dy   (dy positive = down)
```

Verified against the numbers above: L=300, R=100, m=100 gives (300-100)/2 =
+100, measured +100. MarginV 100 -> 220 gives -120, measured -120.

**The trap:** an event margin of **0 means "inherit the style's"**, not "zero".
A ghost whose `dx` equals the base margin would compute `R = 0` and silently
inherit, halving its own displacement. Task 4 clamps with `max(1, ...)`.

- [ ] **Step 1: Confirm the gate still reads GO on this machine**

```bash
python scratch/probes/probe_margins.py
```

Expected: `control moved +120px`, then `GATE: offsets on BOTH axes`. If the
control line reports it did not move, STOP — nothing below is usable.

---

## Task 1: Extract `scripts/ass_emit.py` — a pure move

**Files:**
- Create: `scripts/ass_emit.py`
- Modify: `scripts/s06_generate_ass.py` (delete lines 93–96 and 112–401, add an import)
- Modify: `scripts/karaoke_styles/preview_effects.py:32-37` (import source)
- Test: no new test. The 28-token golden (`tests/test_effect_port_regression.py`)
  and the whole suite are the fence, because a pure move must change nothing.

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, in `scripts/ass_emit.py`, with signatures **identical to the ones in
  `s06_generate_ass.py` today** — the underscore prefixes stay, because
  `tests/test_s06_layout_events.py`, `tests/test_s06_capability_report.py` and
  `scripts/karaoke_styles/preview_effects.py` import them by those names and
  renaming costs test churn for zero behaviour:
  - `DESIGN_HEIGHT: int = 720`
  - `SIDE_MARGIN_RATIO: float = 0.05`
  - `_escape_ass_text(text: str) -> str`
  - `_quantize_kf_durations_to_centiseconds(durations_ms: list[int], *, target_ms: int, gap_cs: int = 0) -> list[int]`
  - `_build_karaoke_text(words: list[dict], line_start_ms: int, effect: str, style_effect: str = "highlight", line_style: str | None = None) -> str`
  - `_effect_capability_gaps(lines: list[dict], styles: dict[str, KaraokeStyle]) -> dict[str, list[str]]`
  - `_build_layout_events(line: dict, style: KaraokeStyle, *, scale: float, play_res: tuple[int, int], fade_tag: str, start_ts: str, end_ts: str, start_ms: int, effect: str) -> list[str]`
- `s06_generate_ass.py` re-exports all seven, so `from scripts.s06_generate_ass
  import _build_layout_events` keeps working unchanged.

- [ ] **Step 1: Record the green baseline before touching anything**

```bash
python -m pytest -q --no-header --tb=no 2>&1 | tail -3
```

Write the exact totals line down. Expected: `760 passed, 165 subtests passed`.
If it is not 760, use whatever it actually says as the denominator for every
later reconciliation and say so — do not carry a number forward from this plan.

- [ ] **Step 2: Create `scripts/ass_emit.py` with the moved code**

Create the file with this header, then **move** (cut, do not retype) the bodies
of `_escape_ass_text` (s06 lines 112–120), `_quantize_kf_durations_to_centiseconds`
(122–145), `_build_karaoke_text` (147–273), `_effect_capability_gaps` (275–299)
and `_build_layout_events` (301–400) out of `scripts/s06_generate_ass.py` and
into it, in that order, unchanged — comments, docstrings and blank lines
included. Retyping is how a "pure move" stops being pure.

```python
r"""Karaoke lines -> ASS Dialogue events.

The render layer. It sits ABOVE both the style vocabulary
(scripts/karaoke_styles/) and the timing analysis (scripts/review_wizard/),
and the pipeline stage (s06_generate_ass.py) sits above it — which is exactly
why it is here and not inside karaoke_styles: that package imports
review_wizard in zero places today, and putting the emitter inside it would
drag the review pipeline into the one clean leaf package in the tree.

The one rule that governs the times in here: \k, \t and \move all run on the
DIALOGUE's clock, which starts one preroll before line["start"]. Measuring an
attack from the line instead throws every animation early by the preroll and
leaves a lead-in effect with nowhere to come from.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.review_wizard.highlight_velocity import build_word_highlight_segments
from scripts.review_wizard.timing_layers import (
    classify_line_timing,
    gap_should_be_absorbed,
)
from scripts.karaoke_styles.library import KaraokeStyle
from scripts.karaoke_styles.ass_compile import compile_syllable, unsupported_props
from scripts.karaoke_styles.effects import (
    DEFAULT_EFFECT,
    EFFECTS,
    TextEffect,
    resolve_effect,
    syllable_ass,
)
from scripts.karaoke_styles.fonts import measure, resolve_font_path
from scripts.karaoke_styles.layout import place

# Preset pixel values (fontsize, outline, shadow, margin_v) are authored
# against this canvas height and scaled to whatever the render asks for.
DESIGN_HEIGHT = 720
# Side margin as a share of frame width, so a long line wraps before the edge
# instead of at the flat 20px the style line used to carry.
SIDE_MARGIN_RATIO = 0.05
```

- [ ] **Step 3: Point `s06_generate_ass.py` at the new module**

Delete from `scripts/s06_generate_ass.py`: the `DESIGN_HEIGHT` /
`SIDE_MARGIN_RATIO` block (lines 93–96 with their comments) and the five
function definitions now living in `ass_emit.py`. Then, immediately after the
existing `from scripts.karaoke_styles.layout import place` line, add:

```python
# The emitter moved out (scripts/ass_emit.py) so this stage is what its name
# says: read analysis.json, pick a preset, call the emitter, write the file.
# Re-exported here because tests and preview_effects.py import them from this
# module by these names.
from scripts.ass_emit import (  # noqa: F401
    DESIGN_HEIGHT,
    SIDE_MARGIN_RATIO,
    _build_karaoke_text,
    _build_layout_events,
    _effect_capability_gaps,
    _escape_ass_text,
    _quantize_kf_durations_to_centiseconds,
)
```

The imports `build_word_highlight_segments`, `classify_line_timing`,
`gap_should_be_absorbed`, `compile_syllable`, `unsupported_props`, `measure`,
`resolve_font_path` and `place` may now be unused in `s06_generate_ass.py`.
Delete only the ones no remaining line references — check each with
`grep -n "<name>" scripts/s06_generate_ass.py` before deleting it. `EFFECTS`,
`TextEffect`, `resolve_effect`, `DEFAULT_EFFECT`, `syllable_ass` and several
`timing_layers` names are still used by `_generate_ass` and `main`; leave them.

- [ ] **Step 4: Point `preview_effects.py` at the new module**

In `scripts/karaoke_styles/preview_effects.py`, replace:

```python
from scripts.s06_generate_ass import (  # noqa: E402
    SIDE_MARGIN_RATIO,
    _build_karaoke_text,
    _build_layout_events,
    style_row,
)
```

with:

```python
from scripts.ass_emit import (  # noqa: E402
    SIDE_MARGIN_RATIO,
    _build_karaoke_text,
    _build_layout_events,
)
from scripts.s06_generate_ass import style_row  # noqa: E402
```

`style_row` stays in `s06_generate_ass.py`: it writes a `[V4+ Styles]` row, not
an event, and nothing in the spec moves it.

- [ ] **Step 5: Run the golden and the full suite — a pure move changes nothing**

```bash
python -m pytest tests/test_effect_port_regression.py -q --no-header
```

Expected: `2 passed` (28 tokens across 7 effects, checked as subtests).

```bash
python -m pytest -q --no-header --tb=short 2>&1 | tail -5
```

Expected: exactly the totals from Step 1, `760 passed, 165 subtests passed`. A
different number means the move was not pure — find what changed, do not adjust
the expectation.

- [ ] **Step 6: Prove `s06` really got smaller and the import is real**

```bash
python -c "import scripts.ass_emit as m; print(len(open('scripts/s06_generate_ass.py').readlines()), 'lines in s06;', len(open('scripts/ass_emit.py').readlines()), 'lines in ass_emit'); print(m._build_layout_events.__module__)"
```

Expected: s06 down from 1055 to roughly 750, `ass_emit` roughly 330, and the
module name printed as `scripts.ass_emit` — not `scripts.s06_generate_ass`.

- [ ] **Step 7: Commit**

Add one row to the table in `scratch/probes/README.md` first:

```
| `probe_margins.py` | T0 gate: can an event be displaced without \pos, through its own Margin fields? (yes, both axes) |
```

```bash
git add scripts/ass_emit.py scripts/s06_generate_ass.py scripts/karaoke_styles/preview_effects.py scratch/probes docs/superpowers/plans/2026-08-20-camadas-cor-e-mascara.md
git commit -m "refactor(ass): extract the emitter out of s06 into scripts/ass_emit.py"
```

---

## Task 2: Colour and alpha tracks

**Files:**
- Modify: `scripts/karaoke_styles/keyframes.py` (new prop sets, value-preserving `resolve`)
- Modify: `scripts/karaoke_styles/ass_compile.py` (colour table)
- Test: `tests/test_ass_colour.py` (create), `tests/test_keyframes.py` (extend)

**Interfaces:**
- Consumes: `Track`, `Effect`, `resolve` from Task 0's untouched `keyframes.py`.
- Produces:
  - `keyframes.COLOR_PROPS: frozenset[str]` = `{"fill_color", "outline_color", "shadow_color", "unsung_color"}`
  - `keyframes.ALPHA_PROPS: frozenset[str]` = `{"fill_alpha", "outline_alpha", "shadow_alpha"}`
  - `IN_PLACE_PROPS` grows to include both, so `ASS_SUPPORTED == IN_PLACE_PROPS` still holds.
  - `resolve(track, *, attack_ms, duration_ms) -> list[tuple[int, str | float]]` — the
    value is now preserved, not coerced with `float()`. Only the time stays arithmetic.
  - `ass_compile._ass_colour(value: str) -> str` — `"#RRGGBB"` -> `"&HBBGGRR&"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ass_colour.py`:

```python
r"""Colour tracks: authored as #RRGGBB, emitted as libass &HBBGGRR&.

Colour is NOT interpolated in Python -- \t interpolates it, so only the
endpoints are ever emitted. A three-key colour track emits two \t's and no
intermediate colour at all, which is what these tests pin.
"""

import unittest

from scripts.karaoke_styles.ass_compile import _ass_colour, compile_syllable
from scripts.karaoke_styles.keyframes import Effect, Track


def _tags(effect, **kw):
    kw.setdefault("text", "x")
    kw.setdefault("duration_cs", 40)
    kw.setdefault("attack_ms", 0)
    return compile_syllable(effect, **kw)


class ColourConversionTests(unittest.TestCase):
    def test_hex_is_byte_reversed_into_ass_order(self):
        # ASS stores &HBBGGRR&: the byte order is reversed from web hex, which
        # is the single most common way to get a colour silently wrong.
        self.assertEqual("&H0000FF&", _ass_colour("#FF0000"))   # red
        self.assertEqual("&HFF0000&", _ass_colour("#0000FF"))   # blue
        self.assertEqual("&H00FF00&", _ass_colour("#00FF00"))   # green

    def test_the_hash_is_optional_and_case_is_normalised(self):
        self.assertEqual("&HEFBEAD&", _ass_colour("adbeef"))
        self.assertEqual("&HEFBEAD&", _ass_colour("#AdBeEf"))

    def test_a_malformed_colour_is_refused_not_silently_truncated(self):
        for bad in ("#FFF", "", "#GGGGGG", "12345678"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    _ass_colour(bad)


class ColourTrackTests(unittest.TestCase):
    def test_each_colour_prop_writes_its_own_register(self):
        cases = {
            "fill_color": "\\1c",
            "unsung_color": "\\2c",
            "outline_color": "\\3c",
            "shadow_color": "\\4c",
        }
        for prop, tag in cases.items():
            with self.subTest(prop=prop):
                out = _tags(Effect("e", (Track(prop, ((0, "#FF0000"),)),)))
                self.assertIn(f"{tag}&H0000FF&", out)

    def test_each_alpha_prop_writes_its_own_register_and_inverts(self):
        # Neutral 1.0 = fully visible; ASS alpha is transparency, so it inverts.
        cases = {
            "fill_alpha": "\\1a",
            "outline_alpha": "\\3a",
            "shadow_alpha": "\\4a",
        }
        for prop, tag in cases.items():
            with self.subTest(prop=prop):
                out = _tags(Effect("e", (Track(prop, ((0, 1.0),)),)))
                self.assertIn(f"{tag}&H00&", out)
                out = _tags(Effect("e", (Track(prop, ((0, 0.0),)),)))
                self.assertIn(f"{tag}&HFF&", out)

    def test_only_the_endpoints_are_emitted_never_an_interpolated_colour(self):
        # Three keys -> a resting static plus exactly two \t's, each carrying a
        # colour that was AUTHORED. Nothing in between is computed here: libass
        # does the interpolation, and a Python-side midpoint would be a second,
        # differently-rounded answer to the same question.
        effect = Effect("e", (
            Track("outline_color", ((0, "#000000"), (100, "#FF00FF"), (300, "#000000"))),
        ))
        out = _tags(effect)
        self.assertEqual(2, out.count("\\t("))
        self.assertIn("\\3c&H000000&\\t(0,100,\\3c&HFF00FF&)\\t(100,300,\\3c&H000000&)", out)

    def test_a_colour_track_is_anchored_on_the_attack_like_any_other(self):
        effect = Effect("e", (Track("outline_color", ((0, "#000000"), (100, "#FFFFFF"))),))
        out = _tags(effect, attack_ms=1234)
        self.assertIn("\\t(1234,1334,", out)


if __name__ == "__main__":
    unittest.main()
```

Append to `tests/test_keyframes.py`, inside `class TrackResolutionTests`:

```python
    def test_a_colour_value_survives_resolve_instead_of_being_coerced(self):
        # resolve() used to call float() on every value. With colour in the
        # vocabulary the value is no longer always numeric, so only the TIME
        # stays arithmetic.
        track = Track("fill_color", ((0, "#FF00AA"), (100, "#00FFAA")))
        self.assertEqual(
            [(500, "#FF00AA"), (600, "#00FFAA")],
            resolve(track, attack_ms=500, duration_ms=400),
        )

    def test_numeric_values_are_still_floats_after_resolve(self):
        track = Track("blur", ((0, 3), (100, 0)))
        values = [v for _, v in resolve(track, attack_ms=0, duration_ms=400)]
        self.assertEqual([3.0, 0.0], values)
        for value in values:
            self.assertIsInstance(value, float)
```

Add `Track` and `resolve` to the import block at the top of
`tests/test_keyframes.py` if they are not already there (they are).

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_ass_colour.py tests/test_keyframes.py -q --no-header --tb=line
```

Expected: `ImportError: cannot import name '_ass_colour'` for the new file, and
in `test_keyframes.py` a `ValueError: unknown effect property: 'fill_color'`.
Both are the right kind of red — the names do not exist yet.

- [ ] **Step 3: Add the vocabulary to `keyframes.py`**

Replace the prop-set block near the top of `scripts/karaoke_styles/keyframes.py`:

```python
# Colour, authored as "#RRGGBB" and converted at emission. NOT interpolated
# here: \t interpolates colour itself, so only the endpoints are ever emitted.
COLOR_PROPS = frozenset({"fill_color", "outline_color", "shadow_color", "unsung_color"})
# Per-register transparency. Neutral 1.0 = fully visible, like `alpha`.
ALPHA_PROPS = frozenset({"fill_alpha", "outline_alpha", "shadow_alpha"})
# Properties libass can animate on a syllable without owning its position.
IN_PLACE_PROPS = (
    frozenset({"scale_y", "alpha", "blur", "outline"}) | COLOR_PROPS | ALPHA_PROPS
)
```

Leave `LAYOUT_PROPS`, `FUTURE_PROPS` and `ALL_PROPS` exactly as they are —
`ALL_PROPS` is derived from `IN_PLACE_PROPS`, so it grows on its own.

Then make `resolve` value-preserving:

```python
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
```

Add `from typing import Any` to the imports at the top of the file.

- [ ] **Step 4: Add the colour table to `ass_compile.py`**

In `scripts/karaoke_styles/ass_compile.py`, replace the `_alpha_tag` function
and the `PROP_TAG` dict with:

```python
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
```

`_alpha_of("alpha")` produces exactly the `\alpha&HXX&` the old `_alpha_tag`
did, which is why the golden stays byte-identical. The
`assert ASS_SUPPORTED == IN_PLACE_PROPS` line below it needs no change and is
the thing that will catch it if these two lists ever drift.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/test_ass_colour.py tests/test_keyframes.py tests/test_ass_compile.py tests/test_effect_port_regression.py -q --no-header
```

Expected: all pass, and the golden still passes byte for byte — colour props
were added, none of the four existing tags changed.

- [ ] **Step 6: SABOTAGE — see the colour fence red**

```bash
cat > scratch/probes/cases_colour.json <<'JSON'
[
  ["byte order not reversed", "return f\"&H{text[4:6]}{text[2:4]}{text[0:2]}&\".upper()", "return f\"&H{text[0:2]}{text[2:4]}{text[4:6]}&\".upper()"],
  ["malformed colour accepted", "if len(text) != 6 or any(c not in \"0123456789abcdefABCDEF\" for c in text):", "if False:"],
  ["colour written to the wrong register", "\"outline_color\": lambda v: f\"\\\\3c{_ass_colour(v)}\",", "\"outline_color\": lambda v: f\"\\\\1c{_ass_colour(v)}\","]
]
JSON
python scratch/probes/sabotage.py scripts/karaoke_styles/ass_compile.py "tests/test_ass_colour.py" scratch/probes/cases_colour.json
```

Expected: **three red rows**, each ending in a `failed` count, and no
`STAYED GREEN` or `NO CARDINALITY` line. A `!! ANCHOR NOT FOUND` means the
sabotage string does not match the code you wrote — fix the anchor and re-run;
an unmatched anchor is a skipped fence, not a passed one.

- [ ] **Step 7: Run the full suite**

```bash
python -m pytest -q --no-header --tb=short 2>&1 | tail -5
```

Expected: `760 + 9 = 769 passed` (7 new tests in `test_ass_colour.py`, 2 in
`test_keyframes.py`), subtests up from 165. Report the actual number with its
denominator; if it is not 769, reconcile before moving on.

- [ ] **Step 8: Commit**

```bash
git add scripts/karaoke_styles/keyframes.py scripts/karaoke_styles/ass_compile.py tests/test_ass_colour.py tests/test_keyframes.py scratch/probes/cases_colour.json
git commit -m "feat(effects): colour and alpha tracks, authored as #RRGGBB"
```

---

## Task 3: Layers — roles, refusal, numbering, ceiling

The task the other three hang off. `Effect(id, tracks)` becomes
`Effect(id, layers)`; a layer becomes one more Dialogue on the path that
already exists.

**Files:**
- Modify: `scripts/karaoke_styles/keyframes.py` (`Layer`, `ROLE_Z`, `MAX_LAYERS`, `MAIN_REFUSED`, new `Effect`)
- Modify: `scripts/karaoke_styles/ass_compile.py` (`compile_layer`, `_move_tag` takes a layer)
- Modify: `scripts/karaoke_styles/effects.py` (10 effects wrapped, `syllable_ass` gains `layer_index`)
- Modify: `scripts/ass_emit.py` (`build_line_events`, both workers gain `layer_index`)
- Modify: `scripts/s06_generate_ass.py:_generate_ass` (calls `build_line_events`)
- Modify: `scripts/karaoke_styles/preview_effects.py:build_ass` (calls `build_line_events`)
- Test: `tests/test_layers.py` (create)

**Interfaces:**
- Consumes: `COLOR_PROPS`, `ALPHA_PROPS` from Task 2.
- Produces:
  - `keyframes.ROLE_Z: dict[str, int]` = `{"under": -1, "main": 0, "over": 1}`
  - `keyframes.MAX_LAYERS: int = 4`
  - `keyframes.MAIN_REFUSED: frozenset[str]` = `{"fill_color", "fill_alpha"}`
  - `keyframes.Layer(role: str, tracks: tuple[Track, ...] = (), offset: tuple[float, float] = (0.0, 0.0))` — frozen dataclass
  - `keyframes.Effect(id: str, layers: tuple[Layer, ...])` with properties
    `main -> Layer`, `tracks -> tuple[Track, ...]` (flattened over all layers),
    `layer_numbers -> tuple[int, ...]`, `needs_layout -> bool`, `props() -> set[str]`
  - `ass_compile.compile_layer(layer, *, text, duration_cs, attack_ms, anchor=None, frame=None, karaoke="kf") -> str`
  - `effects.syllable_ass(effect, duration_cs, text, *, offset_ms=0, style_effect=DEFAULT_EFFECT, layer_index=0, frame=None) -> str`
  - `ass_emit.build_line_events(line, style, *, effect, style_effect, style_key, scale, play_res, margin_lr, fade_tag, start_ts, end_ts, start_ms, line_start_ms) -> list[str]`
  - `ass_emit._build_layout_events(...)` gains keyword-only `layer_index: int = 0, layer_no: int = 0`
  - `ass_emit._build_karaoke_text(...)` gains keyword-only `layer_index: int = 0, frame: tuple[int, int] | None = None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_layers.py`:

```python
r"""Layers: three roles, one main, a ceiling of four, and Layer 0 for main-only.

The three rules here are each a measurement, not a preference:

  * fill colour is REFUSED on a main layer because \kf sweeps SecondaryColour
    -> PrimaryColour, so a track writing \1c writes the register the fill reads
    from. Measured: animating \1c, setting \1c statically and animating \1a all
    stop the sweep dead, while \3c and \2c leave it alone.
  * the ceiling is FOUR because layer cost is linear in burn time -- 538 events
    burn 60s of 1920x1080 in 4.5s, 2152 events in 13.4s, 8608 in 49.4s -- and 4
    keeps a 3-minute song at roughly 40s.
  * a main-only effect must number Layer 0, byte for byte what shipped before
    layers existed.
"""

import unittest

from scripts.karaoke_styles.keyframes import (
    MAIN_REFUSED,
    MAX_LAYERS,
    ROLE_Z,
    Effect,
    Layer,
    Track,
)


class LayerRoleTests(unittest.TestCase):
    def test_the_roles_are_exactly_three(self):
        self.assertEqual({"under", "main", "over"}, set(ROLE_Z))

    def test_an_unknown_role_is_refused_at_definition_time(self):
        with self.assertRaises(ValueError) as caught:
            Layer("glow")
        self.assertIn("glow", str(caught.exception))

    def test_fill_colour_on_a_main_layer_is_refused_BY_NAME(self):
        # Fence 1. Not "ignored", not "dropped": named in the error, because a
        # silently-dropped fill track is a dead karaoke sweep that nobody sees
        # until they watch the burned video.
        for prop in sorted(MAIN_REFUSED):
            with self.subTest(prop=prop):
                with self.assertRaises(ValueError) as caught:
                    Layer("main", (Track(prop, ((0, "#FF0000") if "color" in prop else (0, 0.5),)),))
                message = str(caught.exception)
                self.assertIn(prop, message)
                self.assertIn("sweep", message)

    def test_the_same_props_are_free_on_an_under_or_over_layer(self):
        # This is the whole point of the roles: the two rules compose instead
        # of fighting. Non-main layers carry \k, not \kf -- no sweep to kill.
        for role in ("under", "over"):
            with self.subTest(role=role):
                layer = Layer(role, (
                    Track("fill_color", ((0, "#FF0000"),)),
                    Track("fill_alpha", ((0, 0.5),)),
                ))
                self.assertEqual(2, len(layer.tracks))

    def test_outline_and_unsung_colour_are_free_on_main(self):
        # Measured: \3c and \2c leave the sweep alive. Refusing them would be
        # superstition, and it would make colour flare cost an extra event.
        layer = Layer("main", (
            Track("outline_color", ((0, "#000000"), (200, "#FF00FF"))),
            Track("unsung_color", ((0, "#888888"),)),
            Track("shadow_color", ((0, "#000000"),)),
        ))
        self.assertEqual(3, len(layer.tracks))

    def test_a_main_layer_may_not_be_offset(self):
        with self.assertRaises(ValueError):
            Layer("main", (), offset=(4.0, 0.0))


class EffectShapeTests(unittest.TestCase):
    def test_exactly_one_main_layer_is_required(self):
        with self.assertRaises(ValueError):
            Effect("none", (Layer("under"),))
        with self.assertRaises(ValueError):
            Effect("two", (Layer("main"), Layer("main")))
        self.assertEqual(1, len(Effect("ok", (Layer("main"),)).layers))

    def test_the_ceiling_is_four_layers(self):
        # Fence 3.
        four = tuple([Layer("under"), Layer("under"), Layer("main"), Layer("over")])
        self.assertEqual(MAX_LAYERS, len(four))
        Effect("four", four)                       # at the ceiling: fine
        with self.assertRaises(ValueError) as caught:
            Effect("five", four + (Layer("over"),))
        self.assertIn(str(MAX_LAYERS), str(caught.exception))

    def test_tracks_are_flattened_across_every_layer(self):
        effect = Effect("e", (
            Layer("under", (Track("blur", ((0, 6.0),)),)),
            Layer("main", (Track("outline", ((0, 2.0),)),)),
        ))
        self.assertEqual({"blur", "outline"}, effect.props())
        self.assertEqual(2, len(effect.tracks))

    def test_needs_layout_sees_a_layout_prop_on_any_layer(self):
        self.assertFalse(Effect("a", (Layer("main", (Track("blur", ((0, 1.0),)),)),)).needs_layout)
        self.assertTrue(Effect("b", (
            Layer("under", (Track("offset_x", ((0, 3.0),)),)),
            Layer("main"),
        )).needs_layout)

    def test_main_returns_the_one_main_layer(self):
        main = Layer("main", (Track("blur", ((0, 1.0),)),))
        self.assertIs(main, Effect("e", (Layer("under"), main, Layer("over"))).main)


class LayerNumberingTests(unittest.TestCase):
    def test_a_main_only_effect_is_layer_zero(self):
        # Fence 2. Byte for byte what shipped before layers existed, which is
        # why the golden needs no hand-written exception.
        self.assertEqual((0,), Effect("e", (Layer("main"),)).layer_numbers)

    def test_an_under_plus_main_effect_numbers_zero_then_one(self):
        effect = Effect("e", (Layer("under"), Layer("main")))
        self.assertEqual((0, 1), effect.layer_numbers)

    def test_the_whole_set_is_translated_so_its_minimum_is_zero(self):
        self.assertEqual((0, 1, 2), Effect("e", (Layer("under"), Layer("main"), Layer("over"))).layer_numbers)
        self.assertEqual((0, 1), Effect("f", (Layer("main"), Layer("over"))).layer_numbers)

    def test_two_layers_in_the_same_role_share_a_number(self):
        # Chromatic aberration is two ghosts; both sit under, both draw before
        # main, and their order between themselves is file order.
        effect = Effect("e", (Layer("under"), Layer("under"), Layer("main")))
        self.assertEqual((0, 0, 1), effect.layer_numbers)

    def test_under_always_numbers_below_main(self):
        # ASS draws lower Layer first, so this ordering IS the z-order.
        for layers in (
            (Layer("under"), Layer("main")),
            (Layer("under"), Layer("main"), Layer("over")),
        ):
            with self.subTest(count=len(layers)):
                effect = Effect("e", layers)
                numbers = dict(zip((l.role for l in layers), effect.layer_numbers))
                self.assertLess(numbers["under"], numbers["main"])


if __name__ == "__main__":
    unittest.main()
```

Append to the same file:

```python
from scripts.karaoke_styles.effects import EFFECTS, syllable_ass
from scripts.karaoke_styles.library import get_preset
from scripts.ass_emit import build_line_events


def _demo_line():
    """One analysis.json-shaped line: two words, three syllables."""
    def syl(text, start, end):
        return {"text": text, "start": start, "end": end,
                "karaoke_start": start, "karaoke_end": end, "confidence": 1.0}
    return {
        "start": 1.0, "end": 2.2, "style": "verse",
        "words": [
            {"word": "sol", "start": 1.0, "end": 1.4,
             "syllables": [syl("sol", 1.0, 1.4)]},
            {"word": "brilha", "start": 1.5, "end": 2.2,
             "syllables": [syl("bri", 1.5, 1.85), syl("lha", 1.85, 2.2)]},
        ],
    }


def _events(effect, style_effect=None, preset="pill"):
    style = get_preset(preset).styles["verse"]
    return build_line_events(
        _demo_line(), style,
        effect=effect, style_effect=style_effect or effect, style_key="verse",
        scale=1.5, play_res=(1920, 1080), margin_lr=96,
        fade_tag="{\\fad(120,120)}",
        start_ts="0:00:00.70", end_ts="0:00:02.50",
        start_ms=700, line_start_ms=1000,
    )


class EmittedLayerTests(unittest.TestCase):
    def test_every_shipped_effect_emits_one_event_per_layer_per_path(self):
        # Cardinality first: an empty EFFECTS would make every claim below a
        # universal green.
        self.assertGreaterEqual(len(EFFECTS), 10)
        checked = 0
        for name, effect in EFFECTS.items():
            with self.subTest(effect=name):
                layers = 1 if not hasattr(effect, "layers") else len(effect.layers)
                events = _events(name)
                if effect.needs_layout:
                    self.assertEqual(0, len(events) % layers, (name, len(events)))
                    self.assertEqual(3 * layers, len(events))  # 3 syllables
                else:
                    self.assertEqual(layers, len(events))
                checked += 1
        self.assertEqual(len(EFFECTS), checked)

    def test_a_main_only_effect_emits_layer_zero_and_inherited_margins(self):
        # Fence 2, end to end. "0,0,0" means "inherit the style row" -- exactly
        # what every shipped line has carried since before layers existed.
        events = _events("highlight")
        self.assertEqual(1, len(events))
        self.assertTrue(events[0].startswith("Dialogue: 0,"), events[0])
        self.assertIn(",0,0,0,,", events[0])

    def test_the_karaoke_clock_is_identical_on_every_layer(self):
        # The one invariant no effect may touch. Same clock on every copy, or
        # the layers drift apart against the audio.
        import re
        for name, effect in EFFECTS.items():
            if not hasattr(effect, "layers") or effect.needs_layout:
                continue
            with self.subTest(effect=name):
                clocks = {
                    sum(int(n) for n in re.findall(r"\\k[fo]?(\d+)", event))
                    for event in _events(name)
                }
                self.assertEqual(1, len(clocks), (name, clocks))

    def test_only_the_main_layer_carries_the_sweep(self):
        effect = EFFECTS["highlight"]
        self.assertEqual("main", effect.main.role)
        self.assertIn("\\kf", _events("highlight")[0])


class SyllableLayerTests(unittest.TestCase):
    def test_layer_index_selects_which_layer_is_rendered(self):
        self.assertIn("\\kf", syllable_ass("highlight", 40, "x", layer_index=0))

    def test_an_out_of_range_layer_index_raises_rather_than_returning_nothing(self):
        with self.assertRaises(IndexError):
            syllable_ass("highlight", 40, "x", layer_index=1)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_layers.py -q --no-header --tb=line
```

Expected: `ImportError: cannot import name 'Layer'`. Every test in the file is
red for the same reason, which is correct at this point.

- [ ] **Step 3: Add `Layer` and reshape `Effect` in `keyframes.py`**

Replace the `Effect` dataclass in `scripts/karaoke_styles/keyframes.py` with:

```python
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
```

- [ ] **Step 4: Add `compile_layer` to `ass_compile.py`**

In `scripts/karaoke_styles/ass_compile.py`:

1. Change the import line to
   `from .keyframes import IN_PLACE_PROPS, Effect, Layer, resolve`.
2. Change `_move_tag`'s first parameter from `effect: Effect` to
   `layer: Layer`, and its body's `effect.tracks` to `layer.tracks` (one
   occurrence, inside the `tracks = {...}` comprehension).
3. Rename `compile_syllable` to `compile_layer`, change its first parameter
   from `effect: Effect` to `layer: Layer`, change the two `effect.tracks`
   reads to `layer.tracks`, change the `_move_tag(effect, ...)` call to
   `_move_tag(layer, ...)`, and add two keyword-only parameters plus the new
   final line:

```python
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
    unlocks LAYOUT_PROPS. `frame` is the (width, height) a mask sweeps across.
    """
    ...
    return f"{{{''.join(statics)}{''.join(transforms)}\\{karaoke}{duration_cs}}}{text}"
```

4. Add the main-layer entry point immediately after it, so effects.py, the
   golden and every existing caller keep working:

```python
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
```

`unsupported_props(effect, *, anchored=False)` needs no change: it reads
`effect.tracks`, which is now flattened over every layer, so a property asked
for on an under layer is reported just the same.

- [ ] **Step 5: Wrap the ten effects and teach `syllable_ass` about layers**

In `scripts/karaoke_styles/effects.py`:

1. Import `Layer`: `from .keyframes import Effect, Layer, Track`, and import
   `compile_layer` alongside the existing names from `.ass_compile`.
2. Wrap every `Effect(...)` in `EFFECTS` and the module-level `REVEAL`. The
   mechanical rule is `Effect("x", (T1, T2))` -> `Effect("x", (Layer("main", (T1, T2)),))`.
   All ten, with their comments left exactly where they are:

```python
REVEAL = Effect("reveal", (Layer("main", (Track("alpha", ((0, 0.0), (REVEAL_FADE_MS, 1.0))),)),))
```

```python
    "highlight": Effect("highlight", (Layer("main"),)),
    "none": Effect("none", (Layer("main"),)),
    "flash": Effect("flash", (Layer("main", (Track("outline", ((0, 8.0), (200, 2.0))),)),)),
    "focus": Effect("focus", (Layer("main", (Track("blur", ((0.0, 3.0), (1.0, 0.0)), time="frac"),)),)),
    "pop": Effect("pop", (Layer("main", (
        Track("scale_y", ((0, 1.0), (POP_RISE_MS, POP_SCALE_Y),
                          (POP_RISE_MS + POP_FALL_MS, 1.0))),
    )),)),
    "reveal": REVEAL,
    "typewriter": TextEffect("typewriter", _typewriter),
    "fly-in": Effect("fly-in", (Layer("main", (
        Track("offset_y", ((-160, 80.0), (0, 0.0)), accel=0.6),
        Track("alpha", ((-160, 0.0), (-40, 1.0))),
    )),)),
    "swing": Effect("swing", (Layer("main", (
        Track("rotate", ((-200, 0.0), (-110, -14.0), (0, 0.0)), accel=0.5),
    )),)),
    "punch": Effect("punch", (Layer("main", (
        Track("scale", ((-80, 1.0), (0, 0.88), (110, 1.22), (280, 1.0)), accel=0.7),
    )),)),
```

3. Replace `_in_place` and `syllable_ass`:

```python
def _in_place(layer, d: int, t: str, off: int, *, karaoke: str, frame=None) -> str:
    """Compile a layer and splice the soft edge in just before the karaoke tag."""
    token = compile_layer(
        layer, text=t, duration_cs=d, attack_ms=off, frame=frame, karaoke=karaoke
    )
    return token.replace(f"\\{karaoke}", f"{SOFT_EDGE}\\{karaoke}", 1)
```

```python
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
```

`chosen.layers[layer_index]` raises `IndexError` on its own for an out-of-range
index, which is what the test asks for.

4. Update the `__main__` self-check at the bottom of the file so it walks every
   layer, not just layer 0. Replace the first loop with:

```python
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
```

and change the final `print` to
`print(f"ok: {len(EFFECTS)} effects, {_layers_checked} layers ->", available_effects())`.

- [ ] **Step 6: Teach the emitter to iterate layers**

In `scripts/ass_emit.py`:

1. `_build_karaoke_text` gains two keyword-only parameters after `line_style`:
   `*, layer_index: int = 0, frame: tuple[int, int] | None = None`, and its
   inner `append_segment` passes them through to `syllable_ass`:

```python
        target.append(
            syllable_ass(
                effect,
                duration_cs,
                visible_segment,
                offset_ms=offset_cs * 10,
                style_effect=style_effect,
                layer_index=layer_index,
                frame=frame,
            )
        )
```

2. `_build_layout_events` gains `layer_index: int = 0` and `layer_no: int = 0`
   in its keyword-only block. Inside, replace the tail of the function (from
   `chosen = EFFECTS[effect] ...` down) with:

```python
    chosen = EFFECTS[effect] if effect in EFFECTS else EFFECTS[DEFAULT_EFFECT]
    layer = chosen.layers[layer_index]
    karaoke = "kf" if layer.role == "main" else "k"
    dx, dy = layer.offset
    events = []
    for spot, attack_ms, duration_cs in zip(placed, attacks, durations):
        # On this path the offset is free: the syllable already carries \pos,
        # so a ghost is the same event drawn a few pixels over.
        anchor = (spot.x + spot.width / 2 + dx, spot.y + dy)
        token = compile_layer(
            layer,
            text=spot.text,
            duration_cs=duration_cs,
            attack_ms=attack_ms,
            anchor=anchor,
            frame=(width_px, height_px),
            karaoke=karaoke,
        )
        # An effect that animates offset compiles to \move, which already
        # carries the destination. Emitting \pos as well leaves libass with two
        # positioning tags; it keeps the first and drops the other, so the
        # motion would silently vanish (or the placement would).
        placement = "" if "\\move(" in token else f"\\pos({anchor[0]:.1f},{anchor[1]:.1f})"
        lead_cs = attack_ms // 10
        lead = f"{{\\k{lead_cs}}}" if lead_cs > 0 else ""
        events.append(
            f"Dialogue: {layer_no},{start_ts},{end_ts},{style.name},,0,0,0,,"
            f"{fade_tag}{{\\an2{placement}}}{lead}{token}"
        )
    return events
```

   and change the import at the top of `ass_emit.py` from `compile_syllable` to
   `compile_layer` (`compile_syllable` is no longer used there).

3. Add `build_line_events` at the end of `ass_emit.py`:

```python
def build_line_events(
    line: dict,
    style: KaraokeStyle,
    *,
    effect: str,
    style_effect: str,
    style_key: str,
    scale: float,
    play_res: tuple[int, int],
    margin_lr: int,
    fade_tag: str,
    start_ts: str,
    end_ts: str,
    start_ms: int,
    line_start_ms: int,
) -> list[str]:
    r"""Every Dialogue this line emits: one per layer, or one per (layer, syllable).

    A layer is one more Dialogue on the path that already exists, so layers are
    cheap on a non-layout preset (L x 52 on the reference job) and expensive on
    a layout one (L x 538). The ceiling of 4 is set by the worse case.

    `start_ms` is the DIALOGUE's start -- one preroll before line["start"] --
    because \k, \t and \move all run on that clock. `line_start_ms` is
    line["start"], which is what the non-layout builder measures word gaps
    against.
    """
    chosen = EFFECTS[effect]
    if isinstance(chosen, TextEffect):
        layers: tuple = (None,)
        numbers: tuple[int, ...] = (0,)
    else:
        layers, numbers = chosen.layers, chosen.layer_numbers

    events: list[str] = []
    for index, (layer, number) in enumerate(zip(layers, numbers)):
        if chosen.needs_layout:
            events += _build_layout_events(
                line, style,
                scale=scale, play_res=play_res, fade_tag=fade_tag,
                start_ts=start_ts, end_ts=end_ts, start_ms=start_ms,
                effect=effect, layer_index=index, layer_no=number,
            )
            continue
        text = _build_karaoke_text(
            line["words"], line_start_ms, effect,
            style_effect=style_effect, line_style=style_key,
            layer_index=index, frame=play_res,
        )
        dx, dy = layer.offset if layer is not None else (0.0, 0.0)
        if dx or dy:
            # Measured (T0 gate, scratch/probes/probe_margins.py): with
            # alignment 2 the text is centred between the event's OWN MarginL
            # and MarginR, so centre_x = W/2 + (L - R)/2, and MarginV is the
            # distance from the bottom of the frame. Both verified against a
            # \pos control that moved by exactly the amount it was handed.
            #
            # The clamp is not cosmetic: an event margin of 0 means "inherit
            # the style's", NOT zero, so a ghost whose dx reached the base
            # margin would silently halve its own displacement.
            ml = max(1, round(margin_lr + dx))
            mr = max(1, round(margin_lr - dx))
            mv = max(1, round(style.margin_v * scale - dy))
        else:
            # 0,0,0 = inherit the style row, byte for byte what every shipped
            # line has carried since before layers existed.
            ml = mr = mv = 0
        events.append(
            f"Dialogue: {number},{start_ts},{end_ts},{style.name},,"
            f"{ml},{mr},{mv},,{fade_tag}{text}"
        )
    return events
```

- [ ] **Step 7: Point `s06` and the preview at `build_line_events`**

In `scripts/s06_generate_ass.py:_generate_ass`, replace the `kf_text = ...`
assignment and the whole `if EFFECTS[chosen_effect].needs_layout: ... else: ...`
block with:

```python
        chosen_effect = resolve_effect(line.get("effect", DEFAULT_EFFECT), s.highlight_effect)
        # One Dialogue per layer off the layout path, one per (layer, syllable)
        # on it. A main-only effect is a single Layer 0 event, unchanged.
        event_lines.extend(build_line_events(
            line, s,
            effect=chosen_effect,
            style_effect=s.highlight_effect,
            style_key=style_key,
            scale=scale,
            play_res=(int(width), int(height)),
            margin_lr=margin_lr,
            fade_tag=fade_tag,
            start_ts=start_ts,
            end_ts=end_ts,
            start_ms=display_start_ms,
            line_start_ms=start_ms,
        ))
```

and add `build_line_events` to the `from scripts.ass_emit import (...)` block.

In `scripts/karaoke_styles/preview_effects.py:build_ass`, replace the
`if EFFECTS[name].needs_layout: ... else: ...` block inside the
`for line, win_start, win_end in windows:` loop with:

```python
            events += build_line_events(
                line, style,
                effect=name,
                style_effect=name,
                style_key=str(line.get("style") or "verse"),
                scale=scale,
                play_res=(WIDTH, HEIGHT),
                margin_lr=MARGIN_LR,
                fade_tag=fade,
                start_ts=_ts(win_start), end_ts=_ts(win_end),
                start_ms=win_start * 10,
                line_start_ms=round(float(line["start"]) * 1000),
            )
```

and change its import to
`from scripts.ass_emit import SIDE_MARGIN_RATIO, build_line_events`
(`_build_karaoke_text` and `_build_layout_events` are no longer referenced
there — confirm with `grep -n "_build_" scripts/karaoke_styles/preview_effects.py`
before removing them).

- [ ] **Step 8: Run the tests to verify they pass**

```bash
python -m pytest tests/test_layers.py tests/test_ass_compile.py tests/test_keyframes.py tests/test_effect_port_regression.py tests/test_s06_layout_events.py tests/test_preview_effects.py -q --no-header
```

Expected: all pass. The golden in particular: `compile_syllable` delegating to
the main layer must produce the same 28 tokens byte for byte.

- [ ] **Step 9: SABOTAGE — see fences 1, 2 and 3 red**

```bash
cat > scratch/probes/cases_layers.json <<'JSON'
[
  ["fence 1: allow fill colour on main", "refused = sorted({track.prop for track in self.tracks} & MAIN_REFUSED)", "refused = []"],
  ["fence 2: number layers from 1", "return tuple(z - base for z in zs)", "return tuple(z - base + 1 for z in zs)"],
  ["fence 3: raise the ceiling to 5", "MAX_LAYERS = 4", "MAX_LAYERS = 5"],
  ["main layer stops being unique", "if mains != 1:", "if False:"],
  ["under stops sorting below main", "ROLE_Z = {\"under\": -1, \"main\": 0, \"over\": 1}", "ROLE_Z = {\"under\": 1, \"main\": 0, \"over\": -1}"]
]
JSON
python scratch/probes/sabotage.py scripts/karaoke_styles/keyframes.py "tests/test_layers.py tests/test_effect_port_regression.py tests/test_ass_generation.py" scratch/probes/cases_layers.json
```

Expected: **five red rows**. Note what fence 2 actually catches: the 28-token
golden pins the *token text* and does NOT contain the Dialogue `Layer` field,
so it does **not** go red on a renumbering — the spec's claim that it would is
wrong. What goes red is
`test_a_main_only_effect_is_layer_zero` and
`test_a_main_only_effect_emits_layer_zero_and_inherited_margins` in
`tests/test_layers.py`, which check the number directly and the emitted
`Dialogue: 0,` prefix end to end. If any row prints `STAYED GREEN`, that fence
does not catch what it claims — fix the test, not the expectation.

- [ ] **Step 10: Run the full suite**

```bash
python -m pytest -q --no-header --tb=short 2>&1 | tail -5
```

Expected: `769 + 17 = 786 passed`. Report with the denominator and reconcile
against the previous total before moving on.

- [ ] **Step 11: Commit**

```bash
git add scripts/karaoke_styles/keyframes.py scripts/karaoke_styles/ass_compile.py scripts/karaoke_styles/effects.py scripts/karaoke_styles/preview_effects.py scripts/ass_emit.py scripts/s06_generate_ass.py tests/test_layers.py scratch/probes/cases_layers.json
git commit -m "feat(effects): layers with three roles, a ceiling of four, and Layer 0 for main-only"
```

---

## Task 4: `glow_layer` and `ghost_layer`

Constructors, not roles. They build an `under` layer with the right tracks;
role stays the only axis the compiler needs in order to refuse.

The T0 gate came back **GO on both axes**, so this task is built as written and
`ghost_layer` works on both paths — no layout-exclusive fallback needed.

**Files:**
- Modify: `scripts/karaoke_styles/effects.py` (two constructors)
- Test: `tests/test_layers.py` (extend)

**Interfaces:**
- Consumes: `Layer`, `Track` (Task 3); colour props (Task 2); the margin
  mapping proved by Task 0 and implemented in `build_line_events` (Task 3).
- Produces:
  - `effects.glow_layer(*, color: str = "#FFFFFF", blur: float = 9.0, spread: float = 5.0, alpha: float = 0.6) -> Layer`
  - `effects.ghost_layer(dx: float, dy: float, color: str, *, alpha: float = 0.85, blur: float = 0.0) -> Layer`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_layers.py`:

```python
from scripts.karaoke_styles.effects import ghost_layer, glow_layer


class LayerConstructorTests(unittest.TestCase):
    def test_glow_builds_an_under_layer_that_is_wider_and_softer(self):
        layer = glow_layer(color="#38E8FF", blur=9.0, spread=5.0, alpha=0.6)
        self.assertEqual("under", layer.role)
        props = {track.prop: track.keys[0][1] for track in layer.tracks}
        self.assertEqual(9.0, props["blur"])
        self.assertEqual(5.0, props["outline"])
        self.assertEqual("#38E8FF", props["fill_color"])
        self.assertEqual("#38E8FF", props["outline_color"])
        self.assertEqual(0.6, props["alpha"])

    def test_glow_is_static_so_it_never_emits_a_transform(self):
        # A glow that animates is a different effect. Every track is one key,
        # which compiles to a resting tag and no \t at all.
        for track in glow_layer().tracks:
            with self.subTest(prop=track.prop):
                self.assertEqual(1, len(track.keys))

    def test_ghost_carries_its_displacement_as_a_static_offset(self):
        layer = ghost_layer(-4.0, 2.0, "#00E5FF")
        self.assertEqual("under", layer.role)
        self.assertEqual((-4.0, 2.0), layer.offset)
        props = {track.prop: track.keys[0][1] for track in layer.tracks}
        self.assertEqual("#00E5FF", props["fill_color"])
        self.assertEqual("#00E5FF", props["outline_color"])

    def test_ghost_needs_no_layout_which_is_the_whole_point(self):
        # If a ghost forced needs_layout, any preset wanting chromatic
        # aberration would become a layout preset and multiply its event count
        # by ten. The T0 gate exists so it does not have to.
        effect = Effect("aberration", (
            ghost_layer(-4.0, 0.0, "#00E5FF"),
            ghost_layer(4.0, 0.0, "#FF006E"),
            Layer("main"),
        ))
        self.assertFalse(effect.needs_layout)
        self.assertEqual((0, 0, 1), effect.layer_numbers)


class GhostDisplacementTests(unittest.TestCase):
    """The margin arithmetic, against the numbers the T0 gate measured."""

    def _margins(self, event):
        fields = event.split(",")
        return tuple(int(f) for f in fields[5:8])

    def test_an_offset_layer_writes_its_own_margins_off_the_layout_path(self):
        from scripts.karaoke_styles.keyframes import Effect as _E
        import scripts.karaoke_styles.effects as fx
        fx.EFFECTS["_ghosttest"] = _E("_ghosttest", (
            ghost_layer(-6.0, 3.0, "#00E5FF"),
            Layer("main"),
        ))
        try:
            events = _events("_ghosttest")
        finally:
            del fx.EFFECTS["_ghosttest"]
        self.assertEqual(2, len(events))
        ghost, main = events
        # centre_x = W/2 + (L - R)/2, so dx=-6 needs L = 96-6, R = 96+6.
        # MarginV is the distance from the BOTTOM, so dy=+3 (down) needs
        # V = round(margin_v * scale) - 3.
        base_v = round(get_preset("pill").styles["verse"].margin_v * 1.5)
        self.assertEqual((90, 102, base_v - 3), self._margins(ghost))
        # The main layer is untouched: 0,0,0 means "inherit the style row".
        self.assertEqual((0, 0, 0), self._margins(main))
        self.assertTrue(ghost.startswith("Dialogue: 0,"))
        self.assertTrue(main.startswith("Dialogue: 1,"))

    def test_a_margin_never_reaches_zero_because_zero_means_inherit(self):
        # The trap the T0 gate turned up: an event margin of 0 is "use the
        # style's", not "no margin". A ghost whose dx reaches the base margin
        # would otherwise silently halve its own displacement.
        from scripts.karaoke_styles.keyframes import Effect as _E
        import scripts.karaoke_styles.effects as fx
        fx.EFFECTS["_farghost"] = _E("_farghost", (
            ghost_layer(999.0, 999.0, "#00E5FF"),
            Layer("main"),
        ))
        try:
            ghost = _events("_farghost")[0]
        finally:
            del fx.EFFECTS["_farghost"]
        for value in self._margins(ghost):
            self.assertGreaterEqual(value, 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_layers.py -q --no-header --tb=line
```

Expected: `ImportError: cannot import name 'ghost_layer'`.

- [ ] **Step 3: Add the two constructors**

In `scripts/karaoke_styles/effects.py`, after the `SOFT_EDGE` / timing
constants block and before `_in_place`:

```python
# ── Layer constructors ────────────────────────────────────────────────────
# NOT engine roles. Role is the axis the compiler needs in order to refuse;
# these are authoring convenience, and convenience should not become an engine
# concept. Both build an `under` layer, which carries \k rather than \kf -- so
# the fill-colour prohibition does not reach them, which is precisely why glow
# and ghost live outside main.

def glow_layer(
    *,
    color: str = "#FFFFFF",
    blur: float = 9.0,
    spread: float = 5.0,
    alpha: float = 0.6,
) -> Layer:
    r"""A soft wide copy of the line, drawn behind it.

    Made of LAYERS, not of the `glow` property -- that one stays reserved for a
    renderer that does real glow rather than stacking blurred copies.

    Every track is a single key, so this compiles to a resting tag and no \t:
    a glow that animates is a different effect, and the one that ships should
    cost the least it can.
    """
    return Layer("under", (
        Track("blur", ((0, blur),)),
        Track("outline", ((0, spread),)),
        # Both registers, because an under layer carries \k: without \1c the
        # glyph body would show through at the STYLE's fill colour instead of
        # the halo's.
        Track("fill_color", ((0, color),)),
        Track("unsung_color", ((0, color),)),
        Track("outline_color", ((0, color),)),
        Track("alpha", ((0, alpha),)),
    ))


def ghost_layer(
    dx: float,
    dy: float,
    color: str,
    *,
    alpha: float = 0.85,
    blur: float = 0.0,
) -> Layer:
    r"""A displaced coloured copy of the line -- one half of an aberration.

    The displacement is a STATIC Layer.offset, not an offset_x/offset_y track,
    and that is load-bearing: those are LAYOUT_PROPS, so a ghost built from
    them would force needs_layout and multiply any preset wanting glitch by ten
    events per line. Measured instead (T0 gate): the Dialogue's own
    MarginL/MarginR/MarginV displace an unpositioned line on BOTH axes, so
    ass_emit.build_line_events turns this offset into margins off the layout
    path and into the anchor on it.
    """
    tracks = [
        Track("fill_color", ((0, color),)),
        Track("unsung_color", ((0, color),)),
        Track("outline_color", ((0, color),)),
        Track("alpha", ((0, alpha),)),
    ]
    if blur:
        tracks.append(Track("blur", ((0, blur),)))
    return Layer("under", tuple(tracks), offset=(dx, dy))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_layers.py -q --no-header
```

Expected: all pass, including the two margin-arithmetic tests.

- [ ] **Step 5: SABOTAGE — see the displacement fence red**

```bash
cat > scratch/probes/cases_ghost.json <<'JSON'
[
  ["margin sign flipped", "ml = max(1, round(margin_lr + dx))", "ml = max(1, round(margin_lr - dx))"],
  ["dx applied at full width instead of half", "mr = max(1, round(margin_lr - dx))", "mr = max(1, round(margin_lr))"],
  ["MarginV sign flipped", "mv = max(1, round(style.margin_v * scale - dy))", "mv = max(1, round(style.margin_v * scale + dy))"],
  ["zero-means-inherit clamp removed", "ml = max(1, round(margin_lr + dx))\n            mr = max(1, round(margin_lr - dx))\n            mv = max(1, round(style.margin_v * scale - dy))", "ml = round(margin_lr + dx)\n            mr = round(margin_lr - dx)\n            mv = round(style.margin_v * scale - dy)"],
  ["offset ignored entirely", "if dx or dy:", "if False:"]
]
JSON
python scratch/probes/sabotage.py scripts/ass_emit.py "tests/test_layers.py" scratch/probes/cases_ghost.json
```

Expected: **five red rows**, no `STAYED GREEN`, no `ANCHOR NOT FOUND`.

- [ ] **Step 6: Run the full suite and commit**

```bash
python -m pytest -q --no-header --tb=short 2>&1 | tail -5
```

Expected: `786 + 6 = 792 passed`. Reconcile before committing.

```bash
git add scripts/karaoke_styles/effects.py tests/test_layers.py scratch/probes/cases_ghost.json
git commit -m "feat(effects): glow_layer and ghost_layer constructors"
```

---

## Task 5: `shine` — an animated `\clip` band

> **CORRECTION, measured during execution — read before this task's code.**
> Everything below that describes the band as a **diagonal four-point vector
> drawing** is wrong, and the spec's supporting claim is wrong with it. The
> spec's 48-of-48 tag survey reported that `\clip` vector masks "animated by
> `	`" render. Burned on this machine, three instants, with two controls:
> an animated **rectangular** `\clip(x1,y1,x2,y2)` sweeps **581px**; the
> **static** vector form draws, and its two endpoint shapes differ by
> **407px**; the same vector band **animated through `	` produces no ink at
> any instant**. libass interpolates the four-number rectangle and leaves a
> vector drawing frozen at its resting shape. The survey confirmed that the
> tag *renders*, not that the animation *runs* — the exact failure class the
> spec itself warns about.
>
> **Ruling:** the band is an axis-aligned rectangle. `SHINE_SKEW` is deleted;
> `SHINE_CLEARANCE = 1.0` is added so `v=0` and `v=1` put the band strictly
> off the frame rather than exactly touching its edge (the coordinates are
> rounded to ints, so touching can round the wrong way and light a one-pixel
> stripe at an instant the design says is dark). The diagonal was never
> load-bearing — the spec asks only that the band be "soft and wide". The
> implemented geometry, the replacement `ShineBandTests`, and the six-row
> sabotage batch are what shipped; the code blocks below are the superseded
> first draft, kept because the reasoning around them still holds.
> Independent re-measurement: `scratch/clipcheck/check.py`.

**Files:**
- Modify: `scripts/karaoke_styles/keyframes.py` (`MASK_PROPS`, `time="abs"`)
- Modify: `scripts/karaoke_styles/ass_compile.py` (`_shine_clip`, the mask branch)
- Modify: `scripts/karaoke_styles/effects.py` (`shine_layer`)
- Test: `tests/test_shine.py` (create)

**Interfaces:**
- Consumes: `Layer`, `Track`, `compile_layer` (Task 3).
- Produces:
  - `keyframes.MASK_PROPS: frozenset[str]` = `{"shine"}`, folded into `ALL_PROPS`
  - `TIME_MODES` grows to `("ms", "frac", "abs")`
  - `ass_compile.SHINE_HALF_WIDTH: float = 0.10`, `ass_compile.SHINE_SKEW: float = 0.22`
  - `ass_compile._shine_clip(value: float, frame: tuple[int, int]) -> str`
  - `effects.shine_layer(*, color: str = "#FFFFFF", start_ms: int = 0, travel_ms: int = 900, alpha: float = 0.9, blur: float = 2.0) -> Layer`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_shine.py`:

```python
r"""shine: one mask, not a generic vector clip.

Generic \clip is a large vocabulary in exchange for one look, so it stays out
until something needs it. `shine` carries a single normalised number -- 0.0 is
a band entirely left of the frame, 1.0 entirely right of it -- and compiles to
\clip plus \t(\clip(...)).

It works in FRAME coordinates, not text coordinates. On the layout path each
syllable's box is known, but off it the line's extent is not known without
measuring, and measuring there would force any preset wanting shine to become
a layout preset. The band crosses the frame instead: visually near-identical
on a centred line that occupies most of the width, and available on both paths.
"""

import re
import unittest

from scripts.karaoke_styles.ass_compile import (
    SHINE_HALF_WIDTH,
    SHINE_SKEW,
    _shine_clip,
    compile_layer,
)
from scripts.karaoke_styles.effects import shine_layer
from scripts.karaoke_styles.keyframes import MASK_PROPS, Layer, Track

FRAME = (1920, 1080)


def _xs(clip: str) -> list[int]:
    """The four x coordinates of a \\clip drawing, in order."""
    numbers = [int(n) for n in re.findall(r"-?\d+", clip)]
    return numbers[0::2]


class ShineBandTests(unittest.TestCase):
    def test_the_band_is_a_four_point_diagonal_polygon(self):
        clip = _shine_clip(0.5, FRAME)
        self.assertTrue(clip.startswith("\\clip(m "), clip)
        self.assertEqual(1, clip.count(" l "))
        self.assertEqual(8, len(re.findall(r"-?\d+", clip)))

    def test_it_spans_the_full_frame_height(self):
        ys = [int(n) for n in re.findall(r"-?\d+", _shine_clip(0.5, FRAME))][1::2]
        self.assertEqual({0, FRAME[1]}, set(ys))

    def test_it_is_skewed_so_the_top_leads_the_bottom(self):
        clip = _shine_clip(0.5, FRAME)
        x_top_left, x_top_right, x_bottom_right, x_bottom_left = _xs(clip)
        self.assertGreater(x_top_left, x_bottom_left)
        self.assertGreater(x_top_right, x_bottom_right)
        self.assertAlmostEqual(
            round(FRAME[0] * SHINE_SKEW * 2), x_top_left - x_bottom_left, delta=1
        )

    def test_zero_puts_the_whole_band_left_of_the_frame(self):
        self.assertLess(max(_xs(_shine_clip(0.0, FRAME))), 0)

    def test_one_puts_the_whole_band_right_of_the_frame(self):
        self.assertGreater(min(_xs(_shine_clip(1.0, FRAME))), FRAME[0])

    def test_the_band_marches_right_as_the_value_rises(self):
        # Cardinality and monotonicity together: a probe that sampled one
        # instant could not tell a moving band from a stuck one.
        centres = [sum(_xs(_shine_clip(v / 10, FRAME))) / 4 for v in range(11)]
        self.assertEqual(11, len(centres))
        for before, after in zip(centres, centres[1:]):
            self.assertLess(before, after)

    def test_the_band_is_wide_enough_to_be_soft(self):
        # It crosses the FRAME, so a narrow band would miss a short line
        # entirely. Documented risk, bounded here.
        clip = _shine_clip(0.5, FRAME)
        width = max(_xs(clip)) - min(_xs(clip))
        self.assertGreater(width, FRAME[0] * SHINE_HALF_WIDTH)


class ShineCompilationTests(unittest.TestCase):
    def test_a_shine_track_compiles_to_a_resting_clip_plus_transforms(self):
        layer = Layer("over", (Track("shine", ((0, 0.0), (900, 1.0)), time="abs"),))
        out = compile_layer(
            layer, text="x", duration_cs=40, attack_ms=1234, frame=FRAME, karaoke="k"
        )
        self.assertEqual(1, out.count("\\clip(m") - out.count("\\t(0,900,\\clip(m"))
        self.assertIn("\\t(0,900,\\clip(m", out)

    def test_abs_time_ignores_the_syllable_attack(self):
        # A line-wide sweep must be the SAME animation on every syllable, or
        # each token would drag its own band along behind it.
        layer = Layer("over", (Track("shine", ((0, 0.0), (900, 1.0)), time="abs"),))
        first = compile_layer(layer, text="x", duration_cs=40, attack_ms=0,
                              frame=FRAME, karaoke="k")
        later = compile_layer(layer, text="x", duration_cs=40, attack_ms=1234,
                              frame=FRAME, karaoke="k")
        self.assertEqual(first, later)

    def test_ms_time_still_follows_the_attack(self):
        # The control for the test above: if `ms` mode did not shift either,
        # that test would prove nothing about `abs`.
        layer = Layer("over", (Track("shine", ((0, 0.0), (900, 1.0))),))
        first = compile_layer(layer, text="x", duration_cs=40, attack_ms=0,
                              frame=FRAME, karaoke="k")
        later = compile_layer(layer, text="x", duration_cs=40, attack_ms=1234,
                              frame=FRAME, karaoke="k")
        self.assertNotEqual(first, later)
        self.assertIn("\\t(1234,2134,", later)

    def test_a_shine_track_without_a_frame_raises_instead_of_dropping_the_mask(self):
        layer = Layer("over", (Track("shine", ((0, 0.0), (900, 1.0)), time="abs"),))
        with self.assertRaises(ValueError) as caught:
            compile_layer(layer, text="x", duration_cs=40, attack_ms=0, karaoke="k")
        self.assertIn("frame", str(caught.exception))

    def test_shine_is_the_only_mask_property(self):
        self.assertEqual({"shine"}, set(MASK_PROPS))


class ShineLayerTests(unittest.TestCase):
    def test_it_builds_an_over_layer_that_draws_above_main(self):
        layer = shine_layer()
        self.assertEqual("over", layer.role)
        self.assertIn("shine", {track.prop for track in layer.tracks})

    def test_both_colour_registers_are_pinned_so_the_copy_is_uniform(self):
        # The over layer carries \k, so without \2c the not-yet-sung half of
        # the copy would draw at the STYLE's waiting colour and the sweep would
        # read as two different lights.
        props = {track.prop for track in shine_layer().tracks}
        self.assertIn("fill_color", props)
        self.assertIn("unsung_color", props)

    def test_the_sweep_is_measured_from_the_dialogue_not_the_syllable(self):
        shine = next(t for t in shine_layer().tracks if t.prop == "shine")
        self.assertEqual("abs", shine.time)
        self.assertEqual((0.0, 1.0), tuple(v for _, v in shine.keys))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_shine.py -q --no-header --tb=line
```

Expected: `ImportError: cannot import name 'SHINE_HALF_WIDTH'`.

- [ ] **Step 3: Add `MASK_PROPS` and the `abs` time mode to `keyframes.py`**

After the `ALPHA_PROPS` block:

```python
# The one mask. Generic vector \clip is a large vocabulary in exchange for one
# look, so it stays out until something needs it. The value is the normalised
# position of a diagonal band: 0.0 before the frame's left edge, 1.0 past its
# right.
MASK_PROPS = frozenset({"shine"})
```

Then fold it into `ALL_PROPS`:

```python
ALL_PROPS = IN_PLACE_PROPS | LAYOUT_PROPS | FUTURE_PROPS | MASK_PROPS
```

`MASK_PROPS` deliberately stays OUT of `IN_PLACE_PROPS`, because
`assert ASS_SUPPORTED == IN_PLACE_PROPS` in `ass_compile.py` pins that set to
the ones with a straight `PROP_TAG` entry, and `shine` is a special case there
— the same shape `MOVE_PROPS` already has.

```python
# "abs" is measured from the DIALOGUE rather than from the syllable's attack.
# A line-wide mask needs the same animation on every syllable of the line; with
# "ms" each token would drag its own band along behind it.
TIME_MODES = ("ms", "frac", "abs")
```

and in `resolve`:

```python
    for at, value in track.keys:
        if track.time == "abs":
            ms = max(0, int(round(at)))
        else:
            scale = duration_ms if track.time == "frac" else 1
            ms = max(0, int(round(attack_ms + at * scale)))
        resolved[ms] = value if isinstance(value, str) else float(value)
```

(delete the `scale = ...` line that currently sits above the loop).

- [ ] **Step 4: Add the band to `ass_compile.py`**

Import `MASK_PROPS` alongside the others, then add above `unsupported_props`:

```python
# The band's own geometry, as fractions of the FRAME width. Wide and soft on
# purpose: shine works in frame coordinates because the non-layout path never
# measures its line, so a narrow band would miss a short line entirely. The
# documented cost is that a very short line gets a band wider than itself --
# acceptable, because the band is soft.
SHINE_HALF_WIDTH = 0.10
SHINE_SKEW = 0.22


def _shine_clip(value: float, frame: tuple[int, int]) -> str:
    r"""\clip drawing for a diagonal band at normalised position `value`.

    0.0 puts the band entirely left of the frame and 1.0 entirely right of it,
    so a 0 -> 1 track sweeps it clean across and nothing is masked at either
    end of the travel.
    """
    width, height = frame
    half = width * SHINE_HALF_WIDTH
    skew = width * SHINE_SKEW
    centre = -half - skew + float(value) * (width + 2 * half + 2 * skew)
    points = (
        (centre - half + skew, 0),
        (centre + half + skew, 0),
        (centre + half - skew, height),
        (centre - half - skew, height),
    )
    (x0, y0), *rest = points
    tail = " ".join(f"{round(x)} {round(y)}" for x, y in rest)
    return f"\\clip(m {round(x0)} {round(y0)} l {tail})"
```

In `unsupported_props`, add the mask to the usable set — the emitter always
knows the frame, and `compile_layer` raises loudly rather than dropping it when
someone calls it without one:

```python
    usable = set(ASS_SUPPORTED) | set(MASK_PROPS)
```

In `compile_layer`, add the mask branch at the top of the track loop, before
the `if track.prop in MOVE_PROPS or track.prop not in usable:` line:

```python
    for track in layer.tracks:
        if track.prop in MASK_PROPS:
            if frame is None:
                raise ValueError(
                    f"track {track.prop!r} needs the frame size to place its "
                    "band; pass frame=(width, height)"
                )
            keys = resolve(track, attack_ms=attack_ms, duration_ms=duration_ms)
            statics.append(_shine_clip(keys[0][1], frame))
            for (t0, _), (t1, v1) in zip(keys, keys[1:]):
                if t1 <= t0:
                    continue
                accel = "" if track.accel == 1.0 else f"{_fmt(track.accel)},"
                transforms.append(f"\\t({t0},{t1},{accel}{_shine_clip(v1, frame)})")
            continue
        if track.prop in MOVE_PROPS or track.prop not in usable:
            continue
```

- [ ] **Step 5: Add `shine_layer` to `effects.py`**

After `ghost_layer`:

```python
def shine_layer(
    *,
    color: str = "#FFFFFF",
    start_ms: int = 0,
    travel_ms: int = 900,
    alpha: float = 0.9,
    blur: float = 2.0,
) -> Layer:
    r"""A bright copy of the line, masked to a diagonal band that crosses it.

    An `over` layer, so it draws on top of main; everything outside the band is
    clipped away, which is what makes it read as a light rather than as a
    second line of text.

    The shine track is time="abs" -- measured from the DIALOGUE, not from each
    syllable's attack -- because the band belongs to the line, not to the
    syllable. With "ms" every token would drag its own band behind it.

    ponytail: the clip tags repeat once per syllable token, because the emitter
    builds a line as a run of per-syllable groups and hoisting them would mean
    a layer-level text prefix the emitter does not have. They are identical, so
    libass lands on the same band; it costs bytes, not correctness. Hoist if a
    file size ever matters.
    """
    return Layer("over", (
        Track("shine", ((start_ms, 0.0), (start_ms + travel_ms, 1.0)), time="abs"),
        Track("fill_color", ((0, color),)),
        Track("unsung_color", ((0, color),)),
        Track("alpha", ((0, alpha),)),
        Track("blur", ((0, blur),)),
    ))
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_shine.py tests/test_keyframes.py tests/test_ass_compile.py tests/test_effect_port_regression.py -q --no-header
```

Expected: all pass.

- [ ] **Step 7: SABOTAGE — see the band fence red**

```bash
cat > scratch/probes/cases_shine.json <<'JSON'
[
  ["band never leaves the frame at v=0", "centre = -half - skew + float(value) * (width + 2 * half + 2 * skew)", "centre = float(value) * width"],
  ["band stops moving", "centre = -half - skew + float(value) * (width + 2 * half + 2 * skew)", "centre = width / 2"],
  ["skew removed, band goes vertical", "skew = width * SHINE_SKEW", "skew = 0.0"],
  ["mask silently dropped without a frame", "raise ValueError(", "pass\n            if False: raise ValueError("],
  ["band no longer spans the frame height", "(centre + half - skew, height),", "(centre + half - skew, height // 2),"]
]
JSON
python scratch/probes/sabotage.py scripts/karaoke_styles/ass_compile.py "tests/test_shine.py" scratch/probes/cases_shine.json
```

Expected: **five red rows**. Then the `abs` mode, whose fence lives in
`keyframes.py`:

```bash
cat > scratch/probes/cases_abs.json <<'JSON'
[
  ["abs mode follows the attack after all", "if track.time == \"abs\":\n            ms = max(0, int(round(at)))", "if False:\n            ms = 0"]
]
JSON
python scratch/probes/sabotage.py scripts/karaoke_styles/keyframes.py "tests/test_shine.py" scratch/probes/cases_abs.json
```

Expected: **one red row** (`test_abs_time_ignores_the_syllable_attack`). Note
that `test_ms_time_still_follows_the_attack` is that test's control and must
stay green under this sabotage — if BOTH go red the sabotage broke the
instrument, not the claim.

- [ ] **Step 8: Full suite and commit**

```bash
python -m pytest -q --no-header --tb=short 2>&1 | tail -5
```

Expected: `792 + 16 = 808 passed`. Reconcile.

```bash
git add scripts/karaoke_styles/keyframes.py scripts/karaoke_styles/ass_compile.py scripts/karaoke_styles/effects.py tests/test_shine.py scratch/probes/cases_shine.json scratch/probes/cases_abs.json
git commit -m "feat(effects): shine, a diagonal band mask compiled to an animated clip"
```

---

## Task 6: The four presets, and the reconciliation that actually catches things

Four looks, four effects, four presets — all data, no hand-written tags. That
is the point of the vocabulary: the next preset is data, not a special case.

**Files:**
- Modify: `scripts/karaoke_styles/effects.py` (4 new entries in `EFFECTS`)
- Modify: `scripts/karaoke_styles/library.py` (4 bases, 4 style dicts, 4 `StylePreset`s)
- Modify: `scripts/karaoke_styles/preview_effects.py:46-56` (4 `PRESET_FOR_EFFECT` entries)
- Modify: `tests/test_karaoke_style_library.py:30-60` (three list literals)
- Test: `tests/test_karaoke_style_library.py`, `tests/test_preview_effects.py`

**Interfaces:**
- Consumes: `glow_layer`, `ghost_layer` (Task 4), `shine_layer` (Task 5),
  colour tracks (Task 2), `Layer` (Task 3).
- Produces: effect ids `glow`, `aberration`, `flare`, `sweep`; preset ids of the
  same four names; `library.GLOW_STYLES`, `ABERRATION_STYLES`, `FLARE_STYLES`,
  `SWEEP_STYLES`.

**Note on the name `glow`.** The effect id is `glow`; the *property* `glow` in
`FUTURE_PROPS` is a different namespace and stays refused by name. The glow
built here is made of **layers**, not of that property, which stays reserved
for a renderer that does real glow rather than stacking blurred copies.

- [ ] **Step 1: Write the failing tests**

In `tests/test_karaoke_style_library.py`, extend the three literals near the
top (keep the existing entries in their existing order — the id test asserts
the exact ordered list):

```python
MODERN_PRESET_IDS = [
    "pill",
    "focus-pull",
    "bold-highlight",
    "word-reveal",
    "word-pop",
    "typewriter",
    "glitch",
    "fly-in",
    "swing",
    "punch",
    # Layer presets: the four looks that could not exist before colour, layers
    # and a mask. Only "aberration" and "glow" cost extra events; "flare" is a
    # single main layer animating \3c, and "sweep" adds one over layer.
    "glow",
    "aberration",
    "flare",
    "sweep",
]

LAYER_PRESET_IDS = ["glow", "aberration", "flare", "sweep"]

MODERN_PRESET_EFFECT = {
    ...,                      # leave the ten existing entries untouched
    "glow": "glow",
    "aberration": "aberration",
    "flare": "flare",
    "sweep": "sweep",
}
```

and append this class to the same file:

```python
class LayerPresetTests(unittest.TestCase):
    def test_every_layer_preset_selects_its_own_effect_on_every_style(self):
        from scripts.karaoke_styles.effects import EFFECTS

        checked = 0
        for preset_id in LAYER_PRESET_IDS:
            styles = get_preset(preset_id).styles
            # Count before verdict: an empty styles dict would pass the loop.
            self.assertEqual(supported_style_keys(), set(styles))
            for key, style in styles.items():
                with self.subTest(preset=preset_id, style=key):
                    expected = "none" if key == "ad_lib" else preset_id
                    self.assertEqual(expected, style.highlight_effect)
                    self.assertIn(style.highlight_effect, EFFECTS)
                    checked += 1
        self.assertEqual(len(LAYER_PRESET_IDS) * len(supported_style_keys()), checked)

    def test_no_layer_preset_exceeds_the_measured_ceiling(self):
        from scripts.karaoke_styles.effects import EFFECTS
        from scripts.karaoke_styles.keyframes import MAX_LAYERS

        for preset_id in LAYER_PRESET_IDS:
            with self.subTest(preset=preset_id):
                self.assertLessEqual(len(EFFECTS[preset_id].layers), MAX_LAYERS)

    def test_only_aberration_and_glow_pay_for_extra_events(self):
        from scripts.karaoke_styles.effects import EFFECTS

        self.assertEqual(1, len(EFFECTS["flare"].layers))
        self.assertEqual(2, len(EFFECTS["sweep"].layers))
        self.assertEqual(2, len(EFFECTS["glow"].layers))
        self.assertEqual(3, len(EFFECTS["aberration"].layers))

    def test_no_layer_preset_needs_the_positioned_path(self):
        # The whole reason the T0 gate was run first: a ghost that forced
        # needs_layout would multiply these presets by ten events per line.
        from scripts.karaoke_styles.effects import EFFECTS

        for preset_id in LAYER_PRESET_IDS:
            with self.subTest(preset=preset_id):
                self.assertFalse(EFFECTS[preset_id].needs_layout)

    def test_flare_rests_in_a_neutral_pose(self):
        # A track's FIRST key is the resting pose, held from the Dialogue's
        # first frame. An effect opening on its animated extreme leaves the
        # whole unsung tail of the line sitting in that extreme -- measured on
        # burned frames when punch rested at 0.86 and swing at -9 degrees.
        from scripts.karaoke_styles.effects import EFFECTS

        for track in EFFECTS["flare"].main.tracks:
            with self.subTest(prop=track.prop):
                self.assertEqual(track.keys[0][1], track.keys[-1][1])
```

In `tests/test_preview_effects.py` nothing needs editing —
`test_default_showcase_covers_every_registered_effect` and
`test_every_effect_is_drawn_in_its_own_preset_style` already iterate `EFFECTS`
and will go red on their own until `PRESET_FOR_EFFECT` gains the four entries.
That is the fence for Step 5.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_karaoke_style_library.py tests/test_preview_effects.py -q --no-header --tb=line
```

Expected: `KeyError: 'Unknown karaoke style preset: glow'` and a failing
`test_existing_preset_ids_are_available`.

- [ ] **Step 3: Add the four effects**

In `scripts/karaoke_styles/effects.py`, at the end of the `EFFECTS` dict:

```python
    # ── Layer effects. Colour, layers and a mask, all as data. ────────────
    #
    # Cost, in Dialogue events per line off the layout path: flare 1 (free),
    # glow and sweep 2, aberration 3. Measured layer cost is linear in burn
    # time, so 3 is roughly 2.3x the single-layer baseline.

    # A soft halo behind the line. Made of an under layer, NOT of the `glow`
    # property -- that one stays reserved for a renderer that does real glow.
    "glow": Effect("glow", (
        glow_layer(color="#38E8FF", blur=9.0, spread=5.0, alpha=0.6),
        Layer("main"),
    )),
    # Chromatic aberration, both sides: a cyan copy left and a magenta copy
    # right, each one Dialogue, each displaced by the event's own margins off
    # the layout path. The glitch preset's one-sided shadow trick is what this
    # replaces.
    "aberration": Effect("aberration", (
        ghost_layer(-4.0, 0.0, "#00E5FF"),
        ghost_layer(4.0, 0.0, "#FF006E"),
        Layer("main"),
    )),
    # Colour flare on the attack -- and it costs no extra event at all, because
    # \3c is one of the two registers the karaoke sweep does not read from.
    # That is what the layer roles buy: the cheap answer stays available.
    # Rests at the outline's own dark, winds to hot pink on the attack, settles
    # back: the first key is the resting pose, so the unsung tail of the line
    # is not left sitting in the flare.
    "flare": Effect("flare", (Layer("main", (
        Track("outline_color", ((-60, "#0A0A12"), (0, "#FF5CA8"), (260, "#0A0A12"))),
        Track("outline", ((-60, 2.4), (0, 6.0), (260, 2.4))),
    )),)),
    # A light sweeping across the line once, as it appears. The band is an
    # over layer masked to a swept \clip band, and it crosses the FRAME rather
    # than the text, which is what keeps it off the positioned path.
    "sweep": Effect("sweep", (
        Layer("main"),
        shine_layer(color="#FFFFFF", start_ms=120, travel_ms=900, alpha=0.9),
    )),
```

- [ ] **Step 4: Add the four presets**

In `scripts/karaoke_styles/library.py`, after the `GLITCH_STYLES` block and
before the `STYLE_EFFECTS` table:

```python
# ── Layer presets ─────────────────────────────────────────────────────────
# The four looks that needed colour, layers and a mask to exist as data. Same
# face and geometry as word-pop, so the LAYER work is the only variable you are
# comparing and not a second one.

_GLOW_BASE = replace(
    _WORD_POP_BASE,
    primary_color=_c(150, 165, 190),     # waiting: cool slate, so the halo reads
    secondary_color=_c(255, 255, 255),   # sung: white inside a cyan halo
    outline_color=_c(6, 10, 18),
    highlight_effect="glow",
)
GLOW_STYLES: dict[str, KaraokeStyle] = _modern_variants(_GLOW_BASE, loud_fontsize=64)

_ABERRATION_BASE = replace(
    _WORD_POP_BASE,
    primary_color=_c(122, 134, 166),     # waiting: muted slate, so the sweep reads
    secondary_color=_c(255, 255, 255),
    outline_color=_c(8, 8, 12),
    highlight_effect="aberration",
)
ABERRATION_STYLES: dict[str, KaraokeStyle] = _modern_variants(
    _ABERRATION_BASE, loud_fontsize=64
)

_FLARE_BASE = replace(
    _WORD_POP_BASE,
    primary_color=_c(214, 214, 224),
    secondary_color=_c(255, 236, 245),
    # The flare ANIMATES this register, so the style value is only the resting
    # pose; effects.py's first key is what actually holds between attacks.
    outline_color=_c(10, 10, 18),
    highlight_effect="flare",
)
FLARE_STYLES: dict[str, KaraokeStyle] = _modern_variants(_FLARE_BASE, loud_fontsize=64)

_SWEEP_BASE = replace(
    _WORD_POP_BASE,
    primary_color=_c(158, 160, 172),
    secondary_color=_c(255, 214, 120),   # sung: warm gold under a white light
    outline_color=_c(10, 8, 6),
    highlight_effect="sweep",
)
SWEEP_STYLES: dict[str, KaraokeStyle] = _modern_variants(_SWEEP_BASE, loud_fontsize=64)
```

and four entries at the end of `PRESET_LIBRARY`, after `"punch"`:

```python
    "glow": StylePreset(
        id="glow",
        label="Glow",
        version=1,
        description="A soft cyan halo behind every line, drawn as its own layer.",
        styles=GLOW_STYLES,
    ),
    "aberration": StylePreset(
        id="aberration",
        label="Aberration",
        version=1,
        description="Two-sided chromatic aberration: a cyan copy left, a magenta copy right.",
        styles=ABERRATION_STYLES,
    ),
    "flare": StylePreset(
        id="flare",
        label="Flare",
        version=1,
        description="The rim flares hot pink on every attack and settles back — no extra events.",
        styles=FLARE_STYLES,
    ),
    "sweep": StylePreset(
        id="sweep",
        label="Sweep",
        version=1,
        description="A soft light sweeps across the line once as it appears.",
        styles=SWEEP_STYLES,
    ),
```

`_modern_variants` already gives `ad_lib` its own italic size bump but does not
touch `highlight_effect`, so every style in each preset inherits the base's.
`STYLE_EFFECTS` is the LINE-level table and stays as it is — `ad_lib` keeps
`"none"` through `resolve_effect`, which is why the test above expects `"none"`
for that key.

- [ ] **Step 5: Register the four in the preview**

In `scripts/karaoke_styles/preview_effects.py`, add to `PRESET_FOR_EFFECT`:

```python
    "aberration": "aberration",
    "flare": "flare",
    "glow": "glow",
    "sweep": "sweep",
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/test_karaoke_style_library.py tests/test_preview_effects.py tests/test_layers.py tests/test_shine.py -q --no-header
```

Expected: all pass.

- [ ] **Step 7: Full suite**

```bash
python -m pytest -q --no-header --tb=short 2>&1 | tail -5
```

Expected: `808 + 5 = 813 passed`. Report with the denominator, and re-derive:
`760 baseline + 9 (T2) + 17 (T3) + 6 (T4) + 16 (T5) + 5 (T6) = 813`. If the two
do not agree, find out why before calling anything done — a total that does not
reconcile is an opinion with a number attached.

- [ ] **Step 8: Re-run the colour probe that justifies the main-layer refusal**

The refusal is a unit test, but what makes it TRUE is a pixel measurement.
Re-run it so the claim is backed on this machine, today:

```bash
python scratch/probes/probe_colour_kf.py
```

Expected: the last line reads `control swept <N>px, so the verdicts above are
real` with N > 50, and the six rows show `\1c` animated / `\1c` static / `\1a`
as **fill DEAD** and `\3c` / `\2c` as **fill ALIVE**. If the control line says
it did not sweep, the probe is broken and no row is usable — say so rather than
reporting the column.

- [ ] **Step 9: Generate the four presets on the real job**

```bash
for p in glow aberration flare sweep; do
  mkdir -p "scratch/preset-preview/$p"
  cp jobs/publi-bet/analysis.json "scratch/preset-preview/$p/analysis.json"
  python scripts/s06_generate_ass.py --job-dir "scratch/preset-preview/$p" --preset "$p" --resolution 1920x1080
done
grep -c "^Dialogue:" scratch/preset-preview/*/output.ass
```

Expected event counts, from 52 lines on the non-layout path:
`pill 52` (baseline), `flare 52` (1 layer), `glow 104` and `sweep 104`
(2 layers), `aberration 156` (3 layers). If a count is not `52 x layers`, stop
— a layer is either missing or duplicated.

- [ ] **Step 10: Visible-text reconciliation — the fence that catches regressions**

A wrong layer either loses text or duplicates it, and the non-space character
count catches both. Extend `scratch/probes/reconcile.py`: change its preset
tuple in BOTH loops from `("fly-in", "swing", "punch")` to

```python
PRESETS = ("fly-in", "swing", "punch", "glow", "aberration", "flare", "sweep")
```

and make the second loop (the `\pos`/`\move` check) skip the non-layout ones,
since they legitimately carry neither:

```python
for preset in PRESETS:
    events = dialogues(ROOT / preset / "output.ass")
    positioned = sum(1 for e in events if "\\pos(" in e or "\\move(" in e)
    if preset in ("glow", "aberration", "flare", "sweep"):
        # Off the layout path by design -- that is what the T0 gate bought.
        print(f"{preset:>11} : {positioned} of {len(events)} positioned "
              f"(expected 0 -- non-layout path)")
        if positioned != 0:
            status = 1
        continue
    print(f"{preset:>11} : {positioned} of {len(events)} events carry \\pos or \\move")
    if positioned != len(events):
        status = 1
```

The first loop compares each preset's concatenated visible text against the
baseline and needs no change beyond the tuple — but a multi-layer preset
repeats the line once per layer, so its concatenation is `L x` the baseline.
Fix the comparison to divide out the layer count rather than to loosen it:

```python
LAYERS = {"fly-in": 1, "swing": 1, "punch": 1,
          "flare": 1, "glow": 2, "sweep": 2, "aberration": 3}

for preset in PRESETS:
    path = ROOT / preset / "output.ass"
    texts, chars = visible(path)
    n = LAYERS[preset]
    # Re-derivation, not a looser assertion: the file must be exactly n copies
    # of the baseline text, so slicing off one copy has to reproduce it AND the
    # whole thing has to be n times as long. Either alone would pass on a file
    # that lost a syllable from every copy.
    per_layer = len(chars) // n
    ok = len(chars) == n * len(base_chars) and chars[:per_layer] == base_chars
    status |= 0 if ok else 1
    print(f"{preset:>11} : {len(texts)} Dialogue events, {len(chars)} non-space "
          f"chars = {n} x {per_layer}  -> "
          f"{'IDENTICAL to baseline' if ok else 'DIFFERS'}")
```

Then run it:

```bash
python scratch/probes/reconcile.py
```

Expected: `baseline pill : 52 Dialogue lines, 1401 non-space chars (per-line
sum: 1401)`, then `IDENTICAL to baseline` for all seven presets, with
`flare 52 events / 1401 chars = 1 x 1401`, `glow 104 / 2802 = 2 x 1401`,
`sweep 104 / 2802 = 2 x 1401`, `aberration 156 / 4203 = 3 x 1401`. Exit code 0.

- [ ] **Step 11: SABOTAGE — see the reconciliation red**

A check that has never been seen red is not a check. Drop one syllable from one
layer and confirm it is caught:

```bash
python - <<'PY'
from pathlib import Path
p = Path("scratch/preset-preview/glow/output.ass")
backup = p.read_text(encoding="utf-8-sig")
lines = backup.splitlines()
for i, line in enumerate(lines):
    if line.startswith("Dialogue: 0,"):
        head, _, tail = line.partition(",,")
        lines[i] = head + ",," + tail[: len(tail) - 3]     # lose 3 characters
        print("sabotaged:", lines[i][-60:])
        break
p.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
PY
python scratch/probes/reconcile.py; echo "exit=$?"
```

Expected: `glow ... -> DIFFERS` and `exit=1`. Then restore and re-confirm green:

```bash
python scripts/s06_generate_ass.py --job-dir scratch/preset-preview/glow --preset glow --resolution 1920x1080
python scratch/probes/reconcile.py; echo "exit=$?"
```

Expected: `IDENTICAL to baseline` for all seven and `exit=0`.

- [ ] **Step 12: Measure the burn — "seconds, not minutes" is a measurement**

The 3-layer cost was *interpolated* in the spec (between the measured 2-layer
1.65x and 4-layer 2.99x rows). Measure it directly rather than trusting the
interpolation:

```bash
for p in pill flare glow sweep aberration; do
  n=$(grep -c "^Dialogue:" "scratch/preset-preview/$p/output.ass")
  s=$( { /usr/bin/time -f "%e" ffmpeg -y -loglevel error -f lavfi -t 60 \
        -i color=c=black:s=1920x1080:r=30 -vf "ass=output.ass" \
        -c:v libx264 -preset ultrafast -f null - ; } 2>&1 \
        | tail -1 )
  echo "$p: $n events, ${s}s for 60s of 1920x1080"
done
```

If `/usr/bin/time` is unavailable on this shell, use the Python fallback, which
also prints the realtime multiple:

```bash
python - <<'PY'
import subprocess, time
from pathlib import Path
for preset in ("pill", "flare", "glow", "sweep", "aberration"):
    path = Path("scratch/preset-preview") / preset / "output.ass"
    n = sum(1 for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.startswith("Dialogue:"))
    start = time.time()
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", "60",
         "-i", "color=c=black:s=1920x1080:r=30", "-vf", "ass=output.ass",
         "-c:v", "libx264", "-preset", "ultrafast", "-f", "null", "-"],
        cwd=path.parent, check=True,
    )
    secs = time.time() - start
    print(f"{preset:>11}: {n:4d} events  {secs:6.2f}s for 60s @1920x1080  "
          f"({60 / secs:5.1f}x realtime)")
PY
```

Expected shape, from the measured layer-cost table (1 layer 4.5s, 2 layers
7.4s, 4 layers 13.4s for 60s): `pill` and `flare` near 4.5s, `glow` and `sweep`
near 7.4s, `aberration` between the 2- and 4-layer rows — this is the number
the spec interpolated, so **write down what it actually measures** rather than
the interpolation. Scale to a 3-minute song by x3 and confirm every preset is
still tens of seconds, not minutes. If `aberration` lands above the 4-layer row
despite having 3 layers, say so — that would mean cost is not linear after all
and the ceiling needs revisiting.

- [ ] **Step 13: Watch the four looks**

```bash
python scripts/karaoke_styles/preview_effects.py --job jobs/publi-bet glow aberration flare sweep
```

Expected: `ok -> .../scratch/effects_preview.mp4  (..., 4 effects on 4 lines of
jobs/publi-bet)`. Open it and confirm each look reads as intended — a halo, a
two-sided colour split, a rim that flares on the attack, and a light crossing
the line. A still frame is not enough for `sweep`: use
`python scratch/probes/strip.py` or scrub the video, because a mask that never
moves looks identical to a working one in a single frame. That is the exact
failure mode every probe in `scratch/probes/` hit at least once.

- [ ] **Step 14: Commit**

```bash
git add scripts/karaoke_styles/effects.py scripts/karaoke_styles/library.py scripts/karaoke_styles/preview_effects.py tests/test_karaoke_style_library.py scratch/probes/reconcile.py
git commit -m "feat(styles): glow, aberration, flare and sweep presets, built from layers"
```

- [ ] **Step 15: Record the execution notes**

Append an `## Execution notes` section to this plan file with, at minimum:

- the final suite total **with its denominator** and the reconciliation
  arithmetic (`760 + 53 = 813`, or whatever it actually is);
- every fence that was seen red, and any that did **not** go red on the first
  try and had to be rewritten — the previous plan had two, and hiding them
  would make the next plan repeat them;
- the burn times **measured** in Step 12, labelled as measured, next to the
  spec's interpolated 2.3x estimate;
- the reconciliation line for all seven presets with denominators;
- anything the plan got wrong. Every probe written during the research was
  wrong at least once before it was right; assume this plan is too, and write
  down where.

```bash
git add docs/superpowers/plans/2026-08-20-camadas-cor-e-mascara.md
git commit -m "docs: execution notes for the layers, colour and mask plan"
```

---

## Self-review against the spec

| spec section | task |
|---|---|
| T0 gate: offset without `\pos` | Task 0 — **run, GO on both axes**, mapping recorded |
| Extract `ass_emit.py` before anything new | Task 1 |
| Colour vocabulary, `#RRGGBB`, not interpolated in Python | Task 2 |
| Value-preserving `resolve()` | Task 2 |
| `Effect(id, layers)`, three roles, one `main` | Task 3 |
| `fill_color` refused on `main` (fence 1) | Task 3, Step 9 sabotage |
| Layer numbering, `main`-only = Layer 0 (fence 2) | Task 3, Step 9 sabotage |
| Ceiling of 4 (fence 3) | Task 3, Step 9 sabotage |
| Non-`main` layers carry `\k`, not `\kf` | Task 3, `compile_layer(karaoke=...)` |
| A layer is one more Dialogue; L x 52 vs L x 538 | Task 3, `build_line_events` |
| `glow_layer` / `ghost_layer` as constructors, not roles | Task 4 |
| `shine` only, frame coordinates, `\clip` + `\t(\clip)` | Task 5 |
| New presets, data only | Task 6 |
| Visible-text reconciliation, 52 lines / 1401 chars | Task 6, Steps 10–11 |
| Burn time measured, not assumed | Task 6, Step 12 |
| Four looks demonstrable through `preview_effects.py --job jobs/publi-bet` | Task 6, Step 13 |
| `FUTURE_PROPS` stay refused by name | untouched — Task 2 leaves `FUTURE_PROPS` alone |
| Out of scope: `\p1`, `\frx`/`\fry`, `\fax`/`\fay`, `\fsp`, `\kt`, generic `\clip`, GPU compiler | no task adds any of them |
| `typewriter` stays the single hand-written `TextEffect` | Task 3 leaves it as a `TextEffect` |

**One place this plan corrects the spec.** The spec says fence 2's sabotage
makes "the 28-token golden go red". It does not: the golden pins the token
*text*, which contains no Dialogue `Layer` field. Task 3 Step 9 documents this
and puts the fence where it actually bites — `layer_numbers` directly, plus the
emitted `Dialogue: 0,` prefix end to end.

**Two open risks carried from the spec, unresolved by design.**

- Glow per syllable on the layout path with 3 layers is 1614 events, a cost
  *interpolated* between the measured 2-layer and 4-layer rows at roughly 2.3x
  baseline. No preset here combines a layer effect with a layout effect, so the
  interpolation is not load-bearing yet. Measure before shipping one that does.
- `shine` in frame coordinates will look wrong on a very short line. Accepted:
  the band is soft and wide, and measuring the line would force any preset
  wanting shine onto the positioned path.

---

## Execution notes

Task 6 executed 2026-08-20 on `mvp-pipeline-runner`, system python 3.11.9,
ffmpeg 8.1 (Gyan build), Windows 11. Reference job `jobs/publi-bet`.

### Suite total, with denominators and both reconciliations

Entering Task 6: **819 passed, 218 subtests passed, 0 failed** (measured with
the pre-existing GPU-spike WIP present, which is the real tree).
Leaving Task 6: **824 passed, 292 subtests passed, 0 failed**.

Task delta: **+5 tests** (all in `tests/test_karaoke_style_library.py`,
44 -> 49) and **+74 subtests**, reconciled per file rather than asserted:

| file | subtests before | after | delta |
|---|---|---|---|
| `tests/test_karaoke_style_library.py` | 32 | 90 | +58 |
| `tests/test_preview_effects.py` | 20 | 28 | +8 |
| `tests/test_layers.py` | 31 | 39 | +8 |
| every other file | unchanged | unchanged | 0 |
| **total** | **218** | **292** | **+74** |

The +58 re-derives as 46 new (4 presets x 9 style keys = 36, plus 4 + 4 + 2)
plus 12 from three existing loops that now iterate 14 presets instead of 10.
The two +8 rows are the four new effects entering two loops that iterate
`EFFECTS`. Before/after per file measured by stashing only the four source
files, not by estimating.

**Whole-plan reconciliation.** Session baseline before Task 1 was
760 passed / 165 subtests. Per-task deltas T2 +9, T3 +22 then +7, T4 +6,
T5 +15, T6 +5:

    760 + 9 + 22 + 7 + 6 + 15 = 819   (entering T6 -- matches the measurement)
    819 + 5 = 824                     (leaving T6 -- matches the measurement)

**The total closes on both.**

> The brief predicted `808 + 5 = 813` and re-derived it as
> `760 + 9 + 17 (T3) + 6 + 16 (T5) + 5`. That arithmetic is stale: T3 shipped
> +22 then +7 (= +29, not 17) and T5 shipped +15, not 16. The brief was
> extracted before those two tasks finished. The measured tree is the
> authority; nothing was adjusted to make it agree.

### What the plan got wrong

Four things, all found by measuring rather than by reading.

**1. Step 10's re-derivation assumed the wrong file layout.** The brief's
`chars[:per_layer] == base_chars` treats a multi-layer file as `L` whole
copies of the baseline concatenated. It is not: `ass_emit` writes a line's
layers consecutively, so the event order is
`line1/layer0, line1/layer1, line2/layer0, ...` and event `j` belongs to layer
`j % L`. Run as written, the check called **glow, sweep and aberration
DIFFERS** while their character counts were exactly `L x 1401` -- a false
negative, and the same shape of error every probe in `scratch/probes/` has hit:
a verdict over a population that could not have matched.

Fixed by reconciling **per layer** instead, which is strictly stronger than the
brief's version rather than looser: every layer's own visible text is compared
to the baseline separately (so a syllable lost from one layer only is still
caught), **and** the total must still be exactly `L x 1401` (so a duplication
present in every copy is caught too). Either check alone would pass a file the
other rejects.

**2. The brief's Step 1 test expected `"none"` for the `ad_lib` style key.**
`_modern_variants` copies the base's `highlight_effect` to every key, so
`style.highlight_effect` is the preset's effect on all nine keys; the `"none"`
for `ad_lib` comes from `STYLE_EFFECTS` through `resolve_effect`, which is a
different table. The brief's own Step 4 note asserts both, which cannot both
hold. The existing `test_each_modern_preset_selects_its_own_effect` already
pins the single-value-across-all-styles behaviour, so the new test was written
to match it (`preset_id` for every key, `ad_lib` included).

**3. Two cardinality guards the brief did not mention had to move.**
`test_every_modern_preset_covers_all_style_keys` hard-codes
`assertEqual(10, len(MODERN_PRESET_IDS))` and
`test_no_other_preset_takes_the_layout_path` hard-codes
`assertEqual(7, len(others))`. Both went red on Step 6 and were updated to 14
and 11. These are the "count before verdict" guards doing their job -- they are
supposed to fail when the population changes.

**4. Layer cost is NOT linear in the layer count.** See Step 12 below.

### Step 8 -- colour probe, re-run on this machine

    sweep front (rightmost unsung column) at t=(0.15, 0.45, 0.75)

      plain sweep (control)              [324, 461, 598]  moved= +274  fill ALIVE
      sweep + \t on \1c (fill colour)    [324, -1, -1]  moved= -325  fill DEAD
      sweep + static \1c override        [-1, -1, -1]  moved=   +0  fill DEAD
      sweep + \t on \3c (outline)        [324, 461, 598]  moved= +274  fill ALIVE
      sweep + \t on \2c (unsung)         [324, 461, 598]  moved= +274  fill ALIVE
      sweep + \t on \1a (fill alpha)     [324, 461, -1]  moved= -325  fill DEAD

      control swept 274px, so the verdicts above are real

Control swept 274px (> 50), so the column is usable. `\1c` animated, `\1c`
static and `\1a` are dead; `\3c` and `\2c` are alive. The main-layer refusal
stands, and `flare` animating `\3c` on the main layer is legitimate.

### Step 9 -- event counts against `52 x layers`

52 lines, all four off the positioned path:

| preset | layers | predicted | measured |
|---|---|---|---|
| pill (baseline) | 1 | 52 | **52** |
| flare | 1 | 52 | **52** |
| glow | 2 | 104 | **104** |
| sweep | 2 | 104 | **104** |
| aberration | 3 | 156 | **156** |

Every count is exactly `52 x layers`. The `pill` baseline file was confirmed
current by regenerating it into a scratch directory and comparing: byte
identical (sha256 `75a8e3aaf49b6706...`), so the baseline is not stale.

### Step 10 -- visible-text reconciliation, with denominators

    baseline  pill : 52 Dialogue lines, 1401 non-space chars (per-line sum: 1401)
         fly-in : 538 Dialogue events, 1401 non-space chars = 1 x 1401; 1 of 1 layers match the 1401-char baseline  -> IDENTICAL to baseline
          swing : 538 Dialogue events, 1401 non-space chars = 1 x 1401; 1 of 1 layers match the 1401-char baseline  -> IDENTICAL to baseline
          punch : 538 Dialogue events, 1401 non-space chars = 1 x 1401; 1 of 1 layers match the 1401-char baseline  -> IDENTICAL to baseline
           glow : 104 Dialogue events, 2802 non-space chars = 2 x 1401; 2 of 2 layers match the 1401-char baseline  -> IDENTICAL to baseline
     aberration : 156 Dialogue events, 4203 non-space chars = 3 x 1401; 3 of 3 layers match the 1401-char baseline  -> IDENTICAL to baseline
          flare :  52 Dialogue events, 1401 non-space chars = 1 x 1401; 1 of 1 layers match the 1401-char baseline  -> IDENTICAL to baseline
          sweep : 104 Dialogue events, 2802 non-space chars = 2 x 1401; 2 of 2 layers match the 1401-char baseline  -> IDENTICAL to baseline
         fly-in : 538 of 538 events carry \pos or \move
          swing : 538 of 538 events carry \pos or \move
          punch : 538 of 538 events carry \pos or \move
           glow : 0 of 104 positioned (expected 0 -- non-layout path)
     aberration : 0 of 156 positioned (expected 0 -- non-layout path)
          flare : 0 of 52 positioned (expected 0 -- non-layout path)
          sweep : 0 of 104 positioned (expected 0 -- non-layout path)

Exit code 0. **11 layers compared, 1401 characters each, 15411 characters
total, against a 1401-character baseline that re-derives against its own
per-line sum.** No preset is judged on an empty set.

### Step 11 -- SABOTAGE, seen RED twice and green again

**Sabotage A (the brief's): 3 characters off the first `Dialogue: 0,` line of
glow.**

    sabotaged: \bord5\1c&HFFE838&\2c&HFFE838&\3c&HFFE838&\alpha&H66&\be1\k1
           glow : 104 Dialogue events, 2867 non-space chars = 2 x 1401; 1 of 2 layers match the 1401-char baseline  -> DIFFERS
                  layer 0: first divergence at char 17: baseline 'poVaivaivaiOlhaogolpenostoriesPrintdegre' vs '{\blur9\bord5\1c&HFFE838&\2c&HFFE838&\3c'
    exit=1

RED, and it names the preset and the layer. (The character count went *up*,
to 2867: trimming the tail broke a closing `}`, so tag text leaked into the
visible-text extraction. The check catches it on both axes regardless.)
Restored by regenerating: all seven `IDENTICAL`, `exit=0`.

**Sabotage B (added): one character off the LAST layer, aberration layer 2.**
This is what the per-layer rewrite bought -- the brief's version could only
have seen it as a total-length change, without localising it.

    before tail: f23}pa{\k10}{\be1\kf1}po
     after tail: kf23}pa{\k10}{\be1\kf1}p
     aberration : 156 Dialogue events, 4202 non-space chars = 3 x 1401; 2 of 3 layers match the 1401-char baseline  -> DIFFERS
                  layer 2: first divergence at char 18: baseline 'oVaivaivaiOlhaogolpenostoriesPrintdegree' vs 'VaivaivaiOlhaogolpenostoriesPrintdegreen'
    exit=1

RED, naming layer 2. Restored by regenerating: all seven `IDENTICAL`, `exit=0`.

**A third sabotage attempt was a no-op and was discarded, not counted.** It
tried `text.replace("papo", "pap")`, but the emitter splits that word across
tag groups (`pa{\k10}{\be1\kf1}po`), so the substring never occurred and
nothing changed. The probe stayed green -- correctly, since nothing had been
sabotaged. Recorded because "green after a sabotage" is worthless unless the
sabotage is confirmed to have landed.

### Step 12 -- burn time, MEASURED (and where it contradicts the spec)

60s of 1920x1080 through `ffmpeg -vf ass=... -c:v libx264 -preset ultrafast
-f null -`, best of 2-3 runs, this machine:

| preset | layers | events | **measured** 60s burn | x baseline | 3-min song |
|---|---|---|---|---|---|
| pill | 1 | 52 | **4.12s** | 1.00x | ~12.4s |
| flare | 1 | 52 | **4.51s** | 1.09x | ~13.5s |
| sweep | 2 | 104 | **4.95s** | 1.20x | ~14.8s |
| aberration | 3 | 156 | **11.59s** | **2.81x** | ~34.8s |
| glow | 2 | 104 | **12.82s** (12.90s on a 3-run repeat) | **3.11x** | ~38.5s |

Every preset is **tens of seconds for a 3-minute song, not minutes**.

**The 3-layer number the spec interpolated: interpolated ~2.3x, measured
2.81x.** The spec interpolated between its measured 2-layer (1.65x, 7.4s) and
4-layer (2.99x, 13.4s) rows. The direct measurement is higher than the
interpolation but still below the 4-layer row, so the ceiling of 4 is not
threatened. Recorded as measured, beside the interpolation it replaces.

**The finding the spec's model does not survive: cost is not a function of the
layer count.** `glow` has TWO layers and burns *slower* than `aberration`'s
three (12.82s vs 11.59s), and `sweep` has two layers and burns at almost the
1-layer baseline (4.95s). Controls, same file, same 104 events, only one tag
changed:

| control | measured | reading |
|---|---|---|
| glow as shipped | 12.90s | -- |
| glow, `\blur9` -> `\blur0` | **8.20s** | the blur alone costs 4.7s |
| glow, `\bord5` -> `\bord0` (blur kept) | **11.17s** | the wide outline costs 1.7s |

Stripped of its blur, glow's two layers cost 8.20s = **2.0x** the 4.12s
baseline, and aberration's three plain layers cost 11.59s = **2.81x**. So
*plain* layers are roughly linear, and what a layer DRAWS is the dominant
term: a gaussian blur over a wide outline adds more than a whole extra layer,
while a `\clip`-masked band costs almost nothing because the rasteriser culls
most of it. The comment in `effects.py` was corrected to say this; budget by
what the layer draws, not by counting layers.

### Step 13 -- watching the four looks

`preview_effects.py --job jobs/publi-bet glow aberration flare sweep` ->
`scratch/effects_preview.mp4`, 74.8s, 4 effects on 4 lines. Each look was
checked with a measurement as well as a frame, because a still cannot tell a
working animation from a stuck one.

- **glow** -- reads as intended: a soft cyan halo around the whole line, white
  sung text inside it, cool slate unsung. The halo sits exactly behind the
  line (its under layer is ASS Layer 0, main is Layer 1, so no collision).
- **flare** -- reads as intended, and *pulses*. Counting hot-pink rim pixels
  across 53 frames of one line gives nine clean spikes, one per syllable
  attack (peak 2218px), resting at 35-59px between them. That is the
  resting-pose claim confirmed on burned pixels rather than in tags.
- **sweep** -- reads as intended, and *moves*. Measured by burning the over
  layer ALONE over black, so the band is the only ink in frame and nothing
  else can be mistaken for it: the band spans x 409..664 at +0.50s and
  x 751..912 at +0.70s, a **295px centre travel**. Two controls: the same
  events with `\t` stripped produce **no ink at any of 6 instants** (the
  resting clip sits off-frame at x -257..-1, so the band exists only while
  animating); and the band shows ink at only 2 of 6 sampled instants because
  it is only over the text for part of its crossing, which the geometry
  predicts. A first attempt measured the band by subtracting a control frame
  from the full preview and taking the x-centroid of what brightened; that was
  **discarded as contaminated** -- the karaoke fill brightens the same pixels
  as it sings, the centroid was non-monotonic, and its "MOVING" verdict could
  not be attributed to the band.
- **aberration** -- **does NOT render as designed.** See below.

### Open defect: aberration's two ghosts collide

Both ghosts are `under` layers, and `Effect.layer_numbers` maps **role** to the
ASS Layer field (under = -1, main = 0, over = +1, translated to base 0). Two
`under` layers therefore receive the **same** ASS Layer number. libass treats
two same-layer unpositioned events that overlap in time and space as a
collision and pushes the second onto its own row, so the magenta copy renders
about 64px **above** the line instead of 4px to the right of it. The cyan copy
is correct.

Ruled out first: the emitted margins are right. The two ghosts carry
`MarginL/MarginR/MarginV` of `92/100/195` and `100/92/195` -- identical
vertical margin, horizontal margins swapped by 8px, exactly the requested
`dx=+-4, dy=0`. The displacement is not ours.

Control, same three events burned twice, only the Layer field changed:

| variant | magenta ink rows | span |
|---|---|---|
| as emitted (both ghosts on Layer 0) | **474..527** | 53px |
| second ghost moved to Layer 2 | **538..591** | 53px |

Same glyph span both times; a 64px shift caused purely by the Layer field, and
538..591 is the main line's own row. That is the collision, confirmed.

`aberration` is the first effect with two layers sharing a role, which is why
nothing caught this earlier -- `glow` (under + main) and `sweep` (main + over)
each have at most one layer per role and render correctly. The fix belongs in
`keyframes.layer_numbers` (rank within a role, not by role alone); it would
leave `glow` at (0,1) and a main-only effect at (0,) -- so the Task 3 fences
still hold -- and change only `aberration` from (0,0,1) to (0,1,2). It was
**not applied here**: it changes Task 3's shipped contract, and a measurement
that disagrees with the plan is a finding to report, not an expectation to
adjust. The defect is recorded in a comment on the effect itself.
