import unittest
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.common.observability import read_events
from scripts.common.validation import find_word_coverage_errors
from scripts import s05_analyze
from scripts.s05_analyze import _validate_analysis


class AnalysisContractTests(unittest.TestCase):
    def _write_stage05_inputs(
        self,
        job_dir: Path,
        transcript: dict | None = None,
        words: list[dict] | None = None,
    ) -> None:
        aligned_words = [
            {"word": "hello", "start": 0.0, "end": 0.4},
            {"word": "world", "start": 0.5, "end": 1.0},
        ] if words is None else words
        (job_dir / "transcript.json").write_text(
            json.dumps(
                transcript
                or {
                    "language": "en",
                    "alignment_mode": "whisper",
                    "segments": [],
                }
            ),
            encoding="utf-8",
        )
        (job_dir / "aligned.json").write_text(
            json.dumps(
                {
                    "words": aligned_words
                }
            ),
            encoding="utf-8",
        )

    def _run_stage05(self, job_dir: Path, *extra_args: str) -> int:
        argv = ["s05_analyze.py", "--job-dir", str(job_dir), *extra_args]
        root_logger = logging.getLogger()
        try:
            with patch("sys.argv", argv):
                return s05_analyze.main()
        finally:
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)
                if isinstance(handler, logging.FileHandler):
                    handler.close()

    def test_line_missing_words_fails_even_when_not_first_line(self):
        data = {
            "lines": [
                {
                    "text": "hello",
                    "start": 1.0,
                    "end": 1.5,
                    "style": "verse",
                    "words": [{"word": "hello", "start": 1.0, "end": 1.5}],
                },
                {"text": "world", "start": 2.0, "end": 2.5, "style": "verse"},
            ]
        }

        errors = _validate_analysis(data)

        self.assertTrue(any("Line 1 missing key: 'words'" in error for error in errors))

    def test_line_with_inverted_timestamps_fails(self):
        data = {
            "lines": [
                {
                    "text": "bad",
                    "start": 2.0,
                    "end": 1.5,
                    "style": "verse",
                    "words": [{"word": "bad", "start": 2.0, "end": 1.5}],
                }
            ]
        }

        errors = _validate_analysis(data)

        self.assertTrue(any("end <= start" in error for error in errors))

    def test_line_boundaries_must_match_first_and_last_word(self):
        data = {
            "lines": [
                {
                    "text": "hello world",
                    "start": 0.9,
                    "end": 2.1,
                    "style": "verse",
                    "words": [
                        {"word": "hello", "start": 1.0, "end": 1.5},
                        {"word": "world", "start": 1.6, "end": 2.0},
                    ],
                }
            ]
        }

        errors = _validate_analysis(data)

        self.assertTrue(any("does not match first word" in error for error in errors))
        self.assertTrue(any("does not match last word" in error for error in errors))

    def test_repeated_word_coverage_compares_counts_not_plain_set(self):
        aligned = [{"word": "hello"}, {"word": "hello"}, {"word": "world"}]
        analysis = [{"word": "hello"}, {"word": "world"}]

        errors = find_word_coverage_errors(aligned, analysis)

        self.assertTrue(any("hello" in error for error in errors))

    def test_force_rule_based_mode_writes_analysis_without_ollama(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_stage05_inputs(job_dir)

            with patch("scripts.s05_analyze._check_ollama") as check:
                exit_code = self._run_stage05(job_dir, "--force-rule-based")

            self.assertEqual(exit_code, 0)
            check.assert_not_called()
            analysis = json.loads((job_dir / "analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [word["word"] for line in analysis["lines"] for word in line["words"]],
                ["hello", "world"],
            )

    def test_force_rule_based_mode_emits_observability_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_stage05_inputs(job_dir)

            with patch("scripts.s05_analyze._check_ollama") as check:
                exit_code = self._run_stage05(job_dir, "--force-rule-based")

            self.assertEqual(exit_code, 0)
            check.assert_not_called()
            events = read_events(job_dir)
            self.assertTrue(any(event["event"] == "stage05.started" for event in events))
            self.assertTrue(
                any(
                    event["event"] == "stage05.path_selected"
                    and event["details"].get("path") == "rule_based_forced"
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage05.ollama_skipped"
                    and event["details"].get("reason") == "force_rule_based"
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage05.completed"
                    and event["details"].get("line_count") == 1
                    and event["details"].get("style_distribution") == {"verse": 1}
                    for event in events
                )
            )

    def test_forced_alignment_mode_emits_forced_path_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            words = [{"word": "hello", "start": 0.0, "end": 0.4}]
            self._write_stage05_inputs(
                job_dir,
                transcript={
                    "language": "en",
                    "alignment_mode": "forced",
                    "segments": [{"text": "hello", "section": "verse", "words": words}],
                },
                words=words,
            )

            exit_code = self._run_stage05(job_dir)

            self.assertEqual(exit_code, 0)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage05.path_selected"
                    and event["details"].get("path") == "forced_alignment"
                    for event in events
                )
            )
            self.assertFalse(any(event["event"] == "stage05.llm_attempt_started" for event in events))
            self.assertTrue(any(event["event"] == "stage05.completed" for event in events))
            self.assertTrue(
                any(
                    event["event"] == "stage05.ollama_skipped"
                    and event["details"].get("reason") == "forced_alignment"
                    for event in events
                )
            )

    def test_llm_parse_failures_emit_retry_and_fallback_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_stage05_inputs(job_dir)

            with patch("scripts.s05_analyze._check_ollama", return_value=None), patch(
                "scripts.s05_analyze._call_ollama_stream", return_value="not json"
            ):
                exit_code = self._run_stage05(job_dir)

            self.assertEqual(exit_code, 0)
            events = read_events(job_dir)
            self.assertEqual(
                sum(1 for event in events if event["event"] == "stage05.llm_attempt_started"),
                2,
            )
            self.assertEqual(
                sum(1 for event in events if event["event"] == "stage05.llm_parse_failed"),
                2,
            )
            self.assertTrue(
                all(
                    event["details"].get("response_length") == len("not json")
                    for event in events
                    if event["event"] == "stage05.llm_parse_failed"
                )
            )
            self.assertTrue(any(event["event"] == "stage05.ollama_check_succeeded" for event in events))
            self.assertTrue(
                any(
                    event["event"] == "stage05.fallback_used"
                    and event["details"].get("reason") == "llm_unparseable"
                    and event["details"].get("max_retries") == 2
                    for event in events
                )
            )
            self.assertTrue(any(event["event"] == "stage05.completed" for event in events))

    def test_llm_parse_success_emits_response_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_stage05_inputs(job_dir)
            raw_response = json.dumps({"lines": [{"word_indices": [0, 1], "style": "chorus"}]})

            with patch("scripts.s05_analyze._check_ollama", return_value=None), patch(
                "scripts.s05_analyze._call_ollama_stream", return_value=raw_response
            ):
                exit_code = self._run_stage05(job_dir)

            self.assertEqual(exit_code, 0)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage05.llm_parse_succeeded"
                    and event["details"].get("response_length") == len(raw_response)
                    and event["details"].get("line_count") == 1
                    for event in events
                )
            )
            self.assertFalse(any(event["event"] == "stage05.fallback_used" for event in events))

    def test_ollama_check_failure_emits_failed_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_stage05_inputs(job_dir)

            with patch("scripts.s05_analyze._check_ollama", return_value="Ollama not reachable"):
                exit_code = self._run_stage05(job_dir)

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage05.path_selected"
                    and event["details"].get("path") == "llm"
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage05.ollama_check_failed"
                    and event["details"].get("error") == "Ollama not reachable"
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage05.failed"
                    and event["details"].get("reason") == "ollama_check_failed"
                    for event in events
                )
            )
            self.assertFalse(any(event["event"] == "stage05.completed" for event in events))

    def test_validation_failure_emits_validation_failed_and_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_stage05_inputs(job_dir)
            invalid_lines = [
                {
                    "text": "bad",
                    "start": 1.0,
                    "end": 0.5,
                    "style": "verse",
                    "color": "default",
                    "effect": "highlight",
                    "words": [{"word": "bad", "start": 1.0, "end": 0.5}],
                }
            ]

            with patch("scripts.s05_analyze._rule_based_grouper", return_value=invalid_lines):
                exit_code = self._run_stage05(job_dir, "--force-rule-based")

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage05.analysis_invalid"
                    and event["details"].get("error_count", 0) >= 1
                    for event in events
                )
            )
            self.assertTrue(
                any(
                    event["event"] == "stage05.failed"
                    and event["details"].get("reason") == "validation_failed"
                    for event in events
                )
            )
            self.assertFalse(any(event["event"] == "stage05.completed" for event in events))

    def test_missing_inputs_emit_stage05_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            exit_code = self._run_stage05(job_dir)

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage05.failed"
                    and event["details"].get("reason") == "missing_input"
                    for event in events
                )
            )

    def test_missing_job_dir_emits_stage05_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "missing-job"

            exit_code = self._run_stage05(job_dir)

            self.assertEqual(exit_code, 1)
            self.assertFalse(job_dir.exists())
            events = read_events(job_dir.parent / "_stage05")
            self.assertTrue(
                any(
                    event["event"] == "stage05.failed"
                    and event["details"].get("reason") == "job_dir_missing"
                    and event["details"].get("missing_job_dir") == str(job_dir)
                    for event in events
                )
            )

    def test_empty_aligned_words_emit_stage05_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_stage05_inputs(job_dir, words=[])

            exit_code = self._run_stage05(job_dir)

            self.assertEqual(exit_code, 1)
            events = read_events(job_dir)
            self.assertTrue(
                any(
                    event["event"] == "stage05.failed"
                    and event["details"].get("reason") == "aligned_words_empty"
                    for event in events
                )
            )

    def test_completion_event_is_after_analysis_written_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_stage05_inputs(job_dir)

            exit_code = self._run_stage05(job_dir, "--force-rule-based")

            self.assertEqual(exit_code, 0)
            events = read_events(job_dir)
            names = [event["event"] for event in events]
            self.assertLess(names.index("stage05.analysis_written"), names.index("stage05.completed"))


if __name__ == "__main__":
    unittest.main()
