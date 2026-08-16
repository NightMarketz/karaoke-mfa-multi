# Syllable QA 3B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make projected syllable timing honest enough for QA by adding source metadata, confidence, final-export gates, and bounded ASS `\kf` drift.

**Architecture:** Keep the Stage 04 -> Stage 05 phone projection path. Stage 05 declares that syllables are projected from existing phonemes, Stage 06 quantizes visible syllable durations to centiseconds without changing the source timeline, and Stage 08 rejects unsafe syllable artifacts.

**Tech Stack:** Python stdlib, `unittest`, existing pipeline scripts under `scripts/`.

---

## Hardcoded Config Audit

| ID | File | Value | Classification | Risk | Decision | Test |
| --- | --- | --- | --- | --- | --- | --- |
| H3B-001 | `scripts/s05_analyze.py` | `projected_from_stage04_phonemes` | artifact contract | Mislabels MVP as native phonetic alignment | Keep as explicit contract string | `test_stage05_writes_syllable_artifacts_from_word_phonemes` |
| H3B-002 | `scripts/s05_analyze.py` | `phone_projection` | artifact contract | Fallback/export gates cannot reason about source | Keep as explicit per-syllable source | `test_stage05_writes_syllable_artifacts_from_word_phonemes` |
| H3B-003 | `scripts/s05_analyze.py` | confidence components | domain constant | Fake precision if hidden or untested | Keep local and visible in score breakdown | `test_stage05_writes_syllable_artifacts_from_word_phonemes` |
| H3B-004 | `scripts/s06_generate_ass.py` | residual applied to last visible segment | ASS artifact contract | Rounded `\kf` can drift from line duration | Implement as pure helper | `test_syllable_kf_quantization_applies_residual_to_last_visible_segment` |
| H3B-005 | `scripts/s08_validate.py` | weak fallback sources block final safety | export gate contract | Draft timing could be treated as final | Fail validation when present | `test_syllable_alignment_rejects_fallback_source_for_final_export` |

## Task 1: Stage 05 Metadata And Confidence

**Files:**
- Modify: `tests/test_analysis_contract.py`
- Modify: `scripts/s05_analyze.py`

- [ ] **Step 1: Write the failing test**

Add assertions to `test_stage05_writes_syllable_artifacts_from_word_phonemes`:

```python
self.assertEqual(syllable_alignment["syllable_timing_mode"], "projected_from_stage04_phonemes")
self.assertEqual(syllable_alignment["phonetic_backend"], "stage04_existing_phonemes")
self.assertIsNone(syllable_alignment["g2p_backend"])
self.assertFalse(syllable_alignment["native_phone_aligner"])
self.assertTrue(syllable_alignment["safe_for_final_export"])
self.assertEqual(syllable_alignment["syllables"][0]["source"], "phone_projection")
self.assertGreaterEqual(syllable_alignment["syllables"][0]["confidence"], 0.7)
self.assertEqual(syllable_alignment["syllables"][0]["flags"], [])
self.assertIn("phone_coverage", syllable_alignment["syllables"][0]["score_breakdown"])
```

- [ ] **Step 2: Verify red**

Run:

```bash
python -m unittest tests.test_analysis_contract.AssAnalysisContractTests.test_stage05_writes_syllable_artifacts_from_word_phonemes
```

Expected: FAIL because Stage 05 does not yet emit the new metadata fields.

- [ ] **Step 3: Implement minimal Stage 05 metadata**

Add source/mode constants and include `source`, `confidence`, `flags`, and `score_breakdown` only for phone-grounded syllables. Do not introduce a G2P backend.

- [ ] **Step 4: Verify green**

Run the same focused test. Expected: PASS.

## Task 2: ASS Syllable Drift Quantization

**Files:**
- Modify: `tests/test_ass_generation.py`
- Modify: `scripts/s06_generate_ass.py`

- [ ] **Step 1: Write the failing test**

Create `test_syllable_kf_quantization_applies_residual_to_last_visible_segment`:

```python
text = _build_karaoke_text(
    [{
        "word": "abc",
        "start": 10.0,
        "end": 10.10,
        "syllables": [
            {"text": "a", "start": 10.000, "end": 10.034},
            {"text": "b", "start": 10.034, "end": 10.067},
            {"text": "c", "start": 10.067, "end": 10.100},
        ],
    }],
    line_start_ms=10000,
    effect="highlight",
)
self.assertIn(r"\kf3}a", text)
self.assertIn(r"\kf3}b", text)
self.assertIn(r"\kf4}c", text)
```

- [ ] **Step 2: Verify red**

Run:

```bash
python -m unittest tests.test_ass_generation.AssGenerationTests.test_syllable_kf_quantization_applies_residual_to_last_visible_segment
```

Expected: FAIL because current floor-division quantization renders `3,3,3`.

- [ ] **Step 3: Implement minimal quantizer**

Add a helper that converts segment start/end milliseconds to centiseconds and applies residual to the last visible segment in the word/absorbed visual window.

- [ ] **Step 4: Verify green**

Run the focused test. Expected: PASS.

## Task 3: Stage 08 Syllable Safety Gates

**Files:**
- Modify: `tests/test_validate_contracts.py`
- Modify: `scripts/s08_validate.py`

- [ ] **Step 1: Write failing tests**

Add tests that validate these failures:

```python
self.assertTrue(any("missing source" in failure for failure in s08_validate._failures))
self.assertTrue(any("fallback source" in failure for failure in s08_validate._failures))
self.assertTrue(any("outside alignment window" in failure for failure in s08_validate._failures))
self.assertTrue(any("long non-vocal gap" in failure for failure in s08_validate._failures))
```

- [ ] **Step 2: Verify red**

Run:

```bash
python -m unittest tests.test_validate_contracts.ValidateContractsTests
```

Expected: new tests fail because Stage 08 only checks basic syllable timing.

- [ ] **Step 3: Implement minimal validation**

Reject missing source/confidence, reject fallback-like sources for final safety, validate syllables against `alignment_windows.json` when present, and reject overlap with long non-vocal gaps from `vocal_regions.json`.

- [ ] **Step 4: Verify green**

Run the focused validation tests. Expected: PASS.

## Task 4: Final Verification

**Files:**
- No new production files.

- [ ] **Step 1: Run focused suites**

```bash
python -m unittest tests.test_analysis_contract tests.test_ass_generation tests.test_validate_contracts tests.test_highlight_velocity tests.test_pipeline_runner
```

- [ ] **Step 2: Run contract suites**

```bash
python -m unittest tests.test_code_quality_contracts tests.test_project_knowledge_base tests.test_pipeline_stage_contracts tests.test_alignment_windows tests.test_audio_alignment_contracts
```

- [ ] **Step 3: Compile touched scripts**

```bash
python -m py_compile scripts\s05_analyze.py scripts\s06_generate_ass.py scripts\s08_validate.py scripts\review_wizard\highlight_velocity.py
```
