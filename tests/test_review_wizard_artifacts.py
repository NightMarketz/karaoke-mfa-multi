import json
import tempfile
import unittest
from pathlib import Path

from scripts.review_wizard.artifacts import (
    issues_from_artifact_summary,
    summarize_pipeline_artifacts,
    take_and_report_from_summary,
)


class ReviewWizardArtifactsTests(unittest.TestCase):
    def test_summarize_pipeline_artifacts_counts_existing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "transcript.json").write_text(
                json.dumps({"alignment_mode": "forced", "segments": [{"text": "hello"}]}),
                encoding="utf-8",
            )
            (job_dir / "aligned.json").write_text(
                json.dumps({"words": [{"word": "hello"}, {"word": "world"}]}),
                encoding="utf-8",
            )
            (job_dir / "analysis.json").write_text(
                json.dumps({"lines": [{"text": "hello world"}]}),
                encoding="utf-8",
            )

            summary = summarize_pipeline_artifacts(job_dir)

        self.assertEqual(summary["alignment_mode"], "forced")
        self.assertEqual(summary["word_count"], 2)
        self.assertEqual(summary["line_count"], 1)
        self.assertEqual(summary["segment_count"], 1)
        self.assertEqual(summary["line_ids"], ["line-1"])

    def test_low_confidence_syllable_opens_uncertain_issue_with_segment_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "transcript.json").write_text(
                json.dumps({"alignment_mode": "forced", "segments": [{"text": "coração"}]}),
                encoding="utf-8",
            )
            (job_dir / "aligned.json").write_text(
                json.dumps({"words": [{"word": "coração"}]}), encoding="utf-8"
            )
            (job_dir / "analysis.json").write_text(
                json.dumps({
                    "lines": [{
                        "id": "L001",
                        "text": "coração",
                        "words": [{
                            "id": "L001_W001",
                            "word": "coração",
                            "syllables": [
                                {"syllable_id": "L001_W001_S001", "text": "co",
                                 "start": 0.0, "end": 0.2, "confidence": 0.9},
                                {"syllable_id": "L001_W001_S002", "text": "ração",
                                 "start": 0.2, "end": 0.8, "confidence": 0.45},
                            ],
                        }],
                    }]
                }),
                encoding="utf-8",
            )

            summary = summarize_pipeline_artifacts(job_dir)
            issues = issues_from_artifact_summary(summary)

        uncertain = [issue for issue in issues if issue.type == "syllable_uncertain"]
        self.assertEqual(len(uncertain), 1)
        self.assertEqual(uncertain[0].affected_ids, ["L001_W001_S002"])
        self.assertEqual(uncertain[0].suggested_action, "review_syllable_boundaries")

    def test_missing_artifacts_create_review_issue_and_needs_fix_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = summarize_pipeline_artifacts(Path(tmp))

        issues = issues_from_artifact_summary(summary)
        take, report = take_and_report_from_summary(summary, issues)

        self.assertEqual(issues[0].type, "pipeline_artifacts_missing")
        self.assertEqual(take.status, "needs_fix")
        self.assertEqual(report.status, "needs_fix")
        self.assertEqual(report.issue_ids, ["issue-missing-pipeline-artifacts"])


if __name__ == "__main__":
    unittest.main()
