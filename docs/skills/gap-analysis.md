# Skill Gap Analysis

This document tracks useful project-local skills that do not exist yet. It is
an evidence file, not a mandate to create every listed skill.

## Creation Criteria

A candidate skill should be created only when all of these are true:

- The workflow has been repeated or is likely to recur across multiple tasks.
- The project has domain-specific rules that a general skill will miss.
- The skill can name concrete inputs, outputs, and verification steps.
- The skill reduces ambiguity without hiding important engineering judgment.

## Gap Matrix

| Candidate | Evidence | Priority | Creation Criteria |
| --- | --- | --- | --- |
| `audio-alignment-audit` | Alignment constraints appear in `AGENTS.md`, `s03b_lyrics_align.py`, `s04_align.py`, `s06_generate_ass.py`, `s08_validate.py`, and review wizard timing modules. | High | Create when auditing or changing word duration, drift, gap, melisma, sustain, or fallback timing behavior. |
| `hardcoded-config-audit` | Hardcoded paths, models, host/port, thresholds, render defaults, and hardware assumptions were found across setup, server, and pipeline scripts. | High | Create before structural config refactors so each change has evidence, SDD rationale, and tests. |
| `pipeline-stage-contracts` | Stages `s01` through `s08` exchange fixed artifacts such as `vocals.wav`, `transcript.json`, `aligned.json`, `analysis.json`, `output.ass`, and manifests. | High | Create when editing stage inputs, outputs, invalidation rules, manifests, or pipeline orchestration. |
| `review-wizard-qa` | Review wizard modules cover stages, review points, issue resolution, quality gates, preview approval, versioning, and export decisions. | Medium | Create when changing review UX behavior, risk approval, export gating, or preview workflow contracts. |
| `karaoke-style-library` | Style presets, section mapping, effects, and ASS styling are central to output quality and appear in both style library and generation paths. | Medium | Create when adding presets, changing section mapping, or modifying ASS style/effect semantics. |
| `provenance-artifact-audit` | Provenance helpers, manifests, hashes, artifact reuse audit notes, and clean-output integration tests already exist. | Medium | Create when changing artifact reuse, manifest schema, hash validation, or regeneration audit behavior. |
| `pap-ollama-audit` | PAP-Ollama is now present across `.Codex`, `.claude`, and `.agents`, with local model output explicitly treated as untrusted draft material. | Low | Create if local Ollama workflows become more than prompt generation and require repeatable audit checklists. |

## Recommended Order

1. `hardcoded-config-audit`
2. `pipeline-stage-contracts`
3. `audio-alignment-audit`
4. `provenance-artifact-audit`
5. `review-wizard-qa`
6. `karaoke-style-library`
7. `pap-ollama-audit`

## Current Decision

Do not create these skills in this slice. Keep the list as a planning and
review tool until a task needs one of the workflows.
