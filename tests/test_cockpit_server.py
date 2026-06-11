import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("flask")
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

    def test_selected_job_timeline_uses_analysis_text_not_mock_lyrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            (job_dir / "analysis.json").write_text(
                json.dumps({"lines": [{"text": "Linha real do projeto", "start": 1.0, "end": 2.5, "words": []}]}),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/?job={job_id}")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Linha real do projeto", html)
        self.assertNotIn("Faz tanto tempo", html)
        self.assertNotIn(">GAP<", html)
        self.assertNotIn(">DRIFT<", html)
        self.assertNotIn(">MELISMA<", html)

    def test_index_status_chips_do_not_claim_fake_language_or_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(server, "JOBS_DIR", Path(tmp)):
                response = server.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("<strong>--</strong>", html)
        self.assertIn("0 projects indexed", html)
        self.assertNotIn("<strong>pt-BR</strong>", html)
        self.assertNotIn("All Services OK", html)

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

    def test_cockpit_template_and_script_expose_interaction_hooks(self):
        template = Path("templates/cockpit.html").read_text(encoding="utf-8")
        script = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn("data-cockpit-mode", template)
        self.assertIn("data-file-drop", template)
        self.assertIn("data-lyrics-counter", template)
        self.assertIn("initCockpit();", script)
        self.assertIn("function initCockpit()", script)


if __name__ == "__main__":
    unittest.main()
