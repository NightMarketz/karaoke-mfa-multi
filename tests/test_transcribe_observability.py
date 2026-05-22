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
from scripts import s03_transcribe


class _FakeWord:
    def __init__(self, word: str, start: float, end: float, probability: float) -> None:
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class _FakeSegment:
    text = "hello world"
    start = 0.1
    end = 1.2
    words = [
        _FakeWord("hello", 0.1, 0.5, 0.95),
        _FakeWord("world", 0.6, 1.2, 0.91),
    ]


class TranscribeObservabilityTests(unittest.TestCase):
    def _close_logging(self) -> None:
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            if isinstance(handler, logging.FileHandler):
                handler.close()

    def _run_main(self, job_dir: Path, *extra_args: str) -> int:
        self._close_logging()
        argv = [
            "s03_transcribe.py",
            "--job-dir",
            str(job_dir),
            "--model-size",
            "tiny",
            *extra_args,
        ]
        with patch.object(sys, "argv", argv):
            try:
                return s03_transcribe.main()
            finally:
                self._close_logging()

    def test_successful_transcription_emits_structured_events(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            job_dir = Path(tmp) / "job-stage03"
            job_dir.mkdir()
            (job_dir / "vocals.wav").write_bytes(b"fake audio")

            model_instances = []

            class FakeWhisperModel:
                def __init__(self, model_size: str, device: str, compute_type: str) -> None:
                    self.model_size = model_size
                    self.device = device
                    self.compute_type = compute_type
                    model_instances.append(self)

                def transcribe(self, *_args, **_kwargs):
                    info = SimpleNamespace(language="en", language_probability=0.9876)
                    return [_FakeSegment()], info

            fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
            fake_hw = SimpleNamespace(
                transcribe_device="cpu",
                transcribe_compute="int8",
                transcribe_beam_size=1,
                transcribe_vad=False,
            )

            with patch.dict(sys.modules, {"faster_whisper": fake_module}):
                with patch.object(s03_transcribe, "detect", return_value=fake_hw):
                    rc = self._run_main(job_dir)

            self.assertEqual(rc, 0)
            self.assertEqual(len(model_instances), 1)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertIn("stage03.started", names)
            self.assertIn("stage03.whisper_model_loaded", names)
            self.assertIn("stage03.transcript_written", names)
            self.assertIn("stage03.completed", names)

            written = next(event for event in events if event["event"] == "stage03.transcript_written")
            self.assertEqual(written["details"]["segment_count"], 1)
            self.assertEqual(written["details"]["word_count"], 2)
            self.assertEqual(written["details"]["language"], "en")
            self.assertEqual(written["details"]["alignment_mode"], "whisper")

    def test_missing_vocals_emits_input_missing_and_failed_events(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            job_dir = Path(tmp) / "job-stage03-missing"
            job_dir.mkdir()
            fake_hw = SimpleNamespace(
                transcribe_device="cpu",
                transcribe_compute="int8",
                transcribe_beam_size=1,
                transcribe_vad=False,
            )

            with patch.object(s03_transcribe, "detect", return_value=fake_hw):
                rc = self._run_main(job_dir)

            self.assertEqual(rc, 1)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertIn("stage03.input_missing", names)
            self.assertIn("stage03.failed", names)
            failed = [event for event in events if event["event"] == "stage03.failed"][-1]
            self.assertEqual(failed["level"], "error")

    def test_missing_job_dir_records_global_failure_without_creating_job(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            job_dir = Path(tmp) / "missing-job"
            fake_hw = SimpleNamespace(
                transcribe_device="cpu",
                transcribe_compute="int8",
                transcribe_beam_size=1,
                transcribe_vad=False,
            )

            with patch.object(s03_transcribe, "detect", return_value=fake_hw):
                rc = self._run_main(job_dir)

            self.assertEqual(rc, 1)
            self.assertFalse(job_dir.exists())
            events = read_events(job_dir.parent / "_stage03")
            self.assertTrue(
                any(
                    event["event"] == "stage03.failed"
                    and event["details"].get("reason") == "job_dir_missing"
                    and event["details"].get("missing_job_dir") == str(job_dir)
                    for event in events
                )
            )


if __name__ == "__main__":
    unittest.main()
