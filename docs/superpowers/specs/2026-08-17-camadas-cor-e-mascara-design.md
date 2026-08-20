# Layers, colour and mask — design

**Goal:** give the effect language three things it cannot say today — colour,
layers, and a mask — so glow, chromatic aberration, colour flare and a light
sweep become expressible as data, and any preset can reach for them.

**Not a goal:** flagship presets built from hand-written tags. The point of the
vocabulary is that the next preset is data, not a special case.

---

## What the research established

All of it measured on this machine, through the same ffmpeg/libass path the
pipeline burns with. The numbers are load-bearing: three of the decisions below
are shaped by them and would be wrong without them.

### Every tag probed renders — 48 of 48

Each candidate tag was burned and compared pixel-for-pixel against a reference
frame. Everything renders, including the ones no shipped effect uses: `\clip`
vector masks **animated by `\t`**, drawing mode `\p1`, 3D rotation `\frx`/`\fry`,
shear `\fax`/`\fay`, letter spacing `\fsp`, and `\kt` (absolute karaoke time).

**Earlier runs of that probe said 40, then 43.** Every "unsupported" reading was
a defect in the probe, not a gap in libass: a shadow drawn black on black,
`\fade` sampled at an instant where it is fully opaque, `\iclip` masking a region
containing no text, `\q` on a one-word line that never wraps. Each was a verdict
rendered over a situation where the tag could not have mattered. Only the 48/48
is a measurement.

### Animating the fill colour kills the karaoke sweep

`\kf` sweeps SecondaryColour → PrimaryColour, so a colour track writing to `\1c`
writes to the register the fill reads from. Measured by locating the sweep front
(rightmost *sung* column) at three instants:

| effect animates | karaoke fill |
|---|---|
| `\1c` (fill colour) | **dies** |
| `\1c` set statically | **dies** |
| `\1a` (fill alpha) | **dies** |
| `\3c` (outline) | survives |
| `\2c` (unsung) | survives |

The control swept 274px, which is what makes the rest of the column meaningful.
The first version of that probe measured the rightmost *unsung* column, which
sits at the text's right edge from first frame to last — it reported the working
control as a dead fill.

**This is the constraint the layer roles exist to enforce.**

### Layer cost is linear, and 4 is the affordable ceiling

60s of 1920×1080 @30, from a real 538-event generated file:

| layers | events | burn | vs realtime |
|---|---|---|---|
| 1 | 538 | 4.5s | 13.5× |
| 2 | 1076 | 7.4s | 8.1× |
| 4 | 2152 | 13.4s | 4.5× |
| 8 | 4304 | 25.7s | 2.3× |
| 16 | 8608 | 49.4s | 1.2× |

No knee. 4 layers keeps a 3-minute song at roughly 40s of burn; 16 is where the
pipeline's "render time stays in seconds, not minutes" constraint breaks.

---

## Gate: can a layer be offset without `\pos`?

A `ghost` layer needs displacement — that is what chromatic aberration is made
of. On the layout path every syllable already carries `\pos`, so it is free.
**On the non-layout path the line has no `\pos` at all**: position comes from
alignment plus margins. Displacing it would need `\pos`, which would need the
line measured, which would turn any preset wanting glitch into a layout preset
and multiply its event count by ten.

The candidate is the Dialogue event's **own** `MarginL`/`MarginR`/`MarginV`
fields, which exist in the format and override the style's.

| measured result | consequence |
|---|---|
| offsets on both axes | Build as written. Ghost is cheap on both paths. |
| vertical only | Off the layout path, glitch gets vertical displacement only; horizontal becomes layout-exclusive. |
| no offset | **Ghost/glitch becomes layout-exclusive.** T4 shrinks and the glitch preset is expensive. |

Half of T4 depends on the answer. It costs one render to find out, so it is
measured before T4 is designed in detail, not assumed.

---

## Data model

`Effect(id, tracks)` becomes `Effect(id, layers)`, with three roles and no more:

| role | z | carries `\kf` | fill colour |
|---|---|---|---|
| `main` | 0 | **yes**, exactly one per effect | **refused** — kills the sweep |
| `under` | <0 | no | free |
| `over` | >0 | no | free |

`glow` and `ghost` are **not** engine roles. They are constructors —
`glow_layer(color, blur, spread)`, `ghost_layer(dx, dy, color)` — that build an
`under` layer with the right tracks. Role is the axis the compiler needs in order
to *refuse*; the rest is authoring convenience, and convenience should not become
an engine concept.

Non-`main` layers carry `\k`, not `\kf`. They need the same clock (karaoke tags
draw no glyph, they only advance time) but no sweep — and because they have no
sweep, the `\1c` prohibition does not apply to them. That is precisely why colour
flare and glow live outside `main`: the two rules compose instead of fighting.

### New vocabulary

- **Colour:** `fill_color`, `outline_color`, `shadow_color`, `unsung_color`
  → `\1c \3c \4c \2c`; alphas `fill_alpha`, `outline_alpha`, `shadow_alpha`
  → `\1a \3a \4a`. Written as `"#RRGGBB"`, converted at emission.
  **Colour is not interpolated in Python** — libass's `\t` interpolates it, so
  only the endpoints are emitted.
- **Mask:** `shine` only, whose value is the normalised position of a diagonal
  band (`0.0` before the left edge, `1.0` past the right). Compiles to `\clip`
  plus `\t(\clip(...))`. Generic vector clip is a large vocabulary in exchange
  for one look; it stays out until something needs it.

`resolve()` currently coerces every value with `float()`. With colour the value
is no longer always numeric, so it preserves the value and only the *time* stays
arithmetic.

---

## Compiler

**A layer is one more Dialogue, on the path that already exists.**

- Non-layout path (one Dialogue per line): a layer costs one Dialogue **per
  line** — `L × 52` on the reference job.
- Layout path (one Dialogue per syllable): a layer costs one Dialogue **per
  syllable** — `L × 538`.

So layers are cheap on non-layout presets and expensive on layout presets. The
ceiling of 4 is set by the worse case.

**`Layer` field numbering, chosen to protect what already works.** Roles carry
offsets `under=-1, main=0, over=+1`, and the whole set is translated so its
minimum is 0. A `main`-only effect yields `{0}` → **Layer 0**, byte for byte what
ships today, so the 28-token golden stays valid with no hand-written exception.
An `under`+`main` effect yields `under=0, main=1`.

**`shine` works in frame coordinates, not text coordinates.** The band needs to
know where to sweep. On the layout path each syllable's box is known; on the
non-layout path the line's extent is not known without measuring, and measuring
there would force any preset wanting shine to become a layout preset. So the band
crosses the **frame width**. Visually near-identical — the line is centred and
occupies most of the width — and it keeps `shine` available on both paths without
forcing `needs_layout`.

---

## Where the code goes

`_build_karaoke_text`, `_build_layout_events` and `_effect_capability_gaps` move
out of `s06_generate_ass.py` (1055 lines) into a new module, **before** anything
new is added. They are already imported from outside; `s06` goes back to being
what its name says — read `analysis.json`, pick a preset, call the emitter, write
the file and the events.

**The module is `scripts/ass_emit.py`, not `scripts/karaoke_styles/emit.py`.**
Measured: `karaoke_styles` imports `review_wizard` in exactly zero places — it is
a leaf. The emitter needs `build_word_highlight_segments`, `classify_line_timing`
and `gap_should_be_absorbed`, all from `review_wizard`, so putting it inside
`karaoke_styles` would drag the review pipeline into the one clean package in the
tree and invert the dependency direction. A render layer sits *above* both the
style vocabulary and the timing analysis, and the pipeline stage sits above it.

Moving with them, because they are used nowhere else in `s06` and belong with the
emitter: `_escape_ass_text`, `_quantize_kf_durations_to_centiseconds`.
`SIDE_MARGIN_RATIO` and `DESIGN_HEIGHT` are also read by `preview_effects.py`, so
they move too and `s06` imports them back.

**Known wart, not addressed here:** `preview_effects.py` lives inside
`karaoke_styles` but is a development tool that imports a pipeline stage. After
the extraction it imports `ass_emit` instead, which is better but still a leaf
package reaching outward. Moving it to `scripts/preview_effects.py` is a `git mv`
plus import fixes; it is out of scope for this spec.

| file | now | after |
|---|---|---|
| `keyframes.py` | 74 | + `Layer`, roles, colour and `shine` props, value-preserving `resolve` |
| `ass_compile.py` | 161 | + colour table, `\clip` emission, `compile_layer()` |
| `effects.py` | 260 | 10 effects gain `(Layer("main", ...),)`; + layer constructors |
| `s06_generate_ass.py` | 1055 | **shrinks** — three functions and two helpers leave |
| `ass_emit.py` | *(new)* | the three functions, now iterating layers |
| `library.py` | 2538 | new presets, data only |
| `preview_effects.py` | 376 | import source changes; nothing structural |

---

## Build order

```
T0  GATE: offset a layer without \pos (Dialogue margin fields)
     |
     +-- T1  Extract ass_emit.py (pure move, golden proves it)
     |        |
     |        +-- T2  Colour tracks
     |        |
     |        +-- T3  Layers: roles, numbering, ceiling of 4
     |                 |
     |                 +-- T4  glow_layer / ghost_layer
     |                 +-- T5  shine (animated \clip)
     |                          |
     +--------------------------+-- T6  New presets + reconciliation
```

`ass_emit.py` comes out **before** anything new, because it is a pure move the
golden verifies in seconds, and everything after it lands in a file that fits in
one head. Doing it last would mean moving already-modified code, with the golden
testing two changes at once.

---

## Fences

Every fence gets a prescribed sabotage and must be seen red before it counts.
Three are mandatory, because each covers a failure that is otherwise only visible
by watching the video:

1. **`fill_color` on a `main` layer is refused by name.** Sabotage: allow it, and
   watch the sweep die. The test locates the sweep front, and **the control must
   move first** — the research probe reported a working fill as dead by measuring
   the wrong edge, and a control that cannot fail would have let that stand.
2. **A `main`-only effect emits `Layer 0`.** Sabotage: number from 1, and watch
   the 28-token golden go red.
3. **The 4-layer ceiling.** Sabotage: raise to 5 and watch the error not come.
   Plus one burn-time measurement as a cost fence.

And the one that actually catches regressions, which is not a unit test:
**visible-text reconciliation** against the baseline, as in the 538-of-538 check.
A wrong layer either loses text or duplicates it, and the non-space character
count catches both.

Report counts with denominators. A check over an empty set is a universal green.

---

## Out of scope, deliberately

Probed, and they **render**, but none of the four chosen looks needs them. They
arrive when a preset asks, not before:

`\p1` (shapes, bars, particles) · `\frx`/`\fry` (3D rotation) · `\fax`/`\fay`
(shear) · `\fsp` (animated tracking) · `\kt` (absolute karaoke time, filling out
of text order) · generic vector `\clip` — only `shine`.

Also still out: the **GPU compiler** and the `FUTURE_PROPS` (`glow`, `gradient`,
`motion_blur`, `audio`), which stay refused by name. Worth noting that the glow
being built here is made of **layers**, not of the `glow` prop — that one stays
reserved for a renderer that does real glow rather than stacking blurred copies.

`typewriter` remains the single hand-written `TextEffect`. Nothing here changes
that.

---

## Open risks

- **Glow per syllable on the layout path with 3 layers is 1614 events.** That
  count falls between two measured rows (2 layers = 1076 events at 1.65×
  baseline, 4 layers = 2152 at 2.99×), so the cost is *interpolated* at roughly
  2.3× baseline and 5.8× realtime — not measured. It fits, but a preset wanting
  both glow and `fly-in` has spent most of the budget on one effect. Worth
  measuring directly before shipping such a preset rather than trusting the
  interpolation.
- The T0 gate can shrink T4. That is the point of running it first.
- `shine` in frame coordinates will look wrong on a very short line, which
  occupies little of the frame width. Acceptable: the band is soft and wide.
