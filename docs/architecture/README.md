# Arquitetura (visão)

Resumo. O detalhe técnico canônico está em [../../spec/SDD.md](../../spec/SDD.md).

- **Servidor**: `server.py`, Flask puro, single-user local, **sem auth**. 22 rotas; toda `/job/<id>` passa por guarda de path.
- **Estado**: cada job é um diretório `jobs/{job_id}/` — única fonte de verdade ([ADR-001](../../spec/ADR/ADR-001-file-based-architecture.md)).
- **Pipeline**: processos Python `s01–s08` orquestrados por `scripts/pipeline_runner.py`; cada estágio via subprocess, com watchdog = timeout do estágio + 60s.
- **Caminho MVP**: com `lyrics.txt` → alinhamento forçado (`s03b`) → `s04` (HubertFA) → `s05` (análise) → `s06` (ASS `\kf`) → `s07` (render ffmpeg) → `s08` (validação). Sem letra, cai no fallback Whisper (`s03`).
- **Config**: `pipeline.toml`, sobreponível por env `KARAOKE_*`. Precedência CLI > env > toml > default.
- **Qualidade**: Review Wizard + export gate + manifests SHA-256 barram export com erro perceptual ou artefato adulterado.

```
Upload → s01/s02 (ingest) → [s03b|s03] → s04 → s05 → s06 → s07 → s08 → Review Wizard → export
```

Módulos: `scripts/review_wizard/` (estado, issue, export, timing), `scripts/common/`
(observabilidade, paths, status, proveniência, validação), `scripts/karaoke_styles/`
(Style Library). Diagramas em [../../spec/GRAPHS.md](../../spec/GRAPHS.md).
