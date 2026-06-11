import unittest

from scripts.review_wizard.contracts import Issue, Project
from scripts.review_wizard.issue_resolution import approve_issue_risk, apply_issue_suggestion


def _project_with_issue() -> Project:
    return Project.new(project_id="proj-1", job_id="abc123def456").with_issue(
        Issue(
            id="issue-1",
            type="melisma_unreviewed",
            severity="high",
            perceptual_impact=0.9,
            confidence=0.6,
            priority_score=0.9,
            start_s=10.0,
            end_s=14.0,
            affected_ids=["syll-1"],
            suggested_action="review_melisma_segments",
        )
    )


class ReviewWizardIssueResolutionTests(unittest.TestCase):
    def test_approve_issue_risk_closes_issue_and_records_operation(self):
        project = _project_with_issue()

        updated = approve_issue_risk(
            project,
            issue_id="issue-1",
            approved_by="user",
            reason="Preview sounds acceptable.",
        )

        self.assertEqual(updated.issues[0].status, "risk_approved")
        self.assertEqual(updated.edit_operations[0].operation, "approve_issue_risk")
        self.assertEqual(updated.edit_operations[0].target_id, "issue-1")
        self.assertEqual(updated.edit_operations[0].created_by, "user")
        self.assertEqual(updated.edit_operations[0].details["reason"], "Preview sounds acceptable.")

    def test_apply_issue_suggestion_closes_issue_and_records_operation(self):
        project = _project_with_issue()

        updated = apply_issue_suggestion(project, issue_id="issue-1", applied_by="user")

        self.assertEqual(updated.issues[0].status, "suggestion_applied")
        self.assertEqual(updated.edit_operations[0].operation, "apply_issue_suggestion")
        self.assertEqual(updated.edit_operations[0].details["suggested_action"], "review_melisma_segments")

    def test_approve_issue_risk_requires_reason(self):
        with self.assertRaises(ValueError):
            approve_issue_risk(_project_with_issue(), "issue-1", "user", " ")

    def test_resolution_rejects_unknown_or_closed_issue(self):
        project = _project_with_issue()
        closed = approve_issue_risk(project, "issue-1", "user", "accepted")

        with self.assertRaises(ValueError):
            apply_issue_suggestion(project, "missing", "user")
        with self.assertRaises(ValueError):
            apply_issue_suggestion(closed, "issue-1", "user")


if __name__ == "__main__":
    unittest.main()
