---
name: hardcoded-config-audit
description: Use when changing hardcoded paths, model names, host or port values, render defaults, hardware assumptions, configuration defaults, timing thresholds, or centralizing project configuration.
---

# Hardcoded Config Audit

## Core Rule

Do not replace hardcoded values because they look untidy. Replace them only
when there is Evidence, SDD rationale, and tests that describe the intended
behavior.

## Required Workflow

1. Build an evidence table before editing code.
2. Classify each value as runtime configuration, domain constant, artifact
   contract, test fixture, or documentation example.
3. Keep artifact contracts stable unless `pipeline-stage-contracts` is also in
   scope.
4. Keep alignment thresholds stable unless `audio-alignment-audit` is also in
   scope.
5. Write or update tests before production code changes.
6. Prefer the precedence `CLI args` > `environment` > `pipeline.toml` >
   internal defaults.

## Evidence Table

Use this shape in the context contract or audit document:

| ID | File | Value | Classification | Risk | Decision | Test |
| --- | --- | --- | --- | --- | --- | --- |
| H001 | `scripts/s02_demix.py` | `C:/.../demucs_env/python.exe` | runtime configuration | Breaks on another machine | Move behind config/env resolution | `test_demucs_python_prefers_env_override` |

## Classification Guide

| Classification | Examples | Default Decision |
| --- | --- | --- |
| Runtime configuration | paths, model names, host, port, codec, timeout | Move to config/env/CLI with current value as default. |
| Domain constant | minimum word duration, gap threshold, sustain threshold | Keep named and tested; move only with alignment tests. |
| Artifact contract | `vocals.wav`, `analysis.json`, `output.ass` | Keep stable or use `pipeline-stage-contracts`. |
| Test fixture | sample job names, expected outputs | Keep in tests unless shared fixtures reduce duplication. |
| Documentation example | command snippets, examples | Keep if accurate; link to canonical config docs when possible. |

## Common Mistakes

- Moving artifact names into generic config before proving a real need.
- Changing threshold values while only intending to change where they are read.
- Letting setup scripts, runtime scripts, and tests keep different defaults for
  the same model or path.
- Writing tests after the refactor and never seeing them fail.

## Verification

At minimum, run the focused tests for the touched area and
`python -m unittest tests.test_project_knowledge_base` when routing or docs
change.
