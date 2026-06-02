import json
import tempfile
import unittest
from pathlib import Path

from scripts.review_wizard.contracts import Issue, Project
from scripts.review_wizard.wizard import adjust_review_point_timing
from scripts.review_wizard.review_points import (
    ReviewPoint,
    build_review_points,
    filtered_review_points,
    next_open_point_after,
    next_open_point,
    point_navigation,
    points_for_stage,
    review_point_window,
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

    def test_aligned_words_fill_line_word_points_when_analysis_words_are_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "Coracao aberto",
                                "start": 0.0,
                                "end": 1.8,
                                "style": "verse",
                                "words": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "aligned.json").write_text(
                json.dumps(
                    {
                        "words": [
                            {"word": "Coracao", "start": 0.0, "end": 0.8},
                            {"word": "aberto", "start": 0.9, "end": 1.8},
                            {"word": "outside", "start": 2.0, "end": 2.5},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            project = Project.new(project_id="proj-1", job_id="abc123def456")

            points = build_review_points(job_dir, project)

        self.assertEqual([point.text for point in points if point.level == "word"], ["Coracao", "aberto"])
        self.assertEqual(points[1].source, "aligned")

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

    def test_open_timestamped_issues_become_quality_review_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            valid_issue = Issue(
                id="issue-1",
                type="drift",
                severity="high",
                perceptual_impact=0.9,
                confidence=0.8,
                priority_score=0.72,
                start_s=10.1,
                end_s=11.0,
                affected_ids=["line-1", "line-1:word-1"],
                suggested_action="review_alignment",
            )
            invalid_issue = Issue(
                id="issue-2",
                type="overlap",
                severity="medium",
                perceptual_impact=0.4,
                confidence=0.8,
                priority_score=0.3,
                start_s=12.0,
                end_s=12.0,
                affected_ids=["line-2"],
                suggested_action="adjust_timing",
            )
            closed_issue = Issue(
                id="issue-3",
                type="gap",
                severity="low",
                perceptual_impact=0.2,
                confidence=0.8,
                priority_score=0.1,
                start_s=13.0,
                end_s=14.0,
                affected_ids=["line-3"],
                suggested_action="inspect",
                status="resolved",
            )
            project = (
                Project.new(project_id="proj-1", job_id="abc123def456")
                .with_issue(valid_issue)
                .with_issue(invalid_issue)
                .with_issue(closed_issue)
            )

            points = build_review_points(job_dir, project)

        quality_points = points_for_stage(points, "quality")
        self.assertEqual([point.id for point in quality_points], ["issue:issue-1"])
        self.assertEqual(quality_points[0].level, "issue")
        self.assertIn("drift", quality_points[0].text)
        self.assertIn("review alignment", quality_points[0].text)
        self.assertEqual(quality_points[0].priority, 0.72)
        self.assertEqual(quality_points[0].severity, "high")
        self.assertEqual(quality_points[0].issue_ids, ["issue-1"])
        self.assertEqual(quality_points[0].affected_ids, ["line-1", "line-1:word-1"])

    def test_next_open_point_uses_stage_and_priority_order(self):
        points = [
            ReviewPoint(id="p1", stage_id="alignment", level="line", text="A", start_s=3, end_s=4, priority=0.1),
            ReviewPoint(id="p2", stage_id="alignment", level="line", text="B", start_s=1, end_s=2, priority=0.9),
            ReviewPoint(id="p3", stage_id="quality", level="issue", text="C", start_s=1, end_s=2, priority=1.0),
        ]

        self.assertEqual(next_open_point(points, "alignment").id, "p2")

    def test_filtered_review_points_support_status_and_level_filters(self):
        points = [
            ReviewPoint(id="line-1", stage_id="alignment", level="line", text="A", start_s=1, end_s=2),
            ReviewPoint(
                id="line-1:word-1",
                stage_id="alignment",
                level="word",
                text="word",
                start_s=1.1,
                end_s=1.5,
                status="approved",
            ),
            ReviewPoint(id="issue-1", stage_id="quality", level="issue", text="Drift", start_s=1, end_s=2),
        ]

        self.assertEqual(
            [point.id for point in filtered_review_points(points, stage_id="alignment", status_filter="open")],
            ["line-1"],
        )
        self.assertEqual(
            [point.id for point in filtered_review_points(points, stage_id="alignment", level_filter="word")],
            ["line-1:word-1"],
        )
        self.assertEqual(
            [point.id for point in filtered_review_points(points, stage_id="quality", level_filter="issue")],
            ["issue-1"],
        )

    def test_point_navigation_reports_position_neighbors_and_next_open_after_active(self):
        points = [
            ReviewPoint(id="line-1", stage_id="alignment", level="line", text="A", start_s=1, end_s=2, status="approved"),
            ReviewPoint(id="line-2", stage_id="alignment", level="line", text="B", start_s=3, end_s=4),
            ReviewPoint(id="line-3", stage_id="alignment", level="line", text="C", start_s=5, end_s=6),
        ]

        nav = point_navigation(points, active_point_id="line-2")

        self.assertEqual(nav["position"], 2)
        self.assertEqual(nav["total"], 3)
        self.assertEqual(nav["previous_id"], "line-1")
        self.assertEqual(nav["next_id"], "line-3")
        self.assertEqual(nav["next_open_id"], "line-3")

    def test_next_open_point_after_uses_visible_queue_order(self):
        points = [
            ReviewPoint(id="line-1", stage_id="alignment", level="line", text="A", start_s=1, end_s=2, priority=0.1),
            ReviewPoint(id="line-2", stage_id="alignment", level="line", text="B", start_s=3, end_s=4, priority=0.9),
            ReviewPoint(id="line-3", stage_id="alignment", level="line", text="C", start_s=5, end_s=6, priority=0.2),
        ]

        self.assertEqual(next_open_point_after(points, "line-1").id, "line-2")
        self.assertEqual(next_open_point_after(points, "line-3").id, "line-1")

    def test_review_point_window_centers_active_point_when_possible(self):
        points = [
            ReviewPoint(id=f"p{i}", stage_id="alignment", level="word", text=str(i), start_s=i, end_s=i + 0.1)
            for i in range(1, 21)
        ]

        window = review_point_window(points, active_point_id="p10", window_size=6)

        self.assertEqual([point.id for point in window["items"]], ["p7", "p8", "p9", "p10", "p11", "p12"])
        self.assertEqual(window["start"], 7)
        self.assertEqual(window["end"], 12)
        self.assertEqual(window["total"], 20)
        self.assertTrue(window["has_previous"])
        self.assertTrue(window["has_next"])

    def test_review_point_window_includes_active_point_near_end(self):
        points = [
            ReviewPoint(id=f"p{i}", stage_id="alignment", level="word", text=str(i), start_s=i, end_s=i + 0.1)
            for i in range(1, 21)
        ]

        window = review_point_window(points, active_point_id="p19", window_size=6)

        self.assertEqual([point.id for point in window["items"]], ["p15", "p16", "p17", "p18", "p19", "p20"])
        self.assertEqual(window["start"], 15)
        self.assertEqual(window["end"], 20)
        self.assertTrue(window["has_previous"])
        self.assertFalse(window["has_next"])

    def test_timing_edits_override_review_point_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "analysis.json").write_text(
                json.dumps({"lines": [{"text": "A", "start": 1.0, "end": 2.0, "words": []}]}),
                encoding="utf-8",
            )
            project = Project.new(project_id="proj-1", job_id="abc123def456")
            project = adjust_review_point_timing(project, "line-1", edited_by="user", start_s=1.25, end_s=2.5)

            points = build_review_points(job_dir, project)

        self.assertEqual(points[0].status, "edited")
        self.assertEqual(points[0].start_s, 1.25)
        self.assertEqual(points[0].end_s, 2.5)


if __name__ == "__main__":
    unittest.main()
