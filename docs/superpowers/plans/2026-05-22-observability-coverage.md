# Observability Coverage Task

**Goal:** Make every important moment of the local Karaoke MFA app observable, auditable, and easy to debug without reading scattered logs manually.

**Current assessment:** Observability is useful but incomplete. The app has `status.json`, per-job `pipeline.log`, SSE progress, validation output, and some drift metrics. It does not yet have a structured event trail, stage duration summary, machine-readable warnings/failures, or UI-visible diagnostics for every transition.

**Target outcome:** Every job writes:

- `events.jsonl`: append-only structured event stream.
- `observability_summary.json`: final compact summary for UI/debug.
- Existing `status.json`: latest state only.
- Existing `pipeline.log`: human-readable log.

Each event should include at minimum:

- `job_id`
- `timestamp`
- `event`
- `stage`
- `level`
- `message`
- `duration_ms` when applicable
- `artifact` when an artifact is checked or written
- `details` object for stage-specific metadata

---

## Task 1: Shared Observability Helpers

**Files:**

- Create: `scripts/common/observability.py`
- Create: `tests/test_observability_contracts.py`
- Modify: `scripts/common/status.py` if needed

**Steps:**

- [ ] Add `write_event(job_dir, event, stage, level="info", message="", details=None)`.
- [ ] Add `StageTimer` context manager that writes `stage_started` and `stage_finished` events.
- [ ] Add `record_artifact(job_dir, stage, path, required=True)` with file existence/size details.
- [ ] Add `build_observability_summary(job_dir)` reading `events.jsonl`.
- [ ] Test that JSONL appends valid JSON objects and never corrupts previous events.
- [ ] Test that a failed stage event includes `level="error"` and message.

---

## Task 2: Server And Job Lifecycle Events

**Files:**

- Modify: `server.py`
- Modify: `tests/test_server_contracts.py`

**Moments to cover:**

- [ ] Server receives new job request.
- [ ] Lyrics missing rejection.
- [ ] Suno ZIP received.
- [ ] ZIP member rejected as unsafe.
- [ ] Individual stems received.
- [ ] Stem conversion starts/finishes/fails.
- [ ] `meta.json` written.
- [ ] `status.json` initialized.
- [ ] Pipeline thread queued/started.
- [ ] Running job deletion blocked.
- [ ] Job detail page opened.
- [ ] Output/ASS download requested.

**Verification:**

- [ ] Tests assert unsafe ZIP rejection writes an error event.
- [ ] Tests assert successful job creation writes lifecycle events before pipeline starts.

---

## Task 3: Pipeline Runner Stage Events

**Files:**

- Modify: `scripts/pipeline_runner.py`
- Modify: `tests/test_pipeline_runner.py`

**Moments to cover:**

- [ ] Stage plan built, including chosen forced/Whisper path.
- [ ] Each stage command started with timeout and sanitized command metadata.
- [ ] Each stage command finished with return code and duration.
- [ ] Timeout captured as a structured event.
- [ ] Nonzero stage failure captures last stderr/stdout tail.
- [ ] Validation gate pass/fail recorded.
- [ ] Final job state `done`/`failed` recorded.
- [ ] Running registry cleanup recorded.

**Verification:**

- [ ] Test failed command writes `stage_failed` event.
- [ ] Test successful runner writes `pipeline_finished`.
- [ ] Test timeout writes `stage_timeout`.

---

## Task 4: Stage 03 / 03b Alignment Observability

**Files:**

- Modify: `scripts/s03b_lyrics_align.py`
- Modify: `scripts/s03_transcribe.py`
- Modify: `scripts/test_lyrics_robustness.py` only if needed

**Moments to cover:**

- [ ] Lyrics file loaded: line count, section count, unknown markers.
- [ ] Stage directions stripped count.
- [ ] Forced alignment full text generated: word count.
- [ ] CTC alignment started/finished.
- [ ] Pitch/onset correction engine selected.
- [ ] Low-confidence words count.
- [ ] Transcript written with segment/word counts.
- [ ] Whisper fallback path records model, device, compute type, language probability.

**Verification:**

- [ ] `s08_validate.py` can report unknown section markers from transcript.
- [ ] Unit/robustness test confirms section marker diagnostics are preserved.

---

## Task 5: Stage 04 HubertFA Observability

**Files:**

- Modify: `scripts/s04_align.py`
- Modify: `tests/test_s04_temp_workspace.py`

**Moments to cover:**

- [ ] Temporary HubertFA batch dir created under job dir.
- [ ] Batch prep count: segments prepared/skipped.
- [ ] HubertFA subprocess started with timeout value.
- [ ] HubertFA timeout recorded.
- [ ] Fallback timing used: reason and word count.
- [ ] HubertFA parse failures recorded per segment/stem.
- [ ] Source distribution recorded before writing `aligned.json`.
- [ ] Temp dir cleanup success/failure recorded.

**Verification:**

- [ ] Test timeout path records `hubertfa_timeout` event.
- [ ] Test cleanup records no temp batch directories remaining.

---

## Task 6: Stage 05 Analysis Observability

**Files:**

- Modify: `scripts/s05_analyze.py`
- Modify: `tests/test_analysis_contract.py`

**Moments to cover:**

- [ ] Analysis mode chosen: forced, LLM, or `--force-rule-based`.
- [ ] Ollama connectivity checked/skipped.
- [ ] LLM attempt count, parse success/failure, response length.
- [ ] Rule-based fallback used with reason.
- [ ] Analysis validation errors recorded as `analysis_invalid`.
- [ ] Style distribution recorded.
- [ ] Word coverage count recorded.
- [ ] `analysis.json` written with line count.

**Verification:**

- [ ] Test `--force-rule-based` writes event and does not call Ollama.
- [ ] Test invalid analysis writes error event and exits nonzero.

---

## Task 7: Stage 06 ASS Observability

**Files:**

- Modify: `scripts/s06_generate_ass.py`
- Modify: `tests/test_ass_generation.py`

**Moments to cover:**

- [ ] Preset selected.
- [ ] Style distribution recorded.
- [ ] Lines skipped due inverted timestamps.
- [ ] ASS dialogue count and `\kf` count recorded.
- [ ] Display window clamp/overlap prevention count.
- [ ] ASS validation errors recorded.
- [ ] `output.ass` written with size.

**Verification:**

- [ ] Test generated ASS records no layer-0 overlap.
- [ ] Test escaped ASS text event/validation remains clean.

---

## Task 8: Stage 07 Render Observability

**Files:**

- Modify: `scripts/s07_output.py`
- Add/modify tests if practical with mocked subprocess calls.

**Moments to cover:**

- [ ] Input artifact check for `instrumental.wav`, `vocals.wav`, `output.ass`.
- [ ] Audio mix path selected: instrumental only vs mixed vocals/instrumental.
- [ ] Canvas/background duration selected.
- [ ] FFmpeg command started with timeout.
- [ ] FFmpeg return code/duration recorded.
- [ ] Output MP4 written with size/duration if probe succeeds.

**Verification:**

- [ ] Mocked render failure writes structured error event.
- [ ] Missing vocals warning is visible in summary.

---

## Task 9: Stage 08 Validation Summary

**Files:**

- Modify: `scripts/s08_validate.py`
- Modify: `tests/test_validate_contracts.py`

**Moments to cover:**

- [ ] Validation start/finish recorded.
- [ ] Each validation section records pass/fail/warn counts.
- [ ] Contract failures are written to `observability_summary.json`.
- [ ] Warnings are grouped by category: legacy, fallback, style, drift, artifact.
- [ ] Exit code is recorded.

**Verification:**

- [ ] Test missing word coverage appears in summary failures.
- [ ] Test ASS overlap appears in summary failures.
- [ ] Test legacy `metadata.json` appears as warning only.

---

## Task 10: UI And SSE Observability

**Files:**

- Modify: `templates/job.html`
- Modify: `templates/index.html`
- Modify: `static/app.js`
- Modify: `static/app.css`

**Moments to cover:**

- [ ] SSE connected/disconnected/retry visible in browser console and UI state.
- [ ] Failed status displays stage, error, and latest validation failures.
- [ ] Done status displays validation summary.
- [ ] Dashboard shows running/failed/done badges from status.
- [ ] Job page shows latest event timeline from `events.jsonl` or summary endpoint.
- [ ] Download buttons remain available for partial artifacts when validation fails.

**Verification:**

- [ ] Browser smoke test for job page with failed summary.
- [ ] Browser smoke test for done summary and download links.
- [ ] JS unit/smoke test for SSE failure message rendering if test harness exists.

---

## Task 11: Developer Commands

Add a small local checklist command set to docs or scripts:

- [ ] `python -m unittest discover tests -v`
- [ ] `python scripts\test_lyrics_robustness.py`
- [ ] `python scripts\s08_validate.py --job-dir jobs\test-struggle`
- [ ] Optional: `python scripts\s05_analyze.py --job-dir jobs\test-struggle --force-rule-based`
- [ ] Optional: `python scripts\s06_generate_ass.py --job-dir jobs\test-struggle --preset section-coded`

---

## Done Criteria

- [ ] Every stage writes structured start/finish/fail events.
- [ ] Every user-visible failure has a structured event and `status.json.error`.
- [ ] `observability_summary.json` is generated for every completed or failed job.
- [ ] UI can show latest failure cause without server logs.
- [ ] Validation failures are machine-readable.
- [ ] Tests cover event writing, stage failure, timeout, analysis failure, ASS overlap, and UI failed/done states.
- [ ] `test-struggle` validation passes or reports clear structured failures.
