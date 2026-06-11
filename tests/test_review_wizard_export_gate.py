import unittest

from scripts.review_wizard.contracts import Issue, Project, QualityReport
from scripts.review_wizard.export_gate import approve_preview, can_export_final
from scripts.review_wizard.export_summary import review_export_summary
from scripts.review_wizard.review_points import ReviewPoint


def _preview_evidence(scope: str = "full_preview") -> dict[str, object]:
    return {
        "scope": scope,
        "artifact_path": "output.mp4",
        "artifact_sha256": "a" * 64,
        "artifact_size_bytes": 128,
        "take_id": "take-1",
        "quality_report_id": "qr-1",
        "quality_status": "needs_fix",
    }


class ReviewWizardExportGateTests(unittest.TestCase):
    def test_export_summary_counts_reviewed_pending_and_risky_points(self):
        points = [
            ReviewPoint(
                id="p1",
                stage_id="alignment",
                level="line",
                text="A",
                start_s=1,
                end_s=2,
                status="approved",
            ),
            ReviewPoint(
                id="p2",
                stage_id="alignment",
                level="line",
                text="B",
                start_s=3,
                end_s=4,
                status="open",
            ),
            ReviewPoint(
                id="p3",
                stage_id="quality",
                level="issue",
                text="C",
                start_s=5,
                end_s=6,
                status="skipped_with_risk",
            ),
        ]

        summary = review_export_summary(points)

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["approved"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["risk_accepted"], 1)
        self.assertEqual(summary["by_stage"]["alignment"]["pending"], 1)

    def test_ready_project_can_export_without_preview_gate(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = project.with_quality_report(
            QualityReport(id="qr-1", take_id="take-1", status="ready", score=0.98)
        )

        decision = can_export_final(project)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ready")

    def test_needs_fix_requires_preview_approval(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = project.with_quality_report(
            QualityReport(
                id="qr-1",
                take_id="take-1",
                status="needs_fix",
                score=0.70,
                issue_ids=["issue-1"],
            )
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
        critical_after = can_export_final(
            approve_preview(
                project,
                approved_by="user",
                scope="critical_snippets",
                evidence=_preview_evidence("critical_snippets"),
            )
        )
        full_after = can_export_final(
            approve_preview(
                project,
                approved_by="user",
                scope="full_preview",
                evidence=_preview_evidence("full_preview"),
            )
        )

        self.assertFalse(before.allowed)
        self.assertEqual(before.reason, "preview_required")
        self.assertFalse(critical_after.allowed)
        self.assertEqual(critical_after.reason, "full_preview_required")
        self.assertTrue(full_after.allowed)
        self.assertEqual(full_after.reason, "full_preview_approved_with_risk")

    def test_missing_quality_report_blocks_export(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        decision = can_export_final(project)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "quality_review_required")

    def test_preview_approval_rejects_unknown_scope(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        with self.assertRaises(ValueError):
            approve_preview(
                project,
                approved_by="user",
                scope="unknown",
                evidence=_preview_evidence("unknown"),
            )

    def test_full_preview_approval_records_auditable_evidence(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = approve_preview(
            project,
            approved_by="user",
            scope="full_preview",
            evidence=_preview_evidence("full_preview"),
        )

        self.assertEqual(updated.preview_renders[0]["scope"], "full_preview")
        self.assertTrue(updated.preview_renders[0]["approved"])
        self.assertEqual(updated.preview_renders[0]["artifact_path"], "output.mp4")
        self.assertEqual(updated.preview_renders[0]["artifact_sha256"], "a" * 64)
        self.assertEqual(updated.preview_renders[0]["artifact_size_bytes"], 128)
        self.assertEqual(updated.preview_renders[0]["take_id"], "take-1")

    def test_preview_approval_rejects_invalid_scope(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        with self.assertRaises(ValueError) as error:
            approve_preview(
                project,
                approved_by="user",
                scope="song_preview",
                evidence=_preview_evidence("song_preview"),
            )

        self.assertEqual(str(error.exception), "invalid preview scope: song_preview")

    def test_preview_approval_requires_render_evidence(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        with self.assertRaises(ValueError) as error:
            approve_preview(project, approved_by="user", scope="full_preview", evidence={})

        self.assertEqual(str(error.exception), "preview evidence missing: artifact_path")

    def test_legacy_preview_without_artifact_hash_does_not_unlock_export(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = project.with_quality_report(
            QualityReport(id="qr-1", take_id="take-1", status="needs_fix", score=0.70)
        )
        project = project.__class__(
            **{
                **project.to_dict(),
                "preview_renders": [
                    {"scope": "full_preview", "approved": True, "approved_by": "user"}
                ],
            }
        )

        decision = can_export_final(project)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "preview_required")

    def test_full_preview_approval_is_stale_after_new_quality_report(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = project.with_quality_report(
            QualityReport(id="qr-1", take_id="take-1", status="needs_fix", score=0.70)
        )
        project = approve_preview(
            project,
            approved_by="user",
            scope="full_preview",
            evidence=_preview_evidence("full_preview"),
        )
        project = project.with_quality_report(
            QualityReport(id="qr-2", take_id="take-2", status="needs_fix", score=0.80)
        )

        decision = can_export_final(project)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "preview_required")


if __name__ == "__main__":
    unittest.main()
