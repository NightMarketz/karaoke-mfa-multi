# Review Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first production-shaped Review Wizard slice: complete contracts, wizard state, prepared text review, quality issues, non-destructive takes, preview/export gates, and UI entry points.

**Architecture:** Add a new isolated `scripts/review_wizard` package that owns Review Wizard contracts and pure domain logic. Flask reads/writes those contracts and renders wizard screens, while existing pipeline stages keep producing current artifacts. Separate future plans will deepen syllable timing, melisma analysis, timeline rendering, and export fidelity.

**Tech Stack:** Python dataclasses, Flask/Jinja, existing file-based jobs, standard-library `unittest`, existing ASS/MP4 pipeline scripts, static CSS/JS.

---

## SDD Ownership

- **Agent A: Contracts and persistence**
  - Owns `scripts/review_wizard/contracts.py`, `scripts/review_wizard/store.py`, `tests/test_review_wizard_contracts.py`.
- **Agent B: Wizard state and gates**
  - Owns `scripts/review_wizard/wizard.py`, `tests/test_review_wizard_state.py`.
- **Agent C: Text preparation and issue generation**
  - Owns `scripts/review_wizard/text_prep.py`, `scripts/review_wizard/quality.py`, `tests/test_review_wizard_text_prep.py`, `tests/test_review_wizard_quality.py`.
- **Agent D: Takes, edit operations, preview/export gates**
  - Owns `scripts/review_wizard/versioning.py`, `scripts/review_wizard/export_gate.py`, `tests/test_review_wizard_versioning.py`, `tests/test_review_wizard_export_gate.py`.
- **Agent E: Flask routes and templates**
  - Owns `server.py`, `templates/review_wizard.html`, `templates/job.html`, `static/app.css`, `static/app.js`, `tests/test_review_wizard_server.py`.

Agents are not alone in the codebase. Do not revert or rewrite another agent's files. If an interface needs to change, update the owning agent's contract through a small explicit patch.

## Verification Rules

Every test command must run with a timeout in the Codex tool call. Use these time budgets unless a task states otherwise:

- Focused unit test: `timeout_ms=30000`
- Focused Flask/server test: `timeout_ms=60000`
- Full Review Wizard suite: `timeout_ms=120000`
- Py compile check: `timeout_ms=30000`

Final verification command set:

```powershell
python -m py_compile server.py scripts\review_wizard\contracts.py scripts\review_wizard\store.py scripts\review_wizard\wizard.py scripts\review_wizard\text_prep.py scripts\review_wizard\quality.py scripts\review_wizard\versioning.py scripts\review_wizard\export_gate.py
python -m unittest tests.test_review_wizard_contracts tests.test_review_wizard_state tests.test_review_wizard_text_prep tests.test_review_wizard_quality tests.test_review_wizard_versioning tests.test_review_wizard_export_gate tests.test_review_wizard_server
```

---

## File Structure

- Create: `scripts/review_wizard/__init__.py`
- Create: `scripts/review_wizard/contracts.py`
- Create: `scripts/review_wizard/store.py`
- Create: `scripts/review_wizard/wizard.py`
- Create: `scripts/review_wizard/text_prep.py`
- Create: `scripts/review_wizard/quality.py`
- Create: `scripts/review_wizard/versioning.py`
- Create: `scripts/review_wizard/export_gate.py`
- Create: `templates/review_wizard.html`
- Create: `tests/test_review_wizard_contracts.py`
- Create: `tests/test_review_wizard_state.py`
- Create: `tests/test_review_wizard_text_prep.py`
- Create: `tests/test_review_wizard_quality.py`
- Create: `tests/test_review_wizard_versioning.py`
- Create: `tests/test_review_wizard_export_gate.py`
- Create: `tests/test_review_wizard_server.py`
- Modify: `server.py`
- Modify: `templates/job.html`
- Modify: `static/app.css`
- Modify: `static/app.js`

---

### Task 1: Review Wizard Contracts

**Files:**
- Create: `scripts/review_wizard/__init__.py`
- Create: `scripts/review_wizard/contracts.py`
- Test: `tests/test_review_wizard_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_review_wizard_contracts.py`:

```python
import unittest

from scripts.review_wizard.contracts import (
    AlignmentTake,
    EditOperation,
    Issue,
    LyricLine,
    MediaAsset,
    MelismaSegment,
    PreparedText,
    Project,
    QualityReport,
    Syllable,
    TextSection,
    Word,
)


class ReviewWizardContractTests(unittest.TestCase):
    def test_project_contract_contains_gold_standard_top_level_keys(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        payload = project.to_dict()

        self.assertEqual(payload["project_id"], "proj-1")
        self.assertEqual(payload["job_id"], "abc123def456")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["media_assets"], [])
        self.assertEqual(payload["alignment_takes"], [])
        self.assertEqual(payload["edit_operations"], [])
        self.assertEqual(payload["issues"], [])
        self.assertEqual(payload["quality_reports"], [])
        self.assertEqual(payload["preview_renders"], [])
        self.assertIsNone(payload["approved_take_id"])
        self.assertEqual(payload["style_preset_id"], "default")
        self.assertEqual(payload["style_overrides"], {})

    def test_hierarchical_text_serializes_line_word_syllable_melisma(self):
        syllable = Syllable(
            id="syll-1",
            text="mor",
            start_s=1.2,
            end_s=2.4,
            confidence=0.91,
            melisma_segments=[
                MelismaSegment(id="mel-1", start_s=1.2, end_s=1.7, kind="note"),
                MelismaSegment(id="mel-2", start_s=1.7, end_s=2.4, kind="note"),
            ],
        )
        word = Word(id="word-1", text="amor", syllables=[syllable])
        line = LyricLine(id="line-1", text="amor", section="chorus", words=[word])
        section = TextSection(id="sec-1", label="Chorus", lines=[line])
        prepared = PreparedText(language="pt", sections=[section])

        payload = prepared.to_dict()

        self.assertEqual(payload["sections"][0]["lines"][0]["words"][0]["syllables"][0]["text"], "mor")
        self.assertEqual(
            len(payload["sections"][0]["lines"][0]["words"][0]["syllables"][0]["melisma_segments"]),
            2,
        )

    def test_issue_quality_and_take_contracts_are_traceable(self):
        issue = Issue(
            id="issue-1",
            type="melisma_unreviewed",
            severity="high",
            perceptual_impact=0.91,
            confidence=0.62,
            priority_score=0.88,
            start_s=12.0,
            end_s=14.0,
            affected_ids=["syll-1"],
            suggested_action="review_melisma_segments",
        )
        take = AlignmentTake(
            id="take-1",
            kind="conservative",
            status="needs_review",
            line_ids=["line-1"],
        )
        report = QualityReport(
            id="report-1",
            take_id="take-1",
            status="needs_fix",
            score=0.72,
            issue_ids=["issue-1"],
        )
        op = EditOperation(
            id="op-1",
            operation="move_syllable_boundary",
            target_id="syll-1",
            created_by="user",
            details={"from": 12.34, "to": 12.372, "snap_source": "vocal_onset"},
        )
        media = MediaAsset(id="asset-1", kind="vocal", path="vocals.wav")

        self.assertEqual(issue.to_dict()["suggested_action"], "review_melisma_segments")
        self.assertEqual(take.to_dict()["kind"], "conservative")
        self.assertEqual(report.to_dict()["status"], "needs_fix")
        self.assertEqual(op.to_dict()["details"]["snap_source"], "vocal_onset")
        self.assertEqual(media.to_dict()["kind"], "vocal")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_contracts
```

Expected: fail with `ModuleNotFoundError: No module named 'scripts.review_wizard'`.

- [ ] **Step 3: Implement minimal contracts**

Create `scripts/review_wizard/__init__.py`:

```python
"""Review Wizard domain package."""
```

Create `scripts/review_wizard/contracts.py` with frozen dataclasses and `to_dict()` helpers:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _clean_dict(value: Any) -> Any:
    if isinstance(value, list):
        return [_clean_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean_dict(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class MelismaSegment:
    id: str
    start_s: float
    end_s: float
    kind: str = "note"
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class Syllable:
    id: str
    text: str
    start_s: float | None = None
    end_s: float | None = None
    confidence: float | None = None
    review_status: str = "generated"
    melisma_segments: list[MelismaSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class Word:
    id: str
    text: str
    syllables: list[Syllable] = field(default_factory=list)
    start_s: float | None = None
    end_s: float | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class LyricLine:
    id: str
    text: str
    section: str
    words: list[Word] = field(default_factory=list)
    start_s: float | None = None
    end_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class TextSection:
    id: str
    label: str
    lines: list[LyricLine] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class PreparedText:
    language: str
    sections: list[TextSection] = field(default_factory=list)
    source: str = "generated"
    review_status: str = "needs_review"

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class MediaAsset:
    id: str
    kind: str
    path: str
    needs_stem_extraction: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class AlignmentTake:
    id: str
    kind: str
    status: str
    line_ids: list[str] = field(default_factory=list)
    parent_take_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class EditOperation:
    id: str
    operation: str
    target_id: str
    created_by: str
    details: dict[str, Any] = field(default_factory=dict)
    created_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class Issue:
    id: str
    type: str
    severity: str
    perceptual_impact: float
    confidence: float
    priority_score: float
    start_s: float
    end_s: float
    affected_ids: list[str]
    suggested_action: str
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class QualityReport:
    id: str
    take_id: str
    status: str
    score: float
    issue_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class Project:
    project_id: str
    job_id: str
    schema_version: int = 1
    media_assets: list[MediaAsset] = field(default_factory=list)
    prepared_text: PreparedText | None = None
    evidence_bundle: dict[str, Any] = field(default_factory=dict)
    alignment_takes: list[AlignmentTake] = field(default_factory=list)
    edit_operations: list[EditOperation] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    quality_reports: list[QualityReport] = field(default_factory=list)
    preview_renders: list[dict[str, Any]] = field(default_factory=list)
    approved_take_id: str | None = None
    style_preset_id: str = "default"
    style_overrides: dict[str, Any] = field(default_factory=dict)
    exports: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def new(cls, project_id: str, job_id: str) -> "Project":
        return cls(project_id=project_id, job_id=job_id)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.prepared_text is None:
            payload["prepared_text"] = {}
        return _clean_dict(payload)
```

- [ ] **Step 4: Run the contract tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_contracts
```

Expected: 3 tests pass.

---

### Task 2: Project Store

**Files:**
- Create: `scripts/review_wizard/store.py`
- Modify: `scripts/review_wizard/contracts.py`
- Test: `tests/test_review_wizard_contracts.py`

- [ ] **Step 1: Add failing persistence tests**

Add these imports at the top of `tests/test_review_wizard_contracts.py`:

```python
import json
import tempfile
from pathlib import Path

from scripts.review_wizard.store import load_project, project_path, save_project
```

Add test method:

```python
    def test_project_store_round_trips_review_wizard_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            project = Project.new(project_id="proj-1", job_id="abc123def456")

            save_project(job_dir, project)
            loaded = load_project(job_dir)

            self.assertEqual(project_path(job_dir).name, "review_wizard.json")
            self.assertEqual(loaded.project_id, "proj-1")
            self.assertEqual(loaded.job_id, "abc123def456")
            raw = json.loads(project_path(job_dir).read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], 1)
```

- [ ] **Step 2: Run the failing persistence test**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_contracts.ReviewWizardContractTests.test_project_store_round_trips_review_wizard_json
```

Expected: fail because `scripts.review_wizard.store` does not exist.

- [ ] **Step 3: Implement `from_dict` and store helpers**

Add nested reconstruction helpers and `Project.from_dict` in `scripts/review_wizard/contracts.py`:

```python
def _melisma_segment_from_dict(data: dict[str, Any]) -> MelismaSegment:
    return MelismaSegment(**data)


def _syllable_from_dict(data: dict[str, Any]) -> Syllable:
    return Syllable(
        id=str(data["id"]),
        text=str(data["text"]),
        start_s=data.get("start_s"),
        end_s=data.get("end_s"),
        confidence=data.get("confidence"),
        review_status=str(data.get("review_status", "generated")),
        melisma_segments=[
            _melisma_segment_from_dict(item) for item in data.get("melisma_segments", [])
        ],
    )


def _word_from_dict(data: dict[str, Any]) -> Word:
    return Word(
        id=str(data["id"]),
        text=str(data["text"]),
        syllables=[_syllable_from_dict(item) for item in data.get("syllables", [])],
        start_s=data.get("start_s"),
        end_s=data.get("end_s"),
        confidence=data.get("confidence"),
    )


def _line_from_dict(data: dict[str, Any]) -> LyricLine:
    return LyricLine(
        id=str(data["id"]),
        text=str(data["text"]),
        section=str(data["section"]),
        words=[_word_from_dict(item) for item in data.get("words", [])],
        start_s=data.get("start_s"),
        end_s=data.get("end_s"),
    )


def _section_from_dict(data: dict[str, Any]) -> TextSection:
    return TextSection(
        id=str(data["id"]),
        label=str(data["label"]),
        lines=[_line_from_dict(item) for item in data.get("lines", [])],
    )


def _prepared_text_from_dict(data: dict[str, Any]) -> PreparedText | None:
    if not data:
        return None
    return PreparedText(
        language=str(data["language"]),
        sections=[_section_from_dict(item) for item in data.get("sections", [])],
        source=str(data.get("source", "generated")),
        review_status=str(data.get("review_status", "needs_review")),
    )


    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        return cls(
            project_id=str(data["project_id"]),
            job_id=str(data["job_id"]),
            schema_version=int(data.get("schema_version", 1)),
            media_assets=[MediaAsset(**item) for item in data.get("media_assets", [])],
            prepared_text=_prepared_text_from_dict(dict(data.get("prepared_text") or {})),
            alignment_takes=[AlignmentTake(**item) for item in data.get("alignment_takes", [])],
            edit_operations=[EditOperation(**item) for item in data.get("edit_operations", [])],
            issues=[Issue(**item) for item in data.get("issues", [])],
            quality_reports=[QualityReport(**item) for item in data.get("quality_reports", [])],
            style_preset_id=str(data.get("style_preset_id", "default")),
            style_overrides=dict(data.get("style_overrides", {})),
            approved_take_id=data.get("approved_take_id"),
            evidence_bundle=dict(data.get("evidence_bundle", {})),
            preview_renders=list(data.get("preview_renders", [])),
            exports=list(data.get("exports", [])),
            wizard_steps=dict(data.get("wizard_steps", {})),
        )
```

Create `scripts/review_wizard/store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from scripts.review_wizard.contracts import Project


def project_path(job_dir: Path) -> Path:
    return job_dir / "review_wizard.json"


def save_project(job_dir: Path, project: Project) -> None:
    tmp = job_dir / "review_wizard.json.tmp"
    tmp.write_text(
        json.dumps(project.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(project_path(job_dir))


def load_project(job_dir: Path) -> Project:
    return Project.from_dict(json.loads(project_path(job_dir).read_text(encoding="utf-8")))
```

- [ ] **Step 4: Run persistence tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_contracts
```

Expected: all contract tests pass.

---

### Task 3: Wizard State Machine

**Files:**
- Create: `scripts/review_wizard/wizard.py`
- Modify: `scripts/review_wizard/contracts.py`
- Test: `tests/test_review_wizard_state.py`

- [ ] **Step 1: Write failing wizard state tests**

Create `tests/test_review_wizard_state.py`:

```python
import unittest

from scripts.review_wizard.contracts import Project
from scripts.review_wizard.wizard import (
    REVIEW_WIZARD_STEPS,
    approve_step,
    next_step,
    skip_step_with_risk,
)


class ReviewWizardStateTests(unittest.TestCase):
    def test_steps_are_ordered_around_review_wizard_flow(self):
        self.assertEqual(
            REVIEW_WIZARD_STEPS,
            [
                "import",
                "text_review",
                "alignment_processing",
                "quality_review",
                "preview_approval",
                "export",
            ],
        )

    def test_approve_step_marks_status_and_advances(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = approve_step(project, "import", approved_by="user")

        self.assertEqual(updated.wizard_steps["import"]["status"], "approved")
        self.assertEqual(updated.wizard_steps["import"]["approved_by"], "user")
        self.assertEqual(next_step(updated), "text_review")

    def test_skip_step_with_risk_requires_reason_and_creates_issue(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = skip_step_with_risk(
            project,
            "text_review",
            skipped_by="user",
            reason="lyrics verified externally",
        )

        self.assertEqual(updated.wizard_steps["text_review"]["status"], "skipped_with_risk")
        self.assertEqual(updated.wizard_steps["text_review"]["reason"], "lyrics verified externally")
        self.assertEqual(updated.issues[0].type, "wizard_step_skipped")
        self.assertEqual(updated.issues[0].severity, "medium")

    def test_skip_without_reason_is_rejected(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        with self.assertRaises(ValueError):
            skip_step_with_risk(project, "text_review", skipped_by="user", reason="")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing wizard tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_state
```

Expected: fail because `scripts.review_wizard.wizard` does not exist.

- [ ] **Step 3: Add wizard state to project contract**

Add field to `Project`:

```python
    wizard_steps: dict[str, dict[str, Any]] = field(default_factory=dict)
```

Ensure `to_dict()` includes `wizard_steps`.

- [ ] **Step 4: Implement wizard logic**

Create `scripts/review_wizard/wizard.py`:

```python
from __future__ import annotations

from dataclasses import replace
from time import time

from scripts.review_wizard.contracts import Issue, Project


REVIEW_WIZARD_STEPS = [
    "import",
    "text_review",
    "alignment_processing",
    "quality_review",
    "preview_approval",
    "export",
]


def _default_steps(project: Project) -> dict[str, dict[str, object]]:
    steps = {step: {"status": "not_started"} for step in REVIEW_WIZARD_STEPS}
    steps.update(project.wizard_steps)
    return steps


def approve_step(project: Project, step: str, approved_by: str) -> Project:
    if step not in REVIEW_WIZARD_STEPS:
        raise ValueError(f"Unknown wizard step: {step}")
    steps = _default_steps(project)
    steps[step] = {
        "status": "approved",
        "approved_by": approved_by,
        "approved_at": time(),
    }
    return replace(project, wizard_steps=steps)


def skip_step_with_risk(project: Project, step: str, skipped_by: str, reason: str) -> Project:
    if step not in REVIEW_WIZARD_STEPS:
        raise ValueError(f"Unknown wizard step: {step}")
    if not reason.strip():
        raise ValueError("Skipping a wizard step requires a reason.")
    steps = _default_steps(project)
    steps[step] = {
        "status": "skipped_with_risk",
        "skipped_by": skipped_by,
        "skipped_at": time(),
        "reason": reason.strip(),
    }
    issue = Issue(
        id=f"wizard-risk-{step}",
        type="wizard_step_skipped",
        severity="medium",
        perceptual_impact=0.7,
        confidence=1.0,
        priority_score=0.7,
        start_s=0.0,
        end_s=0.0,
        affected_ids=[step],
        suggested_action="preview_before_export",
    )
    return replace(project, wizard_steps=steps, issues=[*project.issues, issue])


def next_step(project: Project) -> str | None:
    steps = _default_steps(project)
    for step in REVIEW_WIZARD_STEPS:
        if steps[step]["status"] not in {"approved", "skipped_with_risk"}:
            return step
    return None
```

- [ ] **Step 5: Run wizard tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_state
```

Expected: 4 tests pass.

---

### Task 4: Prepared Text Review

**Files:**
- Create: `scripts/review_wizard/text_prep.py`
- Test: `tests/test_review_wizard_text_prep.py`

- [ ] **Step 1: Write failing text preparation tests**

Create `tests/test_review_wizard_text_prep.py`:

```python
import unittest

from scripts.review_wizard.text_prep import prepare_text_for_review


class ReviewWizardTextPrepTests(unittest.TestCase):
    def test_prepare_text_detects_sections_lines_words_and_basic_syllables(self):
        prepared, issues = prepare_text_for_review(
            "[Verse]\nCoração aberto\n[Chorus]\nAmor maior",
            language="pt",
        )

        payload = prepared.to_dict()

        self.assertEqual(prepared.language, "pt")
        self.assertEqual([section.label for section in prepared.sections], ["Verse", "Chorus"])
        self.assertEqual(payload["sections"][0]["lines"][0]["text"], "Coração aberto")
        self.assertEqual(payload["sections"][0]["lines"][0]["words"][0]["text"], "Coração")
        self.assertGreaterEqual(len(payload["sections"][0]["lines"][0]["words"][0]["syllables"]), 2)
        self.assertEqual(issues, [])

    def test_prepare_text_creates_issue_for_long_line(self):
        long_line = " ".join(["palavra"] * 18)

        _, issues = prepare_text_for_review(long_line, language="pt")

        self.assertEqual(issues[0].type, "text_line_too_long")
        self.assertEqual(issues[0].suggested_action, "split_line")

    def test_prepare_text_keeps_display_text_when_contraction_is_likely(self):
        prepared, issues = prepare_text_for_review("para amor", language="pt")

        line = prepared.sections[0].lines[0]

        self.assertEqual(line.text, "para amor")
        self.assertTrue(any(issue.type == "possible_contraction" for issue in issues))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing text prep tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_text_prep
```

Expected: fail because `scripts.review_wizard.text_prep` does not exist.

- [ ] **Step 3: Implement minimal deterministic text preparation**

Create `scripts/review_wizard/text_prep.py`:

```python
from __future__ import annotations

import re

from scripts.review_wizard.contracts import Issue, LyricLine, PreparedText, Syllable, TextSection, Word


VOWELS = "aeiouáéíóúâêôãõàüAEIOUÁÉÍÓÚÂÊÔÃÕÀÜ"


def _slug(prefix: str, index: int) -> str:
    return f"{prefix}-{index + 1}"


def _basic_syllables(word: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for char in word:
        current += char
        if char in VOWELS and current:
            chunks.append(current)
            current = ""
    if current:
        if chunks:
            chunks[-1] += current
        else:
            chunks.append(current)
    return chunks or [word]


def _split_sections(raw_lyrics: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_label = "Verse"
    current_lines: list[str] = []
    for raw in raw_lyrics.splitlines():
        line = raw.strip()
        if not line:
            continue
        marker = re.fullmatch(r"\[([^\]]+)\]", line)
        if marker:
            if current_lines:
                sections.append((current_label, current_lines))
                current_lines = []
            current_label = marker.group(1).strip() or "Verse"
            continue
        current_lines.append(line)
    if current_lines:
        sections.append((current_label, current_lines))
    return sections or [("Verse", [])]


def prepare_text_for_review(raw_lyrics: str, language: str) -> tuple[PreparedText, list[Issue]]:
    issues: list[Issue] = []
    sections: list[TextSection] = []
    line_index = 0
    word_index = 0
    syllable_index = 0
    for section_index, (label, lines) in enumerate(_split_sections(raw_lyrics)):
        lyric_lines: list[LyricLine] = []
        for text in lines:
            words: list[Word] = []
            tokens = re.findall(r"[\wÀ-ÿ']+", text)
            if len(tokens) > 14:
                issues.append(
                    Issue(
                        id=f"issue-long-line-{line_index + 1}",
                        type="text_line_too_long",
                        severity="medium",
                        perceptual_impact=0.65,
                        confidence=1.0,
                        priority_score=0.65,
                        start_s=0.0,
                        end_s=0.0,
                        affected_ids=[_slug("line", line_index)],
                        suggested_action="split_line",
                    )
                )
            if language == "pt" and re.search(r"\bpara\s+amor\b", text, flags=re.IGNORECASE):
                issues.append(
                    Issue(
                        id=f"issue-contraction-{line_index + 1}",
                        type="possible_contraction",
                        severity="low",
                        perceptual_impact=0.4,
                        confidence=0.7,
                        priority_score=0.4,
                        start_s=0.0,
                        end_s=0.0,
                        affected_ids=[_slug("line", line_index)],
                        suggested_action="review_sung_variant",
                    )
                )
            for token in tokens:
                syllables = [
                    Syllable(id=_slug("syllable", syllable_index + idx), text=part)
                    for idx, part in enumerate(_basic_syllables(token))
                ]
                syllable_index += len(syllables)
                words.append(Word(id=_slug("word", word_index), text=token, syllables=syllables))
                word_index += 1
            lyric_lines.append(
                LyricLine(
                    id=_slug("line", line_index),
                    text=text,
                    section=label.lower(),
                    words=words,
                )
            )
            line_index += 1
        sections.append(TextSection(id=_slug("section", section_index), label=label, lines=lyric_lines))
    return PreparedText(language=language, sections=sections), issues
```

- [ ] **Step 4: Run text prep tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_text_prep
```

Expected: 3 tests pass.

---

### Task 5: Quality Issue Prioritization

**Files:**
- Create: `scripts/review_wizard/quality.py`
- Test: `tests/test_review_wizard_quality.py`

- [ ] **Step 1: Write failing quality tests**

Create `tests/test_review_wizard_quality.py`:

```python
import unittest

from scripts.review_wizard.contracts import Issue
from scripts.review_wizard.quality import prioritize_issues, quality_status


class ReviewWizardQualityTests(unittest.TestCase):
    def test_prioritize_issues_orders_by_perceptual_impact_first(self):
        technical = Issue(
            id="technical",
            type="boundary_error",
            severity="high",
            perceptual_impact=0.3,
            confidence=0.9,
            priority_score=0.0,
            start_s=1,
            end_s=2,
            affected_ids=["a"],
            suggested_action="snap_to_onset",
        )
        perceptual = Issue(
            id="perceptual",
            type="melisma_unreviewed",
            severity="medium",
            perceptual_impact=0.9,
            confidence=0.5,
            priority_score=0.0,
            start_s=10,
            end_s=14,
            affected_ids=["b"],
            suggested_action="review_melisma_segments",
        )

        ordered = prioritize_issues([technical, perceptual])

        self.assertEqual([issue.id for issue in ordered], ["perceptual", "technical"])
        self.assertGreater(ordered[0].priority_score, ordered[1].priority_score)

    def test_quality_status_uses_ready_review_and_needs_fix_thresholds(self):
        self.assertEqual(quality_status(score=0.96, critical_open_issues=0), "ready")
        self.assertEqual(quality_status(score=0.90, critical_open_issues=0), "review_suggested")
        self.assertEqual(quality_status(score=0.90, critical_open_issues=1), "needs_fix")
        self.assertEqual(quality_status(score=0.70, critical_open_issues=0), "needs_fix")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing quality tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_quality
```

Expected: fail because `scripts.review_wizard.quality` does not exist.

- [ ] **Step 3: Implement quality scoring helpers**

Create `scripts/review_wizard/quality.py`:

```python
from __future__ import annotations

from dataclasses import replace

from scripts.review_wizard.contracts import Issue


SEVERITY_WEIGHT = {
    "low": 0.1,
    "medium": 0.2,
    "high": 0.3,
    "critical": 0.4,
}


def _priority(issue: Issue) -> float:
    duration = max(0.0, issue.end_s - issue.start_s)
    duration_weight = min(duration / 10.0, 0.15)
    uncertainty_weight = (1.0 - issue.confidence) * 0.15
    severity_weight = SEVERITY_WEIGHT.get(issue.severity, 0.2)
    return round(
        min(1.0, issue.perceptual_impact * 0.6 + severity_weight + uncertainty_weight + duration_weight),
        4,
    )


def prioritize_issues(issues: list[Issue]) -> list[Issue]:
    scored = [replace(issue, priority_score=_priority(issue)) for issue in issues]
    return sorted(scored, key=lambda item: item.priority_score, reverse=True)


def quality_status(score: float, critical_open_issues: int) -> str:
    if critical_open_issues > 0:
        return "needs_fix"
    if score >= 0.95:
        return "ready"
    if score >= 0.85:
        return "review_suggested"
    return "needs_fix"
```

- [ ] **Step 4: Run quality tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_quality
```

Expected: 2 tests pass.

---

### Task 6: Non-Destructive Versioning

**Files:**
- Create: `scripts/review_wizard/versioning.py`
- Test: `tests/test_review_wizard_versioning.py`

- [ ] **Step 1: Write failing versioning tests**

Create `tests/test_review_wizard_versioning.py`:

```python
import unittest

from scripts.review_wizard.contracts import AlignmentTake, Project
from scripts.review_wizard.versioning import add_edit_operation, create_aggressive_candidate, promote_take


class ReviewWizardVersioningTests(unittest.TestCase):
    def test_aggressive_correction_creates_candidate_take_without_replacing_parent(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        parent = AlignmentTake(id="take-1", kind="conservative", status="needs_review")
        project = project.with_alignment_take(parent)

        updated = create_aggressive_candidate(project, parent_take_id="take-1", selected_range=(12.0, 18.0))

        self.assertEqual([take.id for take in updated.alignment_takes], ["take-1", "take-1-aggressive-2"])
        self.assertEqual(updated.alignment_takes[1].kind, "aggressive_candidate")
        self.assertEqual(updated.alignment_takes[1].parent_take_id, "take-1")
        self.assertIsNone(updated.approved_take_id)

    def test_manual_edit_is_operation_not_destructive_rewrite(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = add_edit_operation(
            project,
            operation="move_syllable_boundary",
            target_id="syll-1",
            created_by="user",
            details={"from": 12.34, "to": 12.372, "snap_source": "vocal_onset"},
        )

        self.assertEqual(len(updated.edit_operations), 1)
        self.assertEqual(updated.edit_operations[0].target_id, "syll-1")
        self.assertEqual(updated.edit_operations[0].details["snap_source"], "vocal_onset")

    def test_promote_take_sets_approved_take_id(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = project.with_alignment_take(AlignmentTake(id="take-1", kind="conservative", status="ready"))

        updated = promote_take(project, "take-1")

        self.assertEqual(updated.approved_take_id, "take-1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing versioning tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_versioning
```

Expected: fail because `versioning.py` and `Project.with_alignment_take` do not exist.

- [ ] **Step 3: Add project append helpers**

Add to `Project` in `contracts.py`:

```python
    def with_alignment_take(self, take: AlignmentTake) -> "Project":
        from dataclasses import replace

        return replace(self, alignment_takes=[*self.alignment_takes, take])

    def with_edit_operation(self, operation: EditOperation) -> "Project":
        from dataclasses import replace

        return replace(self, edit_operations=[*self.edit_operations, operation])
```

- [ ] **Step 4: Implement versioning**

Create `scripts/review_wizard/versioning.py`:

```python
from __future__ import annotations

from dataclasses import replace
from time import time

from scripts.review_wizard.contracts import AlignmentTake, EditOperation, Project


def create_aggressive_candidate(
    project: Project,
    parent_take_id: str,
    selected_range: tuple[float, float],
) -> Project:
    if not any(take.id == parent_take_id for take in project.alignment_takes):
        raise ValueError(f"Unknown parent take: {parent_take_id}")
    candidate = AlignmentTake(
        id=f"{parent_take_id}-aggressive-{len(project.alignment_takes) + 1}",
        kind="aggressive_candidate",
        status="needs_review",
        parent_take_id=parent_take_id,
        line_ids=[],
    )
    op = EditOperation(
        id=f"op-aggressive-{len(project.edit_operations) + 1}",
        operation="create_aggressive_candidate",
        target_id=parent_take_id,
        created_by="system",
        created_at=time(),
        details={"start_s": selected_range[0], "end_s": selected_range[1], "candidate_take_id": candidate.id},
    )
    return replace(
        project,
        alignment_takes=[*project.alignment_takes, candidate],
        edit_operations=[*project.edit_operations, op],
    )


def add_edit_operation(
    project: Project,
    operation: str,
    target_id: str,
    created_by: str,
    details: dict,
) -> Project:
    edit = EditOperation(
        id=f"op-{len(project.edit_operations) + 1}",
        operation=operation,
        target_id=target_id,
        created_by=created_by,
        created_at=time(),
        details=details,
    )
    return project.with_edit_operation(edit)


def promote_take(project: Project, take_id: str) -> Project:
    if not any(take.id == take_id for take in project.alignment_takes):
        raise ValueError(f"Unknown take: {take_id}")
    return replace(project, approved_take_id=take_id)
```

- [ ] **Step 5: Run versioning tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_versioning
```

Expected: 3 tests pass.

---

### Task 7: Preview And Export Gate

**Files:**
- Create: `scripts/review_wizard/export_gate.py`
- Test: `tests/test_review_wizard_export_gate.py`

- [ ] **Step 1: Write failing export gate tests**

Create `tests/test_review_wizard_export_gate.py`:

```python
import unittest

from scripts.review_wizard.contracts import Issue, Project, QualityReport
from scripts.review_wizard.export_gate import approve_preview, can_export_final


class ReviewWizardExportGateTests(unittest.TestCase):
    def test_ready_project_can_export_without_preview_gate(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = project.with_quality_report(QualityReport(id="qr-1", take_id="take-1", status="ready", score=0.98))

        decision = can_export_final(project)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ready")

    def test_needs_fix_requires_preview_approval(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = project.with_quality_report(
            QualityReport(id="qr-1", take_id="take-1", status="needs_fix", score=0.70, issue_ids=["issue-1"])
        )
        project = project.with_issue(
            Issue(
                id="issue-1",
                type="melisma_unreviewed",
                severity="high",
                perceptual_impact=0.9,
                confidence=0.6,
                priority_score=0.9,
                start_s=10,
                end_s=14,
                affected_ids=["syll-1"],
                suggested_action="review_melisma_segments",
            )
        )

        before = can_export_final(project)
        after = can_export_final(approve_preview(project, approved_by="user", scope="critical_snippets"))

        self.assertFalse(before.allowed)
        self.assertEqual(before.reason, "preview_required")
        self.assertTrue(after.allowed)
        self.assertEqual(after.reason, "preview_approved_with_risk")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing export gate tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_export_gate
```

Expected: fail because `export_gate.py` and append helpers do not exist.

- [ ] **Step 3: Add project helpers for issues and reports**

Add to `Project` in `contracts.py`:

```python
    def with_issue(self, issue: Issue) -> "Project":
        from dataclasses import replace

        return replace(self, issues=[*self.issues, issue])

    def with_quality_report(self, report: QualityReport) -> "Project":
        from dataclasses import replace

        return replace(self, quality_reports=[*self.quality_reports, report])
```

- [ ] **Step 4: Implement export gate**

Create `scripts/review_wizard/export_gate.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, replace
from time import time

from scripts.review_wizard.contracts import Project


@dataclass(frozen=True)
class ExportDecision:
    allowed: bool
    reason: str


def _latest_report_status(project: Project) -> str:
    if not project.quality_reports:
        return "review_suggested"
    return project.quality_reports[-1].status


def approve_preview(project: Project, approved_by: str, scope: str) -> Project:
    render = {
        "id": f"preview-{len(project.preview_renders) + 1}",
        "scope": scope,
        "approved": True,
        "approved_by": approved_by,
        "approved_at": time(),
    }
    return replace(project, preview_renders=[*project.preview_renders, render])


def can_export_final(project: Project) -> ExportDecision:
    status = _latest_report_status(project)
    if status == "ready":
        return ExportDecision(True, "ready")
    approved_preview = any(render.get("approved") for render in project.preview_renders)
    if status == "needs_fix" and not approved_preview:
        return ExportDecision(False, "preview_required")
    if approved_preview:
        return ExportDecision(True, "preview_approved_with_risk")
    return ExportDecision(True, "review_suggested")
```

- [ ] **Step 5: Run export gate tests**

Run with `timeout_ms=30000`:

```powershell
python -m unittest tests.test_review_wizard_export_gate
```

Expected: 2 tests pass.

---

### Task 8: Flask Review Wizard Entry Point

**Files:**
- Modify: `server.py`
- Create: `templates/review_wizard.html`
- Modify: `templates/job.html`
- Test: `tests/test_review_wizard_server.py`

- [ ] **Step 1: Write failing server tests**

Create `tests/test_review_wizard_server.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from scripts.review_wizard.store import load_project


class ReviewWizardServerTests(unittest.TestCase):
    def test_job_detail_links_to_review_wizard(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "job_id": job_id,
                        "song_name": "Review Song",
                        "preset": "section-coded",
                        "created_at": 1,
                        "duration_s": 12.0,
                        "has_lyrics": True,
                        "source": "zip",
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "status.json").write_text(
                json.dumps({"stage": "done", "progress": 100, "error": "", "updated_at": 1}),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}")

        html = response.get_data(as_text=True)
        self.assertIn(f"/job/{job_id}/review", html)
        self.assertIn("REVIEW WIZARD", html)

    def test_review_wizard_route_bootstraps_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "job_id": job_id,
                        "song_name": "Review Song",
                        "preset": "section-coded",
                        "created_at": 1,
                        "duration_s": 12.0,
                        "has_lyrics": True,
                        "source": "zip",
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "lyrics.txt").write_text("[Verse]\nCoração aberto", encoding="utf-8")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review")

            project = load_project(job_dir)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(project.job_id, job_id)
        self.assertEqual(project.prepared_text.language, "pt")
        self.assertIn("Text Review", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing server tests**

Run with `timeout_ms=60000`:

```powershell
python -m unittest tests.test_review_wizard_server
```

Expected: fail because `/job/<job_id>/review` route and template do not exist.

- [ ] **Step 3: Add server bootstrap helper**

In `server.py`, import:

```python
from scripts.review_wizard.contracts import Project
from scripts.review_wizard.store import load_project, project_path, save_project
from scripts.review_wizard.text_prep import prepare_text_for_review
```

Add helper:

```python
def _ensure_review_project(job_dir: Path, job_id: str) -> Project:
    if project_path(job_dir).exists():
        return load_project(job_dir)
    raw_lyrics = (job_dir / "lyrics.txt").read_text(encoding="utf-8") if (job_dir / "lyrics.txt").exists() else ""
    prepared, issues = prepare_text_for_review(raw_lyrics, language="pt")
    project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
    project = dataclasses.replace(project, prepared_text=prepared, issues=issues)
    save_project(job_dir, project)
    return project
```

Also add `import dataclasses` at the top of `server.py`.

- [ ] **Step 4: Add review route**

In `server.py`:

```python
@app.route("/job/<job_id>/review")
def review_wizard(job_id):
    job_dir = resolve_job_dir(JOBS_DIR, job_id)
    if not job_dir or not job_dir.exists():
        abort(404)
    meta = _read_meta(job_dir)
    project = _ensure_review_project(job_dir, job_id)
    return render_template(
        "review_wizard.html",
        meta=meta,
        project=project.to_dict(),
    )
```

- [ ] **Step 5: Add template**

Create `templates/review_wizard.html`:

```html
{% extends "base.html" %}
{% block title %}Review Wizard{% endblock %}

{% block content %}
<div class="page-header">
  <div class="back-link"><a href="/job/{{ meta.job_id }}" class="mono dim">&lt;- BACK TO JOB</a></div>
  <h1 class="page-title">REVIEW WIZARD</h1>
  <p class="page-sub mono dim">// PROFESSIONAL SYNC REVIEW</p>
</div>

<section class="section">
  <h2 class="section-title">Text Review</h2>
  <p class="mono dim">Review the prepared lyric structure before alignment quality approval.</p>
  <div class="review-grid">
    {% for section in project.prepared_text.sections %}
      <div class="review-card">
        <h3 class="subsection-title">{{ section.label }}</h3>
        {% for line in section.lines %}
          <div class="review-line">
            <span class="mono dim">{{ line.id }}</span>
            <span>{{ line.text }}</span>
          </div>
        {% endfor %}
      </div>
    {% endfor %}
  </div>
</section>

<section class="section">
  <h2 class="section-title">Issues</h2>
  {% if project.issues %}
    {% for issue in project.issues %}
      <div class="issue-row">
        <span class="tag tag-red">{{ issue.severity | upper }}</span>
        <span class="mono">{{ issue.type }}</span>
        <span class="mono dim">{{ issue.suggested_action }}</span>
      </div>
    {% endfor %}
  {% else %}
    <p class="mono dim">No review issues generated yet.</p>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 6: Link from job detail**

In `templates/job.html`, add an action link near existing actions:

```html
<a class="btn btn-primary" href="/job/{{ meta.job_id }}/review">REVIEW WIZARD</a>
```

- [ ] **Step 7: Run server tests**

Run with `timeout_ms=60000`:

```powershell
python -m unittest tests.test_review_wizard_server
```

Expected: 2 tests pass.

---

### Task 9: Focused Issue Editor UI Skeleton

**Files:**
- Modify: `templates/review_wizard.html`
- Modify: `static/app.css`
- Modify: `static/app.js`
- Test: `tests/test_review_wizard_server.py`

- [ ] **Step 1: Add failing focused editor test**

Append to `tests/test_review_wizard_server.py`:

```python
    def test_review_wizard_renders_focused_issue_editor_before_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "job_id": job_id,
                        "song_name": "Review Song",
                        "preset": "section-coded",
                        "created_at": 1,
                        "duration_s": 12.0,
                        "has_lyrics": True,
                        "source": "zip",
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "lyrics.txt").write_text(" ".join(["palavra"] * 18), encoding="utf-8")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review")

        html = response.get_data(as_text=True)
        self.assertIn("focused-issue-editor", html)
        self.assertIn("OPEN TIMELINE", html)
        self.assertIn("APPROVE RISK", html)
```

- [ ] **Step 2: Run failing focused editor test**

Run with `timeout_ms=60000`:

```powershell
python -m unittest tests.test_review_wizard_server.ReviewWizardServerTests.test_review_wizard_renders_focused_issue_editor_before_timeline
```

Expected: fail because focused editor markup is absent.

- [ ] **Step 3: Add focused editor markup**

In `templates/review_wizard.html`, inside the issues section after the issue list:

```html
<div class="focused-issue-editor" data-focused-issue-editor>
  <h3 class="subsection-title">FOCUSED ISSUE EDITOR</h3>
  <p class="mono dim">Select an issue to review the local loop, evidence summary, and quick actions before opening the full timeline.</p>
  <div class="focused-actions">
    <button type="button" class="btn btn-secondary">PLAY LOOP</button>
    <button type="button" class="btn btn-secondary">APPLY SUGGESTION</button>
    <button type="button" class="btn btn-secondary">APPROVE RISK</button>
    <button type="button" class="btn btn-primary">OPEN TIMELINE</button>
  </div>
</div>
```

- [ ] **Step 4: Add minimal CSS**

Append to `static/app.css`:

```css
.review-grid {
  display: grid;
  gap: 1rem;
}

.review-card,
.focused-issue-editor {
  border: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.02);
  padding: 1rem;
}

.review-line,
.issue-row,
.focused-actions {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
}
```

- [ ] **Step 5: Run server tests**

Run with `timeout_ms=60000`:

```powershell
python -m unittest tests.test_review_wizard_server
```

Expected: all Review Wizard server tests pass.

---

### Task 10: Full Review Wizard Verification

**Files:**
- All files touched by Tasks 1-9.

- [ ] **Step 1: Run py compile**

Run with `timeout_ms=30000`:

```powershell
python -m py_compile server.py scripts\review_wizard\contracts.py scripts\review_wizard\store.py scripts\review_wizard\wizard.py scripts\review_wizard\text_prep.py scripts\review_wizard\quality.py scripts\review_wizard\versioning.py scripts\review_wizard\export_gate.py
```

Expected: exit code 0.

- [ ] **Step 2: Run focused Review Wizard suite**

Run with `timeout_ms=120000`:

```powershell
python -m unittest tests.test_review_wizard_contracts tests.test_review_wizard_state tests.test_review_wizard_text_prep tests.test_review_wizard_quality tests.test_review_wizard_versioning tests.test_review_wizard_export_gate tests.test_review_wizard_server
```

Expected: all Review Wizard tests pass.

- [ ] **Step 3: Run nearby regression tests**

Run with `timeout_ms=120000`:

```powershell
python -m unittest tests.test_server_contracts tests.test_common_contracts tests.test_validate_contracts tests.test_ass_generation
```

Expected: all nearby regression tests pass.

- [ ] **Step 4: Search for accidental Suno API regressions**

Run with `timeout_ms=30000`:

```powershell
rg -n -i "suno_api|api/suno|suno_link|suno_truth|taskId|audioId|timestamped|record-info|SUNO_API" server.py scripts tests templates static docs --glob "!docs/superpowers/plans/2026-05-25-review-wizard-implementation.md"
```

Expected: no matches.

---

## Spec Coverage Checklist

- Wizard center: Tasks 3, 8, 9.
- Text Review mandatory/reviewable: Tasks 4, 8.
- Complete contract, incremental implementation: Tasks 1, 2.
- Multi-evidence contract: Task 1 via `evidence_bundle`; extraction modules are assigned to a separate future plan.
- Issues by perceptual impact: Task 5.
- Focused issue editor before timeline: Task 9.
- Aggressive correction creates candidate take: Task 6.
- Non-destructive edit operations: Task 6.
- Preview/export risk gate: Task 7.
- MP4/ASS final export integration: represented by export gate now; ASS/MP4 rendering stays with existing pipeline until a separate export-hardening plan.
- Style preset hook: Task 1.
- Timeout verification: every task specifies timeout budgets.

## Separate Future Plans

These are intentionally not implemented in this first plan:

- Audio Evidence extraction module.
- True syllable-level CTC and phoneme refinement beyond current pipeline artifacts.
- Full melisma analyzer with pitch contour segmentation.
- Advanced timeline canvas/waveform UI.
- ASS melisma curve approximation improvements.
- Full preview render queue and temporary preview MP4 management.
- Benchmark/dataset tooling.
