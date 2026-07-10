# Agentes lógicos

Modelo de **responsabilidades** do pipeline (não são processos separados nem
têm a ver com o `AGENTS.md` da raiz, que é instrução de host de IA). Cada
responsabilidade mapeia para scripts/módulos reais.

| Agente lógico | Responsabilidade | Onde vive |
|---|---|---|
| UploadAgent | Recebe ZIP/stems, valida, normaliza para WAV | `server.py` (`new_job_submit`), `s01_input.py` |
| JobLifecycleAgent | `meta.json`/`status.json`, estados, delete | `server.py`, `scripts/common/` |
| PipelineRunnerAgent | Orquestra estágios, watchdog, invalidação | `scripts/pipeline_runner.py` |
| LyricsAlignmentAgent | Alinhamento forçado (caminho MVP) | `s03b_lyrics_align.py` |
| TimingRefinementAgent | Snap de pitch/onset, melisma, camadas de timing | `s03b_lyrics_align.py`, `scripts/review_wizard/timing_layers.py` |
| AnalysisAgent | Agrupa palavras em linhas com estilo | `s05_analyze.py` |
| ASSGenerationAgent | ASS `\kf` + manifest | `s06_generate_ass.py` |
| RenderAgent | Queima ASS → MP4 (ffmpeg) | `s07_output.py` |
| ValidationAgent | Contract tests + métricas de qualidade | `s08_validate.py`, `scripts/common/validation.py` |
| ReviewWizardAgent | Issues, points, preview, aprovação | `scripts/review_wizard/`, rotas `/review/*` |
| ExportGateAgent | Bloqueia download até liberar | `server.py` (`_blocked_final_export_reason`) |
| ObservabilityAgent | `events.jsonl`, `summary.json`, métricas | `scripts/common/` (observabilidade) |
| StyleLibraryAgent | Fonte única de presets/estilos/efeitos | `scripts/karaoke_styles/library.py` |
| CleanupAgent | Limpeza de diretório/artefatos | `server.py` (`job_delete`), invalidação do runner |

## Contrato de observabilidade

Todo agente de estágio emite: `stage_started`, `stage_command_finished`,
`stage_failed`, `downstream_invalidated`. Fixado por
`tests/test_observability_contracts.py` e os `test_*_observability.py` por estágio.
