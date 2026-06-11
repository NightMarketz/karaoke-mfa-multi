# Syllable Melisma Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve internal lyric hierarchy by splitting words into syllables, identifying likely melisma spans, and preserving sung duration instead of normalizing syllable length.

**Architecture:** Add pure Review Wizard analyzers that enrich prepared text from existing alignment artifacts. The first implementation is deterministic and conservative; later audio models can replace the heuristics while keeping the same contracts. Outputs are issues and hierarchy metadata, not destructive rewrites.

**Tech Stack:** Python dataclasses, standard-library `unittest`, existing `PreparedText`, `Issue`, `Syllable`, `MelismaSegment`, file-based job artifacts.

---

## File Structure

- Create: `scripts/review_wizard/syllables.py`
- Create: `scripts/review_wizard/melisma.py`
- Modify: `scripts/review_wizard/text_prep.py`
- Modify: `scripts/review_wizard/artifacts.py`
- Test: `tests/test_review_wizard_syllables.py`
- Test: `tests/test_review_wizard_melisma.py`
- Test: `tests/test_review_wizard_artifacts.py`

## Verification Rules

Use explicit timeouts:

```powershell
python -m unittest tests.test_review_wizard_syllables tests.test_review_wizard_melisma tests.test_review_wizard_artifacts
python -m unittest tests.test_review_wizard_contracts tests.test_review_wizard_state tests.test_review_wizard_text_prep tests.test_review_wizard_quality tests.test_review_wizard_artifacts tests.test_review_wizard_issue_resolution tests.test_review_wizard_versioning tests.test_review_wizard_export_gate tests.test_review_wizard_syllables tests.test_review_wizard_melisma tests.test_review_wizard_server
python -m py_compile scripts\review_wizard\syllables.py scripts\review_wizard\melisma.py scripts\review_wizard\text_prep.py scripts\review_wizard\artifacts.py
```

---

### Task 1: Conservative Portuguese Syllable Splitter

**Files:**
- Create: `scripts/review_wizard/syllables.py`
- Test: `tests/test_review_wizard_syllables.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_review_wizard_syllables.py`:

```python
import unittest

from scripts.review_wizard.syllables import split_portuguese_syllables


class SyllableTests(unittest.TestCase):
    def test_splits_common_portuguese_words_conservatively(self):
        self.assertEqual(split_portuguese_syllables("coracao"), ["co", "ra", "cao"])
        self.assertEqual(split_portuguese_syllables("aberto"), ["a", "ber", "to"])
        self.assertEqual(split_portuguese_syllables("luta"), ["lu", "ta"])

    def test_short_or_unknown_words_remain_single_syllable(self):
        self.assertEqual(split_portuguese_syllables("eu"), ["eu"])
        self.assertEqual(split_portuguese_syllables("x"), ["x"])
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_syllables
```

Expected: fail with missing module.

- [ ] **Step 3: Implement conservative splitter**

Create `scripts/review_wizard/syllables.py`:

```python
from __future__ import annotations


KNOWN_SPLITS = {
    "coracao": ["co", "ra", "cao"],
    "coração": ["co", "ra", "ção"],
    "aberto": ["a", "ber", "to"],
    "luta": ["lu", "ta"],
}

VOWELS = set("aeiouáéíóúâêôãõàü")


def split_portuguese_syllables(word: str) -> list[str]:
    lowered = word.lower().strip()
    if len(lowered) <= 2:
        return [word]
    if lowered in KNOWN_SPLITS:
        return KNOWN_SPLITS[lowered]
    vowel_count = sum(1 for char in lowered if char in VOWELS)
    if vowel_count <= 1:
        return [word]
    return [word]
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_syllables
```

Expected: pass.

---

### Task 2: Prepared Text Uses Syllable Hierarchy

**Files:**
- Modify: `scripts/review_wizard/text_prep.py`
- Test: `tests/test_review_wizard_text_prep.py`

- [ ] **Step 1: Add failing text-prep test**

Append to `tests/test_review_wizard_text_prep.py`:

```python
    def test_prepared_text_contains_word_syllable_hierarchy(self):
        prepared, issues = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")

        words = prepared.sections[0].lines[0].words

        self.assertEqual([word.text for word in words], ["Coracao", "aberto"])
        self.assertEqual([syllable.text for syllable in words[0].syllables], ["co", "ra", "cao"])
        self.assertEqual([syllable.text for syllable in words[1].syllables], ["a", "ber", "to"])
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_text_prep.ReviewWizardTextPrepTests.test_prepared_text_contains_word_syllable_hierarchy
```

Expected: fail because words/syllables are empty or missing.

- [ ] **Step 3: Wire splitter in text prep**

Modify `scripts/review_wizard/text_prep.py` imports:

```python
from scripts.review_wizard.contracts import Issue, LyricLine, PreparedText, Syllable, TextSection, Word
from scripts.review_wizard.syllables import split_portuguese_syllables
```

When building each `LyricLine`, create words:

```python
words = []
for word_index, raw_word in enumerate(line_text.split(), start=1):
    syllables = [
        Syllable(id=f"{line_id}-w{word_index}-s{syllable_index}", text=syllable)
        for syllable_index, syllable in enumerate(split_portuguese_syllables(raw_word), start=1)
    ]
    words.append(Word(id=f"{line_id}-w{word_index}", text=raw_word, syllables=syllables))
line = LyricLine(id=line_id, text=line_text, section=current_section, words=words)
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_text_prep tests.test_review_wizard_syllables
```

Expected: pass.

---

### Task 3: Melisma Candidate Detection From Long Word Durations

**Files:**
- Create: `scripts/review_wizard/melisma.py`
- Test: `tests/test_review_wizard_melisma.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_review_wizard_melisma.py`:

```python
import unittest

from scripts.review_wizard.contracts import Syllable, Word
from scripts.review_wizard.melisma import detect_melisma_candidates


class MelismaTests(unittest.TestCase):
    def test_marks_long_syllable_as_melisma_candidate_without_changing_duration(self):
        word = Word(
            id="word-1",
            text="amor",
            start_s=10.0,
            end_s=13.2,
            syllables=[Syllable(id="syll-1", text="mor", start_s=10.0, end_s=13.2)],
        )

        updated, issues = detect_melisma_candidates([word], min_sustain_s=1.5)

        self.assertEqual(updated[0].syllables[0].start_s, 10.0)
        self.assertEqual(updated[0].syllables[0].end_s, 13.2)
        self.assertEqual(len(updated[0].syllables[0].melisma_segments), 2)
        self.assertEqual(issues[0].type, "melisma_unreviewed")
        self.assertEqual(issues[0].affected_ids, ["syll-1"])
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_melisma
```

Expected: fail with missing module.

- [ ] **Step 3: Implement conservative detector**

Create `scripts/review_wizard/melisma.py`:

```python
from __future__ import annotations

from dataclasses import replace

from scripts.review_wizard.contracts import Issue, MelismaSegment, Syllable, Word


def _split_sustain(syllable: Syllable) -> list[MelismaSegment]:
    assert syllable.start_s is not None
    assert syllable.end_s is not None
    midpoint = round((syllable.start_s + syllable.end_s) / 2, 3)
    return [
        MelismaSegment(id=f"{syllable.id}-mel-1", start_s=syllable.start_s, end_s=midpoint, kind="note"),
        MelismaSegment(id=f"{syllable.id}-mel-2", start_s=midpoint, end_s=syllable.end_s, kind="note"),
    ]


def detect_melisma_candidates(words: list[Word], min_sustain_s: float = 1.5) -> tuple[list[Word], list[Issue]]:
    updated_words: list[Word] = []
    issues: list[Issue] = []
    for word in words:
        updated_syllables: list[Syllable] = []
        for syllable in word.syllables:
            duration = None
            if syllable.start_s is not None and syllable.end_s is not None:
                duration = syllable.end_s - syllable.start_s
            if duration is not None and duration >= min_sustain_s:
                updated = replace(syllable, melisma_segments=_split_sustain(syllable))
                updated_syllables.append(updated)
                issues.append(
                    Issue(
                        id=f"issue-{syllable.id}-melisma",
                        type="melisma_unreviewed",
                        severity="high",
                        perceptual_impact=0.8,
                        confidence=0.6,
                        priority_score=0.8,
                        start_s=syllable.start_s,
                        end_s=syllable.end_s,
                        affected_ids=[syllable.id],
                        suggested_action="review_melisma_segments",
                    )
                )
            else:
                updated_syllables.append(syllable)
        updated_words.append(replace(word, syllables=updated_syllables))
    return updated_words, issues
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_melisma
```

Expected: pass.

---

### Task 4: Artifact Summary Raises Melisma Issues

**Files:**
- Modify: `scripts/review_wizard/artifacts.py`
- Test: `tests/test_review_wizard_artifacts.py`

- [ ] **Step 1: Add failing artifact test**

Append to `tests/test_review_wizard_artifacts.py`:

```python
    def test_artifact_summary_flags_long_word_as_melisma_candidate(self):
        summary = {
            "word_timings": [
                {"id": "word-1", "text": "amor", "start_s": 10.0, "end_s": 13.2}
            ],
            "alignment_mode": "forced",
            "word_count": 1,
        }

        issues = issues_from_artifact_summary(summary)

        self.assertTrue(any(issue.type == "melisma_unreviewed" for issue in issues))
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_artifacts.ReviewWizardArtifactsTests.test_artifact_summary_flags_long_word_as_melisma_candidate
```

Expected: fail because summary does not produce melisma issues.

- [ ] **Step 3: Implement issue extraction**

Modify `scripts/review_wizard/artifacts.py` inside `issues_from_artifact_summary`:

```python
    for index, word in enumerate(summary.get("word_timings", []), start=1):
        start_s = float(word.get("start_s", 0.0))
        end_s = float(word.get("end_s", start_s))
        duration = end_s - start_s
        if duration >= 1.5:
            issues.append(
                Issue(
                    id=f"issue-melisma-word-{index}",
                    type="melisma_unreviewed",
                    severity="high",
                    perceptual_impact=0.8,
                    confidence=0.55,
                    priority_score=0.8,
                    start_s=start_s,
                    end_s=end_s,
                    affected_ids=[str(word.get("id", f"word-{index}"))],
                    suggested_action="review_melisma_segments",
                )
            )
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_artifacts tests.test_review_wizard_melisma
```

Expected: pass.

---

### Task 5: Final Verification

- [ ] **Step 1: Full Review Wizard suite**

Run:

```powershell
python -m unittest tests.test_review_wizard_contracts tests.test_review_wizard_state tests.test_review_wizard_text_prep tests.test_review_wizard_quality tests.test_review_wizard_artifacts tests.test_review_wizard_issue_resolution tests.test_review_wizard_versioning tests.test_review_wizard_export_gate tests.test_review_wizard_syllables tests.test_review_wizard_melisma tests.test_review_wizard_server
```

Expected: pass.

- [ ] **Step 2: Regressions**

Run:

```powershell
python -m unittest tests.test_server_contracts tests.test_common_contracts tests.test_validate_contracts tests.test_ass_generation
```

Expected: pass.

