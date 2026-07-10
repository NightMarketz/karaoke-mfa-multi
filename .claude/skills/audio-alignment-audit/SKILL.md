---
name: audio-alignment-audit
description: Use when changing timing constants, alignment thresholds, melisma/sustain handling, snap window, preroll/postroll/gap, min word duration, or anything touching forced alignment (s03b), phoneme alignment (s04), or ASS timing (s06). Load-bearing timing values must move only with evidence and the snapshot test.
---

# Audio Alignment Audit

## Core Rule
The timing constants are load-bearing and pinned by a snapshot test. Never
change one without (a) a reason grounded in audio evidence and (b) updating
`tests/test_audio_alignment_contracts.py` in the **same commit**.

## When to Use / When Not
- **Use when:** editing `min_dur`, `MIN_WORD_MS`, overlap tolerance, `--snap-window`, `preroll`/`postroll`/`gap`, melisma/sustain thresholds, or the drift/low-confidence logic.
- **Do NOT use when:** the change is a runtime path/model/timeout (that's `hardcoded-config-audit`) or an artifact schema (that's `pipeline-stage-contracts`).

## SDD Contract (spec-first)
- **Source of truth:** [../../../spec/PROJECT_CONSTITUTION.md](../../../spec/PROJECT_CONSTITUTION.md) §3 (the constants table with file:line) and the snapshot `tests/test_audio_alignment_contracts.py`.
- **Evidence policy** (Constitution §4): clear voice beat > metric beat; CTC alone never creates melisma; pitch alone never creates visible text; aggressive correction → candidate take, never silent overwrite.
- **Must NOT change:** the *meaning* of a constant, or its value, without the snapshot test moving with it.

## The constants (defaults)
| Constant | Default | file:line |
| --- | --- | --- |
| `min_dur` (align) | 50 ms | `scripts/s03b_lyrics_align.py:485`, `scripts/s04_align.py:177` |
| `MIN_WORD_MS` | 80 ms | `scripts/s06_generate_ass.py:456` |
| `min_duration` (validate) | 1 ms | `scripts/common/validation.py:8` |
| overlap tolerance | 0.05 s | `scripts/common/config.py:53` |
| `--snap-window` | 0.75 s | `scripts/s03b_lyrics_align.py:1034` |
| preroll / postroll / gap | 200 / 300 / 50 ms | `scripts/common/config.py:35-37` |

## Required Workflow
1. Read Constitution §3–§4 and the snapshot test.
2. Build an evidence row: which audio observation justifies the change, and which of `s03b`/`s04`/`s06`/`validation` it touches.
3. Update `tests/test_audio_alignment_contracts.py` to the new expected value **first**; watch it fail against current code.
4. Change the code; make the snapshot pass.
5. Confirm no downstream behavior regressed (timing-behavior tests).

## Common Mistakes
- Changing a value in code but not in the snapshot (silent contract drift).
- Treating `--snap-window` function-signature default (1.5s) as effective — the CLI default (0.75s) wins.
- Creating melisma/text from a single modality (violates the evidence policy).

## Executable Verification
```bash
pytest tests/test_audio_alignment_contracts.py tests/test_timestamp_validation.py \
      tests/test_timing_layers.py tests/test_ass_generation.py tests/test_highlight_velocity.py
```
Pass criterion: snapshot matches code, and timing-behavior tests green.
