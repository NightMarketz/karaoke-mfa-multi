# SDD — Karaoke MFA Multi

## 3.1 Visão técnica

O sistema é uma aplicação local Flask que orquestra scripts de pipeline por subprocessos. Cada etapa lê e escreve arquivos padronizados dentro de `jobs/{job_id}`.

```txt
Flask UI/API
  -> PipelineRunner
    -> s03b lyrics align
    -> s04 align/refine
    -> s05 analyze
    -> s06 generate ASS
    -> s07 render MP4
    -> s08 validate
  -> Review Wizard
  -> Export Gate
```

## 3.2 Diretório de job

```txt
jobs/{job_id}/
  meta.json
  status.json
  events.jsonl
  lyrics.txt
  vocals.wav
  instrumental.wav
  transcript.json
  aligned.json
  analysis.json
  output.ass
  output.ass.manifest.json
  output.mp4
  output.mp4.manifest.json
  review_wizard.json
  observability_summary.json
  preview_full.mp4
  preview_full.manifest.json
```

## 3.3 Componentes principais

| Componente                          | Responsabilidade                                                                   |
| ----------------------------------- | ---------------------------------------------------------------------------------- |
| `server.py`                         | Rotas Flask, upload, job lifecycle, Review Wizard, export/download gates.          |
| `scripts/pipeline_runner.py`        | Plano de etapas, subprocessos, timeouts, status, eventos e invalidação downstream. |
| `scripts/s03b_lyrics_align.py`      | Forced alignment usando letra.                                                     |
| `scripts/s04_align.py`              | Refinamento de timing, phonemes e fallback.                                        |
| `scripts/s05_analyze.py`            | Agrupamento de linhas e aplicação de estilos.                                      |
| `scripts/s06_generate_ass.py`       | Geração ASS com `\kf` e manifest.                                                  |
| `scripts/s07_output.py`             | Render MP4 via ffmpeg e manifest.                                                  |
| `scripts/s08_validate.py`           | Validação de contratos e bloqueios.                                                |
| `scripts/common/`                   | Config, safe paths, status, validation, observability, provenance.                 |
| `scripts/review_wizard/`            | Estado de revisão, issues, quality reports, preview e export gate.                 |
| `scripts/karaoke_styles/library.py` | Fonte única de presets, style keys e efeitos.                                      |
| `templates/`, `static/`             | Cockpit, formulário, job detail, Review Wizard, JS/CSS.                            |

## 3.4 Pipeline

| Stage  | Script                 | Inputs                                 | Outputs                          | Contrato                           |
| ------ | ---------------------- | -------------------------------------- | -------------------------------- | ---------------------------------- |
| `s01`  | `s01_input.py`         | Áudio/vídeo                            | `input.wav`, `metadata.json`     | Normaliza entrada legada.          |
| `s02`  | `s02_demix.py`         | Mix único                              | `vocals.wav`, `instrumental.wav` | Opcional no web MVP.               |
| `s03`  | `s03_transcribe.py`    | `vocals.wav`                           | `transcript.json`                | Whisper fallback.                  |
| `s03b` | `s03b_lyrics_align.py` | `vocals.wav`, `lyrics.txt`             | `transcript.json`                | Caminho feliz do MVP.              |
| `s04`  | `s04_align.py`         | `vocals.wav`, `transcript.json`        | `aligned.json`                   | Timing final e phonemes opcionais. |
| `s05`  | `s05_analyze.py`       | `transcript.json`, `aligned.json`      | `analysis.json`                  | Linhas, estilos e palavras.        |
| `s06`  | `s06_generate_ass.py`  | `analysis.json`, opcional `vocals.wav` | `output.ass`, manifest           | ASS com `\kf`.                     |
| `s07`  | `s07_output.py`        | `instrumental.wav`, ASS                | `output.mp4`, manifest           | Render ffmpeg.                     |
| `s08`  | `s08_validate.py`      | Artefatos principais                   | validation summary               | Falha contratos quebrados.         |

## 3.5 Plano de execução web

```txt
queued
  -> aligning_lyrics | transcribing
  -> aligning
  -> analyzing
  -> generating
  -> rendering
  -> validating
  -> done | failed
```

| Stage web                           | Progresso | Timeout                                  |
| ----------------------------------- | --------: | ---------------------------------------- |
| `aligning_lyrics` ou `transcribing` |        5% | timeout de transcrição/alinhamento + 60s |
| `aligning`                          |       25% | `align_hubertfa_timeout_s + 60s`         |
| `analyzing`                         |       50% | `ollama_timeout_s + 60s`                 |
| `generating`                        |       70% | `generate_ass_timeout_s + 60s`           |
| `rendering`                         |       85% | `output_ffmpeg_timeout_s + 60s`          |
| `validating`                        |       95% | `validate_timeout_s + 60s`               |
| `done`                              |      100% | terminal                                 |

## 3.6 Invalidação downstream

| Antes de rerodar | Apagar                                                                                                                                                |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `analyzing`      | `analysis.json`, `output.ass`, `output.ass.manifest.json`, `output.mp4`, `output.mp4.manifest.json`, `preview_full.mp4`, `preview_full.manifest.json` |
| `generating`     | `output.ass`, `output.ass.manifest.json`, `output.mp4`, `output.mp4.manifest.json`, `preview_full.mp4`, `preview_full.manifest.json`                  |
| `rendering`      | `output.mp4`, `output.mp4.manifest.json`, `preview_full.mp4`, `preview_full.manifest.json`                                                            |

## 3.7 Rotas

| Método | Rota                                                      | Contrato                                  |
| ------ | --------------------------------------------------------- | ----------------------------------------- |
| `GET`  | `/`                                                       | Cockpit/dashboard.                        |
| `GET`  | `/job/new`                                                | Formulário de upload.                     |
| `POST` | `/job/new`                                                | Cria job; exige letra e preset válido.    |
| `GET`  | `/job/<job_id>`                                           | Detalhe, status e links.                  |
| `GET`  | `/job/<job_id>/review`                                    | Cria/abre Review Wizard.                  |
| `POST` | `/job/<job_id>/review/points/<point_id>/approve`          | Aprova ponto de revisão.                  |
| `POST` | `/job/<job_id>/review/points/<point_id>/apply-suggestion` | Registra sugestão aplicada.               |
| `POST` | `/job/<job_id>/review/points/<point_id>/skip-risk`        | Pula ponto com risco aceito.              |
| `POST` | `/job/<job_id>/review/preview/critical-snippets/approve`  | Aprova previews críticos.                 |
| `POST` | `/job/<job_id>/review/preview/full/render`                | Renderiza preview completo.               |
| `POST` | `/job/<job_id>/review/preview/full/approve`               | Aprova preview completo.                  |
| `GET`  | `/job/<job_id>/stream`                                    | SSE de `status.json`.                     |
| `GET`  | `/job/<job_id>/output.mp4`                                | Serve MP4 somente se export gate liberar. |
| `GET`  | `/job/<job_id>/output.ass`                                | Serve ASS somente se export gate liberar. |
| `GET`  | `/job/<job_id>/metrics`                                   | Métricas quando houver referência.        |
| `GET`  | `/job/<job_id>/events`                                    | Eventos sanitizados.                      |
| `POST` | `/job/<job_id>/delete`                                    | Remove job se não estiver rodando.        |
| `POST` | `/job/<job_id>/retry-validate`                            | Retry apenas se falhou em `validating`.   |

## 3.8 Configuração

Fonte principal:

```txt
pipeline.toml
```

Áreas:

| Seção          | Chaves                                            |
| -------------- | ------------------------------------------------- |
| `[general]`    | `jobs_dir`, `log_level`                           |
| `[server]`     | `host`, `port`, `secret_key`, `max_upload_mb`     |
| `[ui]`         | `default_style_preset`                            |
| `[hardware]`   | `profile = auto \| z13 \| cpu_only`               |
| `[demix]`      | modelo, timeout, Python do env Demucs             |
| `[transcribe]` | modo, modelo, linguagem, thresholds               |
| `[align]`      | HubertFA dir, checkpoint, language, timeout       |
| `[analyze]`    | Ollama URL, modelo, temperature, timeout          |
| `[generate]`   | preset, resolução, fade                           |
| `[output]`     | codec, bitrate, volumes, framerate, timeout       |

## 3.9 Segurança

| Área     | Regra                                                                     |
| -------- | ------------------------------------------------------------------------- |
| ZIP      | Rejeitar path traversal, `__MACOSX`, paths absolutos e membros inseguros. |
| Upload   | Validar extensão, tamanho e presença de stems obrigatórios.               |
| Job ID   | Usar identificador seguro, não derivado diretamente de input do usuário.  |
| Paths    | Resolver paths dentro de `jobs/{job_id}`.                                 |
| Download | Passar por export gate.                                                   |
| Delete   | Bloquear se job estiver rodando.                                          |
| Logs     | Sanitizar eventos antes de expor na UI.                                   |
