# Critical Snippet Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate, play, and approve issue-specific preview snippets before risky final export.

**Architecture:** Add isolated Review Wizard snippet helpers that derive preview windows from prioritized issues and materialize small preview artifacts under each job. Flask exposes render/play/approve routes while the existing export gate keeps final export blocked until full preview approval. Snippet approval remains partial evidence and never unlocks final export by itself.

**Tech Stack:** Python dataclasses/dicts, Flask/Jinja, file-based jobs, standard-library `unittest`, existing MP4 artifacts, future-compatible FFmpeg invocation hook.

---

## File Structure

- Create: `scripts/review_wizard/snippet_preview.py`
- Modify: `server.py`
- Modify: `templates/review_wizard.html`
- Modify: `static/app.css`
- Test: `tests/test_review_wizard_snippet_preview.py`
- Test: `tests/test_review_wizard_server.py`

## Verification Rules

Run every command with explicit timeout in the Codex tool call:

```powershell
python -m unittest tests.test_review_wizard_snippet_preview tests.test_review_wizard_server
python -m unittest tests.test_review_wizard_contracts tests.test_review_wizard_state tests.test_review_wizard_text_prep tests.test_review_wizard_quality tests.test_review_wizard_artifacts tests.test_review_wizard_issue_resolution tests.test_review_wizard_versioning tests.test_review_wizard_export_gate tests.test_review_wizard_snippet_preview tests.test_review_wizard_server
python -m py_compile server.py scripts\review_wizard\snippet_preview.py scripts\review_wizard\export_gate.py
```

---

### Task 1: Snippet Window Contract

**Files:**
- Create: `scripts/review_wizard/snippet_preview.py`
- Test: `tests/test_review_wizard_snippet_preview.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_review_wizard_snippet_preview.py`:

```python
import unittest

from scripts.review_wizard.contracts import Issue
from scripts.review_wizard.snippet_preview import build_snippet_windows


class SnippetPreviewTests(unittest.TestCase):
    def test_builds_padded_windows_for_critical_and_high_issues(self):
        issues = [
            Issue(
                id="issue-low",
                type="short_word_duration",
                severity="low",
                perceptual_impact=0.2,
                confidence=0.8,
                priority_score=0.16,
                start_s=20.0,
                end_s=20.5,
                affected_ids=["w-low"],
                suggested_action="check_short_word",
            ),
            Issue(
                id="issue-critical",
                type="melisma_unreviewed",
                severity="critical",
                perceptual_impact=0.95,
                confidence=0.7,
                priority_score=0.95,
                start_s=10.0,
                end_s=12.0,
                affected_ids=["s-critical"],
                suggested_action="review_melisma_segments",
            ),
        ]

        windows = build_snippet_windows(issues, pre_roll_s=1.0, post_roll_s=1.5)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["issue_id"], "issue-critical")
        self.assertEqual(windows[0]["start_s"], 9.0)
        self.assertEqual(windows[0]["end_s"], 13.5)
        self.assertEqual(windows[0]["source"], "quality_issue")

    def test_clamps_window_start_to_zero(self):
        issues = [
            Issue(
                id="issue-early",
                type="line_boundary_uncertain",
                severity="high",
                perceptual_impact=0.8,
                confidence=0.7,
                priority_score=0.8,
                start_s=0.4,
                end_s=1.0,
                affected_ids=["line-1"],
                suggested_action="review_line_boundary",
            )
        ]

        windows = build_snippet_windows(issues, pre_roll_s=1.0, post_roll_s=1.0)

        self.assertEqual(windows[0]["start_s"], 0.0)
        self.assertEqual(windows[0]["end_s"], 2.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_snippet_preview
```

Expected: fail with `ModuleNotFoundError` or missing `build_snippet_windows`.

- [ ] **Step 3: Implement minimal window builder**

Create `scripts/review_wizard/snippet_preview.py`:

```python
from __future__ import annotations

from typing import Any

from scripts.review_wizard.contracts import Issue


SNIPPET_SEVERITIES = {"critical", "high"}


def build_snippet_windows(
    issues: list[Issue],
    pre_roll_s: float = 1.0,
    post_roll_s: float = 1.5,
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for issue in sorted(issues, key=lambda item: item.priority_score, reverse=True):
        if issue.status != "open":
            continue
        if issue.severity not in SNIPPET_SEVERITIES:
            continue
        windows.append(
            {
                "issue_id": issue.id,
                "start_s": round(max(0.0, issue.start_s - pre_roll_s), 3),
                "end_s": round(issue.end_s + post_roll_s, 3),
                "source": "quality_issue",
                "severity": issue.severity,
            }
        )
    return windows
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_snippet_preview
```

Expected: pass.

---

### Task 2: Materialize Snippet Preview Artifacts

**Files:**
- Modify: `scripts/review_wizard/snippet_preview.py`
- Test: `tests/test_review_wizard_snippet_preview.py`

- [ ] **Step 1: Add failing materialization test**

Append to `SnippetPreviewTests`:

```python
    def test_materializes_snippet_artifacts_from_output_video_copy_for_now(self):
        import tempfile
        from pathlib import Path

        from scripts.review_wizard.snippet_preview import materialize_snippet_previews

        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "output.mp4").write_bytes(b"video")
            windows = [{"issue_id": "issue-critical", "start_s": 9.0, "end_s": 13.5}]

            renders = materialize_snippet_previews(job_dir, windows)

            self.assertEqual(len(renders), 1)
            self.assertEqual(renders[0]["scope"], "critical_snippets")
            self.assertEqual(renders[0]["issue_id"], "issue-critical")
            self.assertEqual(renders[0]["artifact_path"], "preview_snippets/issue-critical.mp4")
            self.assertEqual((job_dir / "preview_snippets" / "issue-critical.mp4").read_bytes(), b"video")
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_snippet_preview.SnippetPreviewTests.test_materializes_snippet_artifacts_from_output_video_copy_for_now
```

Expected: fail with missing function.

- [ ] **Step 3: Implement materializer**

Add to `scripts/review_wizard/snippet_preview.py`:

```python
import shutil
from pathlib import Path


def materialize_snippet_previews(job_dir: Path, windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = job_dir / "output.mp4"
    if not source.exists():
        raise ValueError("snippet preview source missing: output.mp4")
    snippet_dir = job_dir / "preview_snippets"
    snippet_dir.mkdir(exist_ok=True)
    renders: list[dict[str, Any]] = []
    for window in windows:
        issue_id = str(window["issue_id"])
        target = snippet_dir / f"{issue_id}.mp4"
        shutil.copy2(source, target)
        renders.append(
            {
                "scope": "critical_snippets",
                "issue_id": issue_id,
                "approved": False,
                "render_status": "ready",
                "artifact_path": f"preview_snippets/{issue_id}.mp4",
                "start_s": window["start_s"],
                "end_s": window["end_s"],
            }
        )
    return renders
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_snippet_preview
```

Expected: pass.

---

### Task 3: Flask Routes And UI

**Files:**
- Modify: `server.py`
- Modify: `templates/review_wizard.html`
- Modify: `static/app.css`
- Test: `tests/test_review_wizard_server.py`

- [ ] **Step 1: Add failing server tests**

Append to `ReviewWizardServerTests`:

```python
    def test_render_critical_snippets_route_creates_issue_previews(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            (job_dir / "output.mp4").write_bytes(b"video")
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            issue = Issue(
                id="issue-critical",
                type="melisma_unreviewed",
                severity="critical",
                perceptual_impact=0.95,
                confidence=0.7,
                priority_score=0.95,
                start_s=10.0,
                end_s=12.0,
                affected_ids=["s-critical"],
                suggested_action="review_melisma_segments",
            )
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "issues": [issue],
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.70, issue_ids=["issue-critical"])
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(f"/job/{job_id}/review/preview/snippets/render")

            project = load_project(job_dir)

        self.assertEqual(response.status_code, 302)
        self.assertTrue((job_dir / "preview_snippets" / "issue-critical.mp4").exists())
        self.assertEqual(project.preview_renders[-1]["issue_id"], "issue-critical")

    def test_review_wizard_renders_snippet_preview_player_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            (job_dir / "output.mp4").write_bytes(b"video")
            (job_dir / "preview_snippets").mkdir()
            (job_dir / "preview_snippets" / "issue-critical.mp4").write_bytes(b"video")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "preview_renders": [
                        {
                            "scope": "critical_snippets",
                            "issue_id": "issue-critical",
                            "approved": False,
                            "artifact_path": "preview_snippets/issue-critical.mp4",
                            "start_s": 10.0,
                            "end_s": 12.0,
                        }
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review")

        html = response.get_data(as_text=True)
        self.assertIn("/job/abc123def456/review/preview/snippets/issue-critical.mp4", html)
        self.assertIn("GENERATE CRITICAL SNIPPETS", html)
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_server.ReviewWizardServerTests.test_render_critical_snippets_route_creates_issue_previews tests.test_review_wizard_server.ReviewWizardServerTests.test_review_wizard_renders_snippet_preview_player_link
```

Expected: fail with 404/missing UI.

- [ ] **Step 3: Wire routes**

Modify `server.py` imports:

```python
from scripts.review_wizard.snippet_preview import build_snippet_windows, materialize_snippet_previews
```

Add routes near the preview routes:

```python
@app.post("/job/<job_id>/review/preview/snippets/render")
def review_wizard_render_snippet_previews(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists() or not project_path(job_dir).exists():
        return "Job not found", 404
    project = load_project(job_dir)
    try:
        renders = materialize_snippet_previews(job_dir, build_snippet_windows(project.issues))
    except ValueError as exc:
        return str(exc), 400
    project = dataclasses.replace(project, preview_renders=[*project.preview_renders, *renders])
    save_project(job_dir, project)
    return redirect(url_for("review_wizard", job_id=job_id))


@app.route("/job/<job_id>/review/preview/snippets/<issue_id>.mp4")
def review_wizard_snippet_preview_mp4(job_id: str, issue_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Not found", 404
    path = job_dir / "preview_snippets" / f"{issue_id}.mp4"
    if not path.exists():
        return "Not found", 404
    return send_file(path, mimetype="video/mp4", conditional=True)
```

- [ ] **Step 4: Render UI controls**

Modify `templates/review_wizard.html` inside `.preview-actions` before approval buttons:

```html
    <form
      method="post"
      action="/job/{{ meta.job_id }}/review/preview/snippets/render"
      class="preview-action-form"
    >
      <button type="submit" class="btn btn-ghost">GENERATE CRITICAL SNIPPETS</button>
    </form>
```

After the full preview player block, add:

```html
  {% set snippet_renders = project.preview_renders | selectattr("scope", "equalto", "critical_snippets") | list %}
  {% if snippet_renders %}
    <div class="snippet-preview-list">
      {% for render in snippet_renders %}
        <div class="snippet-preview-item">
          <span class="mono">{{ render.issue_id }}</span>
          <video class="snippet-player" controls preload="metadata" src="/job/{{ meta.job_id }}/review/preview/snippets/{{ render.issue_id }}.mp4">
            Your browser does not support video playback.
          </video>
        </div>
      {% endfor %}
    </div>
  {% endif %}
```

- [ ] **Step 5: Add minimal CSS**

Append to `static/app.css` near preview styles:

```css
.snippet-preview-list {
  display: grid;
  gap: 1rem;
  margin: 1rem 0;
}

.snippet-preview-item {
  display: grid;
  gap: 0.5rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.75rem;
  background: rgba(255,255,255,0.02);
}

.snippet-player {
  width: 100%;
  max-height: 220px;
  border-radius: var(--radius);
}
```

- [ ] **Step 6: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_snippet_preview tests.test_review_wizard_server
```

Expected: pass.

---

### Task 4: Approve Snippet Evidence Without Unlocking Final Export

**Files:**
- Modify: `server.py`
- Modify: `scripts/review_wizard/export_gate.py` only if needed
- Test: `tests/test_review_wizard_server.py`
- Test: `tests/test_review_wizard_export_gate.py`

- [ ] **Step 1: Add failing test**

Append to `ReviewWizardServerTests`:

```python
    def test_approving_snippets_records_partial_evidence_but_final_export_stays_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            (job_dir / "output.mp4").write_bytes(b"video")
            (job_dir / "output.ass").write_text("[Script Info]\n", encoding="utf-8")
            (job_dir / "preview_snippets").mkdir()
            (job_dir / "preview_snippets" / "issue-critical.mp4").write_bytes(b"video")
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            issue = Issue(
                id="issue-critical",
                type="melisma_unreviewed",
                severity="critical",
                perceptual_impact=0.95,
                confidence=0.7,
                priority_score=0.95,
                start_s=10.0,
                end_s=12.0,
                affected_ids=["s-critical"],
                suggested_action="review_melisma_segments",
            )
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "issues": [issue],
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.70, issue_ids=["issue-critical"])
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                approval = client.post(f"/job/{job_id}/review/preview/critical-snippets/approve")
                export_response = client.get(f"/job/{job_id}/output.ass")

            project = load_project(job_dir)

        self.assertEqual(approval.status_code, 302)
        self.assertEqual(project.preview_renders[-1]["scope"], "critical_snippets")
        self.assertEqual(project.preview_renders[-1]["covered_issue_ids"], ["issue-critical"])
        self.assertEqual(export_response.status_code, 403)
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m unittest tests.test_review_wizard_server.ReviewWizardServerTests.test_approving_snippets_records_partial_evidence_but_final_export_stays_blocked
```

Expected: fail until critical snippet evidence points to snippet artifacts.

- [ ] **Step 3: Adjust `_preview_approval_evidence` for critical snippets**

In `server.py`, update the `else` branch of `_preview_approval_evidence` to include snippet artifacts:

```python
    else:
        evidence["covered_issue_ids"] = open_issue_ids
        evidence["snippet_windows"] = [
            {"issue_id": issue.id, "start_s": issue.start_s, "end_s": issue.end_s}
            for issue in project.issues
            if issue.id in open_issue_ids
        ]
        for issue_id in open_issue_ids:
            snippet_name = f"preview_snippets/{issue_id}.mp4"
            snippet_path = job_dir / snippet_name
            if snippet_path.exists():
                artifact_fingerprints[snippet_name] = {
                    "sha256": _sha256_file(snippet_path),
                    "size_bytes": snippet_path.stat().st_size,
                }
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m unittest tests.test_review_wizard_snippet_preview tests.test_review_wizard_export_gate tests.test_review_wizard_server
```

Expected: pass.

---

### Task 5: Final Verification

**Files:** all touched files.

- [ ] **Step 1: Run full Review Wizard suite**

Run:

```powershell
python -m unittest tests.test_review_wizard_contracts tests.test_review_wizard_state tests.test_review_wizard_text_prep tests.test_review_wizard_quality tests.test_review_wizard_artifacts tests.test_review_wizard_issue_resolution tests.test_review_wizard_versioning tests.test_review_wizard_export_gate tests.test_review_wizard_snippet_preview tests.test_review_wizard_server
```

Expected: pass.

- [ ] **Step 2: Run regression suite**

Run:

```powershell
python -m unittest tests.test_server_contracts tests.test_common_contracts tests.test_validate_contracts tests.test_ass_generation
```

Expected: pass.

- [ ] **Step 3: Compile changed Python files**

Run:

```powershell
python -m py_compile server.py scripts\review_wizard\snippet_preview.py scripts\review_wizard\export_gate.py
```

Expected: no output.

