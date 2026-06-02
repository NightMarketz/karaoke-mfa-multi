# Review Timeline Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first usable fine-correction timeline for line/word/syllable timing review, with loop playback hooks and non-destructive edit operations.

**Architecture:** Keep timeline edits as Review Wizard domain operations that create alternate takes and append `EditOperation` records. The initial UI is server-rendered and simple: issue-focused rows, timing inputs, and apply buttons. A richer waveform/canvas editor can replace the controls later without changing the domain contract.

**Tech Stack:** Python dataclasses, Flask/Jinja, standard-library `unittest`, existing `review_wizard.json`, static CSS/JS.

---

## File Structure

- Create: `scripts/review_wizard/timeline_edits.py`
- Modify: `scripts/review_wizard/contracts.py` only if a missing field is required
- Modify: `server.py`
- Modify: `templates/review_wizard.html`
- Modify: `static/app.css`
- Test: `tests/test_review_wizard_timeline_edits.py`
- Test: `tests/test_review_wizard_server.py`

## Verification Rules

Use explicit timeouts:

```powershell
python -m unittest tests.test_review_wizard_timeline_edits tests.test_review_wizard_server
python -m unittest tests.test_review_wizard_contracts tests.test_review_wizard_state tests.test_review_wizard_text_prep tests.test_review_wizard_quality tests.test_review_wizard_artifacts tests.test_review_wizard_issue_resolution tests.test_review_wizard_versioning tests.test_review_wizard_export_gate tests.test_review_wizard_timeline_edits tests.test_review_wizard_server
python -m py_compile server.py scripts\review_wizard\timeline_edits.py
```

---

### Task 1: Timing Edit Domain

**Files:**
- Create: `scripts/review_wizard/timeline_edits.py`
- Test: `tests/test_review_wizard_timeline_edits.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_review_wizard_timeline_edits.py`:

```python
import unittest

from scripts.review_wizard.contracts import Project
from scripts.review_wizard.timeline_edits import apply_timing_edit


class TimelineEditTests(unittest.TestCase):
    def test_apply_timing_edit_records_non_destructive_operation(self):
        project = Project.new(project_id="review-1", job_id="abc123def456")

        updated = apply_timing_edit(
            project,
            target_id="syll-1",
            start_s=10.125,
            end_s=10.610,
            edited_by="local-user",
            reason="Snap syllable to vocal onset",
        )

        self.assertEqual(len(updated.edit_operations), 1)
        op = updated.edit_operations[0]
        self.assertEqual(op.operation, "adjust_timing")
        self.assertEqual(op.target_id, "syll-1")
        self.assertEqual(op.created_by, "local-user")
        self.assertEqual(op.details["start_s"], 10.125)
        self.assertEqual(op.details["end_s"], 10.610)
        self.assertEqual(op.details["reason"], "Snap syllable to vocal onset")

    def test_rejects_inverted_timing_edit(self):
        project = Project.new(project_id="review-1", job_id="abc123def456")

        with self.assertRaises(ValueError) as error:
            apply_timing_edit(
                project,
                target_id="syll-1",
                start_s=10.7,
                end_s=10.6,
                edited_by="local-user",
                reason="bad",
            )

        self.assertEqual(str(error.exception), "timing edit end_s must be greater than start_s")
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_timeline_edits
```

Expected: fail with missing module.

- [ ] **Step 3: Implement minimal domain operation**

Create `scripts/review_wizard/timeline_edits.py`:

```python
from __future__ import annotations

from dataclasses import replace
from time import time

from scripts.review_wizard.contracts import EditOperation, Project


def apply_timing_edit(
    project: Project,
    target_id: str,
    start_s: float,
    end_s: float,
    edited_by: str,
    reason: str,
) -> Project:
    if end_s <= start_s:
        raise ValueError("timing edit end_s must be greater than start_s")
    operation = EditOperation(
        id=f"edit-{len(project.edit_operations) + 1}",
        operation="adjust_timing",
        target_id=target_id,
        created_by=edited_by,
        created_at=time(),
        details={
            "start_s": start_s,
            "end_s": end_s,
            "reason": reason,
        },
    )
    return replace(project, edit_operations=[*project.edit_operations, operation])
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_timeline_edits
```

Expected: pass.

---

### Task 2: Issue-Focused Timing Route

**Files:**
- Modify: `server.py`
- Test: `tests/test_review_wizard_server.py`

- [ ] **Step 1: Add failing route test**

Append to `ReviewWizardServerTests`:

```python
    def test_timing_edit_route_persists_edit_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/timeline/edit",
                    data={
                        "target_id": "syll-1",
                        "start_s": "10.125",
                        "end_s": "10.610",
                        "reason": "Snap syllable to vocal onset",
                    },
                )

            project = load_project(job_dir)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(project.edit_operations[-1].operation, "adjust_timing")
        self.assertEqual(project.edit_operations[-1].target_id, "syll-1")
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_server.ReviewWizardServerTests.test_timing_edit_route_persists_edit_operation
```

Expected: fail with 404.

- [ ] **Step 3: Wire route**

Modify `server.py` imports:

```python
from scripts.review_wizard.timeline_edits import apply_timing_edit
```

Add route:

```python
@app.post("/job/<job_id>/review/timeline/edit")
def review_wizard_apply_timing_edit(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists() or not project_path(job_dir).exists():
        return "Job not found", 404

    project = load_project(job_dir)
    try:
        project = apply_timing_edit(
            project,
            target_id=request.form.get("target_id", ""),
            start_s=float(request.form.get("start_s", "0")),
            end_s=float(request.form.get("end_s", "0")),
            edited_by="local-user",
            reason=request.form.get("reason", ""),
        )
    except ValueError as exc:
        return str(exc), 400
    save_project(job_dir, project)
    return redirect(url_for("review_wizard", job_id=job_id))
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_timeline_edits tests.test_review_wizard_server
```

Expected: pass.

---

### Task 3: Minimal Timeline UI

**Files:**
- Modify: `templates/review_wizard.html`
- Modify: `static/app.css`
- Test: `tests/test_review_wizard_server.py`

- [ ] **Step 1: Add failing UI test**

Append to `ReviewWizardServerTests`:

```python
    def test_review_wizard_renders_minimal_timing_editor_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review")

        html = response.get_data(as_text=True)
        self.assertIn(f'action="/job/{job_id}/review/timeline/edit"', html)
        self.assertIn('name="target_id"', html)
        self.assertIn('name="start_s"', html)
        self.assertIn('name="end_s"', html)
        self.assertIn("APPLY TIMING EDIT", html)
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_server.ReviewWizardServerTests.test_review_wizard_renders_minimal_timing_editor_form
```

Expected: fail because form is missing.

- [ ] **Step 3: Add form to focused issue editor**

Modify `templates/review_wizard.html` inside `.focused-issue-editor` after focused actions:

```html
    <form method="post" action="/job/{{ meta.job_id }}/review/timeline/edit" class="timing-edit-form">
      <label class="visually-hidden" for="timing-target">Target</label>
      <input id="timing-target" name="target_id" class="form-input" type="text" placeholder="target id">
      <label class="visually-hidden" for="timing-start">Start</label>
      <input id="timing-start" name="start_s" class="form-input" type="number" step="0.001" placeholder="start seconds">
      <label class="visually-hidden" for="timing-end">End</label>
      <input id="timing-end" name="end_s" class="form-input" type="number" step="0.001" placeholder="end seconds">
      <input name="reason" class="form-input" type="text" placeholder="reason">
      <button type="submit" class="btn btn-primary">APPLY TIMING EDIT</button>
    </form>
```

- [ ] **Step 4: Add CSS**

Append to `static/app.css`:

```css
.timing-edit-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.75rem;
  margin-top: 1rem;
}
```

- [ ] **Step 5: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_timeline_edits tests.test_review_wizard_server
```

Expected: pass.

---

### Task 4: Final Verification

- [ ] **Step 1: Full Review Wizard suite**

Run:

```powershell
python -m unittest tests.test_review_wizard_contracts tests.test_review_wizard_state tests.test_review_wizard_text_prep tests.test_review_wizard_quality tests.test_review_wizard_artifacts tests.test_review_wizard_issue_resolution tests.test_review_wizard_versioning tests.test_review_wizard_export_gate tests.test_review_wizard_timeline_edits tests.test_review_wizard_server
```

Expected: pass.

- [ ] **Step 2: Regressions**

Run:

```powershell
python -m unittest tests.test_server_contracts tests.test_common_contracts tests.test_validate_contracts tests.test_ass_generation
```

Expected: pass.

