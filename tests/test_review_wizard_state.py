import unittest

from scripts.review_wizard.contracts import Project
from scripts.review_wizard.wizard import (
    REVIEW_WIZARD_STEPS,
    adjust_review_point_timing,
    approve_step,
    approve_review_point,
    next_step,
    skip_review_point_with_risk,
    skip_step_with_risk,
)


class ReviewWizardStateTests(unittest.TestCase):
    def test_steps_are_ordered_around_review_wizard_flow(self):
        self.assertEqual(
            REVIEW_WIZARD_STEPS,
            [
                "import",
                "text_review",
                "alignment_processing",
                "quality_review",
                "preview_approval",
                "export",
            ],
        )

    def test_approve_step_marks_status_and_advances(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = approve_step(project, "import", approved_by="user")

        self.assertEqual(updated.wizard_steps["import"]["status"], "approved")
        self.assertEqual(updated.wizard_steps["import"]["approved_by"], "user")
        self.assertEqual(next_step(updated), "text_review")

    def test_skip_step_records_risk_before_advancing(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = approve_step(project, "import", approved_by="user")
        project = approve_step(project, "text_review", approved_by="user")
        project = approve_step(project, "alignment_processing", approved_by="user")

        updated = skip_step_with_risk(
            project,
            "quality_review",
            skipped_by="user",
            risk_note="Known melisma issue accepted after preview.",
        )

        self.assertEqual(updated.wizard_steps["quality_review"]["status"], "skipped_with_risk")
        self.assertEqual(updated.wizard_steps["quality_review"]["skipped_by"], "user")
        self.assertEqual(
            updated.wizard_steps["quality_review"]["risk_note"],
            "Known melisma issue accepted after preview.",
        )
        self.assertEqual(updated.issues[0].type, "wizard_step_skipped")
        self.assertEqual(updated.issues[0].suggested_action, "preview_before_export")
        self.assertEqual(next_step(updated), "preview_approval")

    def test_next_step_returns_first_unfinished_step(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = approve_step(project, "import", approved_by="user")
        project = skip_step_with_risk(
            project,
            "text_review",
            skipped_by="user",
            risk_note="Text imported from trusted source.",
        )

        self.assertEqual(next_step(project), "alignment_processing")

    def test_approving_unknown_step_is_rejected(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        with self.assertRaises(ValueError):
            approve_step(project, "unknown", approved_by="user")

    def test_skipping_without_risk_note_is_rejected(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        with self.assertRaises(ValueError):
            skip_step_with_risk(project, "quality_review", skipped_by="user", risk_note=" ")

    def test_approve_review_point_records_operation(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = approve_review_point(project, "line-1", approved_by="user")

        self.assertEqual(updated.edit_operations[-1].operation, "approve_review_point")
        self.assertEqual(updated.edit_operations[-1].target_id, "line-1")
        self.assertEqual(updated.edit_operations[-1].created_by, "user")

    def test_skip_review_point_requires_reason_and_records_risk(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = skip_review_point_with_risk(
            project,
            "line-1",
            skipped_by="user",
            risk_note="Acceptable in preview.",
        )

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


if __name__ == "__main__":
    unittest.main()
