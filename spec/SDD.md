# SDD — Software Design Document

Desenho técnico fiel ao branch `mvp-pipeline-runner`. Conferido contra
`server.py`, `scripts/`, `pipeline.toml` e `tests/`.

## 1. Arquitetura

- **Servidor**: `server.py` — Flask puro (`app = Flask(__name__)`, `server.py:102`), sem blueprints, sem `add_url_rule`. Single-user local, **sem autenticação** (o ator é sempre `local-user`).
- **Estado em disco**: cada job é `jobs/{job_id}/` (ver [ADR/ADR-001](ADR/ADR-001-file-based-architecture.md)). Toda rota `/job/<job_id>/...` resolve o diretório via `resolve_job_dir(JOBS_DIR, job_id)`, que rejeita id inseguro (`ValueError` → 404) — guarda de *path traversal*.
- **Pipeline**: processos Python `s01–s08` orquestrados por `scripts/pipeline_runner.py` (`PipelineRunner.run`), cada estágio via `subprocess.run`.
- **Config**: `pipeline.toml` carregado por `scripts/common/config.py`; toda chave é sobreponível por env `KARAOKE_*`.

## 2. Pipeline (estágios)

`s01`/`s02` rodam como ingest/prep **antes** do runner. O plano do runner
(`build_stage_plan`, `pipeline_runner.py:38`) ramifica: se `lyrics.txt` existe →
`s03b` (alinhamento forçado, caminho MVP); senão → `s03` (Whisper, fallback).
Depois sempre `s04 → s05 → s06 → s07 → s08`.

| Estágio | Script | Nome (runner) | Lê | Escreve | Faz |
|---|---|---|---|---|---|
| s01 | `s01_input.py` | (pré-runner) | arquivo do usuário (áudio/vídeo) | `input.wav`, `metadata.json`, cópia `original.*` | Valida + ffprobe, normaliza para WAV. **Legado.** |
| s02 | `s02_demix.py` | (pré-runner) | `input.wav` | `vocals.wav`, `instrumental.wav` | Demucs `htdemucs` em subprocess isolado (`demucs_env`, DirectML). **Opcional no MVP web.** |
| s03 | `s03_transcribe.py` | `transcribing` | `vocals.wav` | `transcript.json` | faster-whisper (CPU, int8) STT com timestamps de palavra. **Fallback** (sem letra). |
| s03b | `s03b_lyrics_align.py` | `aligning_lyrics` | `vocals.wav`, `lyrics.txt` | `transcript.json` (`alignment_mode="forced"`) | Alinhamento forçado (ctc-forced-aligner / MMS-300m, CPU) + *snap* de pitch/onset + melisma. **Caminho MVP.** |
| s04 | `s04_align.py` | `aligning` | `vocals.wav`, `transcript.json` | `aligned.json` | HubertFA (ONNX, DirectML), fonemas via g2p_en → ARPAbet; fallback linear por segmento. |
| s05 | `s05_analyze.py` | `analyzing` | `transcript.json`, `aligned.json`, (`lyrics.txt`) | `analysis.json` | Agrupa palavras em linhas com estilo/cor/efeito. Determinístico no caminho forçado; Ollama (Gemma) no caminho Whisper, com fallback por regra. |
| s06 | `s06_generate_ass.py` | `generating` | `analysis.json`, `vocals.wav` | `output.ass`, `output.ass.manifest.json` | ASS com `\kf` progressivo (pysubs2); segmentação por atividade vocal + highlight-velocity. |
| s07 | `s07_output.py` | `rendering` | `instrumental.wav`, `output.ass` | `output.mp4` | Queima ASS no vídeo (ffmpeg); h264_amf (CQP) com fallback libx264 (CRF); áudio aac. |
| s08 | `s08_validate.py` | `validating` | `transcript.json`, `aligned.json`, `analysis.json`, `output.ass`, (`reference_mapping.json`, `lyrics.txt`) | exit 0/1 + eventos | *Contract tests* (falha dura) + métricas de qualidade (warnings: drift p50/p95, cobertura, taxa de baixa confiança). |

> ⚠️ **Não existe SOFA/ROSVOT nem `--aligner sofa`** neste branch. Os aligners
> reais são ctc-forced-aligner/MMS-300m (`s03b`) e HubertFA (`s04`).

## 3. Plano de execução web e timeouts

Progresso (`status.json`):

```
queued
  → aligning_lyrics | transcribing   (5%)
  → aligning                         (25%)
  → analyzing                        (50%)
  → generating                       (70%)
  → rendering                        (85%)
  → validating                       (95%)
  → done (100%) | failed
```

**Watchdog por estágio** = timeout de config do estágio **+ 60 s**
(`_BUFFER_S = 60`, `pipeline_runner.py:51`). Ex.: `align_hubertfa_timeout_s+60`,
`ollama_timeout_s+60`, `generate_ass_timeout_s+60`, `output_ffmpeg_timeout_s+60`,
`validate_timeout_s+60`.

## 4. Invalidação downstream

Re-rodar um estágio apaga os artefatos que dependem dele antes de reexecutar
(`_INVALIDATION_TARGETS`, `pipeline_runner.py:327`):

- rerun `analyzing` → apaga `analysis.json` + todos os ASS/MP4/preview + manifests.
- rerun `generating` → apaga ASS + MP4 + preview + manifests.
- rerun `rendering` → apaga MP4 + preview + manifests.

## 5. Tabela de rotas (completa — 22 decorators em `server.py`)

Toda `/job/<job_id>/...` passa pela guarda de path. Não há auth; os "gates" são
de workflow/estado (ver §6).

### Upload / criação de job
| Método | Rota | Handler | file:line | Descrição |
|---|---|---|---|---|
| GET | `/job/new` | `new_job_form` | 433 | Form de upload (`new_job.html`); flag `server_busy` quando jobs vivos ≥ `max_concurrent_jobs`. |
| POST | `/job/new` | `new_job_submit` | 642 | Aceita ZIP Suno **ou** `vocals`+`instrumental` + `lyrics_text`. Converte para WAV, escreve `meta.json`/`lyrics.txt`/status, dispara thread do pipeline. JSON de erro (400/429/500) ou redirect. |

### Dashboard / detalhe
| Método | Rota | Handler | file:line | Descrição |
|---|---|---|---|---|
| GET | `/` | `index` | 371 | Cockpit; `?job=` seleciona, `?mode=new\|review`, `?stage=`. HTML. |
| GET | `/job/<job_id>` | `job_detail` | 831 | Página do job (`job.html`): meta, status, drift, presença de output.*. 404 se não existe. |
| POST | `/job/<job_id>/delete` | `job_delete` | 1468 | `rmtree` do diretório. **409** se o job está rodando. Redirect. |

### Pipeline / status
| Método | Rota | Handler | file:line | Descrição |
|---|---|---|---|---|
| GET | `/job/<job_id>/stream` | `job_stream` | 1354 | SSE (`text/event-stream`); relê `status.json` a cada 0.8s até `done`/`failed`. |
| GET | `/job/<job_id>/metrics` | `job_metrics_api` | 1410 | Drift em JSON; 404 se não há referência. |
| GET | `/job/<job_id>/events` | `job_events_api` | 1439 | Eventos + summary, sanitizados (paths→basename, comandos redigidos). `?limit=` 1–300 (default 80). |
| POST | `/job/<job_id>/retry-validate` | `job_retry_validate` | 1531 | Re-roda `s08` em thread. **409** se rodando ou se não falhou exatamente em `validating` (progress 95). |

### Review Wizard
| Método | Rota | Handler | file:line | Descrição |
|---|---|---|---|---|
| GET | `/job/<job_id>/review` | `review_wizard` | 876 | Wizard (`review_wizard.html`); honra `?stage=`, `?status=`, `?level=`, `?point=`, `?section=`. |
| POST | `/job/<job_id>/review/points/<point_id>/approve` | `review_wizard_approve_point` | 1006 | Aprova ponto; avança para o próximo aberto. |
| POST | `/job/<job_id>/review/points/<point_id>/apply-suggestion` | `review_wizard_apply_point_suggestion` | 1034 | Aplica sugestão do ponto. 404 se desconhecido. |
| POST | `/job/<job_id>/review/points/<point_id>/skip-risk` | `review_wizard_skip_point_risk` | 1076 | Pula aceitando risco (`reason`). 400 em `ValueError`. |
| POST | `/job/<job_id>/review/points/<point_id>/timing` | `review_wizard_adjust_point_timing` | 1113 | Ajusta timing (`start_s`/`end_s`). 400 em valor inválido. |
| POST | `/job/<job_id>/review/issues/<issue_id>/approve-risk` | `review_wizard_approve_issue_risk` | 1144 | Aprova risco de issue (`reason`). 400 em `ValueError`. |
| POST | `/job/<job_id>/review/issues/<issue_id>/apply-suggestion` | `review_wizard_apply_issue_suggestion` | 1163 | Aplica correção sugerida da issue. 400 em `ValueError`. |

### Preview / render
| Método | Rota | Handler | file:line | Descrição |
|---|---|---|---|---|
| POST | `/job/<job_id>/review/preview/critical-snippets/approve` | `review_wizard_approve_critical_preview` | 1327 | Aprova preview de trechos críticos (evidence gate). 400 sem evidência. |
| POST | `/job/<job_id>/review/preview/full/render` | `review_wizard_render_full_preview` | 1332 | Copia `output.mp4` → `preview_full.mp4`, registra sha256/size. 400 sem `output.mp4` ou grafo inválido. |
| GET | `/job/<job_id>/review/preview/full.mp4` | `review_wizard_full_preview_mp4` | 1337 | Serve `preview_full.mp4`. **Sem export gate** (é preview). 404 se não renderizado. |
| POST | `/job/<job_id>/review/preview/full/approve` | `review_wizard_approve_full_preview` | 1349 | Aprova preview completo (mesmo evidence gate). |

### Export / download (com export gate)
| Método | Rota | Handler | file:line | Descrição |
|---|---|---|---|---|
| GET | `/job/<job_id>/output.mp4` | `job_output_mp4` | 1380 | Vídeo final. **403** se `_blocked_final_export_reason`; 404 se ausente. |
| GET | `/job/<job_id>/output.ass` | `job_output_ass` | 1395 | Legenda final. **403/404** idêntico. |

### Estático
| Método | Rota | Handler | Descrição |
|---|---|---|---|
| GET | `/static/<path:filename>` | Flask built-in | Estático padrão (implícito de `Flask(__name__)`). |

## 6. Gates (workflow, não auth)

1. **Path-safety** (todas `/job/<id>`): `resolve_job_dir` → 404.
2. **Export gate** (`output.mp4`/`output.ass`) → **403** via `_blocked_final_export_reason` (`server.py:1294`): exige `can_export_final(project)` + fingerprints do full-preview aprovado batendo em disco + `_artifact_graph_valid`. Sem project, cai para validade do grafo.
3. **Preview evidence gate** (`_preview_approval_evidence`, `server.py:1244`): aprovar preview exige ≥1 quality report + artefato primário em disco; grava sha256/size no momento da aprovação.
4. **Full-preview render gate** (`server.py:1203`): exige `output.mp4` + grafo válido.
5. **Concorrência** (`POST /job/new`) → **429** quando threads vivas ≥ `max_concurrent_jobs`.
6. **Delete** → **409** se o job está no registro `_running`.
7. **Retry-validate** → **409** exceto se o job não está vivo e falhou em `validating` (progress 95).

## 7. Configuração (`pipeline.toml`)

Seções: `[general]`, `[server]`, `[ui]`, `[hardware]` (+ `[hardware.z13]`,
`[hardware.cpu_only]`), `[demix]`, `[transcribe]`, `[align]`, `[analyze]`,
`[generate]`, `[output]`. Defaults como `DEFAULT_*` em `scripts/common/config.py`;
env `KARAOKE_*` sobrepõe. Precedência: **CLI > env > `pipeline.toml` > default**.

Notas de fidelidade:
- `[demix].python` é um caminho **absoluto e específico da máquina** (`C:/Users/Katz/miniforge3/envs/demucs_env/python.exe`) — candidato a `hardcoded-config-audit`.
- `[hardware.z13].align_batch_size = 8` no TOML diverge de `DEFAULT_HARDWARE_Z13 = 16` em `config.py:65`; **o TOML vence** quando o arquivo existe.

Máquinas de estado completas em [STATE_MACHINES.md](STATE_MACHINES.md); diagramas
em [GRAPHS.md](GRAPHS.md); schemas em [DATA_DICTIONARY.md](DATA_DICTIONARY.md).
