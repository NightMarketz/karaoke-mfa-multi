# Stage-Navigable Review Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reform the Review Wizard into an interactive, stage-navigable review cockpit where users can inspect previous pipeline phases, review timestamped items, make decisions, and export with an auditable risk summary.

**Architecture:** Add a small domain layer that derives stage view models and timestamped review points from existing job artifacts, then expose that state through Flask routes and render it in one focused wizard page. Keep stage navigation, review point navigation, and review decisions isolated so later timeline/syllable/melisma work can plug in without rewriting the wizard.

**Tech Stack:** Python dataclasses/domain modules, Flask routes/templates, vanilla JS/CSS, unittest test suite, Browser plugin smoke checks.

---

## File Structure

- Create `scripts/review_wizard/stages.py`: canonical stage ids, labels, status derivation, and stage navigation helpers.
- Create `scripts/review_wizard/review_points.py`: `ReviewPoint` contract and builders from `analysis.json`, `aligned.json`, issues, and preview/export state.
- Modify `scripts/review_wizard/contracts.py`: add serializable `ReviewPoint` if a shared contract is preferable; otherwise keep it in `review_points.py` and store only review operations in `Project`.
- Modify `scripts/review_wizard/wizard.py`: connect existing wizard step approval to stage ids and add active stage/active point helpers.
- Modify `server.py`: add routes for stage selection, point selection, point approval, point risk skip, and point timing adjustment.
- Modify `templates/review_wizard.html`: replace dashboard-only layout with stage navigation, active stage panel, active review point panel, compact point queue, preview player, and export summary.
- Modify `static/app.js`: add review wizard client behavior for tab navigation, point selection, loop playback, timestamp seeking, and form enhancement.
- Modify `static/app.css`: add stable, non-flickering wizard layout styles.
- Add/modify tests:
  - `tests/test_review_wizard_stages.py`
  - `tests/test_review_points.py`
  - `tests/test_review_wizard_server.py`
  - `tests/test_review_wizard_contracts.py`
  - optional smoke script under `scripts/smoke/` if browser verification needs repeatability.

---

## Task 1: Stage Navigation Domain

**Files:**
- Create: `scripts/review_wizard/stages.py`
- Test: `tests/test_review_wizard_stages.py`

- [ ] **Step 1: Write failing tests for canonical stage order and previous-stage navigation**

```python
import unittest

from scripts.review_wizard.contracts import Project
from scripts.review_wizard.stages import (
    REVIEW_STAGES,
    active_stage_id,
    stage_view_models,
)
from scripts.review_wizard.wizard import approve_step


class ReviewWizardStagesTests(unittest.TestCase):
    def test_stage_order_matches_full_review_flow(self):
        self.assertEqual(
            [stage.id for stage in REVIEW_STAGES],
            ["import", "lyrics", "alignment", "quality", "preview", "export"],
        )

    def test_user_can_open_previous_or_later_stage_without_mutating_project(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = approve_step(project, "import", approved_by="user")

        self.assertEqual(active_stage_id(project, requested_stage="import"), "import")
        self.assertEqual(active_stage_id(project, requested_stage="lyrics"), "lyrics")
        self.assertEqual(project.wizard_steps["import"]["status"], "approved")

    def test_stage_view_models_include_status_and_counts(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = approve_step(project, "import", approved_by="user")

        stages = stage_view_models(project, active_stage="lyrics", review_points=[])

        self.assertEqual(stages[0]["id"], "import")
        self.assertEqual(stages[0]["status"], "approved")
        self.assertTrue(stages[1]["active"])
        self.assertEqual(stages[1]["review_point_count"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_review_wizard_stages`

Expected: fail with `ModuleNotFoundError: No module named 'scripts.review_wizard.stages'`.

- [ ] **Step 3: Implement stage domain**

Create `scripts/review_wizard/stages.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewStage:
    id: str
    label: str
    description: str


REVIEW_STAGES = [
    ReviewStage("import", "Import", "Audio assets, stems, lyrics source, and pipeline inputs."),
    ReviewStage("lyrics", "Lyrics", "Original and prepared lyric structure."),
    ReviewStage("alignment", "Alignment", "Line, word, syllable, and melisma timing."),
    ReviewStage("quality", "Quality", "Prioritized issues and focused timestamp checks."),
    ReviewStage("preview", "Preview", "Snippet and full-song preview approval."),
    ReviewStage("export", "Export", "ASS/MP4 readiness and remaining risk summary."),
]

_STAGE_IDS = {stage.id for stage in REVIEW_STAGES}
_STEP_TO_STAGE = {
    "import": "import",
    "text_review": "lyrics",
    "alignment_processing": "alignment",
    "quality_review": "quality",
    "preview_approval": "preview",
    "export": "export",
}
_STAGE_TO_STEP = {stage: step for step, stage in _STEP_TO_STAGE.items()}


def active_stage_id(project: Any, requested_stage: str | None = None) -> str:
    if requested_stage in _STAGE_IDS:
        return str(requested_stage)
    steps = getattr(project, "wizard_steps", {}) or {}
    for stage in REVIEW_STAGES:
        step_id = _STAGE_TO_STEP[stage.id]
        if steps.get(step_id, {}).get("status") not in {"approved", "skipped_with_risk"}:
            return stage.id
    return "export"


def stage_status(project: Any, stage_id: str) -> str:
    step_id = _STAGE_TO_STEP[stage_id]
    payload = (getattr(project, "wizard_steps", {}) or {}).get(step_id, {})
    return str(payload.get("status", "needs_review"))


def stage_view_models(project: Any, active_stage: str, review_points: list[Any]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    open_counts: dict[str, int] = {}
    for point in review_points:
        stage_id = getattr(point, "stage_id", None) if not isinstance(point, dict) else point.get("stage_id")
        status = getattr(point, "status", None) if not isinstance(point, dict) else point.get("status")
        if not stage_id:
            continue
        counts[stage_id] = counts.get(stage_id, 0) + 1
        if status == "open":
            open_counts[stage_id] = open_counts.get(stage_id, 0) + 1
    return [
        {
            "id": stage.id,
            "label": stage.label,
            "description": stage.description,
            "status": stage_status(project, stage.id),
            "active": stage.id == active_stage,
            "review_point_count": counts.get(stage.id, 0),
            "open_review_point_count": open_counts.get(stage.id, 0),
        }
        for stage in REVIEW_STAGES
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_review_wizard_stages`

Expected: `OK`.

---

## Task 2: Timestamped ReviewPoint Queue

**Files:**
- Create: `scripts/review_wizard/review_points.py`
- Test: `tests/test_review_points.py`

- [ ] **Step 1: Write failing tests for line and word review points**

```python
import json
import tempfile
import unittest
from pathlib import Path

from scripts.review_wizard.contracts import Issue, Project
from scripts.review_wizard.review_points import (
    ReviewPoint,
    build_review_points,
    next_open_point,
)


class ReviewPointsTests(unittest.TestCase):
    def test_analysis_lines_become_timestamped_alignment_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "Running on fumes",
                                "start": 40.46,
                                "end": 42.90,
                                "style": "verse",
                                "words": [
                                    {"word": "Running", "start": 40.66, "end": 41.46},
                                    {"word": "on", "start": 41.54, "end": 41.68},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            project = Project.new(project_id="proj-1", job_id="abc123def456")

            points = build_review_points(job_dir, project)

        self.assertEqual(points[0].id, "line-1")
        self.assertEqual(points[0].stage_id, "alignment")
        self.assertEqual(points[0].level, "line")
        self.assertEqual(points[0].text, "Running on fumes")
        self.assertEqual(points[0].start_s, 40.46)
        self.assertEqual(points[0].end_s, 42.90)
        self.assertEqual(points[0].duration_s, 2.44)
        self.assertEqual(points[1].level, "word")
        self.assertEqual(points[1].parent_id, "line-1")

    def test_issues_with_timestamps_decorate_matching_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                json.dumps({"lines": [{"text": "Late word", "start": 10.0, "end": 12.0, "words": []}]}),
                encoding="utf-8",
            )
            issue = Issue(
                id="issue-1",
                type="drift",
                severity="high",
                perceptual_impact=0.9,
                confidence=0.8,
                priority_score=0.72,
                start_s=10.1,
                end_s=11.0,
                affected_ids=["line-1"],
                suggested_action="review_alignment",
            )
            project = Project.new(project_id="proj-1", job_id="abc123def456").with_issue(issue)

            points = build_review_points(job_dir, project)

        self.assertEqual(points[0].issue_ids, ["issue-1"])
        self.assertEqual(points[0].severity, "high")

    def test_next_open_point_uses_stage_and_priority_order(self):
        points = [
            ReviewPoint(id="p1", stage_id="alignment", level="line", text="A", start_s=3, end_s=4, priority=0.1),
            ReviewPoint(id="p2", stage_id="alignment", level="line", text="B", start_s=1, end_s=2, priority=0.9),
            ReviewPoint(id="p3", stage_id="quality", level="issue", text="C", start_s=1, end_s=2, priority=1.0),
        ]

        self.assertEqual(next_open_point(points, "alignment").id, "p2")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_review_points`

Expected: fail because `scripts.review_wizard.review_points` does not exist.

- [ ] **Step 3: Implement ReviewPoint builder**

Create `scripts/review_wizard/review_points.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReviewPoint:
    id: str
    stage_id: str
    level: str
    text: str
    start_s: float
    end_s: float
    parent_id: str | None = None
    source: str = "analysis"
    status: str = "open"
    priority: float = 0.0
    issue_ids: list[str] = field(default_factory=list)
    severity: str = "info"
    affected_ids: list[str] = field(default_factory=list)
    suggested_action: str = ""

    @property
    def duration_s(self) -> float:
        return round(max(0.0, self.end_s - self.start_s), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage_id": self.stage_id,
            "level": self.level,
            "text": self.text,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "duration_s": self.duration_s,
            "parent_id": self.parent_id,
            "source": self.source,
            "status": self.status,
            "priority": self.priority,
            "issue_ids": list(self.issue_ids),
            "severity": self.severity,
            "affected_ids": list(self.affected_ids),
            "suggested_action": self.suggested_action,
        }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _issue_status(project: Any, point_id: str) -> str:
    for operation in getattr(project, "edit_operations", []):
        if getattr(operation, "target_id", "") == point_id:
            if getattr(operation, "operation", "") == "approve_review_point":
                return "approved"
            if getattr(operation, "operation", "") == "skip_review_point_with_risk":
                return "skipped_with_risk"
            if getattr(operation, "operation", "") == "adjust_review_point_timing":
                return "edited"
    return "open"


def _decorate_with_issues(points: list[ReviewPoint], project: Any) -> list[ReviewPoint]:
    decorated = []
    for point in points:
        matching = [
            issue for issue in getattr(project, "issues", [])
            if issue.status == "open"
            and (point.id in issue.affected_ids or (issue.start_s <= point.end_s and issue.end_s >= point.start_s))
        ]
        if not matching:
            decorated.append(point)
            continue
        matching.sort(key=lambda issue: issue.priority_score, reverse=True)
        top = matching[0]
        decorated.append(
            replace(
                point,
                priority=max(point.priority, top.priority_score),
                issue_ids=[issue.id for issue in matching],
                severity=top.severity,
                affected_ids=list(top.affected_ids),
                suggested_action=top.suggested_action,
            )
        )
    return decorated


def build_review_points(job_dir: Path, project: Any) -> list[ReviewPoint]:
    analysis = _load_json(job_dir / "analysis.json")
    points: list[ReviewPoint] = []
    for line_index, line in enumerate(analysis.get("lines", []), start=1):
        if "start" not in line or "end" not in line:
            continue
        line_id = f"line-{line_index}"
        points.append(
            ReviewPoint(
                id=line_id,
                stage_id="alignment",
                level="line",
                text=str(line.get("text", "")),
                start_s=float(line["start"]),
                end_s=float(line["end"]),
                priority=0.2,
                status=_issue_status(project, line_id),
            )
        )
        for word_index, word in enumerate(line.get("words", []), start=1):
            if "start" not in word or "end" not in word:
                continue
            word_id = f"{line_id}:word-{word_index}"
            points.append(
                ReviewPoint(
                    id=word_id,
                    stage_id="alignment",
                    level="word",
                    text=str(word.get("word", "")),
                    start_s=float(word["start"]),
                    end_s=float(word["end"]),
                    parent_id=line_id,
                    priority=0.1,
                    status=_issue_status(project, word_id),
                )
            )
    return _decorate_with_issues(points, project)


def points_for_stage(points: list[ReviewPoint], stage_id: str) -> list[ReviewPoint]:
    return [point for point in points if point.stage_id == stage_id]


def next_open_point(points: list[ReviewPoint], stage_id: str) -> ReviewPoint | None:
    candidates = [point for point in points if point.stage_id == stage_id and point.status == "open"]
    if not candidates:
        return None
    return sorted(candidates, key=lambda point: (-point.priority, point.start_s, point.id))[0]
```

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_review_points`

Expected: `OK`.

---

## Task 3: Review Point Decision Operations

**Files:**
- Modify: `scripts/review_wizard/wizard.py`
- Test: `tests/test_review_wizard_state.py`

- [ ] **Step 1: Add failing tests for approving/skipping/adjusting review points**

Append to `tests/test_review_wizard_state.py`:

```python
from scripts.review_wizard.wizard import (
    adjust_review_point_timing,
    approve_review_point,
    skip_review_point_with_risk,
)

    def test_approve_review_point_records_operation(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = approve_review_point(project, "line-1", approved_by="user")

        self.assertEqual(updated.edit_operations[-1].operation, "approve_review_point")
        self.assertEqual(updated.edit_operations[-1].target_id, "line-1")

    def test_skip_review_point_requires_reason_and_records_risk(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = skip_review_point_with_risk(project, "line-1", skipped_by="user", risk_note="Acceptable in preview.")

        self.assertEqual(updated.edit_operations[-1].operation, "skip_review_point_with_risk")
        self.assertEqual(updated.edit_operations[-1].details["risk_note"], "Acceptable in preview.")

    def test_adjust_review_point_timing_records_from_to_values(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = adjust_review_point_timing(
            project,
            "line-1",
            edited_by="user",
            start_s=40.5,
            end_s=42.7,
        )

        self.assertEqual(updated.edit_operations[-1].operation, "adjust_review_point_timing")
        self.assertEqual(updated.edit_operations[-1].details["start_s"], 40.5)
        self.assertEqual(updated.edit_operations[-1].details["end_s"], 42.7)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_review_wizard_state`

Expected: import failure for the new functions.

- [ ] **Step 3: Implement operation helpers**

Add to `scripts/review_wizard/wizard.py`:

```python
from scripts.review_wizard.contracts import EditOperation


def _append_operation(project: Any, operation: str, target_id: str, created_by: str, details: dict[str, Any]) -> Any:
    edit = EditOperation(
        id=f"op-{len(getattr(project, 'edit_operations', [])) + 1}",
        operation=operation,
        target_id=target_id,
        created_by=created_by,
        created_at=time(),
        details=details,
    )
    return replace(project, edit_operations=[*getattr(project, "edit_operations", []), edit])


def approve_review_point(project: Any, point_id: str, approved_by: str) -> Any:
    return _append_operation(project, "approve_review_point", point_id, approved_by, {})


def skip_review_point_with_risk(project: Any, point_id: str, skipped_by: str, risk_note: str) -> Any:
    if not risk_note.strip():
        raise ValueError("Risk note is required when skipping a review point")
    return _append_operation(
        project,
        "skip_review_point_with_risk",
        point_id,
        skipped_by,
        {"risk_note": risk_note.strip()},
    )


def adjust_review_point_timing(project: Any, point_id: str, edited_by: str, start_s: float, end_s: float) -> Any:
    if end_s <= start_s:
        raise ValueError("Review point end_s must be greater than start_s")
    return _append_operation(
        project,
        "adjust_review_point_timing",
        point_id,
        edited_by,
        {"start_s": float(start_s), "end_s": float(end_s)},
    )
```

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_review_wizard_state`

Expected: `OK`.

---

## Task 4: Flask Routes For Stage And Point Interaction

**Files:**
- Modify: `server.py`
- Test: `tests/test_review_wizard_server.py`

- [ ] **Step 1: Write failing server tests**

Add tests to `tests/test_review_wizard_server.py`:

```python
    def test_review_wizard_accepts_stage_and_point_query_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "Running on fumes")
            (job_dir / "analysis.json").write_text(
                json.dumps({"lines": [{"text": "Running on fumes", "start": 40.46, "end": 42.9, "words": []}]}),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=alignment&point=line-1")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-active-stage="alignment"', html)
        self.assertIn('data-active-point-id="line-1"', html)
        self.assertIn("40.46", html)
        self.assertIn("42.9", html)

    def test_review_point_approval_route_advances_to_next_open_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A\\nB")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {"text": "A", "start": 1.0, "end": 2.0, "words": []},
                            {"text": "B", "start": 3.0, "end": 4.0, "words": []},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                client.get(f"/job/{job_id}/review")
                response = client.post(f"/job/{job_id}/review/points/line-1/approve")

        self.assertEqual(response.status_code, 302)
        self.assertIn("point=line-2", response.headers["Location"])
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_review_wizard_server`

Expected: fail because route/template context does not include active stage/point and point route does not exist.

- [ ] **Step 3: Wire route context and point actions**

Modify imports in `server.py`:

```python
from scripts.review_wizard.review_points import build_review_points, next_open_point, points_for_stage
from scripts.review_wizard.stages import active_stage_id, stage_view_models
from scripts.review_wizard.wizard import (
    adjust_review_point_timing,
    approve_review_point,
    skip_review_point_with_risk,
)
```

Inside `review_wizard(job_id)`, after project load:

```python
    requested_stage = request.args.get("stage")
    requested_point_id = request.args.get("point")
    review_points = build_review_points(job_dir, project)
    active_stage = active_stage_id(project, requested_stage)
    stage_points = points_for_stage(review_points, active_stage)
    active_point = next((point for point in stage_points if point.id == requested_point_id), None)
    if active_point is None:
        active_point = next_open_point(review_points, active_stage)
        if active_point is None and stage_points:
            active_point = stage_points[0]
```

Pass these values to `render_template`:

```python
        stages=stage_view_models(project, active_stage, review_points),
        active_stage=active_stage,
        review_points=[point.to_dict() for point in stage_points],
        active_point=active_point.to_dict() if active_point else None,
```

Add routes:

```python
@app.post("/job/<job_id>/review/points/<point_id>/approve")
def review_wizard_approve_point(job_id: str, point_id: str):
    job_dir = resolve_job_dir(JOBS_DIR, job_id)
    project = approve_review_point(load_project(job_dir), point_id, approved_by="local-user")
    save_project(job_dir, project)
    points = build_review_points(job_dir, project)
    current = next((point for point in points if point.id == point_id), None)
    stage = current.stage_id if current else request.form.get("stage", "alignment")
    next_point = next_open_point(points, stage)
    args = {"stage": stage}
    if next_point:
        args["point"] = next_point.id
    return redirect(url_for("review_wizard", job_id=job_id, **args))


@app.post("/job/<job_id>/review/points/<point_id>/skip-risk")
def review_wizard_skip_point_risk(job_id: str, point_id: str):
    job_dir = resolve_job_dir(JOBS_DIR, job_id)
    reason = request.form.get("reason", "")
    project = skip_review_point_with_risk(load_project(job_dir), point_id, skipped_by="local-user", risk_note=reason)
    save_project(job_dir, project)
    points = build_review_points(job_dir, project)
    current = next((point for point in points if point.id == point_id), None)
    stage = current.stage_id if current else request.form.get("stage", "alignment")
    next_point = next_open_point(points, stage)
    args = {"stage": stage}
    if next_point:
        args["point"] = next_point.id
    return redirect(url_for("review_wizard", job_id=job_id, **args))


@app.post("/job/<job_id>/review/points/<point_id>/timing")
def review_wizard_adjust_point_timing(job_id: str, point_id: str):
    job_dir = resolve_job_dir(JOBS_DIR, job_id)
    project = adjust_review_point_timing(
        load_project(job_dir),
        point_id,
        edited_by="local-user",
        start_s=float(request.form["start_s"]),
        end_s=float(request.form["end_s"]),
    )
    save_project(job_dir, project)
    return redirect(url_for("review_wizard", job_id=job_id, stage=request.form.get("stage", "alignment"), point=point_id))
```

- [ ] **Step 4: Run server tests**

Run: `python -m unittest tests.test_review_wizard_server`

Expected: `OK`.

---

## Task 5: Stage-Based Wizard Template

**Files:**
- Modify: `templates/review_wizard.html`
- Modify: `static/app.css`
- Test: `tests/test_review_wizard_server.py`

- [ ] **Step 1: Add failing render contract tests**

Add assertions to the stage query test:

```python
        self.assertIn("review-stage-nav", html)
        self.assertIn("current-review-point", html)
        self.assertIn("review-point-queue", html)
        self.assertIn("PLAY LOOP", html)
        self.assertIn("APPROVE POINT", html)
        self.assertIn("SKIP WITH RISK", html)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_review_wizard_server.ReviewWizardServerTests.test_review_wizard_accepts_stage_and_point_query_params`

Expected: fail because template lacks these markers.

- [ ] **Step 3: Replace dashboard-first wizard structure**

Modify `templates/review_wizard.html` so the top of the content contains:

```html
<section class="review-shell" data-active-stage="{{ active_stage }}" data-active-point-id="{{ active_point.id if active_point else '' }}">
  <nav class="review-stage-nav" aria-label="Review stages">
    {% for stage in stages %}
      <a class="review-stage-link {{ 'is-active' if stage.active else '' }} status-{{ stage.status }}"
         href="/job/{{ meta.job_id }}/review?stage={{ stage.id }}">
        <span class="review-stage-label">{{ stage.label }}</span>
        <span class="review-stage-meta mono">{{ stage.status }} · {{ stage.open_review_point_count }}/{{ stage.review_point_count }}</span>
      </a>
    {% endfor %}
  </nav>

  <div class="review-workspace">
    <aside class="review-point-queue" aria-label="Review point queue">
      <h2 class="section-title">POINTS</h2>
      {% if review_points %}
        {% for point in review_points %}
          <a class="review-point-link {{ 'is-active' if active_point and active_point.id == point.id else '' }} status-{{ point.status }}"
             href="/job/{{ meta.job_id }}/review?stage={{ active_stage }}&point={{ point.id }}">
            <span class="mono">{{ point.level | upper }}</span>
            <strong>{{ point.text }}</strong>
            <span class="mono dim">{{ "%.2f"|format(point.start_s) }}s - {{ "%.2f"|format(point.end_s) }}s</span>
          </a>
        {% endfor %}
      {% else %}
        <p class="mono dim">No timestamped review points for this stage yet.</p>
      {% endif %}
    </aside>

    <section class="current-review-point" aria-label="Current review point">
      {% if active_point %}
        <div class="review-point-header">
          <span class="tag tag-warn">{{ active_point.level | upper }}</span>
          <span class="mono">{{ "%.2f"|format(active_point.start_s) }}s - {{ "%.2f"|format(active_point.end_s) }}s</span>
          <span class="mono dim">{{ "%.3f"|format(active_point.duration_s) }}s</span>
        </div>
        <h2>{{ active_point.text }}</h2>
        <p class="mono dim">Source: {{ active_point.source }} · Severity: {{ active_point.severity }} · {{ active_point.suggested_action }}</p>

        {% if has_full_preview %}
          <video class="karaoke-player review-point-player" controls preload="metadata" data-review-player src="/job/{{ meta.job_id }}/review/preview/full.mp4">
            Your browser does not support video playback.
          </video>
        {% endif %}

        <div class="review-point-actions">
          <button type="button" class="btn btn-ghost" data-play-loop data-start="{{ active_point.start_s }}" data-end="{{ active_point.end_s }}">PLAY LOOP</button>
          <form method="post" action="/job/{{ meta.job_id }}/review/points/{{ active_point.id }}/approve">
            <button type="submit" class="btn btn-primary">APPROVE POINT</button>
          </form>
          <form method="post" action="/job/{{ meta.job_id }}/review/points/{{ active_point.id }}/timing" class="timing-adjust-form">
            <input type="hidden" name="stage" value="{{ active_stage }}">
            <label class="mono">START <input class="form-input" name="start_s" value="{{ "%.3f"|format(active_point.start_s) }}"></label>
            <label class="mono">END <input class="form-input" name="end_s" value="{{ "%.3f"|format(active_point.end_s) }}"></label>
            <button type="submit" class="btn btn-ghost">SAVE TIMING</button>
          </form>
          <form method="post" action="/job/{{ meta.job_id }}/review/points/{{ active_point.id }}/skip-risk" class="risk-skip-form">
            <input type="hidden" name="stage" value="{{ active_stage }}">
            <input class="form-input" name="reason" placeholder="Risk reason">
            <button type="submit" class="btn btn-ghost">SKIP WITH RISK</button>
          </form>
        </div>
      {% else %}
        <h2>No Active Review Point</h2>
        <p class="mono dim">Select a stage or point to begin review.</p>
      {% endif %}
    </section>
  </div>
</section>
```

Keep existing quality/preview/export sections below only as compact supporting sections, or wrap them in stage panels so the main visible workflow is stage/point navigation.

- [ ] **Step 4: Add CSS for stable layout**

Add to `static/app.css`:

```css
.review-shell {
  display: grid;
  gap: 16px;
}

.review-stage-nav {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
}

.review-stage-link,
.review-point-link {
  display: grid;
  gap: 4px;
  border: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.035);
  color: var(--text);
  padding: 10px;
  text-decoration: none;
}

.review-stage-link.is-active,
.review-point-link.is-active {
  border-color: var(--accent);
  background: rgba(0, 245, 255, 0.08);
}

.review-workspace {
  display: grid;
  grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.review-point-queue {
  max-height: 70vh;
  overflow: auto;
}

.current-review-point {
  border: 1px solid var(--border);
  padding: 16px;
  background: rgba(0, 0, 0, 0.28);
}

.review-point-header,
.review-point-actions,
.timing-adjust-form,
.risk-skip-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.review-point-player {
  width: 100%;
  max-height: 360px;
  margin: 12px 0;
  background: #000;
}

@media (max-width: 900px) {
  .review-stage-nav,
  .review-workspace {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Run render tests**

Run: `python -m unittest tests.test_review_wizard_server`

Expected: `OK`.

---

## Task 6: Frontend Interactivity For Playback And Stage Flow

**Files:**
- Modify: `static/app.js`
- Test: `tests/test_review_wizard_server.py`
- Browser verify: local app at `/job/abc123def456/review?stage=alignment`

- [ ] **Step 1: Add render markers for JS hooks**

In the template test, assert:

```python
        self.assertIn("data-review-player", html)
        self.assertIn("data-play-loop", html)
```

- [ ] **Step 2: Add JS behavior**

Modify `DOMContentLoaded` in `static/app.js`:

```javascript
document.addEventListener('DOMContentLoaded', () => {
    initGlobalProgress();
    initJobDetail();
    initReviewWizard();
});
```

Add:

```javascript
function initReviewWizard() {
    const shell = document.querySelector('.review-shell');
    if (!shell) return;

    const player = document.querySelector('[data-review-player]');
    const loopButton = document.querySelector('[data-play-loop]');
    let loopTimer = null;

    if (player && loopButton) {
        loopButton.addEventListener('click', () => {
            const start = Number(loopButton.dataset.start || 0);
            const end = Number(loopButton.dataset.end || start + 2);
            if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
            if (loopTimer) window.clearInterval(loopTimer);
            player.currentTime = Math.max(0, start - 0.25);
            player.play();
            loopTimer = window.setInterval(() => {
                if (player.currentTime >= end + 0.25) {
                    player.pause();
                    window.clearInterval(loopTimer);
                    loopTimer = null;
                }
            }, 80);
        });
    }
}
```

- [ ] **Step 3: Run JS-free contract tests**

Run: `python -m unittest tests.test_review_wizard_server`

Expected: `OK`.

- [ ] **Step 4: Browser smoke verification**

Run the dev server if not already running:

`python server.py`

Open:

`http://127.0.0.1:5000/job/abc123def456/review?stage=alignment`

Check:
- stage nav visible;
- point queue visible;
- active point has timestamp;
- `PLAY LOOP` seeks player near the timestamp;
- no visual blinking.

---

## Task 7: Export Readiness Summary By Stage

**Files:**
- Create or modify: `scripts/review_wizard/export_summary.py`
- Modify: `server.py`
- Modify: `templates/review_wizard.html`
- Test: `tests/test_review_wizard_export_gate.py`

- [ ] **Step 1: Write failing export summary test**

```python
import unittest

from scripts.review_wizard.export_summary import review_export_summary
from scripts.review_wizard.review_points import ReviewPoint


class ReviewWizardExportSummaryTests(unittest.TestCase):
    def test_export_summary_counts_reviewed_pending_and_risky_points(self):
        points = [
            ReviewPoint(id="p1", stage_id="alignment", level="line", text="A", start_s=1, end_s=2, status="approved"),
            ReviewPoint(id="p2", stage_id="alignment", level="line", text="B", start_s=3, end_s=4, status="open"),
            ReviewPoint(id="p3", stage_id="quality", level="issue", text="C", start_s=5, end_s=6, status="skipped_with_risk"),
        ]

        summary = review_export_summary(points)

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["approved"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["risk_accepted"], 1)
        self.assertEqual(summary["by_stage"]["alignment"]["pending"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_review_wizard_export_gate`

Expected: import failure for `export_summary`.

- [ ] **Step 3: Implement summary helper**

Create `scripts/review_wizard/export_summary.py`:

```python
from __future__ import annotations

from typing import Any


def review_export_summary(points: list[Any]) -> dict[str, Any]:
    summary = {
        "total": len(points),
        "approved": 0,
        "pending": 0,
        "risk_accepted": 0,
        "edited": 0,
        "by_stage": {},
    }
    for point in points:
        stage = getattr(point, "stage_id", None) if not isinstance(point, dict) else point.get("stage_id")
        status = getattr(point, "status", None) if not isinstance(point, dict) else point.get("status")
        if stage not in summary["by_stage"]:
            summary["by_stage"][stage] = {"total": 0, "approved": 0, "pending": 0, "risk_accepted": 0, "edited": 0}
        summary["by_stage"][stage]["total"] += 1
        if status == "approved":
            summary["approved"] += 1
            summary["by_stage"][stage]["approved"] += 1
        elif status == "skipped_with_risk":
            summary["risk_accepted"] += 1
            summary["by_stage"][stage]["risk_accepted"] += 1
        elif status == "edited":
            summary["edited"] += 1
            summary["by_stage"][stage]["edited"] += 1
        else:
            summary["pending"] += 1
            summary["by_stage"][stage]["pending"] += 1
    return summary
```

- [ ] **Step 4: Render summary in export stage**

Pass `review_export_summary(review_points)` from `server.py` into template as `review_summary`.

Render compact cards:

```html
<section class="section export-review-summary">
  <h2 class="section-title">EXPORT REVIEW SUMMARY</h2>
  <div class="quality-summary">
    <div class="quality-metric"><span class="stat-label">REVIEWED</span><span class="stat-val">{{ review_summary.approved + review_summary.edited }}</span></div>
    <div class="quality-metric"><span class="stat-label">PENDING</span><span class="stat-val">{{ review_summary.pending }}</span></div>
    <div class="quality-metric"><span class="stat-label">RISK</span><span class="stat-val">{{ review_summary.risk_accepted }}</span></div>
  </div>
</section>
```

- [ ] **Step 5: Run tests**

Run: `python -m unittest tests.test_review_wizard_export_gate tests.test_review_wizard_server`

Expected: `OK`.

---

## Task 8: End-To-End Verification And Hardening

**Files:**
- Modify only files touched by previous tasks if failures reveal gaps.

- [ ] **Step 1: Run targeted Review Wizard tests**

Run:

`python -m unittest tests.test_review_wizard_contracts tests.test_review_wizard_state tests.test_review_wizard_artifacts tests.test_review_points tests.test_review_wizard_stages tests.test_review_wizard_server tests.test_review_wizard_export_gate`

Expected: all `OK`.

- [ ] **Step 2: Run syntax checks**

Run:

`python -m py_compile server.py scripts\\review_wizard\\stages.py scripts\\review_wizard\\review_points.py scripts\\review_wizard\\wizard.py scripts\\review_wizard\\export_summary.py`

Expected: exit code `0`.

- [ ] **Step 3: Run broader server contracts**

Run:

`python -m unittest tests.test_server_contracts tests.test_observability_contracts`

Expected: all `OK`.

- [ ] **Step 4: Browser smoke**

With server running, open:

`http://127.0.0.1:5000/job/abc123def456/review?stage=alignment`

Verify:
- stage nav shows Import, Lyrics, Alignment, Quality, Preview, Export;
- user can navigate back to Import and Lyrics;
- Alignment shows timestamped review point;
- point queue changes active point;
- approve point redirects to next point;
- Play Loop seeks the video;
- Export summary shows reviewed/pending/risk counts;
- no layout overlap or observability flicker.

---

## SDD Dispatch Strategy

Use one fresh implementer subagent per task:

1. Stage Navigation Domain: isolated backend/domain task.
2. Timestamped ReviewPoint Queue: isolated backend/domain task.
3. Review Point Decision Operations: backend state task.
4. Flask Routes: integration task.
5. Stage-Based Template: frontend/template task.
6. Frontend Interactivity: JS/browser task.
7. Export Readiness Summary: backend/template task.
8. Verification And Hardening: final integration/review task.

After each implementer:

1. Dispatch spec reviewer against this plan section.
2. Dispatch code quality reviewer for maintainability, regression risk, and tests.
3. Only then mark the task complete.

All test commands must set explicit command timeouts in the orchestrating tool.

---

## Self-Review

- Spec coverage: Covers navigable phases, previous phase audit, timestamped review points, interaction, decisions, preview loop, and export summary.
- Placeholder scan: No `TBD` or vague implementation placeholders remain; every task has concrete files, tests, commands, and implementation sketches.
- Type consistency: Stage ids are `import`, `lyrics`, `alignment`, `quality`, `preview`, `export`; wizard step ids remain compatible through mapping.
