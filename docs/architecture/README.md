# Architecture Map

## Pipeline Stages

- `scripts/s01_input.py` - input validation and WAV normalization.
- `scripts/s02_demix.py` - Demucs source separation.
- `scripts/s03_transcribe.py` - Whisper transcription when lyrics are absent.
- `scripts/s03b_lyrics_align.py` - lyrics-first CTC alignment.
- `scripts/s04_align.py` - HubertFA phoneme alignment and fallback timing.
- `scripts/s05_analyze.py` - line grouping and style analysis.
- `scripts/s06_generate_ass.py` - ASS subtitle generation.
- `scripts/s07_output.py` - MP4 rendering with ffmpeg.
- `scripts/s08_validate.py` - pipeline validation.

## Orchestration

- `scripts/pipeline_runner.py` runs the staged pipeline for web jobs.
- `server.py` exposes the Flask UI, job lifecycle, review wizard, and exports.
- `pipeline.toml` holds project-level pipeline defaults where they already
  exist.

## Review And Quality

- `scripts/review_wizard/` contains review wizard state, issue, export, and
  timing analysis modules.
- `scripts/common/` contains shared observability, path, status, provenance,
  and validation helpers.
- `tests/` contains unit and contract tests for pipeline behavior.
