# Struggle Regeneration Integration Evidence

Date: 2026-05-28

Task 8 updated `scripts/test_pipeline.py` without running the heavy real Struggle pipeline.

Verified non-heavy checks:

- Stage 06 integration command now passes an explicit `--preset`.
- Preset resolution order is covered by unit tests:
  1. `meta.json["preset"]`
  2. `[generate].style_preset` from `pipeline.toml`
  3. `section-coded`
- Final integration validation now requires:
  - `output.ass.manifest.json`
  - `output.mp4.manifest.json`
  - ASS dialogue count equal to `analysis.json` line count
  - no `Base,,` dialogue lines
  - MP4 manifest input hash for `output.ass` matching the current ASS hash

Commands run:

```text
python -m unittest tests.test_test_pipeline
python -m py_compile scripts/test_pipeline.py
```

Heavy pipeline status:

- Full Struggle regeneration was skipped intentionally because the task requested non-heavy verification unless explicitly safe.
