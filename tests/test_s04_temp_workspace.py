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


class CtcForcedPhonemeAssignmentTests(unittest.TestCase):
    def test_phonemes_assigned_by_audio_position_not_count_ratio(self):
        # Word A occupies [0,1], word B [1,2]. Four phonemes: one in A's span,
        # three in B's. Count-ratio would split them 2/2; positional assignment
        # must give A one phoneme and B three.
        words = [
            {"word": "A", "start": 0.0, "end": 1.0, "source": "ctc_forced"},
            {"word": "B", "start": 1.0, "end": 2.0, "source": "ctc_forced"},
        ]
        ivs = [
            {"text": "a", "xmin": 0.2, "xmax": 0.5},
            {"text": "b", "xmin": 1.1, "xmax": 1.3},
            {"text": "c", "xmin": 1.3, "xmax": 1.6},
            {"text": "d", "xmin": 1.6, "xmax": 1.9},
        ]

        result = s04_align._ctc_forced_with_phonemes(words, ivs, offset=0.0)

        self.assertEqual([p["ph"] for p in result[0]["phonemes"]], ["a"])
        self.assertEqual([p["ph"] for p in result[1]["phonemes"]], ["b", "c", "d"])
        self.assertEqual(result[0]["source"], "ctc_forced+hubertfa")

    def test_degenerate_island_word_grows_into_gap_to_reach_floor(self):
        # 'the' is CTC-compressed to 20 ms with silence on both sides (the real
        # case). Floor 120 ms grows it into the gap without touching neighbours
        # or overlapping them; first/last words pin the line envelope.
        words = [
            {"word": "a", "start": 0.0, "end": 0.4, "source": "ctc_forced"},
            {"word": "the", "start": 0.52, "end": 0.54, "source": "ctc_forced"},
            {"word": "beast", "start": 0.66, "end": 1.2, "source": "ctc_forced"},
        ]
        result = s04_align._ctc_forced_with_phonemes(words, [], offset=0.0, min_word_dur=0.12)

        self.assertEqual((result[0]["start"], result[0]["end"]), (0.0, 0.4))
        self.assertEqual((result[2]["start"], result[2]["end"]), (0.66, 1.2))  # line-sync
        self.assertGreaterEqual(result[1]["end"] - result[1]["start"], 0.12 - 1e-6)
        self.assertGreaterEqual(result[1]["start"], 0.4)   # no overlap with prev
        self.assertLessEqual(result[1]["end"], 0.66)       # no overlap with next

    def test_floor_leaves_healthy_words_and_gaps_untouched(self):
        # A gap between two full-length words is real (held silence) and must
        # survive; neither word is sub-floor, so nothing moves.
        words = [
            {"word": "A", "start": 0.0, "end": 1.0, "source": "ctc_forced"},
            {"word": "B", "start": 5.0, "end": 6.0, "source": "ctc_forced"},
        ]
        result = s04_align._ctc_forced_with_phonemes(words, [], offset=0.0, min_word_dur=0.12)
        self.assertEqual((result[0]["start"], result[0]["end"]), (0.0, 1.0))
        self.assertEqual((result[1]["start"], result[1]["end"]), (5.0, 6.0))

    def test_word_without_phonemes_stays_plain_ctc_forced(self):
        words = [
            {"word": "A", "start": 0.0, "end": 1.0, "source": "ctc_forced"},
            {"word": "B", "start": 5.0, "end": 6.0, "source": "ctc_forced"},
        ]
        # Only phonemes near A; B's span [5,6] captures none.
        ivs = [{"text": "a", "xmin": 0.2, "xmax": 0.5}, {"text": "x", "xmin": 0.6, "xmax": 0.9}]

        result = s04_align._ctc_forced_with_phonemes(words, ivs, offset=0.0)

        self.assertEqual(result[1]["phonemes"], [])
        self.assertEqual(result[1]["source"], "ctc_forced")


_TWO_TIER_TEXTGRID = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 1
tiers? <exists>
size = 2
item []:
    item [1]:
        class = "IntervalTier"
        name = "words"
        xmin = 0
        xmax = 1
        intervals: size = 1
        intervals [1]:
            xmin = 0.0
            xmax = 1.0
            text = "beast"
    item [2]:
        class = "IntervalTier"
        name = "phones"
        xmin = 0
        xmax = 1
        intervals: size = 3
        intervals [1]:
            xmin = 0.0
            xmax = 0.3
            text = "b"
        intervals [2]:
            xmin = 0.3
            xmax = 0.6
            text = "iy"
        intervals [3]:
            xmin = 0.6
            xmax = 1.0
            text = "s"
'''


class TextGridTierParsingTests(unittest.TestCase):
    def test_phone_intervals_ignore_word_tier_and_do_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tg = Path(tmp) / "seg.TextGrid"
            tg.write_text(_TWO_TIER_TEXTGRID, encoding="utf-8")

            parsed = s04_align._parse_textgrid(tg)
            phones = s04_align._phone_intervals(parsed)

        # Each interval keeps its real tier; only the phones tier survives.
        self.assertEqual({v["tier"] for v in parsed}, {"words", "phones"})
        self.assertEqual([v["text"] for v in phones], ["b", "iy", "s"])
        self.assertNotIn("beast", [v["text"] for v in phones])  # word-tier mark dropped


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
                "--allow-cpu-hubertfa",
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

    def test_cpu_only_onnx_provider_skips_hubertfa_and_records_fallback(self):
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
                        "alignment_mode": "forced",
                        "segments": [
                            {
                                "start": 0.0,
                                "end": 1.0,
                                "text": "hello",
                                "words": [
                                    {"word": "hello", "start": 0.0, "end": 1.0},
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fake_g2p_en = ModuleType("g2p_en")
            fake_g2p_en.G2p = lambda: (lambda text: ["HH", "AH0"])
            argv = [
                "s04_align.py",
                "--job-dir",
                str(job_dir),
                "--checkpoint",
                str(model_dir / "model.onnx"),
            ]

            with patch.dict(sys.modules, {"g2p_en": fake_g2p_en}), patch.object(
                sys, "argv", argv
            ), patch.object(
                s04_align,
                "_available_onnx_providers",
                return_value=["AzureExecutionProvider", "CPUExecutionProvider"],
                create=True,
            ), patch.object(s04_align.subprocess, "run") as run:
                self.assertEqual(0, s04_align.main())

            self._close_logging()
            self.assertFalse(
                any("onnx_infer.py" in " ".join(str(part) for part in call.args[0]) for call in run.call_args_list)
            )
            events = _read_events(job_dir)
            event_names = [event["event"] for event in events]
            self.assertIn("stage04.hubertfa_skipped", event_names)
            self.assertIn("stage04.fallback_used", event_names)
            skipped_event = next(
                event for event in events if event["event"] == "stage04.hubertfa_skipped"
            )
            self.assertEqual("cpu_only_onnx_provider", skipped_event["details"]["reason"])
            fallback_event = next(
                event for event in events if event["event"] == "stage04.fallback_used"
            )
            self.assertEqual("cpu_only_onnx_provider", fallback_event["details"]["reason"])

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
