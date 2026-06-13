# Basic UI Audit Polish Design

## Goal

Improve the basic usability issues found in the June 13 UI sweep without changing pipeline behavior, artifact contracts, timing thresholds, or review decisions.

## Scope

- Keep all existing Flask routes and forms working.
- Improve mobile cockpit readability, especially the waveform/timeline area.
- Reduce keyboard/navigation noise in the alignment review surface.
- Fix visible mojibake in shared templates.
- Add contract tests for the UI safeguards.

## Non-Goals

- No changes to audio alignment, validation, stage contracts, manifests, or pipeline thresholds.
- No redesign of the full product shell.
- No new frontend framework.
- No dependency installation.

## Design

The cockpit keeps its compact technical identity, but the mobile timeline should fit the viewport as a compressed status visualization instead of requiring a 620px internal canvas. The review wizard remains dense on desktop, but bulk timeline markers should not flood the main keyboard path because the queue window already provides structured navigation. Shared templates should render clean ASCII/HTML entities instead of corrupted characters.

## Verification

- Unit-style contract tests inspect templates and CSS for the expected UI rules.
- Browser QA checks desktop and mobile routes for blank pages, console health, and basic interactions.
