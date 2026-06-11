import unittest

from scripts.review_wizard.contracts import Issue
from scripts.review_wizard.quality import prioritize_issues, quality_status


class ReviewWizardQualityTests(unittest.TestCase):
    def test_prioritize_issues_orders_by_perceptual_impact_first(self):
        technical = Issue(
            id="technical",
            type="boundary_error",
            severity="high",
            perceptual_impact=0.3,
            confidence=0.9,
            priority_score=0.0,
            start_s=1,
            end_s=2,
            affected_ids=["a"],
            suggested_action="snap_to_onset",
        )
        perceptual = Issue(
            id="perceptual",
            type="melisma_unreviewed",
            severity="medium",
            perceptual_impact=0.9,
            confidence=0.5,
            priority_score=0.0,
            start_s=10,
            end_s=14,
            affected_ids=["b"],
            suggested_action="review_melisma_segments",
        )

        ordered = prioritize_issues([technical, perceptual])

        self.assertEqual([issue.id for issue in ordered], ["perceptual", "technical"])
        self.assertGreater(ordered[0].priority_score, ordered[1].priority_score)

    def test_quality_status_uses_ready_review_and_needs_fix_thresholds(self):
        self.assertEqual(quality_status(score=0.96, critical_open_issues=0), "ready")
        self.assertEqual(quality_status(score=0.90, critical_open_issues=0), "review_suggested")
        self.assertEqual(quality_status(score=0.90, critical_open_issues=1), "needs_fix")
        self.assertEqual(quality_status(score=0.70, critical_open_issues=0), "needs_fix")


if __name__ == "__main__":
    unittest.main()
