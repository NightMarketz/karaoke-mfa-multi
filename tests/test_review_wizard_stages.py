import unittest

from scripts.review_wizard.contracts import Project
from scripts.review_wizard.stages import (
    REVIEW_STAGES,
    active_stage_id,
    stage_view_models,
)
from scripts.review_wizard.wizard import approve_step


class ReviewWizardStagesTests(unittest.TestCase):
    def test_stage_order_matches_full_review_flow(self):
        self.assertEqual(
            [stage.id for stage in REVIEW_STAGES],
            ["import", "lyrics", "alignment", "quality", "preview", "export"],
        )

    def test_user_can_open_previous_or_later_stage_without_mutating_project(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = approve_step(project, "import", approved_by="user")

        self.assertEqual(active_stage_id(project, requested_stage="import"), "import")
        self.assertEqual(active_stage_id(project, requested_stage="lyrics"), "lyrics")
        self.assertEqual(project.wizard_steps["import"]["status"], "approved")

    def test_stage_view_models_include_status_and_counts(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")
        project = approve_step(project, "import", approved_by="user")

        stages = stage_view_models(project, active_stage="lyrics", review_points=[])

        self.assertEqual(stages[0]["id"], "import")
        self.assertEqual(stages[0]["status"], "approved")
        self.assertTrue(stages[1]["active"])
        self.assertEqual(stages[1]["review_point_count"], 0)

    def test_stage_view_models_expose_human_meta_without_zero_zero(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        stages = stage_view_models(project, active_stage="preview", review_points=[])

        self.assertEqual(stages[0]["display_status"], "REVIEW REQUIRED")
        self.assertEqual(stages[0]["display_meta"], "ASSETS CHECK")
        self.assertNotIn("0/0", stages[0]["display_meta"])

        by_id = {stage["id"]: stage for stage in stages}
        self.assertEqual(by_id["lyrics"]["display_meta"], "TEXT REVIEW")
        self.assertEqual(by_id["quality"]["display_meta"], "NO OPEN ISSUES")
        self.assertEqual(by_id["preview"]["display_meta"], "APPROVAL GATE")
        self.assertEqual(by_id["export"]["display_meta"], "FINAL CHECK")


if __name__ == "__main__":
    unittest.main()
