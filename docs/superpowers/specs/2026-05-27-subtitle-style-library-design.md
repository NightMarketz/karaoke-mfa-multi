# Subtitle Style Library Design

## Goal

Unify karaoke subtitle style contracts across lyrics alignment, analysis, ASS generation, and the Review Wizard without changing the current rendered look in the first slice.

The first implementation should make style selection and section mapping dependable. Visual expansion comes later, after the current `default`, `neon`, `cyberpunk`, and `section-coded` presets continue rendering as they do today.

## Product Decision

Use a two-layer approach:

1. Technical unification now.
2. Future visual library support through structured metadata.

The first slice should create a single Python source of truth, likely `scripts/karaoke_styles/library.py`, and move preset/style metadata out of `scripts/s06_generate_ass.py`.

## Current Context

Current style responsibilities are split:

- `scripts/s03b_lyrics_align.py` maps lyric section labels to style keys.
- `scripts/s05_analyze.py` preserves or derives line style/effect decisions.
- `scripts/s06_generate_ass.py` owns ASS style definitions, preset choices, and render conversion.
- Review Wizard contracts already include hooks for `style_preset_id`, `style_overrides`, and future preview/export state.

This creates drift risk: one stage can emit a section/style name another stage does not understand.

## Scope

In scope for the first implementation:

- Create one shared style library module.
- Preserve existing preset ids: `default`, `neon`, `cyberpunk`, and `section-coded`.
- Preserve existing section/style keys used by generated `analysis.json`.
- Preserve the current rendered ASS appearance as closely as practical.
- Expose preset metadata: `id`, `label`, `version`, `description`, supported section styles, and supported effects.
- Make `s03b_lyrics_align.py`, `s05_analyze.py`, and `s06_generate_ass.py` consume the shared library.
- Record `style_preset_id`, `style_version`, and `style_overrides` in Review Wizard/project contracts where style data is represented.
- Add tests that prove existing presets and section mappings remain compatible.

Out of scope for the first implementation:

- Changing colors, typography, motion, or final visual treatment.
- Building a full style editor.
- Introducing user-created preset files.
- Marketplace, sharing, or downloadable style packs.
- Browser-side live typography controls.

## Architecture

### Shared Library

Add a package:

```text
scripts/karaoke_styles/
  __init__.py
  library.py
```

`library.py` should provide:

- immutable preset definitions;
- section label to canonical style key helpers;
- preset lookup and validation;
- ASS style data conversion helpers for Stage 06;
- metadata helpers for UI/API listing.

The shared library should not read job directories or write artifacts. It is pure style contract code.

### Data Model

Use Python dataclasses for the first slice:

```python
@dataclass(frozen=True)
class KaraokeStyle:
    name: str
    fontname: str
    fontsize: int
    bold: bool
    italic: bool
    primary_color: str
    secondary_color: str
    outline_color: str
    back_color: str
    outline: float
    shadow: float
    alignment: int
    margin_v: int
    border_style: int = 1
    flash_on_highlight: bool = False

@dataclass(frozen=True)
class StylePreset:
    id: str
    label: str
    version: int
    description: str
    styles: Mapping[str, KaraokeStyle]
    effects: tuple[str, ...]
```

The shape intentionally matches the current ASS generator so extraction is low-risk.

### Section Mapping

The library should centralize canonical style keys such as:

- `intro`
- `verse`
- `prechorus`
- `chorus`
- `bridge`
- `drop`
- `outro`
- `ad_lib`

Unknown section markers should continue to fall back to `verse`, but that fallback should be explicit and observable where the caller already logs unknown markers.

### Stage Integration

`s03b_lyrics_align.py` should use shared section resolution helpers instead of owning a disconnected map.

`s05_analyze.py` should validate emitted `style` and `effect` values against the shared library. If a model or fallback emits an unknown style, it should use `verse` with an observable warning rather than silently passing an unsupported key downstream.

`s06_generate_ass.py` should import presets from the shared library and keep only ASS file construction logic locally.

## Review Wizard Contract

Project state should keep:

```json
{
  "style_preset_id": "default",
  "style_version": 1,
  "style_overrides": {}
}
```

Rules:

- `style_preset_id` identifies the selected library preset.
- `style_version` records the preset version used when preview/export decisions were made.
- `style_overrides` remains empty in the first implementation but reserves a stable place for future project-level customization.
- Export metadata should record the actual preset id/version used for ASS and MP4 generation.

## UI Direction

The UI should not hardcode available presets long-term. It should be able to list presets from library metadata.

For the first implementation, existing selection behavior can remain visually unchanged. A later UI slice can add descriptions, preview swatches, and style family grouping.

Recommended future preset families:

- `classic`: maximum readability.
- `section-coded`: section-aware karaoke for Suno structures.
- `neon-stage`: energetic pop/electronic look.
- `editorial`: restrained, publication-friendly look.
- `battle-test`: diagnostic style for alignment and QA review.

Only existing presets are required in the first slice.

## Validation

Preset validation should check:

- preset id is known;
- every preset has at least `verse`;
- every style has valid ASS colors;
- every style has positive font size;
- alignment is an ASS-compatible integer;
- supported effects are known by the karaoke text builder;
- section mappings only emit supported canonical style keys or explicit fallback.

Stage 06 should fail clearly if the selected preset is invalid. It should not silently switch to another visual preset.

## Compatibility Requirements

The first implementation must preserve:

- CLI choices for `--preset`;
- generated style names such as `Verse`, `Chorus`, and `Bridge`;
- supported current style keys;
- current default behavior when no preset is specified;
- current ASS validation expectations;
- current preview/export visual output as closely as possible.

Where exact byte-for-byte ASS output is not practical because imports or ordering change, tests should verify semantic equivalence: style names, style counts, dialogue count, karaoke tags, preset id selection, and representative style fields.

## Testing Strategy

Add focused unit tests for:

- listing preset ids includes `default`, `neon`, `cyberpunk`, and `section-coded`;
- each preset validates successfully;
- unknown preset raises a clear error;
- section label mapping matches existing behavior for common labels;
- unknown section falls back to `verse`;
- Stage 06 can render with each preset;
- Stage 06 records selected preset metadata.

Existing ASS generation tests should continue to pass.

## Migration Plan

1. Create `scripts/karaoke_styles/library.py` by moving current dataclasses, color helper, presets, and section mapping into the shared module.
2. Update Stage 06 imports and keep ASS generation behavior unchanged.
3. Update Stage 03b section mapping to use the shared helper.
4. Update Stage 05 validation/fallback to use shared supported style/effect lists.
5. Add tests around library metadata and Stage 06 compatibility.
6. Add or update Review Wizard contract fields for preset id/version/overrides.

## Acceptance Criteria

- There is one source of truth for style presets and section style keys.
- Current preset ids still work.
- Existing rendered visual behavior is intentionally preserved.
- `s03b_lyrics_align.py`, `s05_analyze.py`, and `s06_generate_ass.py` no longer maintain conflicting style definitions.
- Review Wizard/project contracts can store selected style id, style version, and future overrides.
- Tests cover preset lookup, validation, section fallback, and Stage 06 render compatibility.

