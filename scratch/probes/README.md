# Probes and harnesses

Throwaway by intent, kept because the design spec leans on what they measure
and on how they measure it. Not part of the pipeline; nothing imports them.

| script | what it answers |
|---|---|
| `probe_tags.py` | which ASS override tags this libass actually draws (48/48) |
| `probe_colour_kf.py` | whether animating a colour kills the \kf sweep. **Aborts if the control does not sweep** -- it reported a working fill as dead once by measuring the wrong edge |
| `probe_layers.py` | burn cost of stacking N layers per syllable |
| `sabotage.py` | negative-control harness: patch one anchor, run tests, restore. Treats "no tests ran" as a void verdict, not a pass |
| `reconcile.py` | visible-text reconciliation of generated .ass against the 52-line / 1401-char pill baseline, across all seven motion **and** layer presets. A multi-layer preset repeats the line once per layer, so it checks EVERY layer's own text separately (11 layers, 1401 chars each) **and** that the total is exactly `L x 1401` -- either alone would pass a file the other rejects. First draft sliced off the leading `len/L` characters expecting L whole copies of the file; measured, `ass_emit` interleaves a line's layers instead (event `j` is layer `j % L`), so that draft called three working presets DIFFERS |
| `strip.py` | contact sheet across one syllable's animation window |
| `peak.py` | pixel excursion an effect actually delivers |
| `rowbands.py` | ink row bands in a burned frame (line spacing) |
| `montage.py` | one frame per effect, stacked |
| `probe_margins.py` | T0 gate: can an event be displaced without \pos, through its own Margin fields? (yes, both axes) |
| `probe_shine.py` | does libass actually ANIMATE a `\clip` band via `\t`? Caught a real defect: the first `_shine_clip` drew a skewed VECTOR drawing that rendered but never moved under `\t` on this libass; a plain rectangular `\clip(x1,y1,x2,y2)` does animate. `_shine_clip` was rewritten as the rectangle as a result. Static-endpoint control proves "frozen" wasn't just "always off-frame" |

Every one of these was wrong at least once before it was right, always the
same way: a verdict rendered over a situation where the measured thing could
not have appeared. Check the control before trusting the column.
