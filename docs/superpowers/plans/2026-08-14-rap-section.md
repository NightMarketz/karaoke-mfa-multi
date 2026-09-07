# Rap Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `[Rap]` from being reported as an unknown section marker — first by registering it as a verse (Option A), then, only if wanted, by giving it its own style key and visual identity (Option B).

**Architecture:** A lyrics section label travels through four layers: `s03b` resolves `[Label]` to a canonical name plus a style key; `s05` copies the style key into `analysis.json`; `s06` looks up that key in the chosen preset's style dict; `s08` validates the key against a whitelist. Option A touches only the resolution layer, so nothing downstream changes. Option B introduces a genuinely new style key and therefore has to pass all four layers plus the style library.

**Tech Stack:** Python 3.12 (`.venv`), stdlib `unittest`, no new dependencies.

## Global Constraints

- Run everything from the repo root `C:\Users\Katz\OneDrive\Desktop\Meus projetos\karaoke-mfa-multi` with `.venv\Scripts\python.exe`.
- Test runner is `python -m unittest tests.<module>`; `scripts/test_lyrics_robustness.py` is a standalone script run directly, not a unittest module.
- Style keys are lowercase with underscores (`ad_lib`, not `adLib`), and section labels in the maps are lowercase and stripped.
- The repo has substantial uncommitted WIP in other files. Stage only the files each task names — never `git add -A`.
- The current branch is `mvp-pipeline-runner`. Commit there; do not commit to `main`.
- Option B supersedes Option A: B changes the same line A adds. Doing A first is safe, but B is not additive on top of A's value — B flips `"rap": "verse"` to `"rap": "rap"`.

---

## Measured Starting State

Verified on 2026-08-14, before any change:

| Fact | Value |
| --- | --- |
| `_resolve_section("rap")` today | `("rap", "verse")` — via the unknown fallback, which is what makes s08 warn |
| `s03b.SECTION_TO_STYLE` | 55 entries, has `"rap verse"` and `"spoken"`, has no bare `"rap"` |
| `library.SECTION_TO_STYLE` | 56 entries, same gap |
| `library.LYRICS_SECTION_TO_STYLE` | 55 entries, same gap |
| `library.supported_style_keys()` | `{intro, verse, prechorus, chorus, bridge, drop, outro, ad_lib}` — 8 keys |
| Presets in `PRESET_LIBRARY` | 15 |
| s06 behavior on an unknown style key | falls back to `verse` at `scripts/s06_generate_ass.py:722` — a preset without a `rap` entry degrades quietly |
| s08 behavior on an unknown style key | **hard failure**, `scripts/s08_validate.py:770-778` |

Two consequences that shape the tasks:

1. `library.resolve_section` and `library.resolve_lyrics_section` have **no callers outside `library.py`** (only `s03b` has its own `_resolve_section`). Their maps are a public API surface kept for consistency, not the code path that produced the warning. Updating them is about not leaving a contradiction behind, not about fixing the bug.
2. Because s06 falls back but s08 rejects, Option B must land the whitelist changes in the *same commit* as the new style key. A commit that adds `rap` to the maps but not to `s08`'s `valid_styles` leaves the pipeline red.

---

## File Structure

**Option A**

- Modify: `scripts/s03b_lyrics_align.py` — the map that actually runs
- Modify: `scripts/karaoke_styles/library.py` — the two mirror maps
- Modify: `scripts/test_lyrics_robustness.py` — stale "55 total" label
- Create: `tests/test_rap_section_contracts.py` — the behavioral test

**Option B** (everything in A, plus)

- Modify: `scripts/karaoke_styles/library.py` — `STYLE_DEFAULTS`, `SECTION_CODED_STYLES`, `SINGLE_STYLE_KF_STYLES` key tuple
- Modify: `scripts/s05_analyze.py` — `valid_styles`, plus the two docstrings that enumerate styles
- Modify: `scripts/s08_validate.py` — `valid_styles`
- Modify: `tests/test_karaoke_style_library.py` — the 8-key assertion becomes 9
- Modify: `tests/test_rap_section_contracts.py` — extend with the style-key contract

---

# Option A — register `rap` as a verse

One behavior change: `[Rap]` stops being reported as unknown. No visual change, because the unknown fallback already assigned `verse`.

### Task 1: `[Rap]` resolves as a known section

**Files:**
- Create: `tests/test_rap_section_contracts.py`
- Modify: `scripts/s03b_lyrics_align.py:127-215` (the `SECTION_TO_STYLE` literal)
- Modify: `scripts/karaoke_styles/library.py:1586` and `:1645` (both maps)
- Modify: `scripts/test_lyrics_robustness.py:96` (stale count in the heading string)

**Interfaces:**
- Consumes: `s03b._parse_lyrics(path: Path) -> list[dict]`, where each line dict carries `"section": str` and `"unknown_markers": list[str]`; `s03b._resolve_section(label: str) -> tuple[str, str]` returning `(canonical, style_key)`.
- Produces: nothing new — `SECTION_TO_STYLE["rap"] == "verse"` is the only new fact later tasks rely on.

- [ ] **Step 1: Write the failing test**

Create `tests/test_rap_section_contracts.py`:

```python
"""[Rap] must resolve as a known section, not fall through to the unknown path."""
import tempfile
import unittest
from pathlib import Path

from scripts.s03b_lyrics_align import SECTION_TO_STYLE, _parse_lyrics

LYRICS = """[Chorus]
É publi, é publi, é publi de ilusão

[Rap]
Acorda menor, esse brilho é cenário
Cordão no pescoço e contrato milionário
"""


class RapSectionTests(unittest.TestCase):
    def test_rap_is_registered_in_the_map(self):
        self.assertIn("rap", SECTION_TO_STYLE)
        self.assertEqual("verse", SECTION_TO_STYLE["rap"])

    def test_rap_lines_carry_no_unknown_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lyrics.txt"
            path.write_text(LYRICS, encoding="utf-8")
            lines = _parse_lyrics(path)

        self.assertEqual(3, len(lines), f"expected 3 singable lines, got {len(lines)}")
        rap_lines = [ln for ln in lines if ln["section"] == "rap"]
        self.assertEqual(2, len(rap_lines), "the two [Rap] lines must be tagged 'rap'")
        markers = [m for ln in lines for m in ln["unknown_markers"]]
        self.assertEqual([], markers, f"[Rap] still reported as unknown: {markers}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and confirm it fails for the right reason**

Run: `.venv\Scripts\python.exe -m unittest tests.test_rap_section_contracts -v`

Expected: `test_rap_is_registered_in_the_map` fails with `'rap' not found in {...}`, and `test_rap_lines_carry_no_unknown_marker` fails with `[Rap] still reported as unknown: ['Rap', 'Rap']`.

One assertion inside the marker test **passes already**, verified against the current code: the `rap_lines` count. `_resolve_section` preserves the raw label as the canonical name even when it does not recognise it, so lines are tagged `"rap"` either way. The marker list is the only signal that separates "registered" from "fell through", which is why it is the assertion that flips.

The doubled `'Rap'` is not a bug: `unknown_markers` is copied onto every line emitted after the marker appears, so two rap lines carry two copies.

> **Ruling (2026-08-14, human):** an earlier draft of this task also asserted `_resolve_section("rap") == ("rap", "verse")`. That assertion passes identically before and after the change — the unknown fallback returns the same tuple — so it can never go red on this behavior. It was removed rather than kept as documentation. A fence that is never seen red is not a fence.

- [ ] **Step 3: Register `rap` in the map that runs**

In `scripts/s03b_lyrics_align.py`, in the `SECTION_TO_STYLE` literal, next to the existing `"rap verse"` entry:

```python
    "estrofe":          "verse",   # Portuguese
    "estrofa":          "verse",   # Spanish
    "rap":              "verse",   # bare [Rap], common in Suno / pt-BR lyrics
    "rap verse":        "verse",
    "spoken":           "verse",
    "spoken word":      "verse",
```

- [ ] **Step 4: Register it in the two mirror maps**

In `scripts/karaoke_styles/library.py`, inside `SECTION_TO_STYLE` (around line 1596):

```python
    "estrofa": "verse",
    "rap": "verse",
    "rap verse": "verse",
```

and inside `LYRICS_SECTION_TO_STYLE` (around line 1662):

```python
    "estrofa": "verse",
    "rap": "verse",
    "rap verse": "verse",
```

- [ ] **Step 5: Run the test and confirm it passes**

Run: `.venv\Scripts\python.exe -m unittest tests.test_rap_section_contracts -v`
Expected: 3 tests, PASS.

- [ ] **Step 6: Fix the now-stale count in the robustness script**

`scripts/test_lyrics_robustness.py:96` prints `"(55 total)"` while iterating the dict. The loop is fine; only the label lies. Replace the hardcoded number with the live count so it cannot go stale again:

```python
def test_resolve_exact_all_55_entries():
    heading(f"_resolve_section — every SECTION_TO_STYLE entry ({len(SECTION_TO_STYLE)} total)")
```

- [ ] **Step 7: Run the neighbouring suites for regressions**

Run each and confirm PASS:

```bash
.venv\Scripts\python.exe -m unittest tests.test_karaoke_style_library -v
```

```bash
.venv\Scripts\python.exe scripts\test_lyrics_robustness.py
```

Expected: the library suite passes unchanged (it asserts `resolve_section("guitar solo") == ("guitar solo", "bridge")` and the 8-key set — neither is touched by Option A). The robustness script prints `56 total` in that heading now.

- [ ] **Step 8: Commit**

```bash
git add scripts/s03b_lyrics_align.py scripts/karaoke_styles/library.py scripts/test_lyrics_robustness.py tests/test_rap_section_contracts.py
```

```bash
git commit -m "fix(s03b): register bare [Rap] as a verse section

The map already had 'rap verse' and 'spoken' but not bare 'rap', so [Rap]
fell through to the unknown fallback: same 'verse' style, but recorded in
unknown_section_markers and reported by s08 on every rap track.

Registered in all three section maps (s03b plus the two mirrors in the
style library) so the resolution layers do not contradict each other."
```

---

# Option B — `rap` as its own style key

Only worth doing if the rap section should *look* different. Under `single-style-kf` it cannot: that preset builds all 8 styles from one base with identical font, size and colours, so a 9th identical entry changes nothing on screen. B pays off with a preset that differentiates, such as `section-coded`.

B replaces A's mapping value. If A already shipped, B edits that same line.

### Task 2: `rap` becomes a supported style key end to end

This task deliberately bundles the maps, the whitelists and the library defaults into one commit: s08 rejects any style key outside its whitelist, so splitting them would leave an intermediate commit where a rap track fails validation.

**Files:**
- Modify: `scripts/s03b_lyrics_align.py` (the `"rap"` entry from A, value becomes `"rap"`)
- Modify: `scripts/karaoke_styles/library.py:1450` (`STYLE_DEFAULTS`), `:1586`, `:1645`
- Modify: `scripts/s05_analyze.py` — import `supported_style_keys` near line 66, replace the literal at `:640`, and the prose enumerations at `:26` and `:453`
- Modify: `scripts/s08_validate.py` — import near line 40, replace the literal at `:770`
- Modify: `tests/test_karaoke_style_library.py:188-192`
- Test: `tests/test_rap_section_contracts.py`

**Interfaces:**
- Consumes: `library.supported_style_keys() -> set[str]`, `library.STYLE_DEFAULTS: dict[str, dict[str, str]]`.
- Produces: `"rap"` as a valid value of the `style` field in `analysis.json`, accepted by `s05` and `s08` and resolvable by `s06`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rap_section_contracts.py`:

```python
from scripts.karaoke_styles.library import (
    PRESET_LIBRARY,
    STYLE_DEFAULTS,
    supported_style_keys,
)


class RapStyleKeyTests(unittest.TestCase):
    def test_rap_is_a_supported_style_key(self):
        self.assertIn("rap", supported_style_keys())
        self.assertIn("rap", STYLE_DEFAULTS)

    def test_rap_section_maps_to_the_rap_style(self):
        self.assertEqual("rap", SECTION_TO_STYLE["rap"])

    def test_every_preset_still_validates(self):
        from scripts.karaoke_styles.library import validate_all_presets

        self.assertEqual([], validate_all_presets())

    def test_presets_without_a_rap_style_degrade_to_verse(self):
        # s06 falls back at scripts/s06_generate_ass.py:722; this asserts the
        # premise that lets us add 'rap' to some presets and not others.
        for preset_id, preset in PRESET_LIBRARY.items():
            if "rap" not in preset.styles:
                self.assertIn("verse", preset.styles,
                              f"{preset_id} has neither rap nor verse to fall back to")

    def test_stages_take_their_whitelist_from_the_library(self):
        # s05 and s08 must not carry their own copy of the style key set:
        # one source of truth, so a new key cannot be half-registered.
        import scripts.s05_analyze as s05
        import scripts.s08_validate as s08

        for module in (s05, s08):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn(
                '"ad_lib"}', source,
                f"{module.__name__} still hardcodes a style whitelist literal",
            )
            self.assertIn("supported_style_keys", source,
                          f"{module.__name__} must call supported_style_keys()")
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_rap_section_contracts -v`
Expected: `test_rap_is_a_supported_style_key` fails with `'rap' not found in {'intro', 'verse', ...}`, and `test_stages_take_their_whitelist_from_the_library` fails with `scripts.s05_analyze still hardcodes a style whitelist literal`.

- [ ] **Step 3: Add the style key to the library**

In `scripts/karaoke_styles/library.py`, extend `STYLE_DEFAULTS` (line 1450):

```python
    "outro": {"color": "warm", "effect": "fade_in"},
    "rap": {"color": "default", "effect": "highlight"},
    "ad_lib": {"color": "soft", "effect": "none"},
```

and change the value in both maps from `"verse"` to `"rap"`:

```python
    "rap": "rap",
```

- [ ] **Step 4: Point the s03b map at the new key**

In `scripts/s03b_lyrics_align.py`, the entry added in Task 1 becomes:

```python
    "rap":              "rap",     # bare [Rap], common in Suno / pt-BR lyrics
```

- [ ] **Step 5: Point both stage whitelists at the library**

> **Ruling (2026-08-14, human):** an earlier draft duplicated the 9-key literal into both stages behind a `_valid_styles_for_test()` accessor. That preserved a verbatim duplication the review rubric treats as a defect, and named production code after its test. Both stages now read the set from the style library instead — one source of truth. The cost, accepted deliberately: `s05` and `s08` today import only from `scripts.common.*`, and this adds a dependency on `scripts.karaoke_styles.library`.

This swap is **behaviour-preserving today**, verified on 2026-08-14: the literal in both stages is `{"verse", "prechorus", "chorus", "bridge", "drop", "intro", "outro", "ad_lib"}`, and `supported_style_keys()` returns exactly those 8 keys from `STYLE_DEFAULTS`. After Step 3 adds `rap` to `STYLE_DEFAULTS`, both whitelists widen automatically — that is the point.

In `scripts/s05_analyze.py`, add to the import block near line 66:

```python
from scripts.karaoke_styles.library import supported_style_keys
```

and replace the literal at line 640:

```python
    valid_styles = supported_style_keys()
```

Apply the same two changes to `scripts/s08_validate.py`: the import near line 40, and the literal at line 770.

Also update the two places in `scripts/s05_analyze.py` that enumerate styles in prose, so the LLM prompt and the schema docstring do not contradict the code — line 26:

```python
                "style":  "verse",        // verse|chorus|bridge|intro|outro|rap|ad_lib
```

and line 453:

```python
   - "style": one of ["verse", "chorus", "bridge", "intro", "outro", "rap", "ad_lib"]
```

- [ ] **Step 6: Update the library test that pins the key set**

`tests/test_karaoke_style_library.py:188` asserts the exact 8-key set and will now fail. That failure is correct — the set changed. Update it to 9:

```python
    def test_supported_style_keys_include_current_analysis_keys(self):
        self.assertEqual(
            {"intro", "verse", "prechorus", "chorus", "bridge", "drop", "outro",
             "rap", "ad_lib"},
            supported_style_keys(),
        )
```

- [ ] **Step 7: Run the tests and confirm they pass**

```bash
.venv\Scripts\python.exe -m unittest tests.test_rap_section_contracts tests.test_karaoke_style_library -v
```

Expected: all PASS.

- [ ] **Step 8: Prove the fallback claim with a negative control**

The plan asserts that presets without a `rap` entry degrade to `verse` at `scripts/s06_generate_ass.py:722`. Confirm it against the real builder rather than trusting the read:

```bash
.venv\Scripts\python.exe -c "from scripts.karaoke_styles.library import get_preset; p=get_preset('aegisub-classic-blue'); k='rap' if 'rap' in p.styles else 'verse'; print('rap in preset:', 'rap' in p.styles, '| s06 would use:', k)"
```

Expected: `rap in preset: False | s06 would use: verse`. If it prints `True`, a preset already gained a rap style and Task 3's premise needs revisiting.

- [ ] **Step 9: Commit**

```bash
git add scripts/s03b_lyrics_align.py scripts/karaoke_styles/library.py scripts/s05_analyze.py scripts/s08_validate.py tests/test_karaoke_style_library.py tests/test_rap_section_contracts.py
```

```bash
git commit -m "feat(styles): add 'rap' as a first-class style key

s06 falls back to verse for an unknown style key, but s08 hard-rejects it,
so the maps, the library defaults and both stage whitelists have to move
together or a rap track fails validation.

No visual change yet: no preset defines a rap style, so every preset still
renders rap with its verse style."
```

### Task 3: give `rap` a visual identity in `section-coded`

**Files:**
- Modify: `scripts/karaoke_styles/library.py:270-394` (`SECTION_CODED_STYLES`)
- Test: `tests/test_rap_section_contracts.py`

**Interfaces:**
- Consumes: `KaraokeStyle` and the `_c(r, g, b)` colour helper already used throughout `library.py`.
- Produces: `PRESET_LIBRARY["section-coded"].styles["rap"]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rap_section_contracts.py`:

```python
class RapVisualIdentityTests(unittest.TestCase):
    def test_section_coded_defines_a_distinct_rap_style(self):
        styles = PRESET_LIBRARY["section-coded"].styles
        self.assertIn("rap", styles)
        rap, verse = styles["rap"], styles["verse"]
        self.assertEqual("Rap", rap.name)
        self.assertNotEqual(
            (verse.fontsize, verse.primary_color),
            (rap.fontsize, rap.primary_color),
            "a rap style identical to verse is not worth the key",
        )

    def test_rap_is_smaller_than_verse(self):
        # Rap lines carry more syllables per second, so they need more room.
        styles = PRESET_LIBRARY["section-coded"].styles
        self.assertLess(styles["rap"].fontsize, styles["verse"].fontsize)

    def test_single_style_preset_stays_uniform(self):
        styles = PRESET_LIBRARY["single-style-kf"].styles
        sizes = {s.fontsize for s in styles.values()}
        colors = {s.primary_color for s in styles.values()}
        self.assertEqual(1, len(sizes), f"single-style-kf must stay uniform: {sizes}")
        self.assertEqual(1, len(colors), f"single-style-kf must stay uniform: {colors}")
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_rap_section_contracts.RapVisualIdentityTests -v`
Expected: the first two fail with `'rap' not found in {...}`; `test_single_style_preset_stays_uniform` passes and must keep passing.

- [ ] **Step 3: Add the rap entry to `SECTION_CODED_STYLES`**

Read the existing `"verse"` entry in `SECTION_CODED_STYLES` first and copy its field order. Add alongside it, changing only size and colour:

```python
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(230, 230, 235),
        secondary_color=_c(120, 200, 255),
        outline_color=_c(10, 10, 20),
        back_color=_c(0, 0, 0),
        outline=2.4,
        shadow=0.8,
        alignment=2,
        margin_v=60,
        border_style=1,
        flash_on_highlight=False,
    ),
```

If the `"verse"` entry in this dict uses different field names or a different fontname, match it — the values above assume the same `KaraokeStyle` signature used by `AEGISUB_CLASSIC_BLUE_STYLES` at line 416. Fontsize 44 must stay below whatever `verse` uses; check it and adjust rather than assuming.

- [ ] **Step 4: Add the key to the single-style generator so it stays uniform**

`SINGLE_STYLE_KF_STYLES` builds its dict from an explicit key tuple. Without `rap` there, that preset has no rap entry and s06 falls back to verse — which is visually identical anyway, so this is about consistency, not looks:

```python
    for key in ("intro", "verse", "prechorus", "chorus", "bridge", "drop",
                "outro", "rap", "ad_lib")
```

- [ ] **Step 5: Run the tests and confirm they pass**

```bash
.venv\Scripts\python.exe -m unittest tests.test_rap_section_contracts tests.test_karaoke_style_library -v
```

Expected: all PASS, including `test_single_style_preset_stays_uniform` — the generated rap entry copies the same base, so the uniformity check still sees one size and one colour.

- [ ] **Step 6: Commit**

```bash
git add scripts/karaoke_styles/library.py tests/test_rap_section_contracts.py
```

```bash
git commit -m "feat(styles): distinct rap style in the section-coded preset

Rap carries more syllables per second than a sung verse, so it gets a
smaller body in the one preset that differentiates sections. single-style-kf
generates its rap entry from the same base and stays uniform by design."
```

### Task 4: end-to-end verification on the real job

**Files:**
- Uses: `jobs/publi-bet/` (the "Publi de Bet" job, whose lyrics.txt contains `[Rap]`)
- Modify: none

**Interfaces:**
- Consumes: the whole pipeline from `s03b` to `s08`.
- Produces: evidence, not code.

- [ ] **Step 1: Re-resolve the real lyrics without a full rerun**

The cheap proof first, since it needs no model:

```bash
.venv\Scripts\python.exe -c "from pathlib import Path; from scripts.s03b_lyrics_align import _parse_lyrics; ls=_parse_lyrics(Path('jobs/publi-bet/lyrics.txt')); import collections; print(collections.Counter(l['section'] for l in ls)); print('unknown:', [m for l in ls for m in l['unknown_markers']])"
```

Expected: `unknown: []`. The counter is unchanged by this plan and reads, measured on 2026-08-14:

```
{'intro': 2, 'pre-chorus': 4, 'chorus': 12, 'verse 1': 6, 'rap': 14, 'bridge': 4, 'final chorus': 4, 'outro': 6}
```

Note two things about that output. The keys are canonical *labels*, not style keys — `verse 1` and `final chorus` appear raw, and are mapped to styles later. And `rap: 14` is already there before any change, because the unknown fallback preserves the label. Only `unknown` moves: `['Rap']` today, `[]` after Task 1. The counts sum to 52, matching the 52 lines the pipeline aligned.

- [ ] **Step 2: Rerun the pipeline tail**

The section label is decided in s03b, so a true end-to-end needs s03b rerun. Use `--no-pitch` to skip CREPE, which is the ~25 minute part; alignment itself takes about 3.5 minutes:

```bash
.venv\Scripts\python.exe scripts\s03b_lyrics_align.py --job-dir jobs\publi-bet --lyrics jobs\publi-bet\lyrics.txt --language por --no-pitch
```

Then, in order:

```bash
.venv\Scripts\python.exe scripts\s04_align.py --job-dir jobs\publi-bet --allow-cpu-hubertfa --phone-assign sequence
```

```bash
.venv\Scripts\python.exe scripts\s05_analyze.py --job-dir jobs\publi-bet
```

```bash
.venv\Scripts\python.exe scripts\s06_generate_ass.py --job-dir jobs\publi-bet --preset section-coded
```

Note the preset: `section-coded`, not `single-style-kf`. Under `single-style-kf` a rap style is invisible by construction, so verifying there would prove nothing.

- [ ] **Step 3: Confirm the warning is gone and the style is used**

```bash
.venv\Scripts\python.exe scripts\s08_validate.py --job-dir jobs\publi-bet --overlap-tolerance 0.05
```

Expected: the warning `Unknown section markers defaulted to 'verse': ['Rap']` no longer appears, and no new `invalid style` failure appears. s08 will still report the pre-existing syllable failures — 33 invalid durations, syllables outside their word and outside the alignment window. Those are unrelated to this plan and must not be counted as regressions; compare against the baseline of **574 violations** measured on 2026-08-14 and confirm the count did not grow.

```bash
grep "^Style: Rap\|,Rap,," jobs\publi-bet\output.ass | head -3
```

Expected: a `Style: Rap,...` definition line, and at least one `Dialogue:` line whose style field is `Rap`.

- [ ] **Step 4: Record the outcome**

Report the before/after in the task summary: section counter, unknown-marker list, s08 violation count against the 574 baseline, and the number of `Dialogue` lines carrying the `Rap` style. Numbers go with their denominators.

There is nothing to commit in this task — it produces evidence only.

---

## Self-Review

**Spec coverage.** Option A: register the label — Task 1. Option B: new style key end to end — B1; visual identity — B2; proof on the real song — B3. The comparison that motivated the split (single-style-kf renders all 8 styles identically, so B is only worth it on a differentiating preset) is stated in B's preamble and enforced by `test_single_style_preset_stays_uniform`.

**Placeholder scan.** No TBDs. Every code step carries the literal to paste. Two steps deliberately say "read the neighbouring entry first and match it" — B2 Step 3 for the `KaraokeStyle` field order and B2 Step 3's fontsize check. Those are verification instructions against a file the plan cannot fully quote, not deferred decisions.

**Type consistency.** `_resolve_section` returns `(canonical, style_key)` in A1 and is not re-signed later. `_valid_styles_for_test()` is introduced in B1 Step 5 in both modules with the same name and return type, and imported under that name in B1 Step 1. `supported_style_keys()` returns a `set[str]` in both the library and the B1 test. `STYLE_DEFAULTS` entries keep the `{"color": ..., "effect": ...}` shape. Preset styles are addressed as `preset.styles[key]` throughout, matching `validate_preset`.

**Known gap, deliberately not covered.** `library.resolve_section` and `library.resolve_lyrics_section` have no callers today. The plan keeps their maps in sync so the codebase does not hold two contradictory answers, but it does not unify the three maps into one — that refactor is larger than the feature and would touch every section-handling path.
