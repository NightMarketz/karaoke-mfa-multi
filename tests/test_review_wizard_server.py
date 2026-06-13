import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._optional_imports import import_or_skip

import_or_skip("flask")
import server
from scripts.common.provenance import file_sha256, write_manifest
from scripts.review_wizard.contracts import EditOperation, Issue, Project, QualityReport
from scripts.review_wizard.store import load_project
from scripts.review_wizard.store import save_project
from scripts.review_wizard.text_prep import prepare_text_for_review


def _write_job(job_dir: Path, job_id: str, lyrics: str = "[Verse]\nCoracao aberto") -> None:
    job_dir.mkdir()
    (job_dir / "meta.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "song_name": "Review Song",
                "preset": "section-coded",
                "created_at": 1,
                "duration_s": 12.0,
                "has_lyrics": True,
                "source": "zip",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "status.json").write_text(
        json.dumps({"stage": "done", "progress": 100, "error": "", "updated_at": 1}),
        encoding="utf-8",
    )
    (job_dir / "lyrics.txt").write_text(lyrics, encoding="utf-8")


def _write_valid_artifact_graph(
    job_dir: Path,
    *,
    ass_text: str = "[Script Info]\n[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Verse,,0,0,0,,{\\kf100}A\n",
    mp4_bytes: bytes = b"video-v1",
) -> None:
    analysis_path = job_dir / "analysis.json"
    analysis_path.write_text(
        json.dumps({"lines": [{"text": "A", "start": 1.0, "end": 2.0, "words": []}]}),
        encoding="utf-8",
    )
    ass_path = job_dir / "output.ass"
    ass_path.write_text(ass_text, encoding="utf-8")
    write_manifest(
        job_dir / "output.ass.manifest.json",
        {
            "stage": "stage06",
            "run_id": "run-test",
            "preset": "section-coded",
            "renderer_mode": "single_layer_kf",
            "inputs": {
                "analysis.json": {
                    "path": "analysis.json",
                    "sha256": file_sha256(analysis_path),
                }
            },
            "outputs": {"output.ass": {"path": "output.ass"}},
            "metrics": {
                "analysis_line_count": 1,
                "dialogue_count": ass_text.count("\nDialogue:"),
                "kf_count": ass_text.count("\\kf"),
            },
        },
        output_paths={"output.ass": ass_path},
    )
    mp4_path = job_dir / "output.mp4"
    mp4_path.write_bytes(mp4_bytes)
    write_manifest(
        job_dir / "output.mp4.manifest.json",
        {
            "stage": "stage07",
            "inputs": {
                "output.ass": {
                    "path": "output.ass",
                    "sha256": file_sha256(ass_path),
                    "manifest": "output.ass.manifest.json",
                    "manifest_sha256": file_sha256(job_dir / "output.ass.manifest.json"),
                }
            },
            "outputs": {"output.mp4": {"path": "output.mp4"}},
        },
        output_paths={"output.mp4": mp4_path},
    )


def _write_audio_timing_review_job(job_dir: Path, job_id: str) -> None:
    _write_job(job_dir, job_id, "[PreChorus]\nPast the fear")
    (job_dir / "analysis.json").write_text(
        json.dumps(
            {
                "lines": [
                    {
                        "text": "Past the fear",
                        "start": 160.14,
                        "end": 166.48,
                        "words": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "output.ass.manifest.json").write_text(
        json.dumps(
            {
                "timing_audio_layers": {
                    "diagnostics": [
                        {
                            "line_index": 0,
                            "tail_classification": "probable_unwritten_vowel_extension",
                            "confidence": "high",
                            "structural_tail_classification": "instrumental_pause",
                            "review_flags": ["structural_pause_overridden_by_audio_tail"],
                            "audio_evidence": {
                                "start_s": 161.24,
                                "end_s": 166.48,
                                "duration_s": 5.24,
                                "voiced_ratio": 1.0,
                            },
                            "sound_suggestion": {
                                "sound_type": "sustained_final_vowel",
                                "suggested_caption": "fear...",
                                "suggested_user_action": "extend_final_vowel",
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    prepared_text, _ = prepare_text_for_review("Past the fear", language="en")
    save_project(
        job_dir,
        Project(
            project_id=f"review-{job_id}",
            job_id=job_id,
            prepared_text=prepared_text,
        ),
    )


class ReviewWizardServerTests(unittest.TestCase):
    def test_job_detail_links_to_review_wizard(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            _write_job(jobs_dir / job_id, job_id)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}")

        html = response.get_data(as_text=True)
        self.assertIn(f"/job/{job_id}/review", html)
        self.assertIn("REVIEW WIZARD", html)

    def test_review_wizard_route_bootstraps_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "[Verse]\nCoracao aberto")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=lyrics")

            project = load_project(job_dir)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(project.job_id, job_id)
        self.assertEqual(project.prepared_text.language, "pt")
        self.assertIn("lyrics-script-board", response.get_data(as_text=True))

    def test_review_wizard_accepts_stage_and_point_query_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "Running on fumes")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "Running on fumes",
                                "start": 40.46,
                                "end": 42.9,
                                "words": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review?stage=alignment&point=line-1"
                )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-active-stage="alignment"', html)
        self.assertIn('data-active-point-id="line-1"', html)
        self.assertIn("40.46", html)
        self.assertIn("42.9", html)

    def test_review_point_approval_route_advances_to_next_open_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A\nB")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {"text": "A", "start": 1.0, "end": 2.0, "words": []},
                            {"text": "B", "start": 3.0, "end": 4.0, "words": []},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                client.get(f"/job/{job_id}/review")
                response = client.post(f"/job/{job_id}/review/points/line-1/approve")

        self.assertEqual(response.status_code, 302)
        self.assertIn("point=line-2", response.headers["Location"])

    def test_review_wizard_alignment_stage_renders_point_navigation_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B\nC")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "A B",
                                "start": 1.0,
                                "end": 2.0,
                                "words": [
                                    {"word": "A", "start": 1.0, "end": 1.3},
                                    {"word": "B", "start": 1.4, "end": 2.0},
                                ],
                            },
                            {"text": "C", "start": 3.0, "end": 4.0, "words": []},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review?stage=alignment&status=open&level=word&point=line-1:word-2"
                )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("POINT 2 OF 2", html)
        self.assertIn("Status", html)
        self.assertIn("To Review", html)
        self.assertIn("Unit", html)
        self.assertIn("Words", html)
        self.assertIn("PREVIOUS", html)
        self.assertIn("NEXT OPEN", html)
        self.assertIn("line-1%3Aword-1", html)
        self.assertNotIn("<strong>A B</strong>", html)

    def test_review_point_approval_preserves_filters_when_advancing(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "A B",
                                "start": 1.0,
                                "end": 2.0,
                                "words": [
                                    {"word": "A", "start": 1.0, "end": 1.3},
                                    {"word": "B", "start": 1.4, "end": 2.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                client.get(f"/job/{job_id}/review")
                response = client.post(
                    f"/job/{job_id}/review/points/line-1:word-1/approve",
                    data={"stage": "alignment", "status": "open", "level": "word"},
                )

        self.assertEqual(response.status_code, 302)
        self.assertIn("status=open", response.headers["Location"])
        self.assertIn("level=word", response.headers["Location"])
        self.assertIn("point=line-1:word-2", response.headers["Location"])

    def test_review_point_approval_advances_in_visible_queue_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A\nB")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {"text": "A", "start": 1.0, "end": 2.0, "words": []},
                            {"text": "B", "start": 3.0, "end": 4.0, "words": []},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            issue = Issue(
                id="issue-line-1",
                type="drift",
                severity="high",
                perceptual_impact=0.9,
                confidence=0.8,
                priority_score=0.95,
                start_s=1.0,
                end_s=2.0,
                affected_ids=["line-1"],
                suggested_action="review_alignment",
            )
            prepared_text, _ = prepare_text_for_review("A B", language="pt")
            project = Project(
                project_id=f"review-{job_id}",
                job_id=job_id,
                prepared_text=prepared_text,
                issues=[issue],
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/points/line-2/approve",
                    data={"stage": "alignment", "status": "open", "level": "line"},
                )

        self.assertEqual(response.status_code, 302)
        self.assertIn("point=line-1", response.headers["Location"])

    def test_review_wizard_renders_export_review_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A\nB")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {"text": "A", "start": 1.0, "end": 2.0, "words": []},
                            {"text": "B", "start": 3.0, "end": 4.0, "words": []},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                client.get(f"/job/{job_id}/review")
                client.post(f"/job/{job_id}/review/points/line-1/approve")
                response = client.get(f"/job/{job_id}/review?stage=export")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("EXPORT REVIEW SUMMARY", html)
        self.assertIn("REVIEWED", html)
        self.assertIn("PENDING", html)
        self.assertIn("RISK", html)
        self.assertNotIn('class="section export-review-summary"', html)
        self.assertIn('class="export-workspace"', html)

    def test_review_wizard_import_stage_renders_stage_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A")
            (job_dir / "vocals.wav").write_bytes(b"vocals")
            (job_dir / "instrumental.wav").write_bytes(b"instrumental")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=import")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("STAGE DETAILS", html)
        self.assertIn("IMPORT ASSETS", html)
        self.assertIn("vocals.wav", html)
        self.assertIn("instrumental.wav", html)

    def test_adaptive_review_studio_uses_compact_shell_without_overview_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=alignment")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('class="review-overview"', html)
        self.assertNotIn("review-overview-item", html)
        self.assertIn('class="review-command-bar cockpit-command-strip review-cockpit-command-strip"', html)
        self.assertIn("REVIEW WIZARD", html)
        self.assertIn("QUALITY", html)
        self.assertIn("EXPORT", html)
        self.assertIn("PREVIEW", html)

    def test_review_wizard_uses_cockpit_shell_design_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=alignment")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('<body class="cockpit-page review-cockpit-page">', html)
        self.assertIn('class="cockpit-shell review-cockpit-shell"', html)
        self.assertIn('class="cockpit-sidebar review-cockpit-sidebar"', html)
        self.assertIn('class="review-command-bar cockpit-command-strip review-cockpit-command-strip"', html)
        self.assertIn('class="cockpit-status-chips review-status-chips"', html)
        self.assertIn('class="cockpit-chip review-status-chip"', html)
        self.assertIn('class="review-cockpit-grid"', html)
        self.assertIn('class="cockpit-player review-cockpit-player"', html)
        self.assertIn(f"/?job={job_id}&amp;mode=review", html)

    def test_adaptive_review_studio_renders_dense_stage_tabs_with_active_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=alignment")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="review-stage-nav review-stage-tabs"', html)
        self.assertNotIn('role="tablist"', html)
        self.assertNotIn('role="tab"', html)
        self.assertIn('aria-current="page"', html)
        self.assertIn("review-stage-tab", html)

    def test_import_stage_hides_other_stage_panels(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=import")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Text Review", html)
        self.assertNotIn("QUALITY REVIEW", html)
        self.assertNotIn("EXPORT REVIEW SUMMARY", html)
        self.assertNotIn("PREVIEW APPROVAL", html)

    def test_review_wizard_non_point_stages_hide_point_filters_and_empty_point_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=preview")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("FILTER:", html)
        self.assertNotIn("LEVEL:", html)
        self.assertNotIn("No Active Review Point", html)
        self.assertNotIn("No timestamped review points for this stage yet.", html)
        self.assertIn("PREVIEW APPROVAL", html)

    def test_review_wizard_places_active_point_before_queue_in_dom_for_narrow_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "A B",
                                "start": 1.0,
                                "end": 2.0,
                                "words": [
                                    {"word": "A", "start": 1.0, "end": 1.3},
                                    {"word": "B", "start": 1.4, "end": 2.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review?stage=alignment&status=open&level=word"
                )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertLess(html.index('class="current-review-point'), html.index('class="review-point-queue'))
        self.assertIn('aria-label="Alignment workspace"', html)
        self.assertIn("POINT 1 OF", html)
        self.assertIn("PLAY LOOP", html)
        self.assertIn("APPROVE POINT", html)
        self.assertIn("SAVE TIMING", html)
        self.assertIn("SKIP WITH RISK", html)

    def test_review_wizard_alignment_stage_renders_operational_action_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "A B",
                                "start": 1.0,
                                "end": 2.0,
                                "words": [
                                    {"word": "A", "start": 1.0, "end": 1.3},
                                    {"word": "B", "start": 1.4, "end": 2.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review?stage=alignment&status=open&level=word"
                )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("ALIGNMENT ACTION QUEUE", html)
        self.assertIn("NEXT REVIEW", html)
        self.assertIn("2 OPEN WORDS", html)

    def test_review_wizard_alignment_stage_surfaces_next_action_without_hidden_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "A B",
                                "start": 1.0,
                                "end": 2.0,
                                "words": [
                                    {"word": "A", "start": 1.0, "end": 1.3},
                                    {"word": "B", "start": 1.4, "end": 2.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=alignment")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("OPEN POINTS", html)
        self.assertNotIn("OPEN ALLS", html)
        self.assertIn('class="review-next-action"', html)
        self.assertIn("NEXT DECISION", html)
        self.assertIn('<details class="sync-correction-details" aria-label="Timing and risk corrections" open>', html)
        self.assertIn('<details class="queue-window-details" open>', html)
        self.assertIn('class="form-input review-risk-reason"', html)
        self.assertIn("required", html)

    def test_lyrics_stage_renders_script_board_without_scroll_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "[Intro]\nA\nB\n[Verse]\nC\nD\n[Chorus]\nE\nF")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=lyrics&section=Verse")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="lyrics-script-board"', html)
        self.assertIn('class="lyrics-section-rail"', html)
        self.assertIn('class="lyrics-active-section"', html)
        self.assertNotIn("review-text-scroll", html)
        self.assertNotIn("Text Review", html)
        self.assertIn("Verse", html)
        self.assertIn("line-3", html)
        self.assertNotIn("line-5", html)

    def test_lyrics_stage_disambiguates_repeated_sections_and_guides_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "[Verse]\nA\n[Verse]\nB\n[Chorus]\nC")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=lyrics")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="lyrics-review-guidance"', html)
        self.assertIn("LYRICS AUDIT", html)
        self.assertIn("Verse 1", html)
        self.assertIn("Verse 2", html)
        self.assertIn("PREVIEW CHECK", html)

    def test_alignment_stage_renders_sync_cockpit_with_windowed_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, " ".join(f"w{i}" for i in range(1, 31)))
            words = [
                {"word": f"w{i}", "start": float(i), "end": float(i) + 0.3}
                for i in range(1, 31)
            ]
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": " ".join(f"w{i}" for i in range(1, 31)),
                                "start": 1.0,
                                "end": 32.0,
                                "words": words,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review?stage=alignment&status=open&level=word"
                )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("SYNC COCKPIT", html)
        self.assertIn("ISSUE MAP", html)
        self.assertIn("QUEUE WINDOW", html)
        self.assertIn("queue-window-details", html)
        self.assertIn("SHOWING 1-12 OF 30", html)
        self.assertLessEqual(html.count("review-point-link"), 12)
        self.assertNotIn("w30</strong>", html)

    def test_alignment_stage_windows_queue_around_requested_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, " ".join(f"w{i}" for i in range(1, 31)))
            words = [
                {"word": f"w{i}", "start": float(i), "end": float(i) + 0.3}
                for i in range(1, 31)
            ]
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": " ".join(f"w{i}" for i in range(1, 31)),
                                "start": 1.0,
                                "end": 32.0,
                                "words": words,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    "/job/abc123def456/review?stage=alignment&status=open&level=word&point=line-1%3Aword-25"
                )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("POINT 25 OF 30", html)
        self.assertIn("SHOWING 19-30 OF 30", html)
        self.assertIn("w25</strong>", html)
        self.assertNotIn("w1</strong>", html)

    def test_alignment_stage_uses_compact_stat_rail_and_preview_strip(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")
            (job_dir / "preview_full.mp4").write_bytes(b"video")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "A B",
                                "start": 1.0,
                                "end": 2.0,
                                "words": [
                                    {"word": "A", "start": 1.0, "end": 1.3},
                                    {"word": "B", "start": 1.4, "end": 2.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review?stage=alignment&status=open&level=word"
                )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="sync-stat-rail"', html)
        self.assertIn('class="sync-preview-strip"', html)
        self.assertIn('class="sync-correction-details"', html)
        self.assertIn('aria-label="Timing and risk corrections"', html)
        self.assertIn("CORRECTIONS", html)
        self.assertIn("GUIDED REVIEW", html)
        self.assertNotIn("sync-cockpit-summary", html)
        self.assertLess(html.index("review-point-nav"), html.index("sync-correction-details"))
        self.assertLess(html.index("data-play-loop"), html.index("sync-correction-details"))
        self.assertLess(html.index("APPROVE POINT"), html.index("sync-correction-details"))
        correction_panel = html[html.index("sync-correction-details") :]
        self.assertIn("timing-adjust-form", correction_panel)
        self.assertIn("risk-skip-form", correction_panel)
        self.assertIn('name="stage" value="alignment"', correction_panel)
        self.assertIn('name="status" value="open"', correction_panel)
        self.assertIn('name="level" value="word"', correction_panel)

    def test_alignment_stage_renders_read_only_audio_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "A B",
                                "start": 1.0,
                                "end": 2.0,
                                "words": [
                                    {"word": "A", "start": 1.0, "end": 1.3},
                                    {"word": "B", "start": 1.4, "end": 2.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review?stage=alignment&status=open&level=word"
                )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="audio-timeline"', html)
        self.assertIn("AUDIO TIMELINE", html)
        self.assertIn('class="audio-waveform"', html)
        self.assertIn('class="audio-active-region"', html)
        self.assertIn('class="audio-time-ruler"', html)
        self.assertIn('class="audio-playhead"', html)
        self.assertIn('class="audio-time-tick audio-time-tick-start"', html)
        self.assertIn('class="audio-time-tick audio-time-tick-end"', html)
        self.assertIn('data-time-s="0.0"', html)
        self.assertIn('data-time-s="12.0"', html)
        self.assertIn("ACTIVE WINDOW", html)
        self.assertIn("audio-marker-active", html)
        self.assertIn('class="audio-marker-lane audio-marker-lane-line"', html)
        self.assertIn('class="audio-marker-lane audio-marker-lane-word"', html)
        self.assertIn('class="audio-marker-lane audio-marker-lane-highlight"', html)
        self.assertIn('class="audio-marker-lane audio-marker-lane-issue"', html)
        self.assertIn('aria-label="LINE markers"', html)
        self.assertIn('aria-label="WORD markers"', html)
        self.assertIn('aria-label="HIGHLIGHT markers"', html)
        self.assertIn('aria-label="ISSUE markers"', html)
        self.assertIn('aria-label="Audio timeline overview"', html)
        self.assertIn(f"/job/{job_id}/review?stage=alignment&amp;status=all&amp;level=line&amp;point=line-1", html)

    def test_alignment_audio_timeline_renders_highlight_velocity_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "snap")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "snap",
                                "start": 1.0,
                                "end": 4.0,
                                "words": [
                                    {"word": "snap", "start": 1.0, "end": 4.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=alignment")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("audio-marker-highlight", html)
        self.assertIn('data-level="highlight"', html)
        self.assertIn('data-text="a"', html)
        self.assertIn('data-label="HIGHLIGHT"', html)

    def test_alignment_audio_timeline_marker_links_ignore_current_status_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "A B",
                                "start": 1.0,
                                "end": 2.0,
                                "words": [
                                    {"word": "A", "start": 1.0, "end": 1.3},
                                    {"word": "B", "start": 1.4, "end": 2.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            prepared_text, _ = prepare_text_for_review("A B", language="pt")
            project = Project(
                project_id=f"review-{job_id}",
                job_id=job_id,
                prepared_text=prepared_text,
                edit_operations=[
                    EditOperation(
                        id="edit-1",
                        operation="approve_review_point",
                        target_id="line-1",
                        created_by="tester",
                    )
                ],
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review?stage=alignment&status=open&level=word"
                )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/job/{job_id}/review?stage=alignment&amp;status=all&amp;level=line&amp;point=line-1", html)
        self.assertNotIn(f"/job/{job_id}/review?stage=alignment&status=open&level=line&point=line-1", html)

    def test_alignment_audio_timeline_renders_open_issues_as_issue_lane_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "A B",
                                "start": 1.0,
                                "end": 2.0,
                                "words": [
                                    {"word": "A", "start": 1.0, "end": 1.3},
                                    {"word": "B", "start": 1.4, "end": 2.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            issue = Issue(
                id="issue-timing-1",
                type="timing_precision",
                severity="critical",
                perceptual_impact=0.8,
                confidence=0.9,
                priority_score=0.95,
                start_s=1.2,
                end_s=1.6,
                affected_ids=["line-1:word-1"],
                suggested_action="adjust_word_timing",
            )
            prepared_text, _ = prepare_text_for_review("A B", language="pt")
            project = Project(
                project_id=f"review-{job_id}",
                job_id=job_id,
                prepared_text=prepared_text,
                issues=[issue],
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=alignment")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-point-id="issue:issue-timing-1"', html)
        self.assertIn("audio-marker-issue", html)
        self.assertIn("timing precision: adjust word timing", html)

    def test_alignment_audio_timeline_exposes_interactive_selection_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A B")
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "A B",
                                "start": 1.0,
                                "end": 2.0,
                                "words": [
                                    {"word": "A", "start": 1.0, "end": 1.3},
                                    {"word": "B", "start": 1.4, "end": 2.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review?stage=alignment&status=open&level=word&point=line-1%3Aword-2"
                )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-audio-timeline', html)
        self.assertIn('data-duration-s="12.0"', html)
        self.assertIn('data-selected-point-id="line-1:word-2"', html)
        self.assertIn('class="audio-selection-readout"', html)
        self.assertIn('data-audio-selection-readout', html)
        self.assertIn('data-audio-playhead', html)
        self.assertIn('data-audio-active-region', html)
        self.assertIn('data-timeline-marker', html)
        self.assertIn('data-level="word"', html)
        self.assertIn('aria-current="true"', html)
        self.assertIn('data-target-url="/job/abc123def456/review?stage=alignment&amp;status=all&amp;level=word&amp;point=line-1%3Aword-2"', html)
        self.assertIn('data-left-pct="11.667"', html)
        self.assertIn('data-width-pct="5.0"', html)
        self.assertIn("WORD B", html)

    def test_review_wizard_export_separates_technical_export_from_review_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A")
            _write_valid_artifact_graph(job_dir, mp4_bytes=b"mp4")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=export")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("TECHNICAL EXPORT", html)
        self.assertIn("REVIEW COMPLETION", html)
        self.assertIn("READY", html)
        self.assertIn("PENDING REVIEW", html)

    def test_review_wizard_export_not_ready_when_artifact_manifests_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "A")
            (job_dir / "output.mp4").write_bytes(b"mp4")
            (job_dir / "output.ass").write_text("[Script Info]\n", encoding="utf-8")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=export")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("TECHNICAL EXPORT", html)
        self.assertIn("MISSING ARTIFACTS", html)
        self.assertNotIn("TECHNICAL EXPORT</span>\n              <span class=\"tag tag-green\">READY", html)

    def test_review_wizard_lyrics_stage_renders_prepared_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "[Verse]\nA beautiful line")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=lyrics")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("LYRICS STRUCTURE", html)
        self.assertIn("SECTIONS", html)
        self.assertIn("LINES", html)
        self.assertIn("WORDS", html)

    def test_review_wizard_bootstraps_take_and_quality_from_pipeline_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, "[Verse]\nCoracao aberto")
            (job_dir / "transcript.json").write_text(
                json.dumps(
                    {
                        "alignment_mode": "forced",
                        "segments": [
                            {"text": "Coracao aberto", "start": 0.0, "end": 1.8},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "aligned.json").write_text(
                json.dumps(
                    {
                        "words": [
                            {"word": "Coracao", "start": 0.0, "end": 0.8, "source": "ctc_forced"},
                            {"word": "aberto", "start": 0.9, "end": 1.8, "source": "ctc_forced"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            {
                                "text": "Coracao aberto",
                                "start": 0.0,
                                "end": 1.8,
                                "style": "verse",
                                "words": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=quality")

            project = load_project(job_dir)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(project.evidence_bundle["alignment_mode"], "forced")
        self.assertEqual(project.evidence_bundle["word_count"], 2)
        self.assertEqual(project.alignment_takes[0].kind, "pipeline_artifact")
        self.assertEqual(project.quality_reports[0].status, "ready")
        html = response.get_data(as_text=True)
        self.assertIn("QUALITY REVIEW", html)
        self.assertIn("NO QUALITY ISSUES DETECTED", html)
        self.assertNotIn("OPEN TIMELINE", html)
        self.assertNotIn("FOCUSED ISSUE EDITOR", html)

    def test_review_wizard_renders_focused_issue_editor_before_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            long_line = " ".join(["palavra"] * 18)
            _write_job(jobs_dir / job_id, job_id, long_line)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=quality")

        html = response.get_data(as_text=True)
        self.assertIn("focused-issue-editor", html)
        self.assertIn(f"/job/{job_id}/review/issues/issue-long-line-1/approve-risk", html)
        self.assertIn(f"/job/{job_id}/review/issues/issue-long-line-1/apply-suggestion", html)
        self.assertIn('name="reason"', html)
        self.assertIn("OPEN TIMELINE", html)
        self.assertIn("APPROVE RISK", html)

    def test_approve_issue_risk_route_persists_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, " ".join(["palavra"] * 18))

            with patch.object(server, "JOBS_DIR", jobs_dir):
                server.app.test_client().get(f"/job/{job_id}/review")
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/issues/issue-long-line-1/approve-risk",
                    data={"reason": "Preview aprovado."},
                )

            project = load_project(job_dir)

        self.assertEqual(response.status_code, 302)
        self.assertIn("stage=quality", response.headers["Location"])
        self.assertEqual(project.issues[0].status, "risk_approved")
        self.assertEqual(project.edit_operations[0].operation, "approve_issue_risk")

    def test_apply_issue_suggestion_route_persists_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id, " ".join(["palavra"] * 18))

            with patch.object(server, "JOBS_DIR", jobs_dir):
                server.app.test_client().get(f"/job/{job_id}/review")
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/issues/issue-long-line-1/apply-suggestion",
                )

            project = load_project(job_dir)

        self.assertEqual(response.status_code, 302)
        self.assertIn("stage=quality", response.headers["Location"])
        self.assertEqual(project.issues[0].status, "suggestion_applied")
        self.assertEqual(project.edit_operations[0].operation, "apply_issue_suggestion")

    def test_review_wizard_renders_quality_report_and_prioritized_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            low_issue = Issue(
                id="issue-low",
                type="short_word_duration",
                severity="low",
                perceptual_impact=0.2,
                confidence=0.9,
                priority_score=0.18,
                start_s=2.0,
                end_s=2.2,
                affected_ids=["w-low"],
                suggested_action="check_short_word",
            )
            high_issue = Issue(
                id="issue-critical",
                type="melisma_unreviewed",
                severity="critical",
                perceptual_impact=0.95,
                confidence=0.6,
                priority_score=0.97,
                start_s=4.0,
                end_s=6.5,
                affected_ids=["w-critical"],
                suggested_action="review_melisma_segments",
            )
            report = QualityReport(
                id="qr-1",
                take_id="take-main",
                status="needs_fix",
                score=0.82,
                issue_ids=["issue-critical", "issue-low"],
            )
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "issues": [low_issue, high_issue],
                    "quality_reports": [report],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=quality")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("QUALITY REVIEW", html)
        self.assertIn("NEEDS_FIX", html)
        self.assertIn("0.82", html)
        self.assertLess(html.index("issue-critical"), html.index("issue-low"))
        focused = html.index("FOCUSED ISSUE EDITOR")
        self.assertLess(focused, html.rindex("OPEN TIMELINE"))

    def test_quality_stage_renders_audio_timing_sound_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_audio_timing_review_job(job_dir, job_id)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=quality")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("extend_final_vowel", html)
        self.assertIn(">U-SUS<", html)
        self.assertIn(">P-OVR<", html)
        self.assertIn(">SUS<", html)
        self.assertIn('title="Unwritten sustain"', html)
        self.assertIn('title="Pause override"', html)
        self.assertNotIn("probable unwritten vowel extension: fear...", html)
        self.assertNotIn("structural pause overridden by audio tail", html)
        self.assertNotIn("fear...", html)
        self.assertIn("audio 161.24-166.48s | voiced 1.00", html)
        self.assertIn("Source: timing_audio", html)
        self.assertIn(f"/job/{job_id}/review/points/timing-audio:line-1:1/apply-suggestion", html)
        self.assertIn("APPLY SUGGESTION", html)

    def test_alignment_timeline_uses_tags_for_audio_timing_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_audio_timing_review_job(job_dir, job_id)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=alignment")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("U-SUS", html)
        self.assertIn("P-OVR", html)
        self.assertIn("SUS", html)
        self.assertIn("Unwritten sustain", html)
        self.assertIn("Pause override", html)
        self.assertIn("data-tags-json=", html)
        self.assertNotIn("probable unwritten vowel extension: fear...", html)
        self.assertNotIn("structural pause overridden by audio tail", html)
        self.assertNotIn("fear...", html)

    def test_apply_review_point_suggestion_route_persists_audio_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_audio_timing_review_job(job_dir, job_id)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/points/timing-audio:line-1:1/apply-suggestion",
                    data={"stage": "quality", "status": "open", "level": "issue"},
                )

            project = load_project(job_dir)

        self.assertEqual(response.status_code, 302)
        self.assertIn("stage=quality", response.headers["Location"])
        self.assertEqual(project.edit_operations[0].operation, "apply_review_point_suggestion")
        self.assertEqual(project.edit_operations[0].target_id, "timing-audio:line-1:1")
        self.assertEqual(project.edit_operations[0].details["source"], "timing_audio")
        self.assertEqual(project.edit_operations[0].details["suggested_action"], "extend_final_vowel")

    def test_review_wizard_renders_issue_action_forms_with_expected_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            issue = Issue(
                id="issue-risk-1",
                type="melisma_unreviewed",
                severity="critical",
                perceptual_impact=0.95,
                confidence=0.6,
                priority_score=0.97,
                start_s=4.0,
                end_s=6.5,
                affected_ids=["w-critical"],
                suggested_action="review_melisma_segments",
            )
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "issues": [issue],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=quality")

        html = response.get_data(as_text=True)
        approve_action = f'action="/job/{job_id}/review/issues/issue-risk-1/approve-risk"'
        suggestion_action = f'action="/job/{job_id}/review/issues/issue-risk-1/apply-suggestion"'
        self.assertIn(approve_action, html)
        self.assertIn(suggestion_action, html)
        self.assertIn('method="post"', html)
        self.assertIn('name="reason"', html)
        self.assertIn('data-timeline-placeholder="true"', html)
        self.assertNotIn(f'action="/job/{job_id}/review/timeline"', html)

    def test_review_wizard_renders_preview_approval_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            report = QualityReport(
                id="qr-1",
                take_id="take-main",
                status="needs_fix",
                score=0.70,
                issue_ids=[],
            )
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [report],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=preview")

        html = response.get_data(as_text=True)
        self.assertIn("PREVIEW APPROVAL", html)
        self.assertIn("preview_required", html)
        self.assertIn(f"/job/{job_id}/review/preview/full/render", html)
        self.assertIn(f"/job/{job_id}/review/preview/critical-snippets/approve", html)
        self.assertIn(f"/job/{job_id}/review/preview/full/approve", html)
        self.assertNotIn('class="section preview-approval"', html)
        self.assertIn('class="preview-workspace"', html)

    def test_full_preview_render_route_materializes_separate_preview_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            _write_valid_artifact_graph(job_dir)
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.70)
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/preview/full/render"
                )

            project = load_project(job_dir)
            preview_bytes = (job_dir / "preview_full.mp4").read_bytes()

        self.assertEqual(response.status_code, 302)
        self.assertIn("stage=preview", response.headers["Location"])
        self.assertEqual(preview_bytes, b"video-v1")
        self.assertEqual(project.preview_renders[-1]["scope"], "full_preview")
        self.assertFalse(project.preview_renders[-1]["approved"])
        self.assertEqual(project.preview_renders[-1]["artifact_path"], "preview_full.mp4")

    def test_full_preview_render_refuses_stale_output_mp4_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            _write_valid_artifact_graph(job_dir)
            (job_dir / "output.mp4").write_bytes(b"video-v2")
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.70)
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/preview/full/render"
                )

        self.assertEqual(response.status_code, 400)
        self.assertIn("artifact_graph_invalid", response.get_data(as_text=True))
        self.assertFalse((job_dir / "preview_full.mp4").exists())

    def test_full_preview_artifact_can_be_played_from_review_wizard(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            _write_valid_artifact_graph(job_dir)
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.70)
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                client.post(f"/job/{job_id}/review/preview/full/render")
                page = client.get(f"/job/{job_id}/review?stage=preview")
                preview = client.get(f"/job/{job_id}/review/preview/full.mp4")
                preview_status = preview.status_code
                preview.close()

        html = page.get_data(as_text=True)
        self.assertEqual(preview_status, 200)
        self.assertIn(f"/job/{job_id}/review/preview/full.mp4", html)

    def test_preview_approval_routes_persist_reviewed_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            (job_dir / "output.mp4").write_bytes(b"video")
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.70)
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/preview/critical-snippets/approve"
                )

            project = load_project(job_dir)

        self.assertEqual(response.status_code, 302)
        self.assertIn("stage=preview", response.headers["Location"])
        self.assertEqual(project.preview_renders[0]["scope"], "critical_snippets")
        self.assertTrue(project.preview_renders[0]["approved"])
        self.assertEqual(project.preview_renders[0]["artifact_path"], "output.mp4")
        self.assertEqual(project.preview_renders[0]["artifact_size_bytes"], 5)
        self.assertEqual(len(project.preview_renders[0]["artifact_sha256"]), 64)
        self.assertEqual(project.preview_renders[0]["take_id"], "take-main")

    def test_preview_approval_requires_existing_preview_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.70)
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/preview/full/approve"
                )

            project = load_project(job_dir)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(project.preview_renders, [])

    def test_output_routes_block_when_mp4_manifest_is_missing_or_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            _write_valid_artifact_graph(job_dir)
            (job_dir / "output.mp4.manifest.json").unlink()

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                missing_manifest = client.get(f"/job/{job_id}/output.mp4")
                missing_manifest_status = missing_manifest.status_code
                missing_manifest_body = missing_manifest.get_data(as_text=True)
                missing_manifest.close()

            _write_valid_artifact_graph(job_dir)
            (job_dir / "output.mp4").write_bytes(b"video-v2")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                stale_mp4 = client.get(f"/job/{job_id}/output.mp4")
                stale_ass = client.get(f"/job/{job_id}/output.ass")
                stale_mp4_status = stale_mp4.status_code
                stale_mp4_body = stale_mp4.get_data(as_text=True)
                stale_ass_status = stale_ass.status_code
                stale_mp4.close()
                stale_ass.close()

        self.assertEqual(missing_manifest_status, 403)
        self.assertIn("artifact_graph_invalid", missing_manifest_body)
        self.assertEqual(stale_mp4_status, 403)
        self.assertEqual(stale_ass_status, 403)
        self.assertIn("artifact_graph_invalid", stale_mp4_body)

    def test_blocked_review_project_cannot_download_final_artifacts_until_full_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            _write_valid_artifact_graph(job_dir, mp4_bytes=b"video")
            (job_dir / "preview_full.mp4").write_bytes(b"video")
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.70)
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                blocked_mp4 = client.get(f"/job/{job_id}/output.mp4")
                blocked_ass = client.get(f"/job/{job_id}/output.ass")
                client.post(f"/job/{job_id}/review/preview/critical-snippets/approve")
                still_blocked = client.get(f"/job/{job_id}/output.ass")
                client.post(f"/job/{job_id}/review/preview/full/approve")
                allowed_ass = client.get(f"/job/{job_id}/output.ass")
                allowed_ass_status = allowed_ass.status_code
                allowed_ass.close()

        self.assertEqual(blocked_mp4.status_code, 403)
        self.assertEqual(blocked_ass.status_code, 403)
        self.assertEqual(still_blocked.status_code, 403)
        self.assertEqual(allowed_ass_status, 200)

    def test_download_blocks_if_preview_artifact_changes_after_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            _write_valid_artifact_graph(job_dir)
            (job_dir / "preview_full.mp4").write_bytes(b"video-v1")
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.70)
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                approval = client.post(f"/job/{job_id}/review/preview/full/approve")
                (job_dir / "output.mp4").write_bytes(b"video-v2")
                response = client.get(f"/job/{job_id}/output.ass")
                response_status = response.status_code
                response_body = response.get_data(as_text=True)
                response.close()

        self.assertEqual(approval.status_code, 302)
        self.assertEqual(response_status, 403)
        self.assertIn("artifact_changed", response_body)

    def test_download_blocks_if_ass_artifact_changes_after_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            _write_valid_artifact_graph(job_dir)
            (job_dir / "preview_full.mp4").write_bytes(b"video-v1")
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="needs_fix", score=0.70)
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                approval = client.post(f"/job/{job_id}/review/preview/full/approve")
                (job_dir / "output.ass").write_text("[Script Info]\nchanged\n", encoding="utf-8")
                response = client.get(f"/job/{job_id}/output.mp4")
                response_status = response.status_code
                response_body = response.get_data(as_text=True)
                response.close()

        self.assertEqual(approval.status_code, 302)
        self.assertEqual(response_status, 403)
        self.assertIn("artifact_changed", response_body)

    def test_real_struggle_fixture_records_export_bundle_evidence(self):
        fixture_dir = Path("jobs") / "real-struggle-20260522"
        if not (fixture_dir / "output.mp4").exists() or not (fixture_dir / "output.ass").exists():
            self.skipTest("real Struggle fixture with output.mp4/output.ass is not available")

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            for name in (
                "meta.json",
                "status.json",
                "lyrics.txt",
                "transcript.json",
                "aligned.json",
                "analysis.json",
                "output.mp4",
                "output.ass",
            ):
                shutil.copy2(fixture_dir / name, job_dir / name)
            analysis = json.loads((job_dir / "analysis.json").read_text(encoding="utf-8"))
            ass_text = (job_dir / "output.ass").read_text(encoding="utf-8-sig", errors="replace")
            write_manifest(
                job_dir / "output.ass.manifest.json",
                {
                    "stage": "stage06",
                    "run_id": "fixture",
                    "preset": "section-coded",
                    "renderer_mode": "single_layer_kf",
                    "inputs": {
                        "analysis.json": {
                            "path": "analysis.json",
                            "sha256": file_sha256(job_dir / "analysis.json"),
                        }
                    },
                    "outputs": {"output.ass": {"path": "output.ass"}},
                    "metrics": {
                        "analysis_line_count": len(analysis.get("lines", [])),
                        "dialogue_count": ass_text.count("\nDialogue:"),
                        "kf_count": ass_text.count("\\kf"),
                    },
                },
                output_paths={"output.ass": job_dir / "output.ass"},
            )
            write_manifest(
                job_dir / "output.mp4.manifest.json",
                {
                    "stage": "stage07",
                    "inputs": {
                        "output.ass": {
                            "path": "output.ass",
                            "sha256": file_sha256(job_dir / "output.ass"),
                            "manifest": "output.ass.manifest.json",
                            "manifest_sha256": file_sha256(job_dir / "output.ass.manifest.json"),
                        }
                    },
                    "outputs": {"output.mp4": {"path": "output.mp4"}},
                },
                output_paths={"output.mp4": job_dir / "output.mp4"},
            )
            meta = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
            meta["job_id"] = job_id
            (job_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                client.get(f"/job/{job_id}/review")
                render = client.post(f"/job/{job_id}/review/preview/full/render")
                response = client.post(f"/job/{job_id}/review/preview/full/approve")

            project = load_project(job_dir)
            latest = project.preview_renders[-1]

        self.assertEqual(response.status_code, 302)
        self.assertEqual(render.status_code, 302)
        self.assertEqual(latest["scope"], "full_preview")
        self.assertEqual(latest["artifact_path"], "preview_full.mp4")
        self.assertIn("preview_full.mp4", latest["artifact_fingerprints"])
        self.assertIn("output.mp4", latest["artifact_fingerprints"])
        self.assertIn("output.ass", latest["artifact_fingerprints"])
        self.assertEqual(len(latest["artifact_fingerprints"]["output.mp4"]["sha256"]), 64)
        self.assertEqual(len(latest["artifact_fingerprints"]["output.ass"]["sha256"]), 64)

    def test_review_wizard_renders_preview_approval_gate_for_needs_fix_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            issue = Issue(
                id="issue-preview-1",
                type="melisma_unreviewed",
                severity="critical",
                perceptual_impact=0.95,
                confidence=0.6,
                priority_score=0.97,
                start_s=4.0,
                end_s=6.5,
                affected_ids=["w-critical"],
                suggested_action="review_melisma_segments",
            )
            report = QualityReport(
                id="qr-1",
                take_id="take-main",
                status="needs_fix",
                score=0.72,
                issue_ids=["issue-preview-1"],
            )
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "issues": [issue],
                    "quality_reports": [report],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=preview")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("PREVIEW APPROVAL", html)
        self.assertIn("FINAL EXPORT", html)
        self.assertIn("BLOCKED", html)
        self.assertIn("preview_required", html)
        self.assertIn("APPROVE CRITICAL SNIPPETS PREVIEW", html)
        self.assertIn("APPROVE FULL PREVIEW", html)
        self.assertIn(
            f'action="/job/{job_id}/review/preview/critical-snippets/approve"',
            html,
        )
        self.assertIn(
            f'action="/job/{job_id}/review/preview/full/approve"',
            html,
        )
        self.assertIn('method="post"', html)

    def test_preview_stage_guides_publish_readiness_before_approvals(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_job(job_dir, job_id)
            _write_valid_artifact_graph(job_dir)
            prepared_text, _ = prepare_text_for_review("[Verse]\nCoracao aberto", language="pt")
            project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
            project = project.__class__(
                **{
                    **project.to_dict(),
                    "prepared_text": prepared_text,
                    "quality_reports": [
                        QualityReport(id="qr-1", take_id="take-main", status="pass", score=0.96)
                    ],
                }
            )
            save_project(job_dir, project)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=preview")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("TECHNICAL EXPORT", html)
        self.assertIn("PUBLISH REVIEW", html)
        self.assertIn("PUBLISH PENDING", html)
        self.assertIn('class="preview-media-placeholder"', html)
        self.assertIn('class="preview-approval-checklist"', html)
        self.assertRegex(
            html,
            r'(?s)<button[^>]*disabled[^>]*>\s*APPROVE CRITICAL SNIPPETS PREVIEW\s*</button>',
        )
        self.assertRegex(
            html,
            r'(?s)<button[^>]*disabled[^>]*>\s*APPROVE FULL PREVIEW\s*</button>',
        )

    def test_quality_stage_separates_report_issues_from_review_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            _write_audio_timing_review_job(job_dir, job_id)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review?stage=quality")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("REPORT ISSUES", html)
        self.assertIn("REVIEW DECISIONS", html)
        self.assertIn("REVIEW DECISIONS PENDING", html)
        self.assertIn("Audio Timing", html)
        self.assertIn("Extend Final Vowel", html)
        self.assertNotIn("NO QUALITY ISSUES DETECTED", html)


if __name__ == "__main__":
    unittest.main()
