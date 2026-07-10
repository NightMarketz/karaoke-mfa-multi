---
name: hardcoded-config-audit
description: Use when changing hardcoded paths, model names, host/port, render defaults, hardware assumptions, config defaults, timing thresholds, or centralizing configuration. Evidence-first — no value moves without a spec rationale and a test.
---

# Hardcoded Config Audit

## Core Rule
Do not replace a hardcoded value because it looks untidy. Replace it only with
evidence, an SDD rationale, and a test that describes the intended behavior.

## When to Use / When Not
- **Use when:** touching paths, model names, host/port, codecs, timeouts, thresholds, or centralizing config (e.g. the machine-specific `pipeline.toml [demix].python`).
- **Do NOT use when:** the value is a domain constant with alignment meaning (that's `audio-alignment-audit`) or an artifact name (that's `pipeline-stage-contracts`).

## SDD Contract (spec-first)
- **Source of truth:** `pipeline.toml` + `scripts/common/config.py` (`DEFAULT_*`), precedence **CLI > env > `pipeline.toml` > default**.
- **Must NOT change:** artifact contracts, alignment thresholds, the config precedence order.

## Required Workflow
1. Build the Evidence Table below **before** editing code.
2. Classify each value (see guide).
3. Keep artifact contracts stable unless `pipeline-stage-contracts` is also in scope; keep alignment thresholds stable unless `audio-alignment-audit` is in scope.
4. Write/update the test **before** the production change (see it fail).
5. Move behind config/env/CLI with the **current value as default** — behavior unchanged.

## Evidence Table
| ID | File | Value | Classification | Risk | Decision | Test |
| --- | --- | --- | --- | --- | --- | --- |
| H001 | `pipeline.toml [demix].python` | `C:/.../demucs_env/python.exe` | runtime configuration | breaks on another machine | keep as default, resolve via env `KARAOKE_DEMIX_PYTHON` | `test_app_config` |

## Classification Guide
| Classification | Examples | Default Decision |
| --- | --- | --- |
| Runtime configuration | paths, model names, host, port, codec, timeout | move to config/env/CLI, current value as default |
| Domain constant | `min_dur`, gap, sustain threshold | keep named + tested; move only with `audio-alignment-audit` |
| Artifact contract | `vocals.wav`, `analysis.json`, `output.ass` | keep stable or use `pipeline-stage-contracts` |
| Test fixture | sample job names, expected outputs | keep in tests |
| Documentation example | command snippets | keep if accurate; link to canonical config |

## Common Mistakes
- Moving artifact names into generic config before proving a real need.
- Changing a threshold's *value* while only meaning to change *where it is read*.
- Setup, runtime, and tests drifting to different defaults for the same value.
- Writing the test after the refactor and never seeing it fail.

## Executable Verification
```bash
pytest tests/test_app_config.py
pytest tests
```
Pass criterion: config resolves via the documented precedence with unchanged
effective defaults; touched-area tests green.
