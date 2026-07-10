# Plano de Testes

## Como rodar (importante)

Comando canônico — roda **tudo** verde:

```bash
pytest tests
```

`pytest` coleta os dois estilos de teste do repo: a maioria herda
`unittest.TestCase`, e alguns arquivos de contrato são estilo-pytest (`Test*`
sem `TestCase`, ex. `tests/test_audio_alignment_contracts.py`,
`tests/test_pipeline_stage_contracts.py`). Dependências pesadas opcionais (numpy,
etc.) são puladas com `pytest.importorskip` / `tests/_optional_imports.py`.

Alternativa `unittest` (limitada): `python -m unittest discover tests` **ignora
silenciosamente** os arquivos estilo-pytest e, num ambiente **sem** as deps
opcionais, os arquivos guardados por `pytest.importorskip` aparecem como *error*
de coleção em vez de *skip*. Por isso prefira `pytest tests`.

## Cobertura por área

| Área | Testes |
|---|---|
| Config / hardware | `test_app_config`, `test_hw_detect_config` |
| Caminhos seguros / segurança | `test_safe_paths` (zip traversal) |
| Contratos comuns | `test_common_contracts` (meta/status) |
| Estágios (schema-mestre) | `test_pipeline_stage_contracts` (pytest) |
| s01/s02 | `test_s01_s02_observability` |
| s03 transcribe | `test_transcribe_observability` |
| s03b lyrics align | `test_lyrics_alignment_observability` |
| s04 align | `test_s04_temp_workspace` |
| s05 analyze | `test_analysis_contract` |
| s06 generate ASS | `test_ass_generation`, `test_s06_style_contracts`, `test_highlight_velocity` |
| s07 render | `test_s07_observability` |
| s08 validate | `test_validate_contracts` |
| Timing (snapshot) | `test_audio_alignment_contracts` (pytest) |
| Timing (comportamento) | `test_timestamp_validation`, `test_timing_layers` |
| Proveniência | `test_provenance_contracts` |
| Observabilidade | `test_observability_contracts` |
| Style Library | `test_karaoke_style_library` |
| Pipeline runner | `test_pipeline_runner`, `test_test_pipeline`, `test_clean_outputs_integration` |
| Servidor / rotas | `test_server_contracts`, `test_cockpit_server`, `test_review_wizard_server` |
| Review Wizard (lógica) | `test_review_wizard_*` (state, wizard, stages, quality, versioning, store, issue_resolution, text_prep, audio_timeline, stage_summaries, artifacts, export_gate, contracts, frontend_contracts) |
| Cockpit view model | `test_cockpit_view_model`, `test_review_points` |
| Vocal activity | `test_vocal_activity` |
| Project KB | `test_project_knowledge_base` |
| Qualidade de código / UI (estático) | `test_code_quality_contracts`, `test_basic_ui_polish_contracts` |

## Snapshot de constantes de timing

O snapshot de constantes (`tests/test_audio_alignment_contracts.py`) é
estilo-pytest; rode-o via `pytest`. Ele fixa (via AST/regex sobre o código):
`PREROLL_MS=200`, `POSTROLL_MS=300`, `GAP_MS=50`, `overlap_tolerance_s=0.05`,
`low_confidence_threshold=0.25`, `lc_warning_pct=20`, `MIN_WORD_MS=80`,
`min_dur=0.050` (s03b e s04), `--snap-window=0.75`, `find_timestamp_errors`
defaults (`min_duration=0.001`, `overlap_tolerance_s=0.0`). Mudou o valor →
mude este teste no mesmo commit ([Constituição §3](PROJECT_CONSTITUTION.md)).
