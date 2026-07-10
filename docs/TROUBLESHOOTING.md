# Troubleshooting

Problemas comuns, contra o pipeline real (`s01–s08`, config em `pipeline.toml`).

## 1. Download bloqueado (HTTP 403 em `output.mp4`/`output.ass`)
É o **export gate**, não um bug. O motivo vem de `_blocked_final_export_reason`:
- `blocked_missing_artifact` / `artifact_missing` — o arquivo não existe em disco.
- `blocked_hash_mismatch` / `artifact_changed` — o artefato mudou depois de aprovado (hash diverge do manifest).
- `blocked_quality_review_required` — falta um quality report aprovado.
- `blocked_preview_required` / `blocked_full_preview_required` — falta aprovar o preview no Review Wizard.

**Solução:** abra `/job/<id>/review` e complete o fluxo (aprovar issues → aprovar
preview). Se regerou algo, o hash muda e o estado volta para `quality_review` —
reaprovar. Ver [../spec/STATE_MACHINES.md](../spec/STATE_MACHINES.md).

## 2. Job recusado sem letra
No MVP a **letra é obrigatória** ([ADR-002](../spec/ADR/ADR-002-lyrics-first-mvp.md)).
Envie `lyrics_text` no `/job/new`. Sem letra o pipeline cai no fallback Whisper,
menos confiável.

## 3. Demucs falhou / separação de voz não roda (`s02`)
O `s02` roda o Demucs num Python **isolado**, cujo caminho está em
`pipeline.toml [demix].python`. Esse valor é **absoluto e específico da máquina**
(ex.: `C:/Users/Katz/miniforge3/envs/demucs_env/python.exe`).
**Solução:** ajuste `[demix].python` (ou o env `KARAOKE_DEMIX_PYTHON`) para o seu
ambiente Demucs. Confirme com `pip show demucs` nesse ambiente. Timeout padrão:
1800s.

## 4. Análise trava ou volta genérica (`s05`)
Só o caminho **sem letra** usa Ollama (`[analyze].ollama_url`,
`localhost:11434`). Se o Ollama não está no ar, há fallback por regra, mas o
resultado piora. No caminho **com letra** (MVP) a análise é determinística e não
depende de Ollama.

## 5. Alinhamento de fonemas falha (`s04`)
O `s04` usa **HubertFA (ONNX)**; o checkpoint é `[align].checkpoint`
(`models/hubertfa/model.onnx`) e o código em `[align].hubertfa_dir`
(`vendor/HubertFA`). Faltando o checkpoint, o alinhamento cai no fallback linear
por segmento (menos preciso). **Solução:** garanta o `.onnx` no caminho
configurado.

## 6. Estágio estoura timeout
O watchdog de cada estágio = timeout de config do estágio **+ 60s**
(`pipeline_runner.py`). Ajuste o timeout do estágio em `pipeline.toml`
(`hubertfa_timeout_s`, `ollama_timeout_s`, `output_ffmpeg_timeout_s`, etc.) para
máquinas mais lentas.

## 7. `retry-validate` recusado (409)
Só é permitido re-rodar a validação quando o job **falhou exatamente no estágio
`validating`** (progress 95) e não está mais rodando (FR-018). Para outras
falhas, re-rode o estágio pertinente (que invalida os artefatos downstream).

## 8. Linhas longas demais no karaokê
Quebre a letra em linhas curtas (uma frase por linha; use as pausas de
respiração como quebra). Estilo/efeito vêm da Style Library
([ADR-004](../spec/ADR/ADR-004-versioned-style-library.md)), não de edição manual do ASS.
