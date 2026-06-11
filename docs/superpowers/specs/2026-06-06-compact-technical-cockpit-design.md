# Compact Technical Cockpit Design

## Status

Approved visual direction for planning. The source mockup is:

`docs/superpowers/assets/2026-06-06-compact-technical-cockpit.png`

This mockup is the primary visual reference. A later Review Wizard pass should inherit this design language, but the second generated Review Wizard concept is not the source of truth.

## Goal

Create a new primary screen for Karaoke MFA Multi that feels like a compact technical audio-alignment cockpit. The first viewport should focus on starting a new karaoke job, while still exposing project status, waveform context, quality signals, and a quick Review mode.

The screen should be serious, dense, and precise: closer to an audio QA console than a music social app.

## Product Scope

In scope:

- A new main workspace whose default mode is `New Karaoke`.
- A `Review` mode in the same workspace for quick issue triage.
- A bottom project rail for recent jobs and resuming work.
- A central waveform/timeline region that anchors the product identity.
- A right diagnostics panel for pipeline stages, artifacts, validation, and errors.
- A fixed bottom transport/player bar for preview and navigation.
- Navigation from quick Review triage into the existing Review Wizard.

Out of scope for this design slice:

- Replacing all Review Wizard internals.
- A full timing editor in the main screen.
- User accounts, public sharing, music feed behavior, or Suno-like social affordances.
- A full visual style editor.
- New pipeline contracts or stage artifact names.

## Primary Screen Structure

The screen uses a fixed app shell:

- Left sidebar: compact navigation for New, Projects, Review, Exports, and Settings. The active state should be visually quiet and precise.
- Top command strip: project title, current mode, language, preset, duration, pipeline status, quality state, and export readiness.
- Left task panel: default `New Karaoke` form with audio/stems upload, lyrics input or preview, preset selection, and `Start Processing`.
- Main canvas: waveform/timeline workspace with layered lanes for vocals, lyrics, issues, confidence, and playhead.
- Right diagnostics panel: `s01`-`s08` status rows, artifact checklist, validation state, and recent actionable errors.
- Bottom project rail: horizontal recent-job list with compact thumbnail/status, stage, score, duration, and resume action.
- Bottom player bar: transport controls, scrubber, timestamp, active lyric segment, vocal/instrumental toggles, preview, and export shortcuts.

## New Karaoke Mode

`New Karaoke` is the default mode when the app opens.

The left task panel should make the happy path obvious:

1. Add audio or stems.
2. Paste or import lyrics.
3. Choose language and style preset.
4. Start processing.

The central timeline should still be visible before processing. Empty state content should feel like an inactive waveform workspace, not a marketing panel. It may show upload zones, expected lanes, and a muted preview of how evidence will appear.

The right diagnostics panel should show a pending stage list before a job starts, then live stage status as the pipeline runs.

## Quick Review Mode

Clicking `Review` changes the main workspace mode instead of navigating away immediately.

Quick Review is a triage surface, not a full editor. It should show:

- The current highest-priority issue.
- A mini waveform or selected timeline region.
- Time range, issue type, severity, confidence, and evidence summary.
- A short affected lyric excerpt.
- Actions: `Approve`, `Apply Suggestion`, `Skip With Risk`, and `Open Review Wizard`.
- A compact queue of next issues.

Allowed quick actions:

- Approve a low-risk review point.
- Apply an existing suggestion when the backend already exposes one.
- Skip with risk and require a reason.
- Open the Review Wizard at the active issue or stage.

Not allowed in Quick Review:

- Dragging word or syllable boundaries.
- Editing melisma segments.
- Rebuilding takes.
- Approving final export when preview approval is required.

Those actions remain in the Review Wizard.

## Review Wizard Relationship

The Review Wizard remains the deep workflow for quality review, preview approval, risk resolution, and export readiness. The main cockpit should link into the Wizard with enough context to land on the active stage or issue.

The navigation model is:

`New Karaoke -> processing status -> Quick Review -> Review Wizard -> Export`

The user should be able to return from the Review Wizard to the cockpit without losing the selected job context.

## Visual System

The visual language should match the selected mockup:

- Base background: near black.
- Panels: graphite and charcoal surfaces with thin dividers.
- Borders: subtle cool gray, not bright neon frames.
- Accents: cyan for evidence, violet for waveform/timeline selection, amber for risk, red for critical issues, green for approved/ready states.
- Radius: 8px or less.
- Typography: compact modern sans-serif; small control labels must be deliberately styled.
- Density: high enough for professional work, with stable row heights and no oversized hero copy.
- Cards: only for repeated project items, issue rows, and compact focused panels.

Avoid:

- Suno branding, exact layout copying, song feed behavior, public/liked/social controls.
- Decorative gradient blobs, bokeh, or marketing-style hero sections.
- Large rounded nested cards.
- One-note purple-only palette.
- Generic SaaS metrics unrelated to alignment quality.

## Component Families

Core component families:

- App shell navigation.
- Mode segmented control: `New Karaoke` and `Review`.
- Upload/input form blocks.
- Compact status chips.
- Stage status rows for `s01` through `s08`.
- Artifact checklist rows.
- Timeline lanes and markers.
- Issue triage row and focused issue panel.
- Project rail item.
- Transport/player controls.

The implementation should reuse shared primitives for buttons, chips, stage rows, issue rows, and timeline markers so the UI does not become one-off CSS.

## Data Flow

The screen should read from existing job metadata and status contracts where possible:

- `meta.json` for job identity and inputs.
- `status.json` for current stage and progress.
- Review Wizard project state for issues, review points, quality reports, preview renders, and export decision.
- Existing artifact availability checks for MP4, ASS, logs, validation output, and preview files.

The main cockpit should not invent new authoritative state for pipeline stages or review decisions. It can create UI-specific view models derived from existing contracts.

## Error Handling

Errors should be visible in the right diagnostics panel and, when tied to a review issue, in Quick Review.

Error presentation rules:

- Show the failed stage.
- Show a short actionable reason.
- Keep debug artifacts discoverable.
- Do not allow final export readiness to appear green if validation or required preview approval is blocked.
- Risk skips must collect a reason before submission.

## Testing Strategy

Initial implementation should include focused tests for:

- The new main route renders with no jobs.
- The new main route renders with recent jobs.
- A selected job exposes derived stage status from existing status data.
- Quick Review mode renders the active issue and action URLs.
- `Open Review Wizard` links to the correct job and active issue/stage context.
- Export readiness does not show ready when the Review Wizard export gate blocks it.
- Mobile or narrow view does not overlap controls, timeline labels, or project rail text.

Visual verification should include desktop and mobile screenshots against the selected mockup's design language after implementation.

## Acceptance Criteria

- The app opens to the new cockpit with `New Karaoke` as the primary mode.
- Recent projects are visible in a bottom rail.
- A selected or running job shows timeline context, pipeline status, artifacts, and validation signals.
- `Review` mode swaps the main task panel into quick issue triage.
- Quick triage exposes approve, apply suggestion, skip with risk, and open Wizard actions when supported by the backend.
- Deep timing and export decisions remain in the Review Wizard.
- The UI feels like a precise alignment cockpit and not a social music feed.
