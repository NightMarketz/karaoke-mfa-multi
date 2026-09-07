# Syllable Timing MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce syllable timing artifacts from existing word phoneme metadata and let Stage 06 render timed syllables.

**Architecture:** Stage 04 already attaches aligned phonemes to words. Stage 05 will conservatively project those phones into syllable groups, write `syllable_map.json` and `syllable_alignment.json`, and enrich `analysis.json` words with timed syllables. Stage 06 and Stage 08 consume the same contracts already added.

**Tech Stack:** Python stdlib JSON, existing Stage 05/06/08 scripts, `unittest`.

---

### Task 1: Stage 05 Projects Phonemes To Syllables

**Files:**
- Modify: `scripts/s05_analyze.py`
- Test: `tests/test_analysis_contract.py`

- [ ] **Step 1: Write failing test**

Add a Stage 05 forced-alignment test using one word with phonemes `B IH N IY TH`.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_analysis_contract.AnalysisContractTests.test_stage05_writes_syllable_artifacts_from_word_phonemes`

- [ ] **Step 3: Implement minimal projection**

Group phones by vowel nuclei; use phone timestamps for syllable starts/ends. If no timed phones exist, leave the word unsyllabified.

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests.test_analysis_contract`

### Task 2: Stage 06 Uses Stage 05 Timed Syllables

**Files:**
- Test: `tests/test_ass_generation.py`

- [ ] **Step 1: Add integration test**

Use an `analysis.json` line containing a word with two timed syllables and assert two `\kf` text chunks render.

- [ ] **Step 2: Run RED/GREEN**

Run: `python -m unittest tests.test_ass_generation.AssGenerationTests.test_stage06_renders_timed_syllables_from_analysis_words`

Expected: pass after Task 1 plus the existing highlight helper.

### Task 3: Stage 08 Accepts Valid Syllable Artifact

**Files:**
- Test: `tests/test_validate_contracts.py`

- [ ] **Step 1: Add happy-path validation test**

Write matching `analysis.json` and `syllable_alignment.json`; assert no validation failures.

- [ ] **Step 2: Run GREEN**

Run: `python -m unittest tests.test_validate_contracts`

### Task 4: Final Verification And Review

- [ ] Run: `python -m unittest tests.test_analysis_contract tests.test_ass_generation tests.test_validate_contracts tests.test_highlight_velocity`
- [ ] Run: `python -m py_compile scripts\s05_analyze.py scripts\s06_generate_ass.py scripts\s08_validate.py scripts\review_wizard\highlight_velocity.py`
- [ ] Dispatch read-only subagent review for spec compliance and code quality.
