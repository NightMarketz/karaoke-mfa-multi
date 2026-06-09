# Context Contract: Compact Technical Cockpit

## Objective

Plan the implementation of the approved compact technical cockpit UI for Karaoke MFA Multi. The first screen should default to `New Karaoke`, expose recent projects below, show pipeline/audio context in a dense cockpit layout, and provide a quick `Review` mode that triages issues before opening the existing Review Wizard.

## Source Of Truth

- Design spec: `docs/superpowers/specs/2026-06-06-compact-technical-cockpit-design.md`
- Visual reference: `docs/superpowers/assets/2026-06-06-compact-technical-cockpit.png`
- Existing Flask UI: `templates/base.html`, `templates/index.html`, `templates/new_job.html`, `templates/job.html`, `templates/review_wizard.html`
- Existing client code: `static/app.js`, `static/app.css`
- Existing server entry point: `server.py`

## Current Architecture Constraints

- The active UI is Flask templates plus `static/app.css` and `static/app.js`.
- `GET /` currently renders `templates/index.html` with `_list_jobs()`.
- `GET /job/new` and `POST /job/new` own the real job creation form and pipeline start.
- Review Wizard routes already exist under `/job/<job_id>/review`.
- Quick Review must reuse existing review state, review points, issue actions, and Review Wizard links.

## Hard Rules

- Do not change stage ids, stage order, artifact names, manifest semantics, or pipeline runner behavior in this UI slice.
- Do not change word timing, minimum duration, drift tolerance, melisma, sustain, pitch, CTC, HubertFA, ASS timing, or audio-alignment algorithms.
- Do not trust generated/model output as authoritative. Treat it as draft only.
- Do not replace the Review Wizard internals in this slice.
- Do not add social/music-feed behavior, public/liked controls, accounts, or Suno branding.
- Keep Quick Review as triage only: approve, apply existing suggestion, skip with risk, open Review Wizard.
- Deep timing edits, melisma segmentation, preview approval, and final export approval remain in the Review Wizard.

## Required UI Behaviors

- `/` opens to the cockpit, with `New Karaoke` as the active mode.
- The cockpit includes a left app rail, top command strip, left task panel, central timeline/waveform canvas, right diagnostics panel, bottom project rail, and fixed player bar.
- Recent projects are shown in a horizontal rail and link to the selected job.
- `Review` mode is selected through a query parameter or UI control and swaps the left task panel into quick issue triage.
- Quick Review links to `/job/<job_id>/review?stage=<stage>&point=<point_id>` when an active issue/review point exists.
- If no job is selected, Review mode shows an empty state that asks the user to pick a recent project.
- The right diagnostics panel must never show export ready when `can_export_final(project)` blocks final export.

## Hardcoded Config Audit

| ID | File | Value | Classification | Risk | Decision | Test |
| --- | --- | --- | --- | --- | --- | --- |
| H001 | `templates/cockpit.html` | Static waveform bar formula | Documentation/mock visual | Makes the cockpit look fake and hides missing audio artifacts | Replace with bars derived from available WAV artifacts, with an explicit empty state when no audio exists | `test_timeline_uses_real_wav_analysis_and_review_points` |
| H002 | `templates/cockpit.html` | Static lyric chips (`Faz tanto tempo`, `que eu nao te vejo`, `a gente cresce`) | Documentation/mock visual | Shows unrelated lyrics for any selected project | Replace with lines from `analysis.json`; show empty state if absent | `test_selected_job_timeline_uses_analysis_text_not_mock_lyrics` |
| H003 | `templates/cockpit.html` | Static issue chips (`GAP`, `DRIFT`, `MELISMA`) | Documentation/mock visual | Claims issues that may not exist | Replace with review points from existing Review Wizard state; show no-open-issues state if absent | `test_selected_job_timeline_uses_analysis_text_not_mock_lyrics` |
| H004 | `templates/cockpit.html` | Static `pt-BR` language chip | Runtime metadata fallback | Implies language metadata that may not exist | Read language from job metadata when present; otherwise display `--` | `test_selected_job_summary_includes_language_without_fake_default` |
| H005 | `templates/cockpit.html` | Static `All Services OK` | Runtime status summary | Claims service health without evidence | Replace with indexed/running/failed job summary | `test_cockpit_service_summary_reports_real_job_counts` |
| H006 | `scripts/cockpit.py` | Expected artifact names | Artifact contract | Changing these would break pipeline contract | Keep stable in this UI slice | Existing artifact row tests |
| H007 | `server.py` | `jobs`, `0.0.0.0`, `5000`, upload limit, secret key, default style preset | Runtime configuration | Breaks portability and hides deployment assumptions | Move to `pipeline.toml` plus environment/CLI precedence | `tests.test_app_config`, `tests.test_server_contracts` |
| H008 | `scripts/cockpit.py` | Waveform bar counts, marker limits, review window padding, priority threshold | View configuration/domain-adjacent UI constants | Hard to audit visually and easy to tune accidentally | Replace with named constants and preserve behavior under tests | `tests.test_cockpit_view_model` |
| H009 | `scripts/s02_demix.py`, `scripts/s05_analyze.py`, `scripts/hw_detect.py` | Demucs path/model/timeout, Ollama URL/temperature/timeout, hardware profile values | Runtime configuration | Breaks portability and can silently diverge from `pipeline.toml` | Resolve through `scripts.common.config` with env/CLI precedence and keep profile defaults in `pipeline.toml` | `tests.test_app_config`, `tests.test_hw_detect_config`, `tests.test_s01_s02_observability`, `tests.test_analysis_contract` |
| H010 | `scripts/s06_generate_ass.py`, `scripts/s07_output.py`, `scripts/test_pipeline.py`, `scripts/struggle_regeneration_audit.py` | Render preset, resolution, fades, output codec/bitrate/volumes/framerate/timeout, smoke Ollama URL | Runtime/render configuration | Different entry points could render with different defaults | Resolve through `[generate]`, `[output]`, and `[analyze]` in `pipeline.toml` | `tests.test_app_config`, `tests.test_ass_generation`, `tests.test_s07_observability`, `tests.test_test_pipeline` |
| H011 | `scripts/s03_transcribe.py`, `scripts/s04_align.py` | Whisper model/language/low-confidence threshold, HubertFA path/checkpoint/language/timeout | Runtime configuration plus domain threshold | Model/path defaults were hidden in scripts; threshold value must not change casually | Move current values to `pipeline.toml` and env resolution without changing numeric behavior | `tests.test_app_config`, `tests.test_transcribe_observability`, `tests.test_s04_temp_workspace` |
| H012 | `scripts/s03b_lyrics_align.py`, review timing modules, style library, tests | Snap windows, minimum durations, style preset ids, artifact filenames, fixture model names | Alignment/style domain constants, artifact contracts, or test fixtures | Moving these without domain skill can change timing semantics or break contracts | Keep stable unless `audio-alignment-audit`, `karaoke-style-library`, or pipeline contract skills are available/in scope | Existing domain and contract tests |

## Verification

- Add focused server/template tests for empty cockpit, recent-job cockpit, selected-job diagnostics, quick review actions, and blocked export readiness.
- Add focused JS/template contract tests for mode toggles and file drop reuse.
- Run targeted tests with explicit timeouts.
- Run `python -m py_compile server.py scripts\\review_wizard\\*.py` or a narrowed equivalent if wildcard behavior is unreliable.
- Verify the rendered cockpit visually against the approved mockup on desktop and mobile before claiming implementation complete.

## Multi-Agent Execution Policy

- Use one fresh implementation agent per task.
- Do not dispatch implementation agents in parallel when they would edit the same files.
- Required review loop per task: implementer self-review, spec-compliance review, then code-quality review.
- Controller must preserve unrelated working-tree changes and stage only files modified by the active task.
