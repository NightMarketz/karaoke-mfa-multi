# Suno Karaoke Product Design

## Goal

Build a reliable local product flow where the user uploads Suno stems plus lyrics, waits for the pipeline, and receives a rendered MP4 with mixed audio and color-coded karaoke subtitles.

## Product Scope

The MVP is a local Flask application. It is not a hosted SaaS product yet. It should run on the user's machine, process files locally, and make the happy path dependable:

1. User opens the web UI.
2. User uploads either a Suno stems ZIP or separate vocal/instrumental files.
3. User pastes lyrics copied from Suno, including section markers like `[Verse]`, `[Chorus]`, `[Bridge]`, `[Drop]`.
4. User chooses a visual preset.
5. App creates a job and shows stage-by-stage progress.
6. Pipeline aligns lyrics, generates color-coded ASS subtitles, renders MP4, validates outputs, and exposes preview/download links.

Out of scope for this MVP:

- User accounts.
- Cloud storage.
- Payment/billing.
- Multi-machine queue workers.
- Browser-side subtitle editing.
- Public internet deployment hardening beyond local-safe upload/path validation.

## Success Criteria

- A valid Suno stems ZIP plus valid lyrics produces `output.mp4` and `output.ass`.
- The final video contains instrumental and vocal audio mixed together.
- Lyrics are displayed with karaoke timing, word-level highlight, and color/style changes by section type.
- Invalid inputs fail with actionable UI messages.
- The pipeline does not publish a final MP4 when internal validation detects inverted timestamps, missing artifacts, or corrupt subtitles.
- The implementation has focused tests for path safety, job contracts, timestamp repair, and ASS generation.

## Architecture

The system remains file-based, because the existing pipeline already works this way and it makes local audio processing easy to inspect. The architecture should be made stricter by introducing shared contracts and a pipeline runner.

Primary modules:

- `server.py`: Flask routes and view rendering only.
- `scripts/common/contracts.py`: typed helpers for job metadata, status, and artifact names.
- `scripts/common/paths.py`: safe job path and archive member validation.
- `scripts/common/status.py`: atomic status updates shared by all stages.
- `scripts/common/validation.py`: reusable timestamp and artifact checks.
- `scripts/pipeline_runner.py`: orchestration of stage commands and final validation.
- Stage scripts: keep domain logic, but stop duplicating status/path/contract behavior.

## Data Contracts

The job directory is the source of truth:

- `meta.json`: job metadata used by the web app and pipeline.
- `status.json`: stage/progress/error state.
- `lyrics.txt`: optional but recommended Suno lyrics.
- `vocals.wav`: normalized vocal stem.
- `instrumental.wav`: normalized instrumental stem.
- `transcript.json`: segment and word timings from forced alignment or Whisper.
- `aligned.json`: word-level timing plus optional phoneme metadata.
- `analysis.json`: line grouping, section style, effects.
- `output.ass`: subtitle output.
- `output.mp4`: final rendered video.
- `pipeline.log`: stage logs.

`metadata.json` from the older Stage 01 flow should be treated as legacy. New product code should use `meta.json`; compatibility can read `metadata.json` only as fallback.

## Pipeline Flow

1. Ingest
   - Validate job id.
   - Validate ZIP members before extraction.
   - Enforce upload size and expanded ZIP limits.
   - Convert accepted audio files to WAV.
   - Write `meta.json`, `lyrics.txt`, and initial `status.json`.

2. Align lyrics
   - If `lyrics.txt` exists, run `s03b_lyrics_align.py`.
   - Otherwise, fail the product MVP with a clear message or run Whisper only in an explicit fallback mode.

3. Attach phonemes/timing refinement
   - Run `s04_align.py`.
   - Repair or reject inverted timestamps before writing `aligned.json`.

4. Analyze sections
   - Run `s05_analyze.py`.
   - For forced lyrics, preserve section labels from `transcript.json` and avoid LLM unless explicitly enabled.

5. Generate subtitles
   - Run `s06_generate_ass.py`.
   - Apply color-coded styles by section.
   - Escape unsafe ASS text tokens.

6. Render
   - Run `s07_output.py`.
   - Mix instrumental and vocal stems.
   - Render subtitles into MP4.

7. Validate
   - Run `s08_validate.py`.
   - Validate `meta.json` and `status.json`, not only audio/lyrics artifacts.
   - Validate word coverage as a sequence or multiset so repeated words cannot disappear silently.
   - If validation fails, mark job failed and keep artifacts for debugging.
   - If validation passes, mark job done.

## Runtime Model

The product should not start unlimited heavy pipelines in parallel. A local queue with one worker is the default MVP behavior. The status model should distinguish:

- `queued`
- `preparing`
- `aligning_lyrics`
- `transcribing`
- `aligning`
- `analyzing`
- `generating`
- `rendering`
- `validating`
- `done`
- `failed`
- `cancelled`

Deleting a running job should either be blocked with a clear message or implemented as cancellation first, deletion second.

## UI Design

The active UI is Flask templates plus `static/app.css` and `static/app.js`. The `web/` folder appears to be an older standalone frontend and should not be part of the MVP unless it is intentionally revived later.

Required UI states:

- New job form: ZIP upload or separate file upload, lyrics textarea, preset selection.
- Job detail: progress, current stage, log summary, validation status.
- Dashboard: live progress for running jobs, using `data-job-id` attributes for SSE binding.
- Done state: video preview, download MP4, download ASS.
- Partial output state: allow downloading ASS if ASS exists even when MP4 render failed.
- Failed state: stage name, actionable error, keep debug artifacts.

Visual presets:

- `classic`: readable white/cyan karaoke.
- `neon`: high-contrast colorful karaoke.
- `section-coded`: verse, chorus, bridge, drop, intro, outro each get distinct colors.

## Error Handling

All job failures should be represented in `status.json`:

```json
{
  "stage": "failed",
  "progress": 0,
  "error": "Human-readable reason",
  "updated_at": 1779380000.0
}
```

The UI should not require reading server logs to understand common failures.

## Testing Strategy

Tests should start with small deterministic units:

- Job id validation and safe path resolution.
- ZIP member validation.
- Meta/status JSON round-trip.
- Timestamp repair rejects or fixes inverted words.
- Zero-duration words are treated as invalid contract output.
- Repeated-word coverage is checked by sequence or multiset, not plain `set`.
- ASS generation preserves valid timing and style names.
- Pipeline runner marks failed when final validation fails.

Then add integration checks using existing sample jobs where possible:

- `scripts/test_lyrics_robustness.py`
- `scripts/s08_validate.py --job-dir jobs/test-struggle`

## Multi-Agent Ownership Model

Implementation should be split by ownership to reduce conflicts:

- Agent A: shared contracts, paths, status, tests.
- Agent B: pipeline runner and server orchestration.
- Agent C: Stage 04 timestamp repair and validation gate.
- Agent D: ASS style/color-coded improvements.
- Agent E: UI states and frontend polish.

Only one agent should edit a given file family at a time. Review should happen after each slice: spec compliance first, then code quality.
