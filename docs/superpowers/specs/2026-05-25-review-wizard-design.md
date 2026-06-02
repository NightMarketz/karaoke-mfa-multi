# Review Wizard Gold Standard Design

## Goal

Build a professional review workflow for karaoke synchronization where the app prepares text, aligns lyrics with multi-evidence audio analysis, surfaces quality risks, lets the user fix or approve them, and exports an MP4 plus Aegisub-compatible ASS.

The core product is the **Review Wizard**. It guides the user through quality decisions without hiding advanced tools. The timeline editor exists as a deep tool invoked from wizard steps, not as the default starting point.

## Product Position

This feature targets a market-leading sync workflow, not a simple automatic karaoke generator. The automatic engine should do most of the work, but publication quality comes from a guided review loop with traceable approvals.

The product should answer two questions for every project:

1. Is this take ready to publish?
2. If not, what exact moments should the user review?

The system must allow export even when risks remain, but risky exports require preview approval and leave an audit trail.

## Core Principles

- Preserve musical duration. Do not normalize syllable length to fixed values.
- Measure boundary and anchor error, not whether every syllable has the same duration.
- Treat model output as a draft until confirmed by evidence, review, or user approval.
- Use conservative automatic decisions by default.
- Provide an aggressive correction button that creates an alternate candidate take.
- Keep edits non-destructive: raw evidence, automatic takes, reprocessed takes, manual edits, and approved take must coexist.
- Keep displayed lyric text separate from sung variants and internal timing.
- Never silently rewrite lyrics, invent words, duplicate melisma text, or discard uncertain vocal evidence.

## Wizard Flow

### 1. Import

The user provides stems or full audio, lyrics, language, and style preset.

Required behavior:

- Accept vocal and instrumental stems when available.
- Represent mixed-audio input in the contract with `needs_stem_extraction` until a local extraction module is enabled.
- Validate upload type, duration, presence of lyrics, and selected language.
- Use a simple style preset now, with a schema hook for a future style editor.

### 2. Text Review

This step is mandatory as a review of what the script prepared, not manual preparation from scratch.

The app prepares:

- normalized lyrics text;
- section markers;
- lines;
- words;
- syllables;
- likely elisions and contractions;
- possible ad-libs, omitted words, or unmapped vocal regions when evidence already exists;
- ambiguity issues.

The user can:

- approve prepared text;
- correct sections, lines, words, and syllables;
- mark instrumental/ad-lib regions;
- confirm or adjust language;
- skip with risk and reason.

Skipping does not block progress, but it creates a risk issue and requires preview approval before final export.

### 3. Alignment Processing

The app runs the conservative multi-evidence alignment pass.

Evidence sources:

- vocal waveform and energy;
- vocal onset and offset candidates;
- phoneme/CTC timing;
- syllable structure;
- pitch contour;
- melisma candidates;
- instrumental beat grid and downbeats;
- transients;
- silence and breath regions;
- prior edits when reprocessing a selection.

The output is an `AlignmentTake` with confidence and explanation metadata.

### 4. Quality Review

This is the main working screen.

The app presents:

- global quality status;
- score by section or time range;
- issue queue ordered by perceptual impact first and technical severity second;
- focused issue editor for each issue;
- aggressive correction button per issue or selected range;
- option to open advanced timeline at the exact timestamp.

Status levels:

- `ready`: export can proceed directly.
- `review_suggested`: export allowed with confirmation or preview.
- `needs_fix`: export allowed only after critical preview approval or explicit risk approval.

### 5. Focused Issue Editor

Clicking an issue opens a small correction panel before opening the full timeline.

The focused editor shows:

- short loop playback;
- mini waveform;
- relevant text hierarchy;
- issue cause;
- confidence and evidence summary;
- recommended action;
- quick actions;
- `Open Timeline` button.

Example quick actions:

- snap syllable to vocal onset;
- realign selected phrase;
- redistribute compressed syllables;
- refine melisma;
- mark as sustain;
- approve risk;
- ignore with reason.

### 6. Advanced Timeline

The advanced timeline is invokable from Text Review, Quality Review, or Preview. It returns the user to the wizard after the edit.

Layers:

- lyric hierarchy: line, word, syllable, melisma, internal segment;
- vocal waveform;
- instrumental waveform;
- pitch contour;
- beat grid and downbeats;
- onsets and transients;
- confidence heatmap;
- issues;
- highlight preview.

Editing modes:

- direct text/block dragging for speed;
- explicit timing handles for precision;
- split and join line, word, syllable, and melisma segment;
- snap to onset, energy peak, pitch change, phoneme boundary, beat, or downbeat;
- lock approved sections;
- compare takes;
- undo and redo;
- reprocess selection conservatively or aggressively.

### 7. Preview Approval

Preview is both a correction tool and a quality gate.

Required previews:

- Critical issues must be previewed before final export when status is `needs_fix`.
- Preview of critical snippets is mandatory.
- A button must always exist to export a full temporary preview of the entire song.

The user can:

- approve current take;
- return to issues;
- open timeline at the current timestamp;
- compare takes;
- approve risk explicitly.

### 8. Export

Primary exports:

- MP4 final for publication.
- ASS file compatible with Aegisub.

Internal or supporting artifacts:

- project JSON with full non-destructive state;
- quality report JSON or HTML;
- preview render artifacts.

ASS export requirements:

- Open cleanly in Aegisub.
- Preserve editable styles.
- Keep displayed lyric text clean.
- Represent syllable timing with compatible karaoke tags.
- Approximate melisma highlight curves when ASS cannot represent the full internal model.
- Avoid duplicating melisma text unless the sung text is explicitly repeated and approved.

## Timing And Quality Metrics

Precision targets are boundary and anchor tolerances, not fixed durations.

| Unit | Publicable target |
| --- | ---: |
| Line or phrase boundary | 80 ms |
| Word boundary | 50 ms |
| Syllable boundary | 30-40 ms |
| Strong consonant or vocal attack | 25 ms |
| Internal melisma segment anchor | 40 ms when visually smooth |

Additional metrics:

- `boundary_error_ms`: distance between chosen timestamp and evidence-backed event.
- `duration_fit`: whether duration follows sung sustain, silence, and transition.
- `highlight_velocity`: whether fill speed feels smooth and musical.
- `melisma_segmentation_quality`: whether internal note changes are represented.
- `legibility`: whether the line is readable at song speed.

## Evidence Authority Policy

The default policy is conservative and directed by decision type.

| Decision | Primary authority | Secondary authority | Rule |
| --- | --- | --- | --- |
| Syllable start with clear attack | vocal onset + phoneme/CTC | pitch, beat | voice wins; beat cannot move more than 25 ms without review |
| Sustained vowel | vocal energy + pitch | CTC | preserve real sustain; do not compress to beat |
| Syllable end | energy drop + phonetic transition | pitch, breath | avoid artificial cuts |
| Internal melisma segment | pitch contour + micro-onsets | vocal energy | segment musical changes without repeating text |
| Line boundary | first/last reliable syllable | beat/downbeat | smooth line visually without moving strong syllables |
| Line break | legibility + breath + phrase shape | original lyrics | avoid breaking inside melisma |
| Highlight visual | approved timing + curve model | beat grid | can smooth display without changing source timing |
| Manual snap | user-selected target | nearby evidence | user choice wins and is recorded |

Hard rules:

- Beat never overrides a clear vocal attack.
- CTC never creates melisma segmentation alone.
- Pitch never creates displayed text.
- Manual edits always win but are stored as operations.
- Conflicts above threshold become issues.
- Aggressive correction creates a candidate take, never a silent replacement.

Initial conflict thresholds:

- Syllable evidence disagreement above 60 ms creates an issue.
- Line evidence disagreement above 100 ms creates an issue.
- Automatic beat snap for strong syllables is capped at 25 ms.
- Melisma segmentation requires stable internal evidence around 80-120 ms or longer.

## Melisma Model

A melisma is a single displayed syllable sung across multiple internal musical movements.

Detect a melisma when:

- one syllable or vowel is prolonged;
- pitch contains multiple stable regions or clear note transitions;
- vocal energy remains connected;
- there is no strong new textual articulation;
- lyrics do not indicate real repetition;
- internal segments meet minimum duration and confidence.

Do not classify as melisma when:

- a new consonant or articulation indicates a new syllable;
- the word or syllable is actually repeated;
- pitch movement is only vibrato;
- movement is a continuous slide without stable internal anchors;
- audio evidence is too ambiguous.

Manual controls:

- split segment;
- join segments;
- move segment boundary;
- mark type as sustain, note melisma, vibrato, slide, or uncertain ornament;
- choose highlight curve: linear, per-segment, energy-based, smoothed, or manual;
- refine melisma automatically;
- compare before and after.

Displayed text appears once. Highlight speed changes inside the syllable according to the approved internal segment model.

## Lyrics Versus Sung Audio

The app must support divergence between written lyrics and sung performance without silently changing the karaoke text.

Supported mappings:

- elision;
- contraction;
- elongated vowel;
- omitted word;
- repeated sung phrase;
- ad-lib;
- backing vocal;
- breath;
- unmapped vocal;
- unvoiced text.

Rules:

- Do not alter displayed text automatically.
- Do not invent visible words automatically.
- Do not remove visible words automatically.
- Strong divergence creates an issue.
- Unmapped vocals remain in an `unmapped_vocal` layer.
- Text without matching vocal remains in an `unvoiced_text` layer.
- Corrections can propose variants, but the user must approve them.

## Issue System

Issue categories:

- Text: long line, ambiguous section, uncertain syllable, likely elision, out-of-vocabulary token, text without canto, canto without text.
- Timing: uncertain boundary, compressed word, drift, evidence conflict, low vocal energy.
- Melisma: unreviewed long melisma, vibrato/melisma confusion, unsegmented slide, unstable pitch change, irregular highlight.
- Musicality: perceptually off entrance, poor line break, ignored breath, rushed phrase.
- Export: unsupported curve, unpreviewed critical section, approved take with open risk.

Each issue has:

- stable id;
- type;
- severity;
- perceptual impact;
- confidence;
- priority score;
- time range;
- affected objects;
- evidence summary;
- suggested action;
- status;
- resolution operation or risk approval.

Priority combines:

- perceptual impact;
- technical severity;
- confidence;
- duration;
- section importance;
- local issue density;
- export risk.

Perceptual impact weighs more than raw technical severity.

## Non-Destructive Versioning

Project state must preserve:

- raw media references;
- prepared text;
- extracted evidence;
- conservative automatic take;
- aggressive candidate takes;
- manual edits;
- approved take;
- quality reports;
- preview approvals;
- export artifacts.

Edits are operations:

```json
{
  "operation": "move_syllable_boundary",
  "target_id": "syllable:abc123",
  "from": 12.34,
  "to": 12.372,
  "snap_source": "vocal_onset",
  "created_by": "user",
  "created_at": 1779680000.0
}
```

## Data Contract

The project contract should be complete from the start, while implementation can fill it incrementally.

Top-level shape:

```json
{
  "project_id": "uuid",
  "schema_version": 1,
  "media_assets": [],
  "prepared_text": {},
  "evidence_bundle": {},
  "alignment_takes": [],
  "edit_operations": [],
  "issues": [],
  "quality_reports": [],
  "preview_renders": [],
  "approved_take_id": null,
  "style_preset_id": "default",
  "style_overrides": {},
  "exports": []
}
```

Core entities:

- `Project`
- `MediaAsset`
- `PreparedText`
- `TextSection`
- `LyricLine`
- `Word`
- `Syllable`
- `Melisma`
- `MelismaSegment`
- `EvidenceBundle`
- `EvidenceTrack`
- `AlignmentTake`
- `EditOperation`
- `Issue`
- `QualityReport`
- `PreviewRender`
- `ExportArtifact`

Every editable entity must have:

- stable id;
- source;
- confidence when generated;
- review status;
- optional evidence references;
- timing in seconds when time-based.

## Module Boundaries

Modules must be isolated and communicate through structured contracts.

1. `Text Preparation`
   - Input: raw lyrics and language.
   - Output: `PreparedText` plus text issues.

2. `Audio Evidence`
   - Input: vocal and instrumental assets.
   - Output: `EvidenceBundle`.

3. `Alignment Engine`
   - Input: `PreparedText` and `EvidenceBundle`.
   - Output: conservative `AlignmentTake`.

4. `Melisma Analyzer`
   - Input: syllable timing, pitch, energy, onsets.
   - Output: melisma annotations and issues.

5. `Quality Engine`
   - Input: take, text, evidence, edit history.
   - Output: `QualityReport` and prioritized issues.

6. `Review Wizard`
   - Input: project state.
   - Output: step approvals, skipped risks, navigation state.

7. `Focused Issue Editor`
   - Input: issue and local context.
   - Output: edit operation, candidate take request, risk approval, or timeline navigation.

8. `Advanced Timeline`
   - Input: selected time range, layers, take.
   - Output: edit operations and candidate takes.

9. `Versioning`
   - Input: operations and generated takes.
   - Output: reproducible current state and approved take.

10. `Preview Engine`
    - Input: take, style preset, selected ranges.
    - Output: snippet preview or full preview render.

11. `Export Engine`
    - Input: approved take and style preset.
    - Output: MP4, ASS, quality report, export metadata.

12. `Style Preset Engine`
    - Input: preset id and overrides.
    - Output: render style for preview and export.

No module should mutate another module's private state.

## Style Scope

This phase uses style presets only.

Supported now:

- choose preset;
- preview preset;
- render MP4 and ASS with preset;
- safe area support;
- schema hook for future overrides.

Not in this phase:

- full visual style editor;
- custom typography UI;
- animation designer;
- marketplace of styles.

The contract must still include `style_preset_id`, `style_overrides`, and `style_version`-compatible data.

## Acceptance Criteria

- User can move through the wizard with explicit step statuses.
- Text Review is required as a review step, but can be skipped with risk and reason.
- Alignment produces a hierarchical take down to syllable and optional melisma segments.
- Quality Review shows prioritized issues by perceptual impact.
- Each issue opens a focused editor before the full timeline.
- Aggressive correction creates an alternate candidate take.
- Manual edits are stored as operations, not destructive rewrites.
- Preview approval is required for risky final export.
- User can export a full preview render.
- Final export produces MP4 and ASS for Aegisub.
- Internal project JSON can represent all entities listed above even if some are initially empty.

## Out Of Scope For First Implementation Plan

- Cloud deployment.
- Authentication and billing.
- Full style editor.
- Benchmark dataset and leaderboard.
- Collaborative multi-user editing.
- Marketplace or sharing features.
- Training a custom model from user corrections.

## Open Implementation Strategy

Implementation should be incremental:

1. Define contracts and schema helpers first.
2. Add wizard state and step approvals.
3. Add prepared text review using existing lyrics flow.
4. Add quality issue model and minimal generated issues.
5. Add focused issue editor UI.
6. Add non-destructive edit operations.
7. Add preview approval gate.
8. Extend alignment toward syllable and melisma detail.
9. Add advanced timeline layers in slices.
10. Harden ASS and MP4 export around approved takes.

Each slice should have tests with explicit timeouts where applicable.
