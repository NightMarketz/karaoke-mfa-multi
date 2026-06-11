import unittest

from scripts.review_wizard.contracts import Project
from scripts.review_wizard.wizard import (
    REVIEW_WIZARD_STEPS,
    approve_review_point,
    approve_step,
    apply_review_point_suggestion,
    next_step,
    skip_review_point_with_risk,
    skip_step_with_risk,
)


def _minimal_project() -> Project:
    return Project.new(project_id="proj-test", job_id="job-test")


class WizardEdgeCaseTests(unittest.TestCase):
    def test_skip_step_with_risk_empty_risk_note_raises(self):
        project = _minimal_project()
        with self.assertRaises(ValueError):
            skip_step_with_risk(project, REVIEW_WIZARD_STEPS[0], "user-1", "")

    def test_skip_step_with_risk_whitespace_only_risk_note_raises(self):
        project = _minimal_project()
        with self.assertRaises(ValueError):
            skip_step_with_risk(project, REVIEW_WIZARD_STEPS[0], "user-1", "   ")

    def test_skip_step_with_risk_valid_adds_issue(self):
        project = _minimal_project()
        updated = skip_step_with_risk(project, REVIEW_WIZARD_STEPS[0], "user-1", "Skipping for now")
        self.assertEqual(len(updated.issues), 1)
        self.assertEqual(updated.issues[0].type, "wizard_step_skipped")

    def test_next_step_returns_first_step_when_no_steps_completed(self):
        project = _minimal_project()
        result = next_step(project)
        self.assertEqual(result, REVIEW_WIZARD_STEPS[0])

    def test_next_step_returns_none_when_all_steps_approved(self):
        project = _minimal_project()
        for step in REVIEW_WIZARD_STEPS:
            project = approve_step(project, step, "user-1")
        result = next_step(project)
        self.assertIsNone(result)

    def test_next_step_advances_past_approved_step(self):
        project = _minimal_project()
        project = approve_step(project, REVIEW_WIZARD_STEPS[0], "user-1")
        result = next_step(project)
        self.assertEqual(result, REVIEW_WIZARD_STEPS[1])

    def test_approve_review_point_appends_edit_operation(self):
        project = _minimal_project()
        updated = approve_review_point(project, "point-abc", "reviewer-1")
        self.assertEqual(len(updated.edit_operations), 1)
        self.assertEqual(updated.edit_operations[0].operation, "approve_review_point")
        self.assertEqual(updated.edit_operations[0].target_id, "point-abc")

    def test_skip_review_point_with_risk_empty_note_raises(self):
        project = _minimal_project()
        with self.assertRaises(ValueError):
            skip_review_point_with_risk(project, "point-xyz", "user-1", "")

    def test_skip_review_point_with_risk_whitespace_note_raises(self):
        project = _minimal_project()
        with self.assertRaises(ValueError):
            skip_review_point_with_risk(project, "point-xyz", "user-1", "  \t  ")

    def test_skip_review_point_with_risk_valid_appends_edit_operation(self):
        project = _minimal_project()
        updated = skip_review_point_with_risk(project, "point-xyz", "user-1", "Acceptable risk")
        self.assertEqual(len(updated.edit_operations), 1)
        self.assertEqual(updated.edit_operations[0].operation, "skip_review_point_with_risk")
        self.assertEqual(updated.edit_operations[0].details["risk_note"], "Acceptable risk")

    def test_apply_review_point_suggestion_appends_edit_operation_with_details(self):
        project = _minimal_project()
        details = {"new_start_s": 1.5, "new_end_s": 2.0}
        updated = apply_review_point_suggestion(project, "point-001", "editor-1", details)
        self.assertEqual(len(updated.edit_operations), 1)
        self.assertEqual(updated.edit_operations[0].operation, "apply_review_point_suggestion")
        self.assertEqual(updated.edit_operations[0].target_id, "point-001")
        self.assertEqual(updated.edit_operations[0].details["new_start_s"], 1.5)

    def test_multiple_operations_accumulate(self):
        project = _minimal_project()
        project = approve_review_point(project, "p1", "user-1")
        project = approve_review_point(project, "p2", "user-1")
        self.assertEqual(len(project.edit_operations), 2)
        self.assertEqual(project.edit_operations[0].id, "op-1")
        self.assertEqual(project.edit_operations[1].id, "op-2")


if __name__ == "__main__":
    unittest.main()
