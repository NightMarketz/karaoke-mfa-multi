import unittest

from scripts.review_wizard.contracts import AlignmentTake, Project
from scripts.review_wizard.versioning import (
    add_edit_operation,
    create_aggressive_candidate,
    promote_take,
)


class ReviewWizardVersioningTests(unittest.TestCase):
    def test_aggressive_correction_creates_candidate_take_without_replacing_parent(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        parent = AlignmentTake(id="take-1", kind="conservative", status="needs_review")
        project = project.with_alignment_take(parent)

        updated = create_aggressive_candidate(
            project,
            parent_take_id="take-1",
            selected_range=(12.0, 18.0),
        )

        self.assertEqual(
            [take.id for take in updated.alignment_takes],
            ["take-1", "take-1-aggressive-2"],
        )
        self.assertEqual(updated.alignment_takes[1].kind, "aggressive_candidate")
        self.assertEqual(updated.alignment_takes[1].parent_take_id, "take-1")
        self.assertIsNone(updated.approved_take_id)

    def test_manual_edit_is_operation_not_destructive_rewrite(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        updated = add_edit_operation(
            project,
            operation="move_syllable_boundary",
            target_id="syll-1",
            created_by="user",
            details={"from": 12.34, "to": 12.372, "snap_source": "vocal_onset"},
        )

        self.assertEqual(len(updated.edit_operations), 1)
        self.assertEqual(updated.edit_operations[0].target_id, "syll-1")
        self.assertEqual(
            updated.edit_operations[0].details["snap_source"],
            "vocal_onset",
        )

    def test_promote_take_sets_approved_take_id(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = project.with_alignment_take(
            AlignmentTake(id="take-1", kind="conservative", status="ready")
        )

        updated = promote_take(project, "take-1")

        self.assertEqual(updated.approved_take_id, "take-1")


if __name__ == "__main__":
    unittest.main()
