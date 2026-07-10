import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests._optional_imports import import_or_skip

import_or_skip("flask")
import server
from scripts.common.observability import read_events


class ServerContractTests(unittest.TestCase):
    def test_extract_suno_zip_rejects_traversal_member(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as zf:
            zf.writestr("nested/../../vocals.wav", b"fake vocal")
            zf.writestr("instrumental.wav", b"fake instrumental")
        data.seek(0)

        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            vocals, instrumental = server._extract_suno_zip(data, job_dir)

            self.assertIsNone(vocals)
            self.assertIsNone(instrumental)
            self.assertFalse((job_dir / "stems" / "vocals.wav").exists())
            events = read_events(job_dir)
            self.assertTrue(any(event["event"] == "zip_member_rejected" for event in events))

    def test_delete_running_job_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text("{}", encoding="utf-8")

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.dict(
                server._running, {job_id: object()}, clear=True
            ):
                response = server.app.test_client().post(f"/job/{job_id}/delete")

            self.assertEqual(response.status_code, 409)
            self.assertTrue(job_dir.exists())
            events = read_events(job_dir)
            self.assertTrue(any(event["event"] == "running_job_deletion_blocked" for event in events))

    def test_new_job_records_lifecycle_events_before_thread_start(self):
        class DummyThread:
            job_dir = None

            def __init__(self, target, args, daemon):
                self.target = target
                self.args = args
                self.daemon = daemon
                self.started = False

            def start(self):
                events_at_start = read_events(self.job_dir)
                assert any(event["event"] == "pipeline_thread_queued" for event in events_at_start)
                self.started = True

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            DummyThread.job_dir = jobs_dir / job_id

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.object(
                server.uuid, "uuid4"
            ) as uuid4, patch.object(server, "_convert_to_wav", return_value=True), patch.object(
                server, "_get_wav_duration", return_value=12.3
            ), patch.object(server.threading, "Thread", DummyThread), patch.dict(
                server._running, {}, clear=True
            ):
                uuid4.return_value.hex = job_id
                response = server.app.test_client().post(
                    "/job/new",
                    data={
                        "lyrics_text": "[Verse]\nhello world",
                        "song_name": "Observed Song",
                        "preset": "section-coded",
                        "vocals": (io.BytesIO(b"voice"), "vocals.wav"),
                        "instrumental": (io.BytesIO(b"music"), "instrumental.wav"),
                    },
                    content_type="multipart/form-data",
                )

            self.assertEqual(response.status_code, 302)
            job_dir = jobs_dir / job_id
            meta = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["preset"], "section-coded")
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertIn("job_request_received", names)
            self.assertIn("individual_stems_received", names)
            self.assertIn("stem_conversion_finished", names)
            self.assertIn("meta_written", names)
            self.assertIn("status_initialized", names)
            self.assertIn("pipeline_thread_queued", names)

    def test_failed_upload_writes_durable_server_event_before_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.object(server.uuid, "uuid4") as uuid4:
                uuid4.return_value.hex = job_id
                response = server.app.test_client().post(
                    "/job/new",
                    data={
                        "lyrics_text": "[Verse]\nhello world",
                        "song_name": "Bad Upload",
                        "preset": "section-coded",
                    },
                    content_type="multipart/form-data",
                )

            self.assertEqual(response.status_code, 400)
            self.assertFalse((jobs_dir / job_id).exists())
            server_events = read_events(jobs_dir / "_server")
            self.assertTrue(
                any(
                    event["event"] == "individual_stems_missing"
                    and event["details"].get("job_id") == job_id
                    for event in server_events
                )
            )

    def test_delete_running_job_does_not_create_missing_job_dir_for_stale_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.dict(
                server._running, {job_id: object()}, clear=True
            ):
                response = server.app.test_client().post(f"/job/{job_id}/delete")

            self.assertEqual(response.status_code, 409)
            self.assertFalse((jobs_dir / job_id).exists())

    def test_list_jobs_skips_ids_that_detail_route_would_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            valid_job = jobs_dir / "abc123def456"
            invalid_job = jobs_dir / "manual-job"
            valid_job.mkdir()
            invalid_job.mkdir()
            (valid_job / "meta.json").write_text(
                json.dumps({"job_id": "abc123def456", "song_name": "Valid"}),
                encoding="utf-8",
            )
            (invalid_job / "meta.json").write_text(
                json.dumps({"job_id": "manual-job", "song_name": "Invalid"}),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                jobs = server._list_jobs()

            self.assertEqual(["abc123def456"], [job["job_id"] for job in jobs])

    def test_new_job_form_renders_style_library_presets(self):
        response = server.app.test_client().get("/job/new")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Aegisub Classic Blue", html)
        self.assertIn('value="aegisub-classic-blue"', html)
        self.assertIn("STYLE LIBRARY", html)

    def test_new_job_rejects_unknown_style_preset_before_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(
                    "/job/new",
                    data={
                        "lyrics_text": "[Verse]\nhello world",
                        "song_name": "Bad Preset",
                        "preset": "not-a-style",
                    },
                    content_type="multipart/form-data",
                )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["error"], "Unknown style preset: not-a-style")
            self.assertEqual([], list(jobs_dir.iterdir()))

    def test_job_events_api_returns_timeline_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
            (job_dir / "status.json").write_text(
                json.dumps({"stage": "failed", "progress": 0, "error": "boom"}),
                encoding="utf-8",
            )
            (job_dir / "events.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event": "stage_started",
                                "stage": "analyzing",
                                "level": "info",
                                "details": {
                                    "input": str(job_dir / "input.mp4"),
                                    "command": ["ffmpeg", "-i", str(job_dir / "input.mp4")],
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "event": "stage05.failed",
                                "stage": "analyzing",
                                "level": "error",
                                "details": {"missing_job_dir": str(job_dir)},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (job_dir / "observability_summary.json").write_text(
                json.dumps({"failures": [{"event": "stage05.failed"}], "warnings": []}),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/events")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["job_id"], job_id)
            self.assertEqual([event["event"] for event in payload["events"]], ["stage_started", "stage05.failed"])
            self.assertEqual(payload["events"][0]["details"]["input"], "input.mp4")
            self.assertEqual(payload["events"][0]["details"]["command"], "3 args redacted")
            self.assertEqual(payload["events"][1]["details"]["missing_job_dir"], job_id)
            self.assertEqual(payload["summary"]["failures"][0]["event"], "stage05.failed")


class ConcurrencyGuardTests(unittest.TestCase):
    def test_new_job_submit_returns_429_when_busy(self):
        from unittest.mock import MagicMock

        job_id = "aabbccddeeff"
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True

        # APP_CONFIG.max_concurrent_jobs defaults to 1; one live thread saturates it.
        with patch.dict(server._running, {job_id: mock_thread}, clear=True):
            response = server.app.test_client().post(
                "/job/new",
                data={},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 429)

    def test_new_job_form_shows_server_busy(self):
        from unittest.mock import MagicMock

        job_id = "aabbccddeeff"
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True

        # APP_CONFIG.max_concurrent_jobs defaults to 1; one live thread saturates it.
        with patch.dict(server._running, {job_id: mock_thread}, clear=True):
            response = server.app.test_client().get("/job/new")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SERVER BUSY", response.data)


class OrphanRecoveryTests(unittest.TestCase):
    def test_recover_orphan_in_running_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "aabbccddeeff"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text(
                json.dumps({"job_id": job_id}), encoding="utf-8"
            )
            (job_dir / "status.json").write_text(
                json.dumps({"stage": "running", "progress": 50, "error": ""}),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.dict(
                server._running, {}, clear=True
            ):
                server._recover_orphan_jobs()

            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["stage"], "failed")

    def test_recover_orphan_in_queued_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "aabbccddeeff"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text(
                json.dumps({"job_id": job_id}), encoding="utf-8"
            )
            (job_dir / "status.json").write_text(
                json.dumps({"stage": "queued", "progress": 0, "error": ""}),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.dict(
                server._running, {}, clear=True
            ):
                server._recover_orphan_jobs()

            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["stage"], "failed")

    def test_does_not_recover_done_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "aabbccddeeff"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text(
                json.dumps({"job_id": job_id}), encoding="utf-8"
            )
            (job_dir / "status.json").write_text(
                json.dumps({"stage": "done", "progress": 100, "error": ""}),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.dict(
                server._running, {}, clear=True
            ):
                server._recover_orphan_jobs()

            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["stage"], "done")


class RetryValidateTests(unittest.TestCase):
    def test_retry_validate_returns_409_if_job_running(self):
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "aabbccddeeff"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text(
                json.dumps({"job_id": job_id}), encoding="utf-8"
            )
            (job_dir / "status.json").write_text(
                json.dumps({"stage": "failed", "progress": 95, "error": ""}),
                encoding="utf-8",
            )

            mock_thread = MagicMock()
            mock_thread.is_alive.return_value = True

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.dict(
                server._running, {job_id: mock_thread}, clear=True
            ):
                response = server.app.test_client().post(f"/job/{job_id}/retry-validate")

        self.assertEqual(response.status_code, 409)

    def test_retry_validate_returns_409_if_wrong_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "aabbccddeeff"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text(
                json.dumps({"job_id": job_id}), encoding="utf-8"
            )
            (job_dir / "status.json").write_text(
                json.dumps({"stage": "failed", "progress": 50, "error": ""}),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.dict(
                server._running, {}, clear=True
            ):
                response = server.app.test_client().post(f"/job/{job_id}/retry-validate")

        self.assertEqual(response.status_code, 409)

    def test_retry_validate_returns_409_if_not_failed(self):
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "aabbccddeeff"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text(
                json.dumps({"job_id": job_id}), encoding="utf-8"
            )
            (job_dir / "status.json").write_text(
                json.dumps({"stage": "done", "progress": 100, "error": ""}),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.dict(
                server._running, {}, clear=True
            ):
                response = server.app.test_client().post(f"/job/{job_id}/retry-validate")

        self.assertEqual(response.status_code, 409)


class RouteContractTests(unittest.TestCase):
    @staticmethod
    def _write_job(job_dir: Path, job_id: str, *, stage: str = "done", progress: int = 100) -> None:
        job_dir.mkdir()
        (job_dir / "meta.json").write_text(
            json.dumps({"job_id": job_id, "song_name": "Test Song", "preset": "section-coded"}),
            encoding="utf-8",
        )
        (job_dir / "status.json").write_text(
            json.dumps({"stage": stage, "progress": progress, "error": "", "updated_at": 1}),
            encoding="utf-8",
        )

    def test_metrics_returns_404_when_reference_mapping_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            self._write_job(job_dir, job_id)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/metrics")

        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertEqual(payload["error"], "no reference data")

    def test_metrics_returns_drift_and_pipeline_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            self._write_job(job_dir, job_id)
            (job_dir / "reference_mapping.json").write_text(
                json.dumps({"lines": [{"reference_start_sec": 1.0, "annotation": "[Verse]"}]}),
                encoding="utf-8",
            )
            (job_dir / "transcript.json").write_text(
                json.dumps({"segments": [{"start": 1.2, "text": "hello"}]}),
                encoding="utf-8",
            )
            (job_dir / "alignment_windows.json").write_text(
                json.dumps(
                    {
                        "windows": [
                            {"block_id": "B001", "line_ids": ["L001"], "audio_start": 0.8, "audio_end": 1.8},
                            {"block_id": "B002", "line_ids": ["L002"], "audio_start": 2.0, "audio_end": 3.0},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "ctc_window_safety_report.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "total_windows": 2,
                            "safe_windows": 1,
                            "unsafe_windows": 1,
                            "long_gap_crossing_windows": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "syllable_alignment.json").write_text(
                json.dumps(
                    {
                        "syllables": [
                            {"source": "phone_projection", "confidence": 0.9},
                            {"source": "phone_projection", "confidence": 0.7},
                            {"source": "duration_interpolation_fallback", "confidence": 0.4},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.object(
                server, "_blocked_final_export_reason", return_value=None
            ):
                response = server.app.test_client().get(f"/job/{job_id}/metrics")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["matched"], 1)
        self.assertIn("p95", payload)
        pipeline = payload["pipeline_metrics"]
        self.assertEqual(pipeline["window_safety_rate"], 0.5)
        self.assertAlmostEqual(pipeline["syllable_projection_rate"], 2 / 3, places=4)
        self.assertEqual(pipeline["syllable_confidence_p50"], 0.7)
        self.assertEqual(pipeline["syllable_confidence_p05"], 0.43)
        self.assertAlmostEqual(pipeline["fallback_usage"], 1 / 3, places=4)
        self.assertEqual(pipeline["long_gap_crossings"], 1)
        self.assertTrue(pipeline["final_export_allowed"])
        self.assertIsNone(pipeline["final_export_block_reason"])

    def test_output_mp4_returns_403_when_output_artifacts_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            self._write_job(job_dir, job_id)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/output.mp4")

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"Export blocked", response.data)

    def test_output_ass_returns_403_when_output_artifacts_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            self._write_job(job_dir, job_id)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/output.ass")

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"Export blocked", response.data)

    def test_stream_returns_sse_content_type_and_done_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            self._write_job(job_dir, job_id, stage="done", progress=100)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/stream")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.content_type)
        self.assertIn(b"done", response.data)


class SyllableBoundaryEditTests(unittest.TestCase):
    @staticmethod
    def _write_job(job_dir: Path, job_id: str) -> None:
        job_dir.mkdir()
        (job_dir / "meta.json").write_text(
            json.dumps({"job_id": job_id, "song_name": "Edit", "preset": "section-coded"}),
            encoding="utf-8",
        )
        (job_dir / "analysis.json").write_text(
            json.dumps({
                "lines": [{
                    "id": "L001",
                    "text": "aah",
                    "words": [{
                        "id": "L001_W001", "word": "aah", "start": 10.0, "end": 11.6,
                        "syllables": [{"syllable_id": "L001_W001_S001", "text": "aah",
                                       "start": 10.0, "end": 11.6, "confidence": 0.5}],
                    }],
                }]
            }),
            encoding="utf-8",
        )
        (job_dir / "output.ass").write_text("[Events]\nDialogue: x {\\kf80}aah\n", encoding="utf-8")
        (job_dir / "output.mp4").write_bytes(b"fake mp4")

    def test_valid_edit_rewrites_segments_records_op_and_invalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            self._write_job(job_dir, job_id)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/syllables/boundary",
                    json={
                        "line_id": "L001",
                        "word_id": "L001_W001",
                        "segments": [
                            {"text": "aa", "start": 10.0, "end": 10.8},
                            {"text": "ah", "start": 10.8, "end": 11.6},
                        ],
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(len(payload["highlight_segments"]), 2)

            analysis = json.loads((job_dir / "analysis.json").read_text(encoding="utf-8"))
            word = analysis["lines"][0]["words"][0]
            self.assertEqual([s["text"] for s in word["highlight_segments"]], ["aa", "ah"])
            self.assertTrue(all(s["source"] == "manual" for s in word["highlight_segments"]))

            # Downstream outputs invalidated (no orphan render).
            self.assertFalse((job_dir / "output.mp4").exists())
            self.assertFalse((job_dir / "output.ass").exists())

            project = server.load_project(job_dir)
            self.assertTrue(
                any(op.operation == "edit_syllable_boundaries" for op in project.edit_operations)
            )
            events = read_events(job_dir)
            self.assertTrue(any(e["event"] == "syllable_boundary_edited" for e in events))

    def test_boundary_outside_word_span_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            self._write_job(job_dir, job_id)

            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().post(
                    f"/job/{job_id}/review/syllables/boundary",
                    json={
                        "line_id": "L001",
                        "word_id": "L001_W001",
                        "segments": [{"text": "aa", "start": 10.0, "end": 12.0}],  # past word end
                    },
                )

            self.assertEqual(response.status_code, 400)
            analysis = json.loads((job_dir / "analysis.json").read_text(encoding="utf-8"))
            self.assertNotIn("highlight_segments", analysis["lines"][0]["words"][0])
            # Nothing invalidated on rejection.
            self.assertTrue((job_dir / "output.mp4").exists())
            self.assertTrue((job_dir / "output.ass").exists())


class SyllableReviewEditorTests(unittest.TestCase):
    @staticmethod
    def _write_job(job_dir: Path, job_id: str) -> None:
        job_dir.mkdir()
        (job_dir / "meta.json").write_text(
            json.dumps({"job_id": job_id, "song_name": "Editor Song"}), encoding="utf-8"
        )
        (job_dir / "analysis.json").write_text(
            json.dumps({
                "lines": [{
                    "id": "L001", "text": "the beast",
                    "words": [
                        {"id": "L001_W001", "word": "the", "start": 1.0, "end": 1.4,
                         "syllables": [{"syllable_id": "s1", "text": "the", "karaoke_start": 1.0,
                                        "karaoke_end": 1.4, "confidence": 0.9}]},
                        {"id": "L001_W002", "word": "beast", "start": 1.5, "end": 2.3,
                         "syllables": [
                             {"syllable_id": "s2", "text": "be", "karaoke_start": 1.5,
                              "karaoke_end": 1.9, "confidence": 0.45},
                             {"syllable_id": "s3", "text": "ast", "karaoke_start": 1.9,
                              "karaoke_end": 2.3, "confidence": 0.8}]},
                    ],
                }]
            }),
            encoding="utf-8",
        )

    def test_pending_queue_lists_low_confidence_words_worst_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            self._write_job(jobs_dir / job_id, job_id)
            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review/syllables/pending"
                )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        # only "beast" (min conf 0.45) is below threshold; "the" (0.9) is not.
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["pending"][0]["word_text"], "beast")
        self.assertEqual(payload["pending"][0]["min_confidence"], 0.45)

    def test_pending_queue_excludes_manually_locked_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            self._write_job(job_dir, job_id)
            analysis = json.loads((job_dir / "analysis.json").read_text(encoding="utf-8"))
            analysis["lines"][0]["words"][1]["highlight_segments"] = [
                {"id": "m1", "text": "beast", "start": 1.5, "end": 2.3, "source": "manual"}
            ]
            (job_dir / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(
                    f"/job/{job_id}/review/syllables/pending"
                )
        self.assertEqual(response.get_json()["count"], 0)

    def test_editor_page_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            self._write_job(jobs_dir / job_id, job_id)
            with patch.object(server, "JOBS_DIR", jobs_dir):
                response = server.app.test_client().get(f"/job/{job_id}/review/syllables")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SYLLABLE REVIEW", response.data)

    def test_audio_and_peaks_routes(self):
        import shutil
        import wave

        tmp = tempfile.mkdtemp()
        try:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            self._write_job(job_dir, job_id)
            with wave.open(str(job_dir / "vocals.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\x00\x10" * 16000 * 3)  # 3s
            with patch.object(server, "JOBS_DIR", jobs_dir):
                client = server.app.test_client()
                audio = client.get(f"/job/{job_id}/audio/vocals")
                peaks = client.get(f"/job/{job_id}/audio/vocals/peaks?start=0.5&end=2.5&buckets=100")
                onsets = client.get(f"/job/{job_id}/audio/vocals/onsets?start=0.5&end=2.5")
                missing = client.get(f"/job/{job_id}/audio/bogus")

            self.assertEqual(audio.status_code, 200)
            self.assertEqual(audio.mimetype, "audio/wav")
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(peaks.status_code, 200)
            self.assertEqual(len(peaks.get_json()["buckets"]), 100)
            self.assertEqual(onsets.status_code, 200)
            onset_times = onsets.get_json()["onsets"]
            self.assertIsInstance(onset_times, list)
            # onsets stay inside the requested window and are sorted
            self.assertTrue(all(0.5 <= t <= 2.5 for t in onset_times))
            self.assertEqual(onset_times, sorted(onset_times))
            audio.close()  # release the send_file handle before cleanup (Windows)
            missing.close()
            peaks.close()
            onsets.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
