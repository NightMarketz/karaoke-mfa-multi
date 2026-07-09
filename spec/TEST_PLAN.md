# TEST_PLAN — Karaoke MFA Multi

## 12.1 Estratégia

A suíte de testes deve proteger contratos, não detalhes frágeis de implementação.

Prioridade:

1. Contratos de artefatos.
2. Segurança de paths/upload.
3. Export gate.
4. Timing mínimo.
5. Provenance.
6. Review Wizard.
7. Integração pipeline.
8. UI apenas depois dos contratos.

## 12.2 Testes unitários

| Área          | Casos                                                                  |
| ------------- | ---------------------------------------------------------------------- |
| Safe paths    | Rejeita `../`, path absoluto, `__MACOSX`, nomes inseguros.             |
| Style Library | Presets existem, effects válidos, fallback de section é observável.    |
| Lyrics parser | Sections conhecidas, markers desconhecidos, linhas vazias, repetições. |
| Timing floors | 50 ms em alinhamento, 80 ms em ASS, 1 ms em validação.                 |
| Hashing       | SHA-256 correto para inputs/outputs.                                   |
| Config        | Defaults e env overrides funcionam.                                    |

## 12.3 Testes de contrato

| Arquivo de teste                          | Protege                                                    |
| ----------------------------------------- | ---------------------------------------------------------- |
| `tests/test_pipeline_stage_contracts.py`  | Schemas de artefatos e invalidation downstream.            |
| `tests/test_audio_alignment_contracts.py` | Floors e thresholds de alinhamento/display/validação.      |
| `tests/test_ass_generation.py`            | ASS, timing e render semantics.                            |
| `tests/test_s06_style_contracts.py`       | Styles e effects no ASS.                                   |
| `tests/test_karaoke_style_library.py`     | Preset ids, style keys e section mapping.                  |
| `tests/test_review_wizard_contracts.py`   | Schema do projeto de revisão.                              |
| `tests/test_review_wizard_export_gate.py` | Gate, previews e risco aceito.                             |
| `tests/test_server_contracts.py`          | Uploads, busy state, events, outputs e retry validate.     |
| `tests/test_provenance_contracts.py`      | Manifests, hashes e artifact graph.                        |
| `tests/test_timing_layers.py`             | Timing audio-backed, tails, drift e review-only decisions. |
| `scripts/test_lyrics_robustness.py`       | Parser, sections, snapping e regressões.                   |

## 12.4 Testes de integração

### Cenário 1 — ZIP válido com letra

Entrada:

* ZIP com vocal e instrumental.
* `lyrics_text`.
* Preset válido.

Esperado:

* `meta.json`.
* `status.json`.
* `lyrics.txt`.
* `vocals.wav`.
* `instrumental.wav`.
* `transcript.json`.
* `aligned.json`.
* `analysis.json`.
* `output.ass`.
* `output.ass.manifest.json`.
* `output.mp4`.
* `output.mp4.manifest.json`.
* `status.stage = done`.

### Cenário 2 — Stems separados

Entrada:

* `vocals`.
* `instrumental`.
* letra.
* preset.

Esperado:

* Conversão para WAV padrão.
* Pipeline completo.
* Manifests válidos.
* Export depende do gate.

### Cenário 3 — Sem letra

Esperado:

* Job não deve seguir caminho feliz do MVP.
* Erro claro.
* Export impossível.

### Cenário 4 — Preset inválido

Esperado:

* Falha antes de criar artefatos pesados.
* Nenhuma troca silenciosa para default.

### Cenário 5 — Manifest alterado

Ação:

* Gerar job válido.
* Alterar `output.ass` depois do manifest.

Esperado:

* Export gate bloqueia.
* Erro indica hash mismatch.

### Cenário 6 — Preview obrigatório

Ação:

* Criar quality report `needs_fix`.

Esperado:

* Download bloqueado.
* Critical snippets ou full preview exigidos.
* Export liberado somente depois da aprovação correta.

## 12.5 Testes de segurança

| Caso                            | Esperado                |
| ------------------------------- | ----------------------- |
| ZIP com `../evil.wav`           | Rejeitado.              |
| ZIP com path absoluto           | Rejeitado.              |
| ZIP com `__MACOSX`              | Rejeitado.              |
| Upload acima de `max_upload_mb` | Rejeitado.              |
| Job ID malicioso na URL         | 404 ou rejeição segura. |
| Delete durante execução         | Bloqueado.              |
| Download antes do gate          | Bloqueado.              |

## 12.6 Testes de observabilidade

| Caso                  | Esperado                           |
| --------------------- | ---------------------------------- |
| Stage inicia          | Evento `stage_started`.            |
| Stage termina         | Evento `stage_command_finished`.   |
| Stage falha           | Evento `stage_failed` com details. |
| Downstream invalidado | Evento `downstream_invalidated`.   |
| Validação falha       | Summary com failures.              |
| Warning de qualidade  | Summary com warnings.              |

## 12.7 Testes manuais mínimos

* [ ] ASS abre no Aegisub.
* [ ] MP4 toca com áudio.
* [ ] Highlight por palavra é perceptível.
* [ ] Review Wizard mostra issues.
* [ ] Preview completo pode ser renderizado.
* [ ] Export bloqueia quando deve.
* [ ] Export libera quando deve.
* [ ] Logs/eventos ajudam a diagnosticar falha.

## 12.8 Comandos mínimos

```bash
python -m pytest
python scripts/s08_validate.py --job-dir jobs/<job_id>
python scripts/test_lyrics_robustness.py
```
