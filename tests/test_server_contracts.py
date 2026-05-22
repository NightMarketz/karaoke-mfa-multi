import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
