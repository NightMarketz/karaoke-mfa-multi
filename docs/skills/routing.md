# Skill Routing

This is the mandatory routing map for project-local skills. Use it before
structural tasks, code review tasks, PAP-Ollama work, and any change touching
audio alignment or pipeline contracts.

## Mandatory Routing

| Trigger | Use Skill | Why |
| --- | --- | --- |
| Hardcoded paths, model names, host/port, render defaults, hardware assumptions, configuration defaults, or threshold centralization. | `hardcoded-config-audit` | These changes are easy to justify aesthetically but risky without evidence, SDD rationale, and tests. |
| Stage `s01`-`s08` inputs, outputs, artifact names, stage order, invalidation targets, manifests, or pipeline runner behavior. | `pipeline-stage-contracts` | The pipeline depends on fixed contracts between stages; a small artifact mismatch can break later steps. |
| Word timing, minimum duration, drift tolerance, gap classification, melisma, sustain, pitch snapping, CTC fallback, HubertFA fallback, or ASS timing. | `audio-alignment-audit` | Alignment quality is the core product constraint and must be protected by explicit checks. |
| Review Wizard stages, review points, issue approval, risk approval, preview render, full preview approval, or export gate behavior. | `review-wizard-qa` | The review flow combines state, UX, and quality decisions that need repeatable QA rules. |
| ASS presets, section mapping, style aliases, supported effects, color/style semantics, or karaoke visual profiles. | `karaoke-style-library` | Styling changes should not duplicate section rules or silently alter rendering semantics. |
| Manifest schema, hash validation, provenance metadata, artifact reuse, clean-output behavior, or regeneration audits. | `provenance-artifact-audit` | Export artifacts must remain traceable to current inputs and not stale runtime leftovers. |
| PAP-Ollama prompts, local Ollama execution, model selection, context contracts, or audit of local model output. | `pap-ollama-audit` | Local model output is an untrusted draft and must stay behind a context contract plus human/Codex audit. |

## Combination Order

Use process skills first, then project-local domain skills.

1. For unclear work, use brainstorming or planning before implementation.
2. For code changes, use TDD before production code.
3. Add project-local skills based on the trigger table.
4. If multiple triggers apply, use the most structural skill first:
   `hardcoded-config-audit`, then `pipeline-stage-contracts`, then
   `audio-alignment-audit`, then narrower workflow skills.

Examples:

- Centralizing render defaults uses `hardcoded-config-audit`; if artifact names
  or stage order change, also use `pipeline-stage-contracts`.
- Changing minimum word duration uses `audio-alignment-audit`; if the value
  moves into shared config, also use `hardcoded-config-audit`.
- Changing review export approval uses `review-wizard-qa`; if manifests or
  hashes change, also use `provenance-artifact-audit`.

## Do Not Use

Do not use a project-local skill when the task only asks for read-only status,
simple file listing, or a narrow explanation that does not touch the trigger
areas above.

Do not create a new skill during routing. New skills must first pass the
creation criteria in [Skill Gap Analysis](gap-analysis.md).

Do not let a local model draft bypass tests, provenance checks, or alignment
constraints.
