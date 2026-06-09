# Compact Technical Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved compact technical cockpit as the new `/` screen, with `New Karaoke` as the default mode, a recent-project rail, selected-job diagnostics, and a quick Review triage mode that links into the existing Review Wizard.

**Architecture:** Add a focused cockpit view-model module that derives UI state from existing job metadata, status, artifacts, and Review Wizard contracts without changing pipeline or timing behavior. Wire `/` to render a new `templates/cockpit.html`, keep `POST /job/new` as the single job-creation endpoint, and keep deep review/export decisions in the existing Review Wizard.

**Tech Stack:** Python dataclasses/view-model helpers, Flask routes/templates, vanilla JS, existing `static/app.css`, unittest server/template tests, Browser/IAB visual verification.

---

## SDD Contract

Use these files as the source of truth before implementation:

- Spec: `docs/superpowers/specs/2026-06-06-compact-technical-cockpit-design.md`
- Visual reference: `docs/superpowers/assets/2026-06-06-compact-technical-cockpit.png`
- Active context contract: `.Codex/tasks/context-contract.md`

Implementation must not change:

- stage ids, artifact names, manifests, pipeline runner behavior;
- word timing, minimum duration, drift thresholds, melisma/sustain logic, CTC/HubertFA behavior, or ASS timing;
- Review Wizard deep approval behavior.

## File Structure

- Create `scripts/cockpit.py`: pure view-model helpers for stage rows, artifact rows, recent project cards, selected job summary, export readiness, and quick Review state.
- Create `tests/test_cockpit_view_model.py`: unit tests for `scripts/cockpit.py`.
- Create `tests/test_cockpit_server.py`: Flask route/template contract tests for `/`.
- Modify `server.py`: import cockpit helpers and pass cockpit context to `templates/cockpit.html`.
- Create `templates/cockpit.html`: new primary screen for the compact technical cockpit.
- Modify `templates/base.html`: add a body class hook for cockpit mode and point nav links to `/`.
- Modify `static/app.js`: add `initCockpit()` for file-drop labels, lyrics counter, and safe mode UI hooks.
- Modify `static/app.css`: add cockpit layout, timeline, diagnostics, project rail, quick-review, and responsive styles.

## Multi-Agent Ownership

Use fresh agents sequentially, not parallel implementers, because several tasks share `server.py`, `templates/`, and `static/`.

- Agent A: `scripts/cockpit.py` and `tests/test_cockpit_view_model.py`.
- Agent B: `server.py`, `tests/test_cockpit_server.py`, and route context.
- Agent C: `templates/cockpit.html` and minimal `templates/base.html` hooks.
- Agent D: `static/app.css` and `static/app.js`.
- Agent E: verification, visual polish, and regression triage only.

After each agent:

1. Run the task-specific tests.
2. Run a spec-compliance review against this plan and the design spec.
3. Run a code-quality review.
4. Commit only that task's files.

---

## Task 1: Cockpit View Model

**Agent:** A

**Files:**
- Create: `scripts/cockpit.py`
- Create: `tests/test_cockpit_view_model.py`

- [ ] **Step 1: Write failing tests for stage rows, artifact rows, recent cards, and quick review**

Create `tests/test_cockpit_view_model.py`:

```python
import tempfile
import unittest
from pathlib import Path

from scripts.cockpit import (
    artifact_rows,
    build_quick_review,
    cockpit_stage_rows,
    recent_project_cards,
    selected_job_summary,
)
from scripts.review_wizard.contracts import Issue, Project
from scripts.review_wizard.review_points import ReviewPoint


class CockpitViewModelTests(unittest.TestCase):
    def test_stage_rows_mark_current_stage_running_and_previous_done(self):
        rows = cockpit_stage_rows({"stage": "aligning", "progress": 47, "error": ""})

        self.assertEqual([row["id"] for row in rows], ["s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08"])
        self.assertEqual(rows[0]["state"], "done")
        self.assertEqual(rows[1]["state"], "done")
        self.assertEqual(rows[2]["state"], "done")
        self.assertEqual(rows[3]["state"], "running")
        self.assertEqual(rows[3]["label"], "Align")
        self.assertEqual(rows[4]["state"], "pending")

    def test_stage_rows_mark_all_done_when_pipeline_done(self):
        rows = cockpit_stage_rows({"stage": "done", "progress": 100, "error": ""})

        self.assertTrue(all(row["state"] == "done" for row in rows))

    def test_artifact_rows_report_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "vocals.wav").write_bytes(b"vocals")
            (job_dir / "lyrics.txt").write_text("[Verse]\nOi", encoding="utf-8")

            rows = artifact_rows(job_dir)

        by_name = {row["name"]: row for row in rows}
        self.assertTrue(by_name["vocals.wav"]["exists"])
        self.assertFalse(by_name["instrumental.wav"]["exists"])
        self.assertTrue(by_name["lyrics.txt"]["exists"])
        self.assertEqual(by_name["vocals.wav"]["state"], "ok")
        self.assertEqual(by_name["instrumental.wav"]["state"], "missing")

    def test_recent_project_cards_keep_resume_links_and_status(self):
        jobs = [
            {
                "job_id": "abc123def456",
                "song_name": "Nova Cancao",
                "duration_s": 272.0,
                "preset": "single-style-kf",
                "status": {"stage": "rendering", "progress": 82, "error": ""},
            }
        ]

        cards = recent_project_cards(jobs)

        self.assertEqual(cards[0]["job_id"], "abc123def456")
        self.assertEqual(cards[0]["title"], "Nova Cancao")
        self.assertEqual(cards[0]["duration_label"], "04:32")
        self.assertEqual(cards[0]["href"], "/?job=abc123def456")
        self.assertEqual(cards[0]["detail_href"], "/job/abc123def456")
        self.assertEqual(cards[0]["stage_label"], "RENDERING")

    def test_selected_job_summary_derives_title_status_and_duration(self):
        job = {
            "job_id": "abc123def456",
            "song_name": "Nova Cancao",
            "duration_s": 272.118,
            "preset": "single-style-kf",
            "status": {"stage": "done", "progress": 100, "error": ""},
        }

        summary = selected_job_summary(job)

        self.assertEqual(summary["job_id"], "abc123def456")
        self.assertEqual(summary["title"], "Nova Cancao")
        self.assertEqual(summary["duration_label"], "04:32.118")
        self.assertEqual(summary["pipeline_label"], "DONE")

    def test_quick_review_uses_highest_priority_open_point_and_wizard_link(self):
        project = Project.new(project_id="review-abc123def456", job_id="abc123def456")
        issue = Issue(
            id="issue-1",
            type="melisma_unreviewed",
            severity="critical",
            perceptual_impact=0.9,
            confidence=0.7,
            priority_score=0.91,
            start_s=10.0,
            end_s=12.0,
            affected_ids=["line-1"],
            suggested_action="review_melisma_segments",
        )
        project = project.__class__(**{**project.to_dict(), "issues": [issue]})
        points = [
            ReviewPoint(id="line-1", stage_id="alignment", level="line", text="A", start_s=1.0, end_s=2.0),
            ReviewPoint(
                id="issue:issue-1",
                stage_id="quality",
                level="issue",
                text="melisma: review",
                start_s=10.0,
                end_s=12.0,
                priority=0.91,
                issue_ids=["issue-1"],
                severity="critical",
                suggested_action="review_melisma_segments",
            ),
        ]

        quick = build_quick_review("abc123def456", project, points)

        self.assertEqual(quick["active_point"]["id"], "issue:issue-1")
        self.assertEqual(quick["open_count"], 2)
        self.assertEqual(quick["wizard_href"], "/job/abc123def456/review?stage=quality&point=issue%3Aissue-1")
        self.assertEqual(quick["approve_action"], "/job/abc123def456/review/points/issue%3Aissue-1/approve")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

`python -m unittest tests.test_cockpit_view_model`

Expected: failure with `ModuleNotFoundError: No module named 'scripts.cockpit'`.

- [ ] **Step 3: Implement the cockpit view-model module**

Create `scripts/cockpit.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from scripts.review_wizard.export_gate import can_export_final


STAGE_DEFINITIONS = [
    {"id": "s01", "label": "Input", "keys": {"queued", "preparing"}},
    {"id": "s02", "label": "Demix", "keys": {"demixing", "demix"}},
    {"id": "s03", "label": "Lyrics Align", "keys": {"aligning_lyrics", "transcribing"}},
    {"id": "s04", "label": "Align", "keys": {"aligning"}},
    {"id": "s05", "label": "Analyze", "keys": {"analyzing"}},
    {"id": "s06", "label": "ASS", "keys": {"generating"}},
    {"id": "s07", "label": "Render", "keys": {"rendering"}},
    {"id": "s08", "label": "Validate", "keys": {"validating", "done"}},
]

EXPECTED_ARTIFACTS = [
    "vocals.wav",
    "instrumental.wav",
    "lyrics.txt",
    "transcript.json",
    "aligned.json",
    "analysis.json",
    "output.ass",
    "output.mp4",
]

REVIEWED_STATUSES = {"approved", "edited", "skipped_with_risk", "suggestion_applied"}


def _status_stage(status: dict[str, Any] | None) -> str:
    return str((status or {}).get("stage", "queued") or "queued")


def _stage_index(stage: str) -> int:
    if stage == "failed":
        return -1
    for index, definition in enumerate(STAGE_DEFINITIONS):
        if stage in definition["keys"]:
            return index
    return 0


def cockpit_stage_rows(status: dict[str, Any] | None) -> list[dict[str, Any]]:
    stage = _status_stage(status)
    error = str((status or {}).get("error", "") or "")
    progress = int((status or {}).get("progress", 0) or 0)

    if stage == "done":
        active_index = len(STAGE_DEFINITIONS) - 1
    else:
        active_index = _stage_index(stage)

    rows: list[dict[str, Any]] = []
    for index, definition in enumerate(STAGE_DEFINITIONS):
        if stage == "done":
            state = "done"
        elif stage == "failed" and index == 0:
            state = "failed"
        elif index < active_index:
            state = "done"
        elif index == active_index:
            state = "failed" if stage == "failed" else "running"
        else:
            state = "pending"
        rows.append(
            {
                "id": definition["id"],
                "label": definition["label"],
                "state": state,
                "progress": progress if index == active_index else (100 if state == "done" else 0),
                "error": error if state == "failed" else "",
            }
        )
    return rows


def artifact_rows(job_dir: Path | None) -> list[dict[str, Any]]:
    rows = []
    for name in EXPECTED_ARTIFACTS:
        exists = bool(job_dir and (job_dir / name).exists())
        rows.append({"name": name, "exists": exists, "state": "ok" if exists else "missing"})
    return rows


def _duration_label(duration_s: Any, *, precise: bool = False) -> str:
    try:
        duration = float(duration_s)
    except (TypeError, ValueError):
        return "--:--"
    minutes = int(duration // 60)
    seconds = duration - (minutes * 60)
    if precise:
        return f"{minutes:02d}:{seconds:06.3f}"
    return f"{minutes:02d}:{int(seconds):02d}"


def _stage_label(status: dict[str, Any] | None) -> str:
    stage = _status_stage(status)
    if stage == "done":
        return "DONE"
    if stage == "failed":
        return "FAILED"
    return stage.replace("_", " ").upper()


def recent_project_cards(jobs: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    cards = []
    for job in jobs[:limit]:
        job_id = str(job.get("job_id", ""))
        status = job.get("status", {}) or {}
        cards.append(
            {
                "job_id": job_id,
                "title": str(job.get("song_name") or "Untitled"),
                "preset": str(job.get("preset") or ""),
                "duration_label": _duration_label(job.get("duration_s")),
                "stage_label": _stage_label(status),
                "progress": int(status.get("progress", 0) or 0),
                "state": _status_stage(status),
                "href": f"/?job={quote(job_id)}",
                "review_href": f"/?job={quote(job_id)}&mode=review",
                "detail_href": f"/job/{quote(job_id)}",
            }
        )
    return cards


def selected_job_summary(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    status = job.get("status", {}) or {}
    return {
        "job_id": str(job.get("job_id", "")),
        "title": str(job.get("song_name") or "Unsaved Project"),
        "preset": str(job.get("preset") or ""),
        "duration_label": _duration_label(job.get("duration_s"), precise=True),
        "pipeline_label": _stage_label(status),
        "progress": int(status.get("progress", 0) or 0),
        "error": str(status.get("error", "") or ""),
    }


def _point_dict(point: Any) -> dict[str, Any]:
    if hasattr(point, "to_dict"):
        return point.to_dict()
    return dict(point)


def build_quick_review(job_id: str, project: Any | None, review_points: list[Any]) -> dict[str, Any]:
    open_points = [
        point for point in review_points
        if str(getattr(point, "status", "open")) not in REVIEWED_STATUSES
    ]
    open_points.sort(key=lambda point: (-float(getattr(point, "priority", 0.0)), float(getattr(point, "start_s", 0.0)), str(getattr(point, "id", ""))))
    active = open_points[0] if open_points else None
    active_payload = _point_dict(active) if active else None
    if active:
        point_id = quote(str(getattr(active, "id", "")), safe="")
        stage = quote(str(getattr(active, "stage_id", "alignment")), safe="")
        wizard_href = f"/job/{quote(job_id)}/review?stage={stage}&point={point_id}"
        approve_action = f"/job/{quote(job_id)}/review/points/{point_id}/approve"
        apply_action = f"/job/{quote(job_id)}/review/points/{point_id}/apply-suggestion"
        risk_action = f"/job/{quote(job_id)}/review/points/{point_id}/skip-risk"
    else:
        wizard_href = f"/job/{quote(job_id)}/review"
        approve_action = ""
        apply_action = ""
        risk_action = ""

    export_decision = can_export_final(project) if project is not None else None
    return {
        "active_point": active_payload,
        "queue": [_point_dict(point) for point in open_points[:8]],
        "open_count": len(open_points),
        "wizard_href": wizard_href,
        "approve_action": approve_action,
        "apply_action": apply_action,
        "risk_action": risk_action,
        "export_allowed": bool(export_decision.allowed) if export_decision else False,
        "export_reason": export_decision.reason if export_decision else "no_project_selected",
    }
```

- [ ] **Step 4: Run view-model tests**

Run:

`python -m unittest tests.test_cockpit_view_model`

Expected: `OK`.

- [ ] **Step 5: Commit Agent A changes**

Run:

`git add scripts/cockpit.py tests/test_cockpit_view_model.py`

Then:

`git commit -m "Add cockpit view model"`

Expected: commit succeeds and only Agent A files are staged.

---

## Task 2: Flask Route And Server Contracts

**Agent:** B

**Files:**
- Modify: `server.py`
- Create: `tests/test_cockpit_server.py`

- [ ] **Step 1: Write failing Flask route tests**

Create `tests/test_cockpit_server.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from scripts.review_wizard.contracts import Issue, Project, QualityReport
from scripts.review_wizard.store import save_project
from scripts.review_wizard.text_prep import prepare_text_for_review


def _write_job(job_dir: Path, job_id: str, *, stage: str = "done", progress: int = 100) -> None:
    job_dir.mkdir()
    (job_dir / "meta.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "song_name": "Nova Cancao",
                "preset": "single-style-kf",
                "created_at": 1,
                "duration_s": 272.118,
                "has_lyrics": True,
                "source": "zip",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "status.json").write_text(
        json.dumps({"stage": stage, "progress": progress, "error": "", "updated_at": 1}),
        encoding="utf-8",
    )
    (job_dir / "lyrics.txt").write_text("[Verse]\nA gente cresce", encoding="utf-8")


class CockpitServerTests(unittest.TestCase):
    def test_index_renders_new_karaoke_cockpit_without_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(server, "JOBS_DIR", Path(tmp)):
                response = server.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("cockpit-shell", html)
        self.assertIn("New Karaoke", html)
        self.assertIn("Start Processing", html)
        self.assertIn("recent-projects-rail", html)
        self.assertIn('action="/job/new"', html)

    def test_index_renders_recent_project_rail_and_selected_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            _write_job(jobs_dir / job_id, job_id, stage="aligning", progress=47)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/?job={job_id}")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Nova Cancao", html)
        self.assertIn("s04", html)
        self.assertIn("Align", html)
        self.assertIn("Running", html)
        self.assertIn("/?job=abc123def456&amp;mode=review", html)

    def test_review_mode_renders_quick_review_actions_and_wizard_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            (job_dir / "analysis.json").write_text(
                json.dumps({"lines": [{"text": "A gente cresce", "start": 10.0, "end": 12.0, "words": []}]}),
                encoding="utf-8",
            )
            prepared_text, _ = prepare_text_for_review("[Verse]\nA gente cresce", language="pt")
            issue = Issue(
                id="issue-1",
                type="drift",
                severity="high",
                perceptual_impact=0.8,
                confidence=0.7,
                priority_score=0.88,
                start_s=10.0,
                end_s=12.0,
                affected_ids=["line-1"],
                suggested_action="review_alignment",
            )
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(**{**project.to_dict(), "prepared_text": prepared_text, "issues": [issue]})
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/?job={job_id}&mode=review")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Issue Triage", html)
        self.assertIn("A gente cresce", html)
        self.assertIn("Approve", html)
        self.assertIn("Apply Suggestion", html)
        self.assertIn("Skip With Risk", html)
        self.assertIn(f"/job/{job_id}/review?stage=alignment", html)

    def test_review_mode_does_not_show_export_ready_when_gate_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            prepared_text, _ = prepare_text_for_review("[Verse]\nA gente cresce", language="pt")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.72)],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/?job={job_id}&mode=review")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Export Ready", html)
        self.assertIn("Not Ready", html)
        self.assertNotIn(">Ready</span>", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

`python -m unittest tests.test_cockpit_server`

Expected: failures because `cockpit.html` and cockpit route context are not wired.

- [ ] **Step 3: Wire `/` to cockpit context**

Modify imports in `server.py`:

```python
from scripts.cockpit import (
    artifact_rows,
    build_quick_review,
    cockpit_stage_rows,
    recent_project_cards,
    selected_job_summary,
)
```

Add this helper near `_list_jobs()`:

```python
def _find_listed_job(jobs: list[dict[str, Any]], job_id: str | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    for job in jobs:
        if job.get("job_id") == job_id:
            return job
    return None
```

Replace the `index()` route body with:

```python
@app.route("/")
def index():
    jobs = _list_jobs()
    selected_job_id = request.args.get("job")
    selected_job = _find_listed_job(jobs, selected_job_id)
    selected_job_dir: Path | None = None
    project = None
    review_points = []
    mode = request.args.get("mode", "new")
    if mode not in {"new", "review"}:
        mode = "new"

    if selected_job:
        try:
            selected_job_dir = resolve_job_dir(JOBS_DIR, selected_job["job_id"])
        except ValueError:
            selected_job_dir = None

    if mode == "review" and selected_job and selected_job_dir and selected_job_dir.exists():
        project = _ensure_review_project(selected_job_dir, selected_job["job_id"])
        review_points = build_review_points(selected_job_dir, project)

    quick_review = (
        build_quick_review(selected_job["job_id"], project, review_points)
        if selected_job and mode == "review"
        else None
    )

    return render_template(
        "cockpit.html",
        mode=mode,
        jobs=jobs,
        recent_projects=recent_project_cards(jobs),
        selected_job=selected_job_summary(selected_job),
        stage_rows=cockpit_stage_rows((selected_job or {}).get("status", {})),
        artifact_rows=artifact_rows(selected_job_dir),
        quick_review=quick_review,
        style_presets=_style_preset_options(),
        default_preset_id=DEFAULT_STYLE_PRESET_ID,
    )
```

- [ ] **Step 4: Run tests and confirm template failure only**

Run:

`python -m unittest tests.test_cockpit_server`

Expected: failure with `jinja2.exceptions.TemplateNotFound: cockpit.html`.

- [ ] **Step 5: Commit Agent B route/test changes after Task 3 template exists**

Do not commit yet if tests fail only because `cockpit.html` is not created. Commit this task after Task 3 passes the route tests.

---

## Task 3: Cockpit Template

**Agent:** C

**Files:**
- Create: `templates/cockpit.html`
- Modify: `templates/base.html`
- Test: `tests/test_cockpit_server.py`

- [ ] **Step 1: Add a cockpit body hook in base template**

Modify `templates/base.html` body tag:

```html
<body class="{% block body_class %}{% endblock %}">
```

Change the nav links:

```html
<nav class="site-nav">
  <a href="/" class="nav-link {% if request.path == '/' %}active{% endif %}">COCKPIT</a>
  <a href="/job/new" class="nav-link nav-cta">+ NEW JOB</a>
</nav>
```

- [ ] **Step 2: Create the cockpit template**

Create `templates/cockpit.html`:

```html
{% extends "base.html" %}
{% block title %}Cockpit - Karaoke MFA Multi{% endblock %}
{% block body_class %}cockpit-page{% endblock %}

{% block content %}
<section class="cockpit-shell" data-cockpit-mode="{{ mode }}">
  <aside class="cockpit-sidebar" aria-label="Main navigation">
    <a class="cockpit-brand" href="/">
      <span class="cockpit-brand-wave">≋</span>
      <span>Karaoke MFA Multi</span>
    </a>
    <nav class="cockpit-nav">
      <a class="cockpit-nav-item {{ 'is-active' if mode == 'new' else '' }}" href="/">
        <span aria-hidden="true">＋</span><span>New</span>
      </a>
      <a class="cockpit-nav-item" href="#recent-projects">
        <span aria-hidden="true">▣</span><span>Projects</span>
      </a>
      {% if selected_job %}
      <a class="cockpit-nav-item {{ 'is-active' if mode == 'review' else '' }}" href="/?job={{ selected_job.job_id }}&mode=review">
        <span aria-hidden="true">◇</span><span>Review</span>
      </a>
      {% else %}
      <span class="cockpit-nav-item is-disabled"><span aria-hidden="true">◇</span><span>Review</span></span>
      {% endif %}
      <span class="cockpit-nav-item is-disabled"><span aria-hidden="true">⇩</span><span>Exports</span></span>
      <span class="cockpit-nav-item is-disabled"><span aria-hidden="true">⚙</span><span>Settings</span></span>
    </nav>
    <div class="cockpit-sidebar-status mono">
      <span>Localhost</span>
      <strong>All Services OK</strong>
    </div>
  </aside>

  <div class="cockpit-main">
    <header class="cockpit-command-strip">
      <div>
        <h1>{{ selected_job.title if selected_job else "New Karaoke" }}</h1>
        <span class="mono dim">{{ "Selected Project" if selected_job else "Unsaved Project" }}</span>
      </div>
      <div class="cockpit-status-chips">
        <span class="cockpit-chip"><small>Language</small><strong>pt-BR</strong></span>
        <span class="cockpit-chip"><small>Preset</small><strong>{{ selected_job.preset if selected_job else "Karaoke Pro" }}</strong></span>
        <span class="cockpit-chip"><small>Pipeline</small><strong>{{ selected_job.pipeline_label if selected_job else "s01 - s08" }}</strong></span>
        <span class="cockpit-chip"><small>Duration</small><strong>{{ selected_job.duration_label if selected_job else "--:--" }}</strong></span>
        <span class="cockpit-chip"><small>Export Ready</small><strong class="{{ 'accent' if quick_review and quick_review.export_allowed else 'warn' }}">{{ "Ready" if quick_review and quick_review.export_allowed else "Not Ready" }}</strong></span>
      </div>
    </header>

    <div class="cockpit-grid">
      <section class="cockpit-task-panel" aria-label="Primary task panel">
        <div class="cockpit-mode-tabs" aria-label="Workspace mode">
          <a class="{{ 'is-active' if mode == 'new' else '' }}" href="{{ '/?job=' ~ selected_job.job_id if selected_job else '/' }}">New Karaoke</a>
          {% if selected_job %}
          <a class="{{ 'is-active' if mode == 'review' else '' }}" href="/?job={{ selected_job.job_id }}&mode=review">Review</a>
          {% else %}
          <span class="is-disabled">Review</span>
          {% endif %}
        </div>

        {% if mode == "review" %}
          <div class="quick-review-panel">
            <h2>Issue Triage</h2>
            {% if quick_review and quick_review.active_point %}
              {% set point = quick_review.active_point %}
              <div class="quick-review-current">
                <span class="tag tag-warn">{{ point.severity | upper }}</span>
                <strong>{{ point.text }}</strong>
                <span class="mono dim">{{ "%.3f"|format(point.start_s) }}s - {{ "%.3f"|format(point.end_s) }}s</span>
                {% if point.evidence_summary %}
                <p class="mono dim">{{ point.evidence_summary }}</p>
                {% endif %}
              </div>
              <div class="quick-review-mini-wave" aria-hidden="true">
                {% for i in range(24) %}
                <span style="height: {{ 18 + ((i * 17) % 62) }}%;"></span>
                {% endfor %}
              </div>
              <div class="quick-review-actions">
                <form method="post" action="{{ quick_review.approve_action }}">
                  <input type="hidden" name="stage" value="{{ point.stage_id }}">
                  <button type="submit" class="btn btn-primary">Approve</button>
                </form>
                <form method="post" action="{{ quick_review.apply_action }}">
                  <input type="hidden" name="stage" value="{{ point.stage_id }}">
                  <button type="submit" class="btn btn-ghost">Apply Suggestion</button>
                </form>
                <form method="post" action="{{ quick_review.risk_action }}" class="quick-risk-form">
                  <input class="form-input" name="reason" placeholder="Risk reason" required>
                  <button type="submit" class="btn btn-ghost">Skip With Risk</button>
                </form>
                <a class="btn btn-ghost" href="{{ quick_review.wizard_href }}">Open Review Wizard</a>
              </div>
            {% elif selected_job %}
              <p class="mono dim">No open review points for this project.</p>
              <a class="btn btn-primary" href="/job/{{ selected_job.job_id }}/review">Open Review Wizard</a>
            {% else %}
              <p class="mono dim">Select a recent project to triage review issues.</p>
            {% endif %}
          </div>
        {% else %}
          <form action="/job/new" method="POST" enctype="multipart/form-data" class="cockpit-new-form" id="cockpitUploadForm">
            <label class="form-section">
              <span class="form-label">Song Title</span>
              <input type="text" name="song_name" class="form-input" placeholder="Nova Cancao" required>
            </label>
            <div class="form-section">
              <span class="form-label">Audio / Stems</span>
              <label class="cockpit-drop" data-file-drop>
                <input type="file" name="suno_zip" accept=".zip">
                <span>Drag and drop audio or stems</span>
                <small class="mono dim">ZIP with vocals + instrumental, or use the legacy upload screen</small>
              </label>
              <a class="mono dim cockpit-legacy-link" href="/job/new">Open full upload form</a>
            </div>
            <label class="form-section">
              <span class="form-label">Lyrics</span>
              <textarea class="form-input cockpit-lyrics" name="lyrics_text" rows="8" required spellcheck="false" placeholder="[Verse]&#10;Faz tanto tempo que eu nao te vejo"></textarea>
              <span class="mono dim" data-lyrics-counter></span>
            </label>
            <label class="form-section">
              <span class="form-label">Preset / Style</span>
              <select class="form-input" name="preset">
                {% for style_preset in style_presets %}
                <option value="{{ style_preset.id }}" {% if style_preset.id == default_preset_id %}selected{% endif %}>{{ style_preset.label }}</option>
                {% endfor %}
              </select>
            </label>
            <button type="submit" class="btn btn-primary cockpit-start">Start Processing</button>
          </form>
        {% endif %}
      </section>

      <section class="cockpit-timeline" aria-label="Audio timeline">
        <div class="cockpit-timeline-toolbar mono">
          <span>Waveform</span>
          <span>Snap 100 ms</span>
          <span>Markers</span>
        </div>
        <div class="cockpit-wave-lanes" aria-hidden="true">
          {% for lane in ["Mix", "Vocals", "Instrumental"] %}
          <div class="cockpit-wave-row">
            <span class="cockpit-lane-label">{{ lane }}</span>
            <div class="cockpit-waveform">
              {% for i in range(64) %}
              <span style="height: {{ 20 + ((i * (loop.index + 9)) % 72) }}%;"></span>
              {% endfor %}
            </div>
          </div>
          {% endfor %}
          <div class="cockpit-lyric-lane">
            <span>Lyrics</span>
            <b>Faz tanto tempo</b><b>que eu nao te vejo</b><b>a gente cresce</b>
          </div>
          <div class="cockpit-issue-lane">
            <span>Issues</span>
            <b>GAP</b><b>DRIFT</b><b>MELISMA</b>
          </div>
          <div class="cockpit-confidence-lane"></div>
        </div>
      </section>

      <aside class="cockpit-diagnostics" aria-label="Diagnostics">
        <section>
          <h2>Pipeline</h2>
          {% for row in stage_rows %}
          <div class="cockpit-stage-row state-{{ row.state }}">
            <span>{{ row.id }}</span><strong>{{ row.label }}</strong><em>{{ row.state | capitalize }}</em>
          </div>
          {% endfor %}
        </section>
        <section>
          <h2>Artifacts</h2>
          {% for artifact in artifact_rows %}
          <div class="cockpit-artifact-row state-{{ artifact.state }}">
            <span>{{ artifact.name }}</span><strong>{{ "OK" if artifact.exists else "Missing" }}</strong>
          </div>
          {% endfor %}
        </section>
      </aside>
    </div>

    <section class="recent-projects-rail" id="recent-projects" aria-label="Recent projects">
      <div class="rail-header">
        <h2>Recent Projects</h2>
        <a href="/job/new">New full form</a>
      </div>
      <div class="project-rail-list">
        {% for project in recent_projects %}
        <article class="project-rail-card state-{{ project.state }}">
          <a href="{{ project.href }}">
            <strong>{{ project.title }}</strong>
            <span class="mono dim">{{ project.duration_label }} · {{ project.stage_label }}</span>
          </a>
          <div class="project-rail-actions">
            <a href="{{ project.href }}">Resume</a>
            <a href="{{ project.review_href }}">Review</a>
          </div>
        </article>
        {% else %}
        <div class="project-rail-empty mono dim">No recent projects yet.</div>
        {% endfor %}
      </div>
    </section>

    <footer class="cockpit-player" aria-label="Transport controls">
      <div class="cockpit-now-playing">
        <strong>{{ selected_job.title if selected_job else "New Karaoke" }}</strong>
        <span class="mono dim">{{ quick_review.open_count if quick_review else 0 }} issues</span>
      </div>
      <div class="cockpit-transport">
        <button type="button" aria-label="Previous">◀</button>
        <button type="button" aria-label="Play">▶</button>
        <button type="button" aria-label="Next">▶</button>
      </div>
      <div class="cockpit-scrubber" aria-hidden="true"><span></span></div>
      <div class="cockpit-player-actions mono">
        <span>Vocal On</span>
        <span>Instrumental On</span>
        <span>{{ "Export Ready" if quick_review and quick_review.export_allowed else "Export Not Ready" }}</span>
      </div>
    </footer>
  </div>
</section>
{% endblock %}
```

- [ ] **Step 3: Run server tests**

Run:

`python -m unittest tests.test_cockpit_server`

Expected: `OK`.

- [ ] **Step 4: Commit Agent B and C changes together if Task 2 was waiting on template**

Run:

`git add server.py templates/base.html templates/cockpit.html tests/test_cockpit_server.py`

Then:

`git commit -m "Add compact cockpit route and template"`

Expected: commit succeeds and does not stage unrelated working-tree changes.

---

## Task 4: Cockpit CSS And Responsive Layout

**Agent:** D

**Files:**
- Modify: `static/app.css`
- Test: `tests/test_cockpit_server.py`

- [ ] **Step 1: Add render contract assertions for important CSS hooks**

Append to `test_index_renders_new_karaoke_cockpit_without_jobs` in `tests/test_cockpit_server.py`:

```python
        self.assertIn("cockpit-sidebar", html)
        self.assertIn("cockpit-timeline", html)
        self.assertIn("cockpit-diagnostics", html)
        self.assertIn("cockpit-player", html)
```

- [ ] **Step 2: Run tests**

Run:

`python -m unittest tests.test_cockpit_server`

Expected: `OK`, because the template already exposes hooks.

- [ ] **Step 3: Add cockpit CSS**

Append this section to `static/app.css`:

```css
/* Compact Technical Cockpit */
.cockpit-page {
  background: #08090c;
}

.cockpit-page .grid-bg,
.cockpit-page .site-header,
.cockpit-page .site-footer {
  display: none;
}

.cockpit-page .site-main {
  max-width: none;
  padding: 0;
}

.cockpit-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  background: #08090c;
  color: #f5f7fb;
  overflow: hidden;
}

.cockpit-sidebar {
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 20px;
  padding: 18px 14px;
  border-right: 1px solid #242833;
  background: #0b0d12;
}

.cockpit-brand,
.cockpit-nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 42px;
  color: #d7dce7;
  text-decoration: none;
}

.cockpit-brand {
  font-weight: 800;
  color: #fff;
}

.cockpit-brand-wave {
  color: #3ee7ff;
}

.cockpit-nav {
  display: grid;
  align-content: start;
  gap: 8px;
}

.cockpit-nav-item {
  padding: 9px 12px;
  border-radius: 7px;
  color: #8d94a3;
}

.cockpit-nav-item.is-active {
  color: #3ee7ff;
  background: rgba(62, 231, 255, 0.08);
  box-shadow: inset 3px 0 0 #3ee7ff;
}

.cockpit-nav-item.is-disabled {
  opacity: 0.42;
}

.cockpit-sidebar-status {
  display: grid;
  gap: 5px;
  color: #7d8493;
  font-size: 0.72rem;
}

.cockpit-sidebar-status strong {
  color: #44d17a;
  font-weight: 600;
}

.cockpit-main {
  min-width: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  height: 100vh;
}

.cockpit-command-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  min-width: 0;
  padding: 14px 18px;
  border-bottom: 1px solid #242833;
  background: #0d1016;
}

.cockpit-command-strip h1 {
  font-size: 1.05rem;
  line-height: 1.1;
  color: #fff;
}

.cockpit-status-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.cockpit-chip {
  min-width: 118px;
  display: grid;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid #242833;
  border-radius: 7px;
  background: #11141b;
}

.cockpit-chip small {
  color: #8d94a3;
  font-size: 0.66rem;
}

.cockpit-chip strong {
  color: #fff;
  font-size: 0.82rem;
}

.cockpit-grid {
  min-height: 0;
  display: grid;
  grid-template-columns: 350px minmax(420px, 1fr) 330px;
  gap: 6px;
  padding: 6px;
}

.cockpit-task-panel,
.cockpit-timeline,
.cockpit-diagnostics {
  min-width: 0;
  border: 1px solid #242833;
  background: #10131a;
  border-radius: 7px;
}

.cockpit-task-panel {
  padding: 12px;
  overflow: auto;
}

.cockpit-mode-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 12px;
  border-bottom: 1px solid #242833;
}

.cockpit-mode-tabs a,
.cockpit-mode-tabs span {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #8d94a3;
  text-decoration: none;
  font-weight: 700;
  font-size: 0.82rem;
}

.cockpit-mode-tabs .is-active {
  color: #3ee7ff;
  border-bottom: 2px solid #3ee7ff;
}

.cockpit-new-form,
.quick-review-panel {
  display: grid;
  gap: 12px;
}

.cockpit-drop {
  min-height: 96px;
  display: grid;
  place-items: center;
  gap: 5px;
  padding: 16px;
  border: 1px dashed #313744;
  border-radius: 7px;
  background: #0c0f15;
  text-align: center;
  cursor: pointer;
}

.cockpit-drop input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.cockpit-lyrics {
  resize: vertical;
  min-height: 140px;
}

.cockpit-start {
  width: 100%;
  min-height: 42px;
  background: #7057ff;
}

.cockpit-legacy-link {
  font-size: 0.72rem;
}

.quick-review-panel h2,
.cockpit-diagnostics h2,
.rail-header h2 {
  color: #fff;
  font-size: 0.78rem;
  text-transform: uppercase;
}

.quick-review-current {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #242833;
  border-radius: 7px;
  background: #0c0f15;
}

.quick-review-mini-wave {
  height: 72px;
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 8px;
  border: 1px solid #242833;
  border-radius: 7px;
  background: #0b0d12;
}

.quick-review-mini-wave span {
  flex: 1;
  background: linear-gradient(180deg, #3ee7ff, #7057ff);
  opacity: 0.76;
}

.quick-review-actions,
.quick-risk-form {
  display: grid;
  gap: 8px;
}

.cockpit-timeline {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
}

.cockpit-timeline-toolbar {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  padding: 10px;
  color: #8d94a3;
  border-bottom: 1px solid #242833;
}

.cockpit-wave-lanes {
  position: relative;
  display: grid;
  gap: 10px;
  padding: 14px;
  overflow: hidden;
}

.cockpit-wave-lanes::after {
  content: "";
  position: absolute;
  top: 44px;
  bottom: 78px;
  left: 43%;
  border-left: 1px solid #3ee7ff;
  box-shadow: 0 0 10px rgba(62, 231, 255, 0.4);
}

.cockpit-wave-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
}

.cockpit-lane-label {
  color: #d7dce7;
  font-size: 0.78rem;
}

.cockpit-waveform {
  height: 70px;
  display: flex;
  align-items: center;
  gap: 2px;
  overflow: hidden;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.cockpit-waveform span {
  flex: 1;
  background: linear-gradient(180deg, #8b5cf6, #5c4be8);
  opacity: 0.78;
}

.cockpit-lyric-lane,
.cockpit-issue-lane {
  display: grid;
  grid-template-columns: 96px repeat(3, minmax(0, 1fr));
  gap: 10px;
  align-items: center;
}

.cockpit-lyric-lane b,
.cockpit-issue-lane b {
  min-height: 34px;
  display: flex;
  align-items: center;
  padding: 0 10px;
  border-radius: 5px;
  font-size: 0.72rem;
}

.cockpit-lyric-lane b {
  background: rgba(112, 87, 255, 0.55);
}

.cockpit-issue-lane b {
  color: #ffb454;
  border: 1px solid rgba(255, 180, 84, 0.5);
  background: rgba(255, 180, 84, 0.12);
}

.cockpit-confidence-lane {
  height: 44px;
  margin-left: 106px;
  background: linear-gradient(90deg, rgba(62, 231, 255, 0.2), rgba(62, 231, 255, 0.65), rgba(112, 87, 255, 0.22));
  border-radius: 4px;
}

.cockpit-diagnostics {
  display: grid;
  align-content: start;
  gap: 6px;
  padding: 10px;
  overflow: auto;
}

.cockpit-diagnostics section {
  display: grid;
  gap: 5px;
  padding-bottom: 10px;
  border-bottom: 1px solid #242833;
}

.cockpit-stage-row,
.cockpit-artifact-row {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  min-height: 30px;
  color: #8d94a3;
  font-size: 0.76rem;
}

.cockpit-artifact-row {
  grid-template-columns: minmax(0, 1fr) auto;
}

.cockpit-stage-row.state-running {
  color: #3ee7ff;
}

.cockpit-stage-row.state-done,
.cockpit-artifact-row.state-ok {
  color: #44d17a;
}

.cockpit-stage-row.state-failed {
  color: #ff4d6d;
}

.recent-projects-rail {
  min-width: 0;
  padding: 8px 10px;
  border-top: 1px solid #242833;
  background: #0d1016;
}

.rail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.rail-header a {
  color: #3ee7ff;
  font-size: 0.76rem;
}

.project-rail-list {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(210px, 260px);
  gap: 10px;
  overflow-x: auto;
}

.project-rail-card {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #242833;
  border-radius: 7px;
  background: #121620;
}

.project-rail-card a {
  color: #f5f7fb;
  text-decoration: none;
}

.project-rail-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.project-rail-actions a {
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #2a2f3a;
  border-radius: 5px;
  font-size: 0.72rem;
}

.project-rail-empty {
  padding: 16px;
  border: 1px dashed #242833;
  border-radius: 7px;
}

.cockpit-player {
  min-height: 84px;
  display: grid;
  grid-template-columns: 230px 140px minmax(180px, 1fr) auto;
  gap: 18px;
  align-items: center;
  padding: 10px 14px;
  border-top: 1px solid #242833;
  background: #11131a;
}

.cockpit-now-playing {
  display: grid;
  gap: 4px;
}

.cockpit-transport {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.cockpit-transport button {
  width: 34px;
  height: 34px;
  border: 1px solid #2a2f3a;
  border-radius: 50%;
  background: #181d27;
  color: #fff;
}

.cockpit-scrubber {
  height: 6px;
  border-radius: 999px;
  background: #2a2f3a;
  overflow: hidden;
}

.cockpit-scrubber span {
  display: block;
  width: 43%;
  height: 100%;
  background: linear-gradient(90deg, #ffb454, #7057ff);
}

.cockpit-player-actions {
  display: flex;
  gap: 14px;
  color: #8d94a3;
  font-size: 0.72rem;
}

@media (max-width: 1120px) {
  .cockpit-shell {
    grid-template-columns: 78px minmax(0, 1fr);
  }

  .cockpit-brand span:last-child,
  .cockpit-nav-item span:last-child,
  .cockpit-sidebar-status {
    display: none;
  }

  .cockpit-grid {
    grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  }

  .cockpit-diagnostics {
    grid-column: 1 / -1;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .cockpit-shell {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .cockpit-sidebar {
    display: none;
  }

  .cockpit-main {
    height: auto;
  }

  .cockpit-command-strip,
  .cockpit-player {
    grid-template-columns: 1fr;
  }

  .cockpit-grid {
    grid-template-columns: 1fr;
  }

  .cockpit-diagnostics {
    grid-template-columns: 1fr;
  }

  .project-rail-list {
    grid-auto-columns: minmax(180px, 86vw);
  }
}
```

- [ ] **Step 4: Run route tests after CSS**

Run:

`python -m unittest tests.test_cockpit_server`

Expected: `OK`.

- [ ] **Step 5: Commit Agent D CSS changes**

Run:

`git add static/app.css tests/test_cockpit_server.py`

Then:

`git commit -m "Style compact technical cockpit"`

Expected: commit succeeds and only CSS plus test updates are staged.

---

## Task 5: Cockpit JavaScript

**Agent:** D

**Files:**
- Modify: `static/app.js`
- Test: `tests/test_cockpit_server.py`

- [ ] **Step 1: Add a script contract test**

Append to `tests/test_cockpit_server.py`:

```python
    def test_cockpit_template_exposes_js_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(server, "JOBS_DIR", Path(tmp)):
                response = server.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertIn("data-file-drop", html)
        self.assertIn("data-lyrics-counter", html)
        self.assertIn("data-cockpit-mode", html)
```

- [ ] **Step 2: Run test**

Run:

`python -m unittest tests.test_cockpit_server.CockpitServerTests.test_cockpit_template_exposes_js_hooks`

Expected: `OK`, because hooks are already in the template.

- [ ] **Step 3: Add `initCockpit()`**

Modify the `DOMContentLoaded` block in `static/app.js`:

```javascript
document.addEventListener('DOMContentLoaded', () => {
    initGlobalProgress();
    initJobDetail();
    initReviewWizard();
    initCockpit();
});
```

Add this function before `renderDriftChart`:

```javascript
function initCockpit() {
    const shell = document.querySelector('.cockpit-shell');
    if (!shell) return;

    shell.querySelectorAll('[data-file-drop]').forEach(drop => {
        const input = drop.querySelector('input[type="file"]');
        if (!input) return;
        const mainLabel = drop.querySelector('span');
        const subLabel = drop.querySelector('small');
        input.addEventListener('change', () => {
            const file = input.files && input.files[0];
            if (!file) return;
            const size = file.size > 1048576
                ? `${(file.size / 1048576).toFixed(1)} MB`
                : `${Math.max(1, Math.round(file.size / 1024))} KB`;
            drop.classList.add('has-file');
            if (mainLabel) mainLabel.textContent = file.name;
            if (subLabel) subLabel.textContent = size;
        });
        ['dragenter', 'dragover'].forEach(type => {
            drop.addEventListener(type, event => {
                event.preventDefault();
                drop.classList.add('is-hovering');
            });
        });
        ['dragleave', 'drop'].forEach(type => {
            drop.addEventListener(type, () => {
                drop.classList.remove('is-hovering');
            });
        });
    });

    const lyrics = shell.querySelector('textarea[name="lyrics_text"]');
    const counter = shell.querySelector('[data-lyrics-counter]');
    if (lyrics && counter) {
        const update = () => {
            const lines = lyrics.value.split('\n').filter(line => {
                const value = line.trim();
                return value && !value.startsWith('[') && !value.startsWith('//');
            });
            counter.textContent = lines.length ? `${lines.length} singable lines detected` : '';
        };
        lyrics.addEventListener('input', update);
        update();
    }
}
```

- [ ] **Step 4: Add CSS states for JS hooks**

Append to the cockpit CSS section in `static/app.css`:

```css
.cockpit-drop.has-file {
  border-style: solid;
  border-color: rgba(68, 209, 122, 0.7);
  background: rgba(68, 209, 122, 0.08);
}

.cockpit-drop.is-hovering {
  border-color: #3ee7ff;
  background: rgba(62, 231, 255, 0.08);
}
```

- [ ] **Step 5: Run server tests**

Run:

`python -m unittest tests.test_cockpit_server`

Expected: `OK`.

- [ ] **Step 6: Commit Agent D JS changes**

Run:

`git add static/app.js static/app.css tests/test_cockpit_server.py`

Then:

`git commit -m "Add cockpit client interactions"`

Expected: commit succeeds.

---

## Task 6: Regression And Visual Verification

**Agent:** E

**Files:**
- Modify only files from Tasks 1-5 if verification finds issues.

- [ ] **Step 1: Run focused unit and server tests**

Run:

`python -m unittest tests.test_cockpit_view_model tests.test_cockpit_server`

Expected: `OK`.

- [ ] **Step 2: Run Review Wizard regression tests affected by quick-review links**

Run:

`python -m unittest tests.test_review_wizard_server tests.test_review_wizard_state tests.test_review_points`

Expected: `OK`.

- [ ] **Step 3: Run existing server contracts**

Run:

`python -m unittest tests.test_server_contracts`

Expected: `OK`.

- [ ] **Step 4: Run syntax checks**

Run:

`python -m py_compile server.py scripts\\cockpit.py static\\app.js`

Expected: exit code `0`.

- [ ] **Step 5: Start local server**

Run:

`python server.py`

Expected: server starts on `http://127.0.0.1:5000` or `http://localhost:5000`.

- [ ] **Step 6: Browser desktop verification**

Open:

`http://127.0.0.1:5000/`

Verify:

- left app rail is visible;
- `New Karaoke` panel is active by default;
- central waveform/timeline is visible;
- right diagnostics panel is visible;
- recent project rail is visible below;
- fixed player bar is visible;
- no text overlaps at desktop width;
- the rendered style follows `docs/superpowers/assets/2026-06-06-compact-technical-cockpit.png`.

- [ ] **Step 7: Browser selected-job and Review mode verification**

Open a valid recent job:

`http://127.0.0.1:5000/?job=<valid_job_id>&mode=review`

Verify:

- `Issue Triage` appears in the task panel;
- action buttons render only when an active point exists;
- `Open Review Wizard` lands at the corresponding `/job/<job_id>/review?stage=...&point=...`;
- export readiness is `Not Ready` when Review Wizard gate blocks export.

- [ ] **Step 8: Browser mobile verification**

Resize to a mobile-width viewport, then verify:

- app rail collapses away;
- command strip wraps without overlap;
- timeline and diagnostics stack vertically;
- project rail scrolls horizontally;
- player bar does not hide form controls.

- [ ] **Step 9: Final commit if verification required fixes**

If Agent E changed files:

`git add <changed files>`

Then:

`git commit -m "Harden compact cockpit verification"`

Expected: only verification-fix files are committed.

---

## SDD Multi-Agent Dispatch Prompts

Use these summaries when dispatching agents. Give each agent the relevant task section in full, the design spec path, the visual reference path, and `.Codex/tasks/context-contract.md`.

### Agent A Prompt

Implement Task 1 only. Create `scripts/cockpit.py` and `tests/test_cockpit_view_model.py`. Do not edit Flask routes, templates, CSS, JS, pipeline code, Review Wizard internals, timing logic, or artifact contracts. Run `python -m unittest tests.test_cockpit_view_model`, self-review, and commit only your files.

### Agent B Prompt

Implement Task 2 only. Wire `/` to the cockpit context in `server.py` and create `tests/test_cockpit_server.py`. Do not create styling or client JS. Do not change `POST /job/new`, pipeline runner, Review Wizard route behavior, timing logic, or artifact contracts. If tests fail only because `templates/cockpit.html` is missing, report `DONE_WITH_CONCERNS` and wait for Agent C.

### Agent C Prompt

Implement Task 3 only. Create `templates/cockpit.html` and add the minimal `body_class` hook in `templates/base.html`. Do not edit CSS beyond existing class references, do not edit server route logic, and do not change Review Wizard templates. Run `python -m unittest tests.test_cockpit_server`, self-review, and coordinate commit with Agent B route changes if needed.

### Agent D Prompt

Implement Tasks 4 and 5 sequentially. Add cockpit styling and client interactions. Do not change backend contracts or Review Wizard behavior. Run `python -m unittest tests.test_cockpit_server` after each task and commit CSS and JS changes separately.

### Agent E Prompt

Implement Task 6 only. Run verification commands, browser checks, and visual comparison against the approved mockup. Fix only issues discovered during verification. Do not add new features. Report exact commands run and any remaining mismatch.

---

## Self-Review

- Spec coverage: The plan covers default `New Karaoke`, project rail, timeline, diagnostics, player bar, Quick Review triage, Review Wizard links, export readiness, visual direction, and responsive verification.
- Scope guard: The plan explicitly forbids timing, stage contract, artifact, manifest, and Review Wizard deep-flow changes.
- Placeholder scan: No placeholder red flags or vague test instructions remain.
- Type consistency: The plan uses `job_id`, `status.stage`, `status.progress`, `ReviewPoint.to_dict()`, `can_export_final(project)`, and existing Review Wizard point action routes consistently.
- Multi-agent safety: No two implementation agents are instructed to edit the same file concurrently; shared-file tasks are sequential and review-gated.
