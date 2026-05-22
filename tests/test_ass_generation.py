import unittest
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.common.observability import read_events
from scripts import s06_generate_ass
from scripts.s06_generate_ass import PRESETS, _build_karaoke_text


class AssGenerationTests(unittest.TestCase):
    def _write_analysis(self, job_dir: Path, lines: list[dict]) -> None:
        (job_dir / "analysis.json").write_text(
            json.dumps({"lines": lines}),
            encoding="utf-8",
        )

    def _sample_line(
        self,
        text: str = "hello world",
        start: float = 1.0,
        end: float = 2.0,
        style: str = "verse",
    ) -> dict:
        return {
            "text": text,
            "start": start,
            "end": end,
            "style": style,
            "effect": "highlight",
            "words": [
                {"word": "hello", "start": start, "end": start + 0.4},
                {"word": "world", "start": start + 0.5, "end": end},
            ],
        }

    def _run_stage06(self, job_dir: Path, *extra_args: str) -> int:
        argv = ["s06_generate_ass.py", "--job-dir", str(job_dir), *extra_args]
        root_logger = logging.getLogger()
        try:
            with patch("sys.argv", argv):
                return s06_generate_ass.main()
        finally:
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)
                if isinstance(handler, logging.FileHandler):
                    handler.close()

    def test_build_karaoke_text_escapes_braces(self):
        text = _build_karaoke_text(
            [{"word": "{bad}", "start": 1.0, "end": 1.5}],
            line_start_ms=1000,
            effect="highlight",
        )

        self.assertNotIn("{bad}", text)
        self.assertIn("bad", text)

    def test_inverted_word_gets_minimum_duration(self):
        text = _build_karaoke_text(
            [{"word": "fast", "start": 2.0, "end": 1.9}],
            line_start_ms=1900,
            effect="highlight",
        )

        self.assertIn("\\kf8", text)

    def test_section_coded_preset_exists(self):
        self.assertIn("section-coded", PRESETS)
        self.assertIn("drop", PRESETS["section-coded"])

    def test_stage06_success_emits_observability_events_and_records_ass_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(
                job_dir,
                [
                    self._sample_line(style="verse"),
                    self._sample_line(text="sing loud", start=2.1, end=3.0, style="chorus"),
                ],
            )

            exit_code = self._run_stage06(job_dir, "--preset", "section-coded")

            self.assertEqual(exit_code, 0)
            ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertIn("stage06.started", names)
            self.assertTrue(
                any(
                    event["event"] == "stage06.preset_selected"
                    and event["details"].get("preset") == "section-coded"
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage06.style_distribution"
                    and event["details"].get("style_distribution") == {"verse": 1, "chorus": 1}
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage06.ass_generated"
                    and event["details"].get("dialogue_count") == ass_content.count("\nDialogue:")
                    and event["details"].get("kf_count") == ass_content.count("\\kf")
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage06.ass_written"
                    and event["details"].get("size_bytes") == (job_dir / "output.ass").stat().st_size
                    for event in events
                )
            )
            self.assertEqual(names[-1], "stage06.completed")

    def test_stage06_missing_analysis_emits_input_missing_and_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            exit_code = self._run_stage06(job_dir)

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage06.input_missing"
                    and event["details"].get("artifact") == "analysis.json"
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage06.failed"
                    and event["details"].get("reason") == "missing_input"
                    for event in events
                )
            )

    def test_stage06_inverted_lines_emit_skip_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(
                job_dir,
                [
                    self._sample_line(),
                    self._sample_line(text="bad", start=4.0, end=3.0),
                ],
            )

            exit_code = self._run_stage06(job_dir)

            self.assertEqual(exit_code, 0)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage06.inverted_lines_skipped"
                    and event["details"].get("skipped_count") == 1
                    and event["details"].get("input_line_count") == 2
                    for event in events
                )
            )

    def test_stage06_validation_failure_emits_validation_failed_and_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir, [self._sample_line()])

            with patch("scripts.s06_generate_ass._generate_ass", return_value="[Script Info]\n"):
                exit_code = self._run_stage06(job_dir)

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage06.validation_failed"
                    and event["details"].get("error_count", 0) >= 1
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage06.failed"
                    and event["details"].get("reason") == "validation_failed"
                    for event in events
                )
            )
            self.assertFalse((job_dir / "output.ass").exists())


if __name__ == "__main__":
    unittest.main()
