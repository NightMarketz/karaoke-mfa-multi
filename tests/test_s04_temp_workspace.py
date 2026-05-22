import json
import logging
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch
import wave

from scripts import s04_align
from scripts.s04_align import _hfa_batch_dir


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\0\0" * 16000)


def _read_events(job_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (job_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class Stage04TempWorkspaceTests(unittest.TestCase):
    def _close_logging(self) -> None:
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            if isinstance(handler, logging.FileHandler):
                handler.close()

    def tearDown(self) -> None:
        self._close_logging()

    def test_hfa_batch_dir_lives_under_job_dir_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            with _hfa_batch_dir(job_dir) as batch_dir:
                self.assertTrue(batch_dir.exists())
                batch_dir.relative_to(job_dir)
                (batch_dir / "probe.txt").write_text("ok", encoding="utf-8")

            self.assertFalse(batch_dir.exists())

    def test_hfa_batch_dir_records_creation_and_cleanup_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            with _hfa_batch_dir(job_dir) as batch_dir:
                batch_name = batch_dir.name

            self.assertFalse(list(job_dir.glob(".hfa_batch_*")))
            events = _read_events(job_dir)
            self.assertEqual(
                ["stage04.temp_dir_created", "stage04.temp_dir_cleanup"],
                [event["event"] for event in events],
            )
            self.assertEqual(batch_name, events[0]["details"]["name"])
            self.assertTrue(events[1]["details"]["removed"])

    def test_timeout_path_records_hubertfa_timeout_and_fallback_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            model_dir = job_dir / "model"
            model_dir.mkdir()
            for name in ("config.json", "vocab.json", "VERSION"):
                (model_dir / name).write_text("{}", encoding="utf-8")
            _write_wav(job_dir / "vocals.wav")
            (job_dir / "transcript.json").write_text(
                json.dumps(
                    {
                        "segments": [
                            {
                                "start": 0.0,
                                "end": 1.0,
                                "text": "hello world",
                                "words": [
                                    {"word": "hello", "start": 0.0, "end": 0.5},
                                    {"word": "world", "start": 0.5, "end": 1.0},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            fake_g2p_en = ModuleType("g2p_en")
            fake_g2p_en.G2p = lambda: (lambda text: ["HH", "AH0", "L", "OW1"])
            argv = [
                "s04_align.py",
                "--job-dir",
                str(job_dir),
                "--checkpoint",
                str(model_dir / "model.onnx"),
                "--hubertfa-timeout",
                "7",
            ]

            with patch.dict(sys.modules, {"g2p_en": fake_g2p_en}), patch.object(
                sys, "argv", argv
            ), patch.object(s04_align.subprocess, "run") as run:
                run.side_effect = subprocess.TimeoutExpired(cmd=["hubertfa"], timeout=7)

                self.assertEqual(0, s04_align.main())
            self._close_logging()

            self.assertFalse(list(job_dir.glob(".hfa_batch_*")))
            events = _read_events(job_dir)
            event_names = [event["event"] for event in events]
            self.assertIn("stage04.hubertfa_started", event_names)
            self.assertIn("stage04.hubertfa_timeout", event_names)
            self.assertIn("stage04.fallback_used", event_names)
            self.assertIn("stage04.aligned_written", event_names)
            timeout_event = next(
                event for event in events if event["event"] == "stage04.hubertfa_timeout"
            )
            self.assertEqual(7, timeout_event["details"]["timeout"])
            fallback_event = next(
                event for event in events if event["event"] == "stage04.fallback_used"
            )
            self.assertEqual("hubertfa_timeout", fallback_event["details"]["reason"])
            self.assertEqual(2, fallback_event["details"]["word_count"])

    def test_missing_job_dir_records_global_failure_without_creating_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_job = Path(tmp) / "missing-job"
            argv = ["s04_align.py", "--job-dir", str(missing_job)]

            with patch.object(sys, "argv", argv):
                self.assertEqual(1, s04_align.main())
            self._close_logging()

            self.assertFalse(missing_job.exists())
            events = _read_events(Path(tmp) / "_stage04")
            self.assertEqual(["stage04.failed"], [event["event"] for event in events])
            self.assertEqual("job_dir_missing", events[0]["details"]["reason"])


if __name__ == "__main__":
    unittest.main()
