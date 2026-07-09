# AGENTS — Karaoke MFA Multi

Aqui, "agents" são unidades operacionais do sistema. Algumas são scripts, outras são serviços internos ou papéis lógicos.

## 6.1 Lista de agentes

| Agent                   | Tipo     | Responsabilidade                                          |
| ----------------------- | -------- | --------------------------------------------------------- |
| `UploadAgent`           | Sistema  | Validar upload, ZIP, stems, preset e letra.               |
| `JobLifecycleAgent`     | Sistema  | Criar `job_id`, diretório, `meta.json`, `status.json`.    |
| `PipelineRunnerAgent`   | Sistema  | Orquestrar etapas, subprocessos, timeouts e invalidation. |
| `LyricsAlignmentAgent`  | Pipeline | Executar forced alignment e gerar `transcript.json`.      |
| `TimingRefinementAgent` | Pipeline | Gerar `aligned.json` com floors e phonemes opcionais.     |
| `AnalysisAgent`         | Pipeline | Gerar linhas, sections, styles e effects.                 |
| `ASSGenerationAgent`    | Pipeline | Gerar ASS com `\kf` e manifest.                           |
| `RenderAgent`           | Pipeline | Renderizar MP4 via ffmpeg e gerar manifest.               |
| `ValidationAgent`       | Pipeline | Validar contratos e artifact graph.                       |
| `ReviewWizardAgent`     | Produto  | Criar issues, quality reports, previews e approvals.      |
| `ExportGateAgent`       | Produto  | Decidir se ASS/MP4 podem ser servidos.                    |
| `ObservabilityAgent`    | Sistema  | Registrar eventos, warnings, failures e summaries.        |
| `StyleLibraryAgent`     | Sistema  | Expor presets, style keys e effects suportados.           |
| `CleanupAgent`          | Sistema  | Apagar jobs com segurança quando permitido.               |

## 6.2 Contrato padrão de agent

Cada agent deve declarar:

```yaml
agent_id:
  responsibility:
  inputs:
  outputs:
  reads:
  writes:
  side_effects:
  failure_modes:
  retry_policy:
  observability_events:
  tests:
```

## 6.3 Exemplo: PipelineRunnerAgent

```yaml
agent_id: PipelineRunnerAgent
responsibility: Orquestrar o pipeline do job por subprocessos.
inputs:
  - job_dir
  - pipeline.toml
  - run_id
outputs:
  - status.json atualizado
  - events.jsonl
  - artefatos downstream
reads:
  - meta.json
  - lyrics.txt
  - vocals.wav
  - instrumental.wav
writes:
  - status.json
  - events.jsonl
  - observability_summary.json
side_effects:
  - executa scripts s03b-s08
  - invalida artefatos downstream
failure_modes:
  - timeout
  - subprocess returncode != 0
  - artefato obrigatório ausente
  - status write failure
retry_policy:
  - retry manual apenas para validating quando permitido
observability_events:
  - stage_started
  - stage_command_finished
  - stage_failed
  - downstream_invalidated
tests:
  - test_pipeline_stage_contracts.py
  - test_server_contracts.py
```
