# Section→style maps: duplication and silent divergence

Found on 2026-08-14 while adding a single section label (`[Rap]`) end to end.
Adding one label required edits in four places; a task shipped "complete" while
the feature silently did nothing, and was caught only by looking at the
generated ASS by hand. This note records the surface so the next person does
not re-derive it.

## The surfaces

Measured at commit `39542f76`, on a clean worktree.

| Surface | Location | Entries | Live? |
| --- | --- | --- | --- |
| `SECTION_TO_STYLE` | `scripts/s03b_lyrics_align.py` | 56 | yes — decides the canonical label |
| `SECTION_TO_STYLE` | `scripts/karaoke_styles/library.py` | 57 | no — `resolve_section` has only test callers |
| `LYRICS_SECTION_TO_STYLE` | `scripts/karaoke_styles/library.py` | 56 | no — same |
| `SECTION_TO_STYLE` | `scripts/s05_analyze.py` | 15 | **yes — decides the ASS style** |
| `STYLE_DEFAULTS` | `scripts/karaoke_styles/library.py` | 9 | yes — source of the stage whitelists |
| `STYLE_DEFAULTS` | `scripts/s05_analyze.py` | 9 | yes — decides colour/effect |
| `VALID_STYLES` | `tests/test_pipeline_stage_contracts.py` | 8 | stale, and see below |
| `valid_styles` | `scripts/test_lyrics_robustness.py` | — | fixed in `6b14b626` to read `supported_style_keys()` |
| `DEFAULT/NEON/CYBERPUNK/SECTION_CODED_STYLES` | `scripts/s06_generate_ass.py:111-408` | ~300 lines | **dead** — unreferenced; the live presets come from the library |

Three of these share the exact name `SECTION_TO_STYLE`, which is what made the
duplication easy to miss: grepping the name finds three hits and looks complete.

## The consequence, measured

`s03b` computes a style key at `_resolve_section` and then **discards it**,
persisting only the canonical label. `s05` re-derives the style from its own
15-entry map via `.get(section, "verse")` — a silent fallback.

Across the 56 labels `s03b` can emit, **31 resolve to a different style in s05
than s03b intends**. Examples, all falling to `verse`:

- `refrão` / `refrao` / `refrán`, `hook`, `big chorus`, `final chorus`, `climax` — intended `chorus`
- `coda`, `ending`, `fade out` — intended `outro`
- `break`, `breakdown`, `solo`, `ponte`, `middle 8`, `instrumental` — intended `bridge`
- `introduction`, `opening` — intended `intro`

On a Brazilian-Portuguese pipeline, `refrão` rendering with the Verse style
instead of Chorus is a visible product defect, not a nit. On the test song
`jobs/publi-bet` it cost 4 lines (`final chorus`) plus 6 (`verse 1`).

## Suggested fix, cheapest first

1. **Persist what is already computed (~3 lines).** Store the style key
   alongside the section label in `s03b`, carry it into the transcript, and have
   `s05` prefer it: `style = seg.get("style") or SECTION_TO_STYLE.get(section, "verse")`.
   s05's map degrades from a second opinion to a legacy fallback, and all 31
   divergences close at once. One test: a segment carrying `style: "rap"`
   reaches `analysis.json`.
2. **Delete `scripts/s06_generate_ass.py:111-408`** — dead, unreferenced, and a
   same-named copy of the live `SECTION_CODED_STYLES`. Zero risk, −300 lines,
   and it removes a whole class of "which one is real?".
3. **Delete the two library maps** rather than merging them. They encode a
   genuinely different policy (`resolve_lyrics_section("pre-chorus")` gives
   `verse`, `resolve_section("pre-chorus")` gives `prechorus`), so a merge would
   silently pick a winner. They are dead production API.

Not recommended: unifying all four maps in one pass.

## Separate finding: a suite that runs nothing

`tests/test_pipeline_stage_contracts.py` contributes **0 tests** under
`python -m unittest` — its six test classes do not subclass `unittest.TestCase`,
so they are pytest-collected and invisible to the unittest runner:

```
python -m unittest tests.test_pipeline_stage_contracts -v
Ran 0 tests in 0.000s / NO TESTS RAN
```

Any verification list that names this suite and reports "all green" is counting
a vacuous pass. Either run it under pytest or convert the classes.
