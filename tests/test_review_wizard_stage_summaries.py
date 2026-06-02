import json
import tempfile
import unittest
from pathlib import Path

from scripts.review_wizard.contracts import (
    Issue,
    LyricLine,
    PreparedText,
    Project,
    TextSection,
    Word,
)
from scripts.review_wizard.review_points import ReviewPoint
from scripts.review_wizard.stage_summaries import build_stage_summaries


class ReviewWizardStageSummariesTests(unittest.TestCase):
    def test_builds_summaries_for_all_review_wizard_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "meta.json").write_text(json.dumps({"duration_s": 123.4}), encoding="utf-8")
            for name in ("vocals.wav", "output.mp4", "lyrics.txt"):
                (job_dir / name).write_bytes(b"x")

            prepared_text = PreparedText(
                language="pt",
                sections=[
                    TextSection(
                        id="section-1",
                        label="Verse",
                        lines=[
                            LyricLine(
                                id="line-1",
                                section="Verse",
                                text="Coracao aberto",
                                words=[
                                    Word(id="word-1", text="Coracao"),
                                    Word(id="word-2", text="aberto"),
                                ],
                            ),
                            LyricLine(
                                id="line-2",
                                section="Verse",
                                text="Sem medo",
                                words=[Word(id="word-3", text="Sem"), Word(id="word-4", text="medo")],
                            ),
                        ],
                    )
                ],
            )
            project = Project.new(project_id="proj-1", job_id="abc123def456")
            project = Project(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "issues": [
                        Issue(
                            id="issue-1",
                            type="timing",
                            severity="critical",
                            perceptual_impact=1.0,
                            confidence=0.9,
                            priority_score=0.95,
                            start_s=1.0,
                            end_s=2.0,
                            affected_ids=["line-1"],
                            suggested_action="review",
                        ),
                        Issue(
                            id="issue-2",
                            type="gap",
                            severity="high",
                            perceptual_impact=0.8,
                            confidence=0.8,
                            priority_score=0.75,
                            start_s=3.0,
                            end_s=4.0,
                            affected_ids=["line-2"],
                            suggested_action="review",
                        ),
                        Issue(
                            id="issue-3",
                            type="minor",
                            severity="low",
                            perceptual_impact=0.2,
                            confidence=0.5,
                            priority_score=0.2,
                            start_s=5.0,
                            end_s=6.0,
                            affected_ids=["line-3"],
                            suggested_action="ignore",
                            status="resolved",
                        ),
                    ],
                }
            )
            review_points = [
                ReviewPoint(
                    id="point-1",
                    stage_id="alignment",
                    level="line",
                    text="Coracao aberto",
                    start_s=1.0,
                    end_s=2.0,
                    status="approved",
                ),
                ReviewPoint(
                    id="point-2",
                    stage_id="alignment",
                    level="word",
                    text="Sem",
                    start_s=3.0,
                    end_s=3.4,
                    status="open",
                ),
                ReviewPoint(
                    id="point-3",
                    stage_id="quality",
                    level="issue",
                    text="gap",
                    start_s=3.0,
                    end_s=4.0,
                    status="skipped_with_risk",
                ),
            ]

            summaries = build_stage_summaries(job_dir, project, review_points)

        self.assertEqual(
            list(summaries.keys()),
            ["import", "lyrics", "alignment", "quality", "preview", "export"],
        )
        self.assertEqual(summaries["import"]["duration_s"], 123.4)
        self.assertTrue(summaries["import"]["assets"]["vocals.wav"])
        self.assertFalse(summaries["import"]["assets"]["instrumental.wav"])
        self.assertFalse(summaries["import"]["assets"]["output.ass"])
        self.assertEqual(summaries["lyrics"]["sections"], 1)
        self.assertEqual(summaries["lyrics"]["lines"], 2)
        self.assertEqual(summaries["lyrics"]["words"], 4)
        self.assertEqual(summaries["alignment"]["total"], 2)
        self.assertEqual(summaries["alignment"]["open"], 1)
        self.assertEqual(summaries["alignment"]["reviewed"], 1)
        self.assertEqual(summaries["quality"]["open_issues"], 2)
        self.assertEqual(summaries["quality"]["critical"], 1)
        self.assertEqual(summaries["quality"]["high"], 1)
        self.assertFalse(summaries["preview"]["has_full_preview"])
        self.assertEqual(summaries["export"]["total"], 3)
        self.assertEqual(summaries["export"]["pending"], 1)
        self.assertEqual(summaries["export"]["risk_accepted"], 1)


if __name__ == "__main__":
    unittest.main()
