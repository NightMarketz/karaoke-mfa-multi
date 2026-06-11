from __future__ import annotations

import sys
import tempfile
import types
import unittest
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.common.observability import read_events
from scripts import s03b_lyrics_align


class LyricsAlignmentObservabilityTests(unittest.TestCase):
    def _close_logging(self) -> None:
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            if isinstance(handler, logging.FileHandler):
                handler.close()

    def _run_main(self, job_dir: Path, lyrics_path: Path, *extra_args: str) -> int:
        self._close_logging()
        argv = [
            "s03b_lyrics_align.py",
            "--job-dir",
            str(job_dir),
            "--lyrics",
            str(lyrics_path),
            "--no-pitch",
            *extra_args,
        ]
        with patch.object(sys, "argv", argv):
            try:
                return s03b_lyrics_align.main()
            finally:
                self._close_logging()

    def test_successful_forced_alignment_emits_structured_events(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            job_dir = Path(tmp) / "job-stage03b"
            job_dir.mkdir()
            (job_dir / "vocals.wav").write_bytes(b"fake audio")
            lyrics_path = job_dir / "lyrics.txt"
            lyrics_path.write_text(
                "[Verse]\n"
                "Hello world\n"
                "[Mystery Part]\n"
                "[Heavy wall of sound]\n"
                "Still here\n",
                encoding="utf-8",
            )

            fake_model = SimpleNamespace(dtype="float32", device="cpu")
            fake_ctc = types.SimpleNamespace(
                load_audio=lambda *_args, **_kwargs: "audio",
                load_alignment_model=lambda *_args, **_kwargs: (fake_model, "tokenizer"),
                generate_emissions=lambda *_args, **_kwargs: ("emissions", 0.02),
                preprocess_text=lambda *_args, **_kwargs: (["tokens"], "hello world still here"),
                get_alignments=lambda *_args, **_kwargs: ("segments", "scores", "<blank>"),
                get_spans=lambda *_args, **_kwargs: "spans",
                postprocess_results=lambda *_args, **_kwargs: [
                    {"start": 0.1, "end": 0.4, "score": 0.98},
                    {"start": 0.5, "end": 0.8, "score": 0.97},
                    {"start": 1.0, "end": 1.3, "score": 0.96},
                    {"start": 1.4, "end": 1.8, "score": 0.95},
                ],
            )
            fake_torch = types.SimpleNamespace(float32="float32")
            fake_hw = SimpleNamespace()

            with patch.dict(sys.modules, {"ctc_forced_aligner": fake_ctc, "torch": fake_torch}):
                with patch.object(s03b_lyrics_align, "detect", return_value=fake_hw):
                    rc = self._run_main(job_dir, lyrics_path)

            self.assertEqual(rc, 0)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertIn("stage03b.started", names)
            self.assertIn("stage03b.lyrics_reference_loaded", names)
            self.assertIn("stage03b.forced_alignment_text_built", names)
            self.assertIn("stage03b.alignment_path_selected", names)
            self.assertIn("stage03b.correction_path_selected", names)
            self.assertIn("stage03b.transcript_written", names)
            self.assertIn("stage03b.completed", names)

            loaded = next(event for event in events if event["event"] == "stage03b.lyrics_reference_loaded")
            self.assertEqual(loaded["details"]["line_count"], 2)
            self.assertEqual(loaded["details"]["section_count"], 2)
            self.assertEqual(loaded["details"]["unknown_marker_count"], 1)
            self.assertEqual(loaded["details"]["stage_direction_stripped_count"], 1)

            written = next(event for event in events if event["event"] == "stage03b.transcript_written")
            self.assertEqual(written["details"]["segment_count"], 2)
            self.assertEqual(written["details"]["word_count"], 4)
            self.assertEqual(written["details"]["section_count"], 2)
            self.assertEqual(written["details"]["unknown_marker_count"], 1)

    def test_missing_lyrics_emits_failed_event(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            job_dir = Path(tmp) / "job-stage03b-missing"
            job_dir.mkdir()
            (job_dir / "vocals.wav").write_bytes(b"fake audio")
            missing_lyrics = job_dir / "missing.txt"

            with patch.object(s03b_lyrics_align, "detect", return_value=SimpleNamespace()):
                rc = self._run_main(job_dir, missing_lyrics)

            self.assertEqual(rc, 1)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertIn("stage03b.input_missing", names)
            self.assertIn("stage03b.failed", names)
            failed = [event for event in events if event["event"] == "stage03b.failed"][-1]
            self.assertEqual(failed["level"], "error")

    def test_missing_job_dir_records_global_failure_without_creating_job(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            job_dir = Path(tmp) / "missing-job"
            missing_lyrics = Path(tmp) / "lyrics.txt"
            missing_lyrics.write_text("[Verse]\nHello", encoding="utf-8")

            with patch.object(s03b_lyrics_align, "detect", return_value=SimpleNamespace()):
                rc = self._run_main(job_dir, missing_lyrics)

            self.assertEqual(rc, 1)
            self.assertFalse(job_dir.exists())
            events = read_events(job_dir.parent / "_stage03b")
            self.assertTrue(
                any(
                    event["event"] == "stage03b.failed"
                    and event["details"].get("reason") == "job_dir_missing"
                    and event["details"].get("missing_job_dir") == str(job_dir)
                    for event in events
                )
            )


if __name__ == "__main__":
    unittest.main()
