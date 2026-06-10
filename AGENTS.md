# Projeto: Karaoke MFA Multi

Este projeto usa Antigravity como IDE, Codex Cowork como orquestrador estratégico e Codex via Ollama como executor local.

## Regras Globais
- Foco em precisão de alinhamento e processamento de áudio.
- Respeitar constraints de tempo e duração mínima de palavras.
- Saídas de modelos locais devem ser tratadas como rascunho não confiável.

## Workflow PAP-Ollama
1. **Context Contract**: Gerar `.Codex/tasks/context-contract.md`.
2. **Local Execution**: `.\.Codex\skills\pap-ollama\scripts\run-ollama.ps1`.
3. **Audit**: Revisão crítica contra regras de alinhamento.

## Skill Routing
- Antes de tarefas estruturais, consultar `docs/skills/routing.md`.
- Hardcodes, configuracao, paths, modelos, host/port e thresholds: usar `hardcoded-config-audit` quando a skill existir.
- Mudancas em estagios `s01`-`s08`, artefatos, manifests ou orquestracao: usar `pipeline-stage-contracts` quando a skill existir.
- Timing, alinhamento, duracao minima, drift, gaps, melisma, sustain ou fallback: usar `audio-alignment-audit` quando a skill existir.

## Alignment Constraints

These values are enforced in code. Changing them affects visual timing, alignment quality, or
validation pass/fail. Update `tests/test_audio_alignment_contracts.py` when any value changes.

### Word Duration Floors

| Constant | Default | Config key | Stage |
|---|---|---|---|
| `min_dur` (alignment) | 50 ms | — (hardcoded floor) | s03b, s04 |
| `MIN_WORD_MS` (display) | 80 ms | — (hardcoded floor) | s06 |
| `validation.min_duration` | 1 ms | — (hardcoded floor) | s08 (find_timestamp_errors) |

- **s03b / s04 `min_dur = 0.050 s`**: Applied during alignment; any word with `end - start < 0.05` is extended. Prevents zero-duration words entering `aligned.json`.
- **s06 `MIN_WORD_MS = 80`**: Applied when building `\kf` segments; any segment shorter than 80 ms is extended so the karaoke fill is perceptible on screen.
- **`validation.min_duration = 0.001 s`**: `find_timestamp_errors` treats words with duration < 1 ms as a hard error.

### Display Window Timing

| Config key | Default | Direction |
|---|---|---|
| `generate_ass_preroll_ms` | 200 ms | Window opens this many ms before first word |
| `generate_ass_postroll_ms` | 300 ms | Window stays open this many ms after last word |
| `generate_ass_gap_ms` | 50 ms | Minimum gap between consecutive line windows |

These are configurable via `pipeline.toml` (`[output]` section) or env vars (`KARAOKE_GENERATE_ASS_PREROLL_MS`, etc.).

### Alignment Snap (s03b only)

| Parameter | CLI flag | Default | Meaning |
|---|---|---|---|
| `snap_window` | `--snap-window` | 0.75 s | Max window to search for a pitch onset when correcting word start |
| `min_word_dur` | — | 0.05 s | Min gap after previous word end before accepting an onset |

### Validation Thresholds

| Config key | Default | Stage |
|---|---|---|
| `validate_overlap_tolerance_s` | 50 ms | s08 (`find_timestamp_errors`, s08) |
| `transcribe_low_confidence_threshold` | 0.25 | s03 (word probability floor for `low_confidence` flag) |
| `transcribe_lc_warning_pct` | 20 % | s03 (% low-confidence words before warning) |
| `vocal_activity.min_duration_s` | 200 ms | review_wizard vocal activity detector |
