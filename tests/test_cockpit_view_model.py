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
