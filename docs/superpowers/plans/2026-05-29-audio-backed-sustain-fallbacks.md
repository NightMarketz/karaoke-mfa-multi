# Audio-Backed Sustain Fallbacks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the remaining karaoke timing failures caused by short textual melismas, unwritten interline melismas, lost final-word tails, and false long tails, while keeping backing-vocal/drift cases flagged for review instead of auto-corrected aggressively.

**Architecture:** Extend the existing timing layer in `scripts/review_wizard/timing_layers.py` rather than changing the global renderer. Use `vocals.wav` evidence to produce conservative render adjustments only when a vocal region is clearly attached to the current lyric; otherwise emit diagnostics for the review workflow.

**Tech Stack:** Python stdlib, `numpy`, existing `VocalActivityProbe`, existing Stage 06 ASS generation, `unittest`.

---

## File Structure

- Modify: `scripts/review_wizard/vocal_activity.py`
  - Add helpers to find contiguous vocal regions in a time window, not only aggregate interval activity.
- Modify: `scripts/review_wizard/timing_layers.py`
  - Add audio-backed classifications for written melisma extension, unwritten interline melisma, lost final-word tail, false long tail, and backing-vocal drift.
  - Keep public data structures compatible with the current manifest.
- Modify: `scripts/s06_generate_ass.py`
  - Apply only safe render mutations: extend written melismas, extend confirmed final tails, trim false long tails.
  - Do not auto-realign backing-vocal/drift cases.
- Modify: `tests/test_vocal_activity.py`
  - Add region-detection tests using synthetic WAVs.
- Modify: `tests/test_timing_layers.py`
  - Add regression tests for every user-reported failure class.
- Modify: `tests/test_ass_generation.py`
  - Add integration tests for Stage 06 applying safe timing mutations and preserving review-only diagnostics.

---

### Task 1: Add Vocal Region Detection

**Files:**
- Modify: `scripts/review_wizard/vocal_activity.py`
- Test: `tests/test_vocal_activity.py`

- [ ] **Step 1: Write failing tests for contiguous vocal regions**

Add these tests to `tests/test_vocal_activity.py`:

```python
def test_finds_contiguous_voiced_regions_inside_window(self):
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "vocals.wav"
        _write_sine_window(wav_path, duration_s=5.0, active_start_s=1.0, active_end_s=2.4)

        probe = VocalActivityProbe.from_wav(wav_path)
        regions = probe.voiced_regions(0.5, 3.0)

        self.assertEqual(len(regions), 1)
        self.assertAlmostEqual(regions[0]["start_s"], 1.0, delta=0.12)
        self.assertAlmostEqual(regions[0]["end_s"], 2.4, delta=0.12)
        self.assertGreater(regions[0]["voiced_ratio"], 0.80)


def test_ignores_short_vocal_noise_regions(self):
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "vocals.wav"
        _write_sine_window(wav_path, duration_s=3.0, active_start_s=1.0, active_end_s=1.08)

        probe = VocalActivityProbe.from_wav(wav_path)
        regions = probe.voiced_regions(0.5, 2.0, min_duration_s=0.20)

        self.assertEqual(regions, [])
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m unittest tests.test_vocal_activity
```

Expected: fails because `VocalActivityProbe.voiced_regions` does not exist.

- [ ] **Step 3: Implement `voiced_regions`**

In `scripts/review_wizard/vocal_activity.py`, add a method to `VocalActivityProbe`:

```python
def voiced_regions(
    self,
    start_s: float,
    end_s: float,
    *,
    min_duration_s: float = 0.20,
    merge_gap_s: float = 0.12,
) -> list[dict[str, float | bool]]:
    start_s = max(0.0, float(start_s))
    end_s = max(start_s, float(end_s))
    if end_s <= start_s:
        return []

    start_frame = max(0, int(start_s / self.frame_hop_s))
    end_frame = min(len(self.frame_rms), int(end_s / self.frame_hop_s) + 1)
    active_spans: list[tuple[int, int]] = []
    span_start: int | None = None

    for frame_index in range(start_frame, end_frame):
        is_active = bool(self.frame_rms[frame_index] >= self.threshold)
        if is_active and span_start is None:
            span_start = frame_index
        elif not is_active and span_start is not None:
            active_spans.append((span_start, frame_index))
            span_start = None
    if span_start is not None:
        active_spans.append((span_start, end_frame))

    merged: list[tuple[int, int]] = []
    merge_gap_frames = max(1, int(merge_gap_s / self.frame_hop_s))
    for span in active_spans:
        if not merged or span[0] - merged[-1][1] > merge_gap_frames:
            merged.append(span)
        else:
            merged[-1] = (merged[-1][0], span[1])

    regions: list[dict[str, float | bool]] = []
    for span_start_frame, span_end_frame in merged:
        region_start = max(start_s, span_start_frame * self.frame_hop_s)
        region_end = min(end_s, span_end_frame * self.frame_hop_s)
        duration = max(0.0, region_end - region_start)
        if duration < min_duration_s:
            continue
        stats = self.interval_stats(region_start, region_end)
        regions.append(
            {
                "start_s": round(region_start, 3),
                "end_s": round(region_end, 3),
                "duration_s": round(duration, 3),
                "voiced_ratio": stats["voiced_ratio"],
                "rms": stats["rms"],
                "threshold": stats["threshold"],
                "active": bool(stats["active"]),
            }
        )
    return regions
```

If the class currently uses different attribute names than `frame_rms`, `frame_hop_s`, or `threshold`, adapt the method to the existing names in that file and keep the return shape exactly as above.

- [ ] **Step 4: Run tests and verify pass**

Run:

```powershell
python -m unittest tests.test_vocal_activity
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add scripts/review_wizard/vocal_activity.py tests/test_vocal_activity.py
git commit -m "feat: detect contiguous vocal regions"
```

---

### Task 2: Classify Written Melisma Extensions

**Files:**
- Modify: `scripts/review_wizard/timing_layers.py`
- Test: `tests/test_timing_layers.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_audio_backed_timing_extends_short_written_melisma_when_tail_voice_continues(self):
    lines = [
        {
            "text": "Hmmmmm",
            "style": "intro",
            "start": 12.74,
            "end": 13.18,
            "words": [{"word": "Hmmmmm", "start": 12.74, "end": 13.18}],
        },
        {
            "text": "Still",
            "style": "intro",
            "start": 18.28,
            "end": 19.16,
            "words": [{"word": "Still", "start": 18.28, "end": 19.16}],
        },
    ]
    audio_activity = {
        (0, 0): {"active": True, "voiced_ratio": 1.0},
        ("tail", 0): {
            "active": True,
            "voiced_ratio": 0.90,
            "start_s": 13.18,
            "end_s": 16.20,
            "duration_s": 3.02,
        },
    }

    timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

    self.assertEqual(timing["tail"]["classification"], "written_melisma_extension")
    self.assertEqual(timing["tail"]["audio_evidence"]["end_s"], 16.20)
```

- [ ] **Step 2: Verify failure**

Run:

```powershell
python -m unittest tests.test_timing_layers.TimingLayersTests.test_audio_backed_timing_extends_short_written_melisma_when_tail_voice_continues
```

Expected: fails because the current classifier leaves the line as `tail_melisma`.

- [ ] **Step 3: Implement written melisma extension classification**

In `build_audio_backed_timing`, before `can_promote_audio_tail`, compute:

```python
is_written_melisma_tail = (
    tail.get("classification") == "tail_melisma"
    and _is_textual_melisma(str(tail.get("word") or ""))
)
can_extend_written_melisma = (
    is_written_melisma_tail
    and tail_stats.get("active")
    and float(tail_stats.get("voiced_ratio", 0.0)) >= 0.55
    and float(tail_stats.get("duration_s", 0.0)) >= 0.40
)
```

Then handle it before lost-tail promotion:

```python
if can_extend_written_melisma:
    tail["classification"] = "written_melisma_extension"
    tail["confidence"] = "high" if float(tail_stats.get("voiced_ratio", 0.0)) >= 0.75 else "medium"
    tail["audio_evidence"] = tail_stats
elif can_promote_audio_tail:
    ...
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest tests.test_timing_layers
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add scripts/review_wizard/timing_layers.py tests/test_timing_layers.py
git commit -m "feat: classify written melisma extensions"
```

---

### Task 3: Apply Safe Written Melisma Extensions

**Files:**
- Modify: `scripts/review_wizard/timing_layers.py`
- Modify: `scripts/s06_generate_ass.py`
- Test: `tests/test_timing_layers.py`

- [ ] **Step 1: Write failing test**

Add:

```python
def test_apply_audio_backed_tail_extensions_extends_written_melisma(self):
    lines = [
        {
            "text": "Hmmmmm",
            "start": 12.74,
            "end": 13.18,
            "style": "intro",
            "words": [{"word": "Hmmmmm", "start": 12.74, "end": 13.18}],
        }
    ]
    timings = [
        {
            "tail": {
                "classification": "written_melisma_extension",
                "word_index": 0,
                "audio_evidence": {"end_s": 16.20, "voiced_ratio": 0.90},
            }
        }
    ]

    extended = apply_audio_backed_tail_extensions(lines, timings)

    self.assertEqual(extended[0]["words"][0]["end"], 16.20)
    self.assertEqual(extended[0]["end"], 16.20)
    self.assertEqual(extended[0]["words"][0]["audio_extension"]["classification"], "written_melisma_extension")
```

- [ ] **Step 2: Verify failure**

Run:

```powershell
python -m unittest tests.test_timing_layers.TimingLayersTests.test_apply_audio_backed_tail_extensions_extends_written_melisma
```

Expected: fails because only `probable_unwritten_vowel_extension` is currently applied.

- [ ] **Step 3: Allow safe extension classes**

In `apply_audio_backed_tail_extensions`, replace:

```python
if tail.get("classification") != "probable_unwritten_vowel_extension":
    continue
```

with:

```python
safe_extension_classes = {
    "probable_unwritten_vowel_extension",
    "written_melisma_extension",
}
if tail.get("classification") not in safe_extension_classes:
    continue
```

- [ ] **Step 4: Update Stage 06 count**

In `scripts/s06_generate_ass.py`, change the `applied_tail_extensions` count so it includes both safe classes:

```python
safe_extension_classes = {
    "probable_unwritten_vowel_extension",
    "written_melisma_extension",
}
"applied_tail_extensions": sum(
    1
    for timing in audio_timings
    if timing.get("tail", {}).get("classification") in safe_extension_classes
),
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m unittest tests.test_timing_layers tests.test_ass_generation
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```powershell
git add scripts/review_wizard/timing_layers.py scripts/s06_generate_ass.py tests/test_timing_layers.py
git commit -m "feat: apply safe written melisma extensions"
```

---

### Task 4: Detect False Long Tails

**Files:**
- Modify: `scripts/review_wizard/timing_layers.py`
- Test: `tests/test_timing_layers.py`

- [ ] **Step 1: Write failing test**

Add:

```python
def test_audio_backed_timing_flags_false_long_tail_when_audio_is_inactive(self):
    lines = [
        {
            "text": "I must carry on",
            "style": "outro",
            "start": 362.78,
            "end": 378.86,
            "words": [
                {"word": "I", "start": 362.78, "end": 362.83},
                {"word": "must", "start": 368.86, "end": 369.38},
                {"word": "carry", "start": 372.32, "end": 372.74},
                {"word": "on", "start": 372.78, "end": 378.86},
            ],
        }
    ]
    audio_activity = {
        (0, 3): {"active": False, "voiced_ratio": 0.09, "start_s": 372.78, "end_s": 378.86},
    }

    timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

    self.assertEqual(timing["tail"]["classification"], "false_long_tail")
    self.assertEqual(timing["tail"]["recommended_fallback"], "trim_to_last_active_vocal")
```

- [ ] **Step 2: Verify failure**

Run:

```powershell
python -m unittest tests.test_timing_layers.TimingLayersTests.test_audio_backed_timing_flags_false_long_tail_when_audio_is_inactive
```

Expected: fails because the current code leaves this as `tail_vowel_extension` with inactive audio evidence.

- [ ] **Step 3: Implement false-tail classification**

In `build_audio_backed_timing`, after `last_word_stats` is loaded and before keeping `tail_vowel_extension`, add:

```python
can_trim_false_long_tail = (
    tail.get("classification") == "tail_vowel_extension"
    and float(tail.get("duration_s", 0.0)) >= 2.0
    and last_word_stats
    and not last_word_stats.get("active")
    and float(last_word_stats.get("voiced_ratio", 0.0)) <= 0.25
)
if can_trim_false_long_tail:
    tail["classification"] = "false_long_tail"
    tail["confidence"] = "high"
    tail["recommended_fallback"] = "trim_to_last_active_vocal"
    tail["audio_evidence"] = last_word_stats
elif can_extend_written_melisma:
    ...
```

Keep the existing `tail_melisma` demotion behavior after this block.

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest tests.test_timing_layers
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add scripts/review_wizard/timing_layers.py tests/test_timing_layers.py
git commit -m "feat: flag false long vocal tails"
```

---

### Task 5: Trim False Long Tails Conservatively

**Files:**
- Modify: `scripts/review_wizard/timing_layers.py`
- Test: `tests/test_timing_layers.py`

- [ ] **Step 1: Write failing test**

Add:

```python
def test_apply_audio_backed_tail_extensions_trims_false_long_tail_to_word_start_plus_minimum(self):
    lines = [
        {
            "text": "I must carry on",
            "start": 362.78,
            "end": 378.86,
            "style": "outro",
            "words": [
                {"word": "I", "start": 362.78, "end": 362.83},
                {"word": "must", "start": 368.86, "end": 369.38},
                {"word": "carry", "start": 372.32, "end": 372.74},
                {"word": "on", "start": 372.78, "end": 378.86},
            ],
        }
    ]
    timings = [
        {
            "tail": {
                "classification": "false_long_tail",
                "word_index": 3,
                "audio_evidence": {"voiced_ratio": 0.09},
            }
        }
    ]

    adjusted = apply_audio_backed_tail_extensions(lines, timings)

    self.assertLess(adjusted[0]["words"][3]["end"], 378.86)
    self.assertGreaterEqual(adjusted[0]["words"][3]["end"], 373.18)
    self.assertEqual(adjusted[0]["words"][3]["audio_trim"]["classification"], "false_long_tail")
```

- [ ] **Step 2: Verify failure**

Run:

```powershell
python -m unittest tests.test_timing_layers.TimingLayersTests.test_apply_audio_backed_tail_extensions_trims_false_long_tail_to_word_start_plus_minimum
```

Expected: fails because no trimming exists.

- [ ] **Step 3: Implement conservative trim**

In `apply_audio_backed_tail_extensions`, before the extension branch, add:

```python
if tail.get("classification") == "false_long_tail":
    word_index = int(tail.get("word_index", -1))
    words = extended_lines[line_index].get("words") or []
    if not (0 <= word_index < len(words)):
        continue
    current_start_s = _time(words[word_index].get("start", words[word_index].get("start_s")), 0.0)
    current_end_s = _time(words[word_index].get("end", words[word_index].get("end_s")), current_start_s)
    trimmed_end_s = min(current_end_s, current_start_s + 0.60)
    if trimmed_end_s > current_start_s:
        words[word_index]["end"] = round(trimmed_end_s, 3)
        words[word_index]["audio_trim"] = {
            "source": "vocals.wav",
            "end_s": round(trimmed_end_s, 3),
            "classification": tail.get("classification"),
        }
        extended_lines[line_index]["end"] = max(
            _time(extended_lines[line_index].get("start"), current_start_s),
            round(trimmed_end_s, 3),
        )
    continue
```

This is intentionally conservative: it prevents a subtitle from staying until the end of the song, but does not invent a precise end time when no active vocal was found.

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest tests.test_timing_layers tests.test_ass_generation
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add scripts/review_wizard/timing_layers.py tests/test_timing_layers.py
git commit -m "feat: trim false long vocal tails"
```

---

### Task 6: Detect Unwritten Interline Melismas as Review Events

**Files:**
- Modify: `scripts/review_wizard/timing_layers.py`
- Test: `tests/test_timing_layers.py`

- [ ] **Step 1: Write failing test**

Add:

```python
def test_audio_backed_timing_flags_unwritten_interline_melisma(self):
    lines = [
        {
            "text": "I won't fall",
            "style": "outro",
            "start": 294.18,
            "end": 298.64,
            "words": [
                {"word": "I", "start": 294.18, "end": 294.23},
                {"word": "won't", "start": 294.24, "end": 294.52},
                {"word": "fall", "start": 294.70, "end": 298.64},
            ],
        },
        {
            "text": "I must carry on",
            "style": "outro",
            "start": 300.22,
            "end": 307.38,
            "words": [{"word": "I", "start": 300.22, "end": 300.27}],
        },
    ]
    audio_activity = {
        (0, 2): {"active": True, "voiced_ratio": 1.0},
        ("tail", 0): {
            "active": True,
            "voiced_ratio": 0.88,
            "start_s": 298.64,
            "end_s": 300.12,
            "duration_s": 1.48,
        },
    }

    timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

    self.assertEqual(timing["tail"]["classification"], "unwritten_interline_melisma")
    self.assertEqual(timing["tail"]["recommended_fallback"], "flag_review_or_create_extension_bar")
```

- [ ] **Step 2: Verify failure**

Run:

```powershell
python -m unittest tests.test_timing_layers.TimingLayersTests.test_audio_backed_timing_flags_unwritten_interline_melisma
```

Expected: fails because the current code either treats this as `tail_vowel_extension` or leaves it unchanged.

- [ ] **Step 3: Implement review-only classification**

In `build_audio_backed_timing`, classify tail activity after an already-long final word as an interline melisma:

```python
can_flag_interline_melisma = (
    tail_stats.get("active")
    and float(tail_stats.get("voiced_ratio", 0.0)) >= 0.60
    and float(tail_stats.get("duration_s", 0.0)) >= 0.75
    and float(tail.get("duration_s", 0.0)) >= TAIL_SUSTAIN_THRESHOLD_S
)
if can_flag_interline_melisma:
    tail["classification"] = "unwritten_interline_melisma"
    tail["confidence"] = "medium"
    tail["recommended_fallback"] = "flag_review_or_create_extension_bar"
    tail["audio_evidence"] = tail_stats
elif can_trim_false_long_tail:
    ...
```

Do not apply this class in `apply_audio_backed_tail_extensions` yet. It should be a diagnostic/review event until the UX has a way to represent non-lyric vocal bars.

- [ ] **Step 4: Add diagnostics summary support**

In `summarize_audio_backed_timing`, no code change should be needed because it already counts arbitrary tail classifications. Add this assertion to the test:

```python
summary = summarize_audio_backed_timing([timing])
self.assertEqual(summary["tails"]["unwritten_interline_melisma"], 1)
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m unittest tests.test_timing_layers
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```powershell
git add scripts/review_wizard/timing_layers.py tests/test_timing_layers.py
git commit -m "feat: flag unwritten interline melismas"
```

---

### Task 7: Mark Backing-Vocal Drift as Review-Only

**Files:**
- Modify: `scripts/review_wizard/timing_layers.py`
- Test: `tests/test_timing_layers.py`

- [ ] **Step 1: Write failing test**

Add:

```python
def test_audio_backed_timing_marks_backing_vocal_drift_without_auto_fix(self):
    lines = [
        {
            "text": "Lights go low",
            "style": "bridge",
            "words": [
                {"word": "Lights", "start": 223.28, "end": 227.24},
                {"word": "go", "start": 232.52, "end": 232.64},
                {"word": "low", "start": 233.12, "end": 233.68},
            ],
        }
    ]
    audio_activity = {
        (0, 0): {"active": True, "voiced_ratio": 1.0},
        (0, 1): {"active": True, "voiced_ratio": 0.95},
        (0, 2): {"active": True, "voiced_ratio": 0.95},
    }

    timing = build_audio_backed_timing(lines, audio_activity=audio_activity)[0]

    self.assertEqual(timing["line_classification"], "review_only_backing_or_drift")
    self.assertEqual(timing["recommended_fallback"], "manual_review_or_local_realign")
```

- [ ] **Step 2: Verify failure**

Run:

```powershell
python -m unittest tests.test_timing_layers.TimingLayersTests.test_audio_backed_timing_marks_backing_vocal_drift_without_auto_fix
```

Expected: fails because line-level classification is not emitted.

- [ ] **Step 3: Implement line-level review marker**

At the end of each loop in `build_audio_backed_timing`, before appending `timing`, add:

```python
has_bad_gap = any(gap.get("classification") == "bad_gap" for gap in timing.get("inter_word_gaps", []))
has_audio_supported_word = any(
    (audio_activity.get((line_index, word_index), {}) or {}).get("active")
    for word_index in range(len(words))
)
if has_bad_gap and has_audio_supported_word:
    timing["line_classification"] = "review_only_backing_or_drift"
    timing["confidence"] = "high"
    timing["recommended_fallback"] = "manual_review_or_local_realign"
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest tests.test_timing_layers
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add scripts/review_wizard/timing_layers.py tests/test_timing_layers.py
git commit -m "feat: mark backing vocal drift for review"
```

---

### Task 8: Integration Verification on the Real Job

**Files:**
- No code file changes unless tests reveal a regression.
- Output artifacts: `jobs/202605290001/output.ass`, `jobs/202605290001/output.ass.manifest.json`, optional `jobs/202605290001/timing-layer-test-v2.mp4`

- [ ] **Step 1: Run full focused test suite**

Run:

```powershell
python -m unittest tests.test_vocal_activity tests.test_timing_layers tests.test_ass_generation
```

Expected: `OK`.

- [ ] **Step 2: Run full suite**

Run:

```powershell
python -m unittest discover tests
```

Expected: `OK`.

- [ ] **Step 3: Regenerate ASS for the real job**

Run:

```powershell
python scripts\s06_generate_ass.py --job-dir jobs\202605290001 --preset single-style-kf
```

Expected:
- `jobs/202605290001/output.ass` is regenerated.
- `jobs/202605290001/output.ass.manifest.json` includes new tail counts such as `written_melisma_extension`, `false_long_tail`, and `unwritten_interline_melisma` when detected.

- [ ] **Step 4: Inspect target cases**

Run:

```powershell
Select-String -Path jobs\202605290001\output.ass -Pattern "Hmm|tomb|Blinded|taking|oooohh|Past|Lights|won.t fall|must carry|Oooo|wooow" -Context 0,0
```

Expected:
- `Hmmmmm` lines have longer `\kf` durations if vocals continue.
- `oooohh uuuhhh` and `Oooo wooow` are extended only when audio evidence is continuous.
- Last `I must carry on` no longer leaves `on` highlighted until the end if audio evidence is inactive.
- `Lights go low` remains review-only; it should not be silently auto-realigned.

- [ ] **Step 5: Render a test MP4**

Run from `jobs/202605290001`:

```powershell
Copy-Item -LiteralPath output.ass -Destination timing-layer-test-v2.ass -Force
ffmpeg -y -i instrumental.wav -i vocals.wav -f lavfi -i color=c=black:s=1920x1080:r=30:d=381.000 -filter_complex "[2:v]ass=timing-layer-test-v2.ass[vout];[0:a]volume=1.0[inst];[1:a]volume=1.0[voc];[inst][voc]amix=inputs=2:duration=first[aout]" -map "[vout]" -map "[aout]" -c:v libx264 -crf 18 -c:a aac -b:a 192k -shortest timing-layer-test-v2.mp4
```

Expected:
- `timing-layer-test-v2.mp4` is created.
- Duration is approximately `378.88s`.

---

## Self-Review

Spec coverage:
- Written melismas: covered by Tasks 2 and 3.
- Unwritten melismas: covered by Task 6 as review-only first.
- Lost final tails: existing `probable_unwritten_vowel_extension` remains; Tasks 2 and 3 expand safe classes.
- False final tails: covered by Tasks 4 and 5.
- Backing vocal contamination: covered by Task 7 as review-only.
- No game-style UI: no UI tasks are included.
- Do not aggressively modify renderer: renderer receives adjusted timing data only from safe classes.

Placeholder scan:
- No `TBD`, `TODO`, or open-ended implementation steps remain.

Type consistency:
- New tail classifications are strings in existing `tail["classification"]`.
- Existing summary functions count arbitrary classifications.
- Existing render mutation remains centralized in `apply_audio_backed_tail_extensions`.
