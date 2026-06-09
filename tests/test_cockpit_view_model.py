import tempfile
import unittest
import wave
from pathlib import Path

from scripts.cockpit import (
    artifact_rows,
    build_cockpit_timeline,
    cockpit_service_summary,
    build_quick_review,
    cockpit_stage_rows,
    recent_project_cards,
    selected_job_summary,
)
from scripts.review_wizard.contracts import Issue, Project
from scripts.review_wizard.review_points import ReviewPoint


def _write_test_wav(path: Path, samples: list[int], *, framerate: int = 8000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(framerate)
        frames = b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in samples)
        wav.writeframes(frames)


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
            "language": "pt-BR",
            "preset": "single-style-kf",
            "status": {"stage": "done", "progress": 100, "error": ""},
        }

        summary = selected_job_summary(job)

        self.assertEqual(summary["job_id"], "abc123def456")
        self.assertEqual(summary["title"], "Nova Cancao")
        self.assertEqual(summary["duration_label"], "04:32.118")
        self.assertEqual(summary["pipeline_label"], "DONE")
        self.assertEqual(summary["language_label"], "pt-BR")

    def test_selected_job_summary_includes_language_without_fake_default(self):
        summary = selected_job_summary(
            {
                "job_id": "abc123def456",
                "song_name": "Nova Cancao",
                "duration_s": 272.118,
                "preset": "single-style-kf",
                "status": {"stage": "done", "progress": 100, "error": ""},
            }
        )

        self.assertEqual(summary["language_label"], "--")

    def test_cockpit_service_summary_reports_real_job_counts(self):
        summary = cockpit_service_summary(
            [
                {"status": {"stage": "done"}},
                {"status": {"stage": "rendering"}},
                {"status": {"stage": "failed"}},
            ]
        )

        self.assertEqual(summary["label"], "3 projects indexed")
        self.assertEqual(summary["state"], "1 running / 1 failed")

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

    def test_timeline_uses_real_wav_analysis_and_review_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            _write_test_wav(job_dir / "vocals.wav", [0, 1000, 3000, 9000, 12000, 4000, 1000, 0])
            _write_test_wav(job_dir / "instrumental.wav", [0, 2000, 5000, 16000, 8000, 3000, 1000, 0])
            (job_dir / "analysis.json").write_text(
                '{"lines":[{"text":"Linha real do projeto","start":1.0,"end":2.5}]}',
                encoding="utf-8",
            )
            points = [
                ReviewPoint(
                    id="issue:1",
                    stage_id="quality",
                    level="issue",
                    text="drift: review alignment",
                    start_s=1.2,
                    end_s=1.8,
                    priority=0.9,
                    severity="high",
                )
            ]

            timeline = build_cockpit_timeline(job_dir, points, bar_count=8)

        self.assertTrue(timeline["has_audio"])
        self.assertEqual([lane["label"] for lane in timeline["lanes"]], ["Mix", "Vocals", "Instrumental"])
        self.assertTrue(any(bar["height"] > 10 for bar in timeline["lanes"][1]["bars"]))
        self.assertEqual(timeline["lyrics"][0]["text"], "Linha real do projeto")
        self.assertEqual(timeline["issues"][0]["text"], "drift: review alignment")
        self.assertEqual(timeline["issues"][0]["severity"], "high")


if __name__ == "__main__":
    unittest.main()
