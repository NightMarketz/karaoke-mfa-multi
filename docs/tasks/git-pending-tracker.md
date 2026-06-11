# Git Pending Tracker

Last checked: 2026-06-02
Branch: `mvp-pipeline-runner`
Latest committed checkpoint: `46a40f3 Harden stage06 audio-backed timing`

This tracker is only for git hygiene: grouping, staging, committing,
ignoring, or removing local pending files. Product validation work belongs in
separate task notes.

## Status Key

- `open`: needs action.
- `staged`: ready for commit.
- `committed`: already committed.
- `ignore_candidate`: likely runtime/scratch output.
- `blocked`: cannot be inspected or changed safely yet.

## Pendencies

| ID | Status | Group | Files | Proposed action |
| --- | --- | --- | --- | --- |
| GIT-001 | committed | Stage 06 audio-backed timing | `scripts/s06_generate_ass.py`, `scripts/common/provenance.py`, `scripts/karaoke_styles/*`, `scripts/review_wizard/highlight_velocity.py`, `scripts/review_wizard/timing_layers.py`, `scripts/review_wizard/vocal_activity.py`, related tests, `docs/tasks/timing-classification-report.md` | Done in `46a40f3`. |
| GIT-010 | open | Pipeline and observability tracked changes | `scripts/common/observability.py`, `scripts/pipeline_runner.py`, `scripts/s04_align.py`, `scripts/s05_analyze.py`, `scripts/s07_output.py`, `scripts/s08_validate.py`, `scripts/test_pipeline.py`, `tests/test_observability_contracts.py`, `tests/test_pipeline_runner.py`, `tests/test_s04_temp_workspace.py`, `tests/test_s07_observability.py`, `tests/test_validate_contracts.py` | Review as one or more pipeline-contract commits. |
| GIT-020 | open | Server and Review Wizard UI tracked changes | `server.py`, `static/app.css`, `static/app.js`, `templates/job.html`, `templates/new_job.html`, `tests/test_server_contracts.py` | Review separately from pipeline stages; likely server/UI commit. |
| GIT-030 | open | Review Wizard untracked backend modules | `scripts/review_wizard/__init__.py`, `artifacts.py`, `audio_timeline.py`, `contracts.py`, `export_gate.py`, `export_summary.py`, `issue_resolution.py`, `quality.py`, `review_points.py`, `stage_summaries.py`, `stages.py`, `store.py`, `text_prep.py`, `versioning.py`, `wizard.py` | Decide whether this is a coherent Review Wizard commit with tests and UI. |
| GIT-031 | open | Review Wizard untracked tests/templates | `templates/review_wizard.html`, `tests/test_review_points.py`, `tests/test_review_wizard_*.py` | Pair with GIT-030 unless tests reveal smaller splits. |
| GIT-040 | open | Project docs and skill routing | `AGENTS.md`, `docs/README.md`, `docs/architecture/README.md`, `docs/skills/README.md`, `docs/skills/gap-analysis.md`, `docs/skills/routing.md`, `docs/tasks/README.md` | Review as docs/process commit. |
| GIT-041 | open | Codex local skills and task notes | `.Codex/skills/hardcoded-config-audit/*`, `.Codex/skills/pap-ollama/*`, `.Codex/tasks/*.md` | Decide whether repo should track local Codex runtime/task material or keep it private/ignored. |
| GIT-042 | open | Superpowers plans/specs | `docs/superpowers/plans/2026-05-25-*.md`, `docs/superpowers/plans/2026-05-27-highlight-velocity-plan.md`, `docs/superpowers/plans/2026-05-28-provenance-artifact-refinement.md`, `docs/superpowers/plans/2026-05-29-audio-backed-sustain-fallbacks.md`, `docs/superpowers/specs/2026-05-25-review-wizard-design.md`, `docs/superpowers/specs/2026-05-29-project-knowledge-base-design.md` | Review as planning docs commit, or archive if stale. |
| GIT-050 | open | Project knowledge base / clean output tests | `tests/test_clean_outputs_integration.py`, `tests/test_project_knowledge_base.py`, `tests/test_test_pipeline.py` | Triage with related production code before staging. |
| GIT-060 | open | Struggle regeneration audit source and reports | `scripts/struggle_regeneration_audit.py`, `struggle-regeneration-report.md`, `struggle-regeneration-audit-round2.md` | Decide whether audit tooling/report belongs in repo. |
| GIT-061 | ignore_candidate | Struggle regeneration image artifacts | `real-struggle-about-to-snap-0439.png`, `single-style-about-to-snap-0439.png` | Usually keep out of git unless needed as fixtures or review evidence. |
| GIT-070 | ignore_candidate | Scratch temp files | `manual_tmp/x.txt`, `manual_tmp2/x.txt` | Likely remove or ignore after confirming no useful evidence. |
| GIT-071 | blocked | Permission-denied scratch directory | `manual_tmp3/` | Git cannot inspect it: `Permission denied`; `Get-Acl` also fails with `UnauthorizedAccessException`. Needs OS permission cleanup outside normal git flow. |
| GIT-080 | open | Line-ending warnings | Many modified/staged files warn `LF will be replaced by CRLF` | Decide whether to normalize `.gitattributes` later; do not mix with feature commits unless required. |

## Suggested Split Order

1. GIT-040/GIT-041/GIT-042: decide what documentation and Codex-local material should be tracked.
2. GIT-010: pipeline and observability tracked changes.
3. GIT-020/GIT-030/GIT-031: Review Wizard server/UI/backend/tests as one reviewed unit or smaller commits.
4. GIT-050: project knowledge base and clean-output tests.
5. GIT-060/GIT-061/GIT-070/GIT-071: audit artifacts and scratch cleanup/ignore decisions.
6. GIT-080: line-ending policy only after feature/doc groups are settled.
