# Stage 06 Sound Suggestion Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Stage 06 audio-backed timing quality by validating sound/caption suggestions, review-only diagnostics, and real synthetic-WAV integration coverage.

**Architecture:** Keep rendering conservative: only safe tail extensions/trims alter ASS timings. Store user-facing sound/caption suggestions in `timing_audio_layers.diagnostics` for review, not as automatically rendered subtitle text.

**Tech Stack:** Python `unittest`, Stage 06 ASS generator, synthetic WAV fixtures, JSON manifests.

---

### Task 1: Add Real WAV Trim Integration Coverage

**Files:**
- Modify: `tests/test_ass_generation.py`

- [x] **Step 1: Write the failing test**

Add a Stage 06 integration test that creates a synthetic `vocals.wav`, runs `s06_generate_ass.main()` without patching audio analysis, and verifies a long inactive final word is trimmed.

```python
def test_stage06_real_wav_trims_false_long_tail_in_final_ass(self):
    with tempfile.TemporaryDirectory() as tmp:
        job_dir = Path(tmp)
        lines = [
            {
                "text": "I must carry on",
                "start": 0.50,
                "end": 4.80,
                "style": "outro",
                "effect": "highlight",
                "words": [
                    {"word": "I", "start": 0.50, "end": 0.56},
                    {"word": "must", "start": 2.00, "end": 2.30},
                    {"word": "carry", "start": 2.44, "end": 2.78},
                    {"word": "on", "start": 2.90, "end": 4.80},
                ],
            }
        ]
        self._write_analysis(job_dir, lines)
        self._write_sine_window(job_dir / "vocals.wav", duration_s=5.0, active_start_s=0.50, active_end_s=2.78)

        exit_code = self._run_stage06(job_dir, "--preset", "single-style-kf")

        self.assertEqual(exit_code, 0)
        manifest = json.loads((job_dir / "output.ass.manifest.json").read_text(encoding="utf-8"))
        ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
        self.assertEqual(manifest["timing_audio_layers"]["summary"]["tails"]["false_long_tail"], 1)
        self.assertEqual(manifest["timing_audio_layers"]["applied_tail_trims"], 1)
        self.assertIn("\\kf60}on", ass_content)
```

- [x] **Step 2: Run test to verify behavior**

Run: `python -m unittest tests.test_ass_generation.AssGenerationTests.test_stage06_real_wav_trims_false_long_tail_in_final_ass`

Expected: PASS if production behavior is already correct; otherwise FAIL showing what Stage 06 still misses.

- [x] **Step 3: Implement minimal production fix only if needed**

If the test fails because Stage 06 does not trim inactive long tails from real WAV evidence, adjust only `scripts/review_wizard/timing_layers.py` while preserving existing `false_long_tail` safeguards.

- [x] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_ass_generation tests.test_timing_layers`

Expected: OK.

### Task 2: Audit Real Manifest Sound Suggestions

**Files:**
- Read: `jobs/202605290001/output.ass.manifest.json`
- Read: `jobs/202605290001/analysis.json`
- Read: `scripts/review_wizard/timing_layers.py`
- Read: `scripts/s06_generate_ass.py`

- [x] **Step 1: Extract review suggestions**

List diagnostics with `sound_suggestion` and inspect these examples:

- `sealed in the tomb`
- `I'm taking back my fate`
- `Lights go low`
- `Past the fear`
- `Oooo wooow`
- `Out of my mind`
- `I won't fall`

- [x] **Step 2: Confirm labels**

Expected labels:

- alignment holes and entry drift use blank caption suggestions.
- backing/ad-lib candidates use `[vocal de apoio]` only when structure does not already explain the issue.
- unwritten interline melismas use `[vocalizacao]`.
- written/probable sustained tails use the final word or `word...`.

### Task 3: Final Verification

**Files:**
- Read/modify only files in the Stage 06 audio-backed timing scope.

- [x] **Step 1: Regenerate real Stage 06**

Run: `python scripts\s06_generate_ass.py --job-dir jobs\202605290001 --preset single-style-kf`

Expected: exit code 0, 79 dialogue lines.

- [x] **Step 2: Run full suite**

Run: `python -m unittest discover tests`

Expected: OK.

- [x] **Step 3: Report scope**

List changed files for this task only and note unrelated dirty worktree entries are not part of the Stage 06 sound suggestion changes.
