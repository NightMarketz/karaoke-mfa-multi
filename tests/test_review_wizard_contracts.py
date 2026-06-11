import json
import tempfile
import unittest
from pathlib import Path

from scripts.review_wizard.contracts import (
    AlignmentTake,
    EditOperation,
    HighlightSegment,
    Issue,
    LyricLine,
    MediaAsset,
    MelismaSegment,
    PreparedText,
    Project,
    QualityReport,
    Syllable,
    TextSection,
    Word,
)
from scripts.review_wizard.store import load_project, project_path, save_project


class ReviewWizardContractTests(unittest.TestCase):
    def test_project_contract_contains_gold_standard_top_level_keys(self):
        project = Project.new(project_id="proj-1", job_id="abc123def456")

        payload = project.to_dict()

        self.assertEqual(payload["project_id"], "proj-1")
        self.assertEqual(payload["job_id"], "abc123def456")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["media_assets"], [])
        self.assertEqual(payload["alignment_takes"], [])
        self.assertEqual(payload["edit_operations"], [])
        self.assertEqual(payload["issues"], [])
        self.assertEqual(payload["quality_reports"], [])
        self.assertEqual(payload["preview_renders"], [])
        self.assertIsNone(payload["approved_take_id"])
        self.assertEqual(payload["style_preset_id"], "default")
        self.assertEqual(payload["style_overrides"], {})

    def test_hierarchical_text_serializes_line_word_syllable_melisma(self):
        syllable = Syllable(
            id="syll-1",
            text="mor",
            start_s=1.2,
            end_s=2.4,
            confidence=0.91,
            melisma_segments=[
                MelismaSegment(id="mel-1", start_s=1.2, end_s=1.7, kind="note"),
                MelismaSegment(id="mel-2", start_s=1.7, end_s=2.4, kind="note"),
            ],
        )
        word = Word(id="word-1", text="amor", syllables=[syllable])
        line = LyricLine(id="line-1", text="amor", section="chorus", words=[word])
        section = TextSection(id="sec-1", label="Chorus", lines=[line])
        prepared = PreparedText(language="pt", sections=[section])

        payload = prepared.to_dict()

        self.assertEqual(payload["sections"][0]["lines"][0]["words"][0]["syllables"][0]["text"], "mor")
        self.assertEqual(
            len(payload["sections"][0]["lines"][0]["words"][0]["syllables"][0]["melisma_segments"]),
            2,
        )

    def test_word_serializes_highlight_velocity_segments(self):
        word = Word(
            id="word-1",
            text="snap",
            start_s=275.42,
            end_s=282.02,
            highlight_segments=[
                HighlightSegment(
                    id="word-1:hv-1",
                    text="sn",
                    start_s=275.42,
                    end_s=275.54,
                    role="consonant_attack",
                ),
                HighlightSegment(
                    id="word-1:hv-2",
                    text="a",
                    start_s=275.54,
                    end_s=281.86,
                    role="sustained_vowel",
                ),
            ],
        )

        payload = word.to_dict()

        self.assertEqual(payload["highlight_segments"][0]["text"], "sn")
        self.assertEqual(payload["highlight_segments"][1]["role"], "sustained_vowel")

    def test_issue_quality_and_take_contracts_are_traceable(self):
        issue = Issue(
            id="issue-1",
            type="melisma_unreviewed",
            severity="high",
            perceptual_impact=0.91,
            confidence=0.62,
            priority_score=0.88,
            start_s=12.0,
            end_s=14.0,
            affected_ids=["syll-1"],
            suggested_action="review_melisma_segments",
        )
        take = AlignmentTake(
            id="take-1",
            kind="conservative",
            status="needs_review",
            line_ids=["line-1"],
        )
        report = QualityReport(
            id="report-1",
            take_id="take-1",
            status="needs_fix",
            score=0.72,
            issue_ids=["issue-1"],
        )
        op = EditOperation(
            id="op-1",
            operation="move_syllable_boundary",
            target_id="syll-1",
            created_by="user",
            details={"from": 12.34, "to": 12.372, "snap_source": "vocal_onset"},
        )
        media = MediaAsset(id="asset-1", kind="vocal", path="vocals.wav")

        self.assertEqual(issue.to_dict()["suggested_action"], "review_melisma_segments")
        self.assertEqual(take.to_dict()["kind"], "conservative")
        self.assertEqual(report.to_dict()["status"], "needs_fix")
        self.assertEqual(op.to_dict()["details"]["snap_source"], "vocal_onset")
        self.assertEqual(media.to_dict()["kind"], "vocal")

    def test_project_store_round_trips_review_wizard_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            project = Project.new(project_id="proj-1", job_id="abc123def456")

            save_project(job_dir, project)
            loaded = load_project(job_dir)

            self.assertEqual(project_path(job_dir).name, "review_wizard.json")
            self.assertEqual(loaded.project_id, "proj-1")
            self.assertEqual(loaded.job_id, "abc123def456")
            raw = json.loads(project_path(job_dir).read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
