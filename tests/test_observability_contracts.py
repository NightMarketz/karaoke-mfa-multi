import json
import tempfile
import unittest
from pathlib import Path

from scripts.common.observability import (
    StageTimer,
    build_observability_summary,
    record_artifact,
    read_events,
    write_event,
)


class ObservabilityContractTests(unittest.TestCase):
    def test_write_event_appends_valid_jsonl_with_job_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "meta.json").write_text(
                '{"job_id":"abc123def456","song_name":"x","preset":"section-coded","created_at":1,"duration_s":1,"has_lyrics":true,"source":"zip"}',
                encoding="utf-8",
            )

            write_event(job_dir, "job_created", "preparing", message="created")
            write_event(job_dir, "stage_started", "aligning", details={"cmd": "s04"})

            lines = (job_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            events = [json.loads(line) for line in lines]
            self.assertEqual(events[0]["job_id"], "abc123def456")
            self.assertEqual(events[0]["event"], "job_created")
            self.assertEqual(events[1]["details"]["cmd"], "s04")

    def test_stage_timer_records_start_and_finish_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            with StageTimer(job_dir, "validating"):
                pass

            events = read_events(job_dir)
            self.assertEqual([event["event"] for event in events], ["stage_started", "stage_finished"])
            self.assertEqual(events[1]["stage"], "validating")
            self.assertGreaterEqual(events[1]["duration_ms"], 0)

    def test_stage_timer_records_failure_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            with self.assertRaises(ValueError):
                with StageTimer(job_dir, "analyzing"):
                    raise ValueError("bad analysis")

            failed = read_events(job_dir)[-1]
            self.assertEqual(failed["event"], "stage_failed")
            self.assertEqual(failed["level"], "error")
            self.assertIn("bad analysis", failed["message"])

    def test_record_artifact_and_summary_group_failures_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            ass_path = job_dir / "output.ass"
            ass_path.write_text("[Events]", encoding="utf-8")

            record_artifact(job_dir, "generating", ass_path)
            record_artifact(job_dir, "rendering", job_dir / "missing.mp4", required=False)
            write_event(job_dir, "validation_failed", "validating", level="error", message="overlap")

            summary = build_observability_summary(job_dir)

            self.assertEqual(summary["total_events"], 3)
            self.assertEqual(summary["artifacts"]["output.ass"]["exists"], True)
            self.assertTrue(any(item["message"] == "overlap" for item in summary["failures"]))
            self.assertTrue((job_dir / "observability_summary.json").exists())

    def test_summary_records_stage_command_durations(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            write_event(job_dir, "stage_command_finished", "rendering", duration_ms=123)

            summary = build_observability_summary(job_dir)

            self.assertEqual(summary["stage_durations_ms"]["rendering"], 123)


if __name__ == "__main__":
    unittest.main()
