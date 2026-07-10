# Máquinas de Estado

Diagramas em [GRAPHS.md](GRAPHS.md); aqui é a verdade textual e as transições
condicionais.

## Ciclo de vida do job

```
queued
  → aligning_lyrics (lyrics.txt existe) | transcribing (sem lyrics.txt)   5%
  → aligning     25%
  → analyzing    50%
  → generating   70%
  → rendering    85%
  → validating   95%
  → done 100% | failed
```

Transição especial: **`failed → validating`** só via `retry-validate`, e **só
se** a falha ocorreu no estágio `validating` (progress 95). Fora disso o retry é
recusado com **409** (FR-018).

## Review Wizard

```
not_created → initialized → text_review → alignment_processing → quality_review
quality_review → ready | needs_fix
needs_fix → focused_issue_editor → (quality_review)
ready → critical_snippets_approved
critical_snippets_approved → export_ready
                           | full_preview_required → full_preview_rendered
                                                   → full_preview_approved
                                                   → export_ready
export_ready → exported
export_ready → quality_review   (artifact_changed: hash/manifest muda)
```

Qualquer mudança de artefato depois de `export_ready` (hash/manifest diferente)
**derruba** o estado de volta para `quality_review`.

## Export gate

```
check_artifacts → check_manifests → check_quality_report → check_preview
```

Estados de bloqueio (**403**): `blocked_missing_artifact`,
`blocked_hash_mismatch`, `blocked_quality_review_required`,
`blocked_preview_required`, `blocked_full_preview_required`.
Estados de liberação: `allowed_ready`,
`allowed_full_preview_approved_with_risk`.

## Ciclo de vida de uma issue

```
open → acknowledged | fixed | skipped_with_risk
     → … → verified | preview_approved → closed
```

`skipped_with_risk` exige `reason` (rota `skip-risk`/`approve-risk`, **400** sem
razão válida). Correção agressiva não sobrescreve: gera candidate take
([ADR-007](ADR/ADR-007-candidate-take.md)).

**Fixado por:** `tests/test_review_wizard_export_gate.py`,
`tests/test_review_wizard_wizard.py`, `tests/test_review_wizard_state.py`,
`tests/test_review_wizard_issue_resolution.py`, `tests/test_server_contracts.py`.
