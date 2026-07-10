---
name: pipeline-stage-contracts
description: Use when changing any pipeline artifact — transcript.json, aligned.json, analysis.json, output.ass, manifests — their fields, the stage that writes them, or the artifact dependency graph (s01–s08). Artifact schemas are contracts; change the contract test first.
---

# Pipeline Stage Contracts

## Core Rule
Artifact names and shapes are contracts consumed by later stages, the server,
and the tests. Change a schema only by updating its contract test first, keeping
the artifact dependency graph intact.

## When to Use / When Not
- **Use when:** editing what a stage reads/writes, an artifact's JSON fields, the ASS structure, a manifest's fields, or the stage ordering/invalidation.
- **Do NOT use when:** the change is a timing constant (`audio-alignment-audit`) or a runtime config value (`hardcoded-config-audit`).

## SDD Contract (spec-first)
- **Source of truth:** [../../../spec/DATA_DICTIONARY.md](../../../spec/DATA_DICTIONARY.md) (per-artifact schema + the test that pins it) and [../../../spec/SDD.md](../../../spec/SDD.md) §2 (stage I/O) & §4 (invalidation). Master schema test: `tests/test_pipeline_stage_contracts.py`.
- **Must NOT change:** artifact filenames, the ordering gates (transcript→s04, aligned→s05, analysis→s06, ass+manifest→s07, mp4 manifest→export), append-only `events.jsonl`, provenance hash chain.

## Artifact → contract test
| Artifact | Pinned by |
| --- | --- |
| transcript.json / aligned.json / analysis.json / graph | `test_pipeline_stage_contracts` |
| analysis.json (lines/style/coverage) | `test_analysis_contract` |
| output.ass (structure, `\kf`, colors) | `test_s06_style_contracts`, `test_ass_generation` |
| manifests (sha256/size/created_at) | `test_provenance_contracts` |
| cross-artifact chain analysis→ass→mp4 | `test_validate_contracts` |
| meta.json / status.json | `test_common_contracts` |
| events.jsonl / summary.json | `test_observability_contracts` |

## Required Workflow
1. Read the artifact's row in DATA_DICTIONARY and open its contract test.
2. If adding/removing/renaming a field, update the contract test **first** (watch it fail).
3. Change the writer stage; keep the filename and dependency graph stable.
4. If the artifact feeds a later stage, update that consumer and its test too.
5. If a stage rerun must drop downstream artifacts, honor `_INVALIDATION_TARGETS` (SDD §4).

## Common Mistakes
- Renaming an artifact file (breaks every consumer + the graph).
- Adding a field without extending the contract test (silent schema drift).
- Regenerating an artifact without invalidating downstream manifests (breaks the export gate hash chain).

## Executable Verification
```bash
pytest tests/test_pipeline_stage_contracts.py tests/test_analysis_contract.py \
      tests/test_ass_generation.py tests/test_s06_style_contracts.py \
      tests/test_provenance_contracts.py tests/test_validate_contracts.py tests/test_observability_contracts.py
```
Pass criterion: every touched artifact's contract test passes and the dependency
graph is unchanged.
