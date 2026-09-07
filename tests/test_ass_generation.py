import unittest
import json
import logging
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch

from tests._optional_imports import import_or_skip

import_or_skip("numpy")
from scripts.common.observability import read_events
from scripts.common.provenance import file_sha256
from scripts.karaoke_styles.library import PRESETS as LIBRARY_PRESETS, get_preset, list_preset_ids
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

    def _write_sine_window(
        self,
        path: Path,
        *,
        duration_s: float,
        active_start_s: float,
        active_end_s: float,
    ) -> None:
        sample_rate = 16000
        frames = int(duration_s * sample_rate)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            payload = bytearray()
            for index in range(frames):
                t = index / sample_rate
                amp = 0.35 * math.sin(2 * math.pi * 220 * t) if active_start_s <= t <= active_end_s else 0.0
                value = int(max(-1.0, min(1.0, amp)) * 32767)
                payload.extend(value.to_bytes(2, byteorder="little", signed=True))
            handle.writeframes(bytes(payload))

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

    def test_long_word_uses_slow_vowel_highlight_segments(self):
        text = _build_karaoke_text(
            [
                {"word": "About", "start": 274.48, "end": 275.22},
                {"word": "to", "start": 275.26, "end": 275.34},
                {"word": "snap", "start": 275.42, "end": 282.02},
            ],
            line_start_ms=274480,
            effect="highlight",
        )

        self.assertIn("\\kf624}a", text)
        self.assertIn("\\kf", text)
        self.assertNotIn("sn a p", text)

    def test_small_inter_word_gaps_are_absorbed_into_previous_highlight_for_visual_continuity(self):
        text = _build_karaoke_text(
            [
                {"word": "Running", "start": 40.66, "end": 41.46},
                {"word": "on", "start": 41.54, "end": 41.68},
                {"word": "fumes", "start": 41.80, "end": 42.60},
            ],
            line_start_ms=40660,
            effect="highlight",
        )

        self.assertIn("\\kf88}Running", text)
        self.assertIn("\\kf26}on", text)
        self.assertNotIn("\\k8", text)
        self.assertNotIn("\\k12", text)

    def test_long_inter_word_gap_keeps_a_single_space_between_words(self):
        # A gap wide enough to survive absorption used to be emitted as its own
        # space-padded part, burning as "the  tomb".
        text = _build_karaoke_text(
            [
                {"word": "the", "start": 43.60, "end": 43.92},
                {"word": "tomb", "start": 45.62, "end": 45.74},
            ],
            line_start_ms=43600,
            effect="highlight",
        )

        self.assertIn("\\k170}", text)          # the gap is still consumed
        self.assertNotIn("  ", text)            # but adds no second space
        self.assertEqual(text, text.strip())    # and no leading/trailing space
        self.assertEqual(1, text.count(" "))

    def test_leading_silence_gap_does_not_indent_the_line(self):
        text = _build_karaoke_text(
            [{"word": "Breathing", "start": 37.22, "end": 38.38}],
            line_start_ms=36000,
            effect="highlight",
        )

        self.assertIn("\\k122}", text)
        self.assertEqual(0, text.count(" "), text)  # nothing to separate

    def _verse_style_line(self, resolution: str) -> list[str]:
        from scripts.s06_generate_ass import _generate_ass

        content = _generate_ass(
            lines=[self._sample_line()],
            styles=PRESETS["section-coded"],
            resolution=resolution,
            fade_in_ms=300,
            fade_out_ms=500,
        )
        line = next(l for l in content.splitlines() if l.startswith("Style: Verse,"))
        return line.split(",")

    def test_style_pixels_scale_with_the_render_height(self):
        # Presets are drawn against 720p. At 1080p an unscaled 52px verse was
        # 4.8% of frame height instead of 7.2%, and the side margin was a flat
        # 20px on a 1920px frame.
        from scripts.karaoke_styles.library import PRESETS as LIB

        verse = LIB["section-coded"]["verse"]
        at720 = self._verse_style_line("1280x720")
        at1080 = self._verse_style_line("1920x1080")

        # fields: Name,Fontname,Fontsize,...,MarginL,MarginR,MarginV,Encoding
        self.assertEqual(str(verse.fontsize), at720[2])
        self.assertEqual(str(round(verse.fontsize * 1.5)), at1080[2])
        self.assertEqual(str(round(verse.margin_v * 1.5)), at1080[-2])
        self.assertEqual(["64", "64"], at720[-4:-2])
        self.assertEqual(["96", "96"], at1080[-4:-2])

    def test_section_coded_preset_exists(self):
        self.assertIn("section-coded", PRESETS)
        self.assertIn("drop", PRESETS["section-coded"])

    def test_single_style_kf_preset_keeps_same_visual_attributes_for_all_sections(self):
        preset = get_preset("single-style-kf")
        styles = list(preset.styles.values())
        first = styles[0]
        for style in styles[1:]:
            self.assertEqual(style.fontname, first.fontname)
            self.assertEqual(style.fontsize, first.fontsize)
            self.assertEqual(style.bold, first.bold)
            self.assertEqual(style.italic, first.italic)
            self.assertEqual(style.primary_color, first.primary_color)
            self.assertEqual(style.secondary_color, first.secondary_color)
            self.assertEqual(style.outline_color, first.outline_color)
            self.assertEqual(style.back_color, first.back_color)
            self.assertEqual(style.outline, first.outline)
            self.assertEqual(style.shadow, first.shadow)
            self.assertEqual(style.margin_v, first.margin_v)

    def test_stage06_accepts_exactly_the_shared_style_library_presets(self):
        self.assertIs(PRESETS, LIBRARY_PRESETS)
        self.assertEqual(list_preset_ids(), list(PRESETS.keys()))
        self.assertIn("aegisub-classic-blue", PRESETS)

    def test_stage06_fails_loudly_when_style_library_import_fails(self):
        script = (
            "import builtins\n"
            "real_import = builtins.__import__\n"
            "def blocked_import(name, *args, **kwargs):\n"
            "    if name == 'scripts.karaoke_styles.library':\n"
            "        raise ImportError('blocked style library import')\n"
            "    return real_import(name, *args, **kwargs)\n"
            "builtins.__import__ = blocked_import\n"
            "import scripts.s06_generate_ass\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("blocked style library import", result.stderr)

    def test_stage06_renders_single_visible_dialogue_per_lyric_line_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir, [self._sample_line()])

            exit_code = self._run_stage06(job_dir, "--preset", "section-coded")

            self.assertEqual(exit_code, 0)
            ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
            dialogue_lines = [
                line for line in ass_content.splitlines()
                if line.startswith("Dialogue:")
            ]
            self.assertEqual(len(dialogue_lines), 1)
            self.assertNotIn("Base,,", dialogue_lines[0])
            self.assertIn("\\kf", dialogue_lines[0])

    def test_stage06_renders_timed_syllables_from_analysis_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(
                job_dir,
                [
                    {
                        "text": "mama",
                        "start": 10.0,
                        "end": 10.8,
                        "style": "verse",
                        "effect": "highlight",
                        "words": [
                            {
                                "word": "mama",
                                "start": 10.0,
                                "end": 10.8,
                                "syllables": [
                                    {"text": "ma", "start": 10.05, "end": 10.30},
                                    {"text": "ma", "start": 10.35, "end": 10.80},
                                ],
                            }
                        ],
                    }
                ],
            )

            exit_code = self._run_stage06(job_dir, "--preset", "section-coded")

            self.assertEqual(exit_code, 0)
            ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
            self.assertIn("\\kf25}ma", ass_content)
            self.assertIn("\\kf45}ma", ass_content)

    def test_syllable_kf_quantization_applies_residual_to_last_visible_segment(self):
        text = _build_karaoke_text(
            [
                {
                    "word": "abc",
                    "start": 10.0,
                    "end": 11.0,
                    "syllables": [
                        {"text": "a", "start": 10.000, "end": 10.214},
                        {"text": "b", "start": 10.214, "end": 10.551},
                        {"text": "c", "start": 10.551, "end": 11.000},
                    ],
                }
            ],
            line_start_ms=10000,
            effect="highlight",
        )

        self.assertIn("\\kf21}a", text)
        self.assertIn("\\kf34}b", text)
        self.assertIn("\\kf45}c", text)

    def test_stage06_writes_ass_manifest_with_generation_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            lines = [
                self._sample_line(style="verse"),
                self._sample_line(text="sing loud", start=2.1, end=3.0, style="chorus"),
            ]
            self._write_analysis(job_dir, lines)
            (job_dir / "status.json").write_text(
                json.dumps({"run_id": "run-stage06-test"}),
                encoding="utf-8",
            )

            exit_code = self._run_stage06(job_dir, "--preset", "section-coded")

            self.assertEqual(exit_code, 0)
            ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
            dialogue_lines = [
                line for line in ass_content.splitlines()
                if line.startswith("Dialogue:")
            ]
            manifest_path = job_dir / "output.ass.manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["stage"], "stage06")
            self.assertEqual(manifest["run_id"], "run-stage06-test")
            self.assertEqual(manifest["preset"], "section-coded")
            self.assertEqual(manifest["renderer_mode"], "single_layer_kf")
            self.assertEqual(manifest["inputs"]["analysis.json"]["sha256"], file_sha256(job_dir / "analysis.json"))
            self.assertEqual(manifest["outputs"]["output.ass"]["sha256"], file_sha256(job_dir / "output.ass"))
            self.assertEqual(manifest["metrics"]["analysis_line_count"], 2)
            self.assertEqual(manifest["metrics"]["dialogue_count"], 2)
            self.assertEqual(manifest["metrics"]["kf_count"], ass_content.count("\\kf"))
            self.assertEqual(manifest["style_distribution"], {"verse": 1, "chorus": 1})
            self.assertIn("timing_layers", manifest)
            self.assertIn("inter_word_gaps", manifest["timing_layers"])
            self.assertIn("tails", manifest["timing_layers"])
            self.assertIn("timing_diagnostics", manifest)
            self.assertIn("events", manifest["timing_diagnostics"])
            self.assertIn("summary", manifest["timing_diagnostics"])
            self.assertEqual(manifest["timing_audio_layers"]["available"], False)
            self.assertEqual(len(dialogue_lines), len(lines))
            self.assertFalse(any("Base,," in line for line in dialogue_lines))

    def test_stage06_manifest_counts_audio_backed_tail_trims(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            line = {
                "text": "I must carry on",
                "start": 10.0,
                "end": 20.0,
                "style": "outro",
                "effect": "fade_in",
                "words": [
                    {"word": "I", "start": 10.0, "end": 10.05},
                    {"word": "must", "start": 15.0, "end": 15.4},
                    {"word": "carry", "start": 18.0, "end": 18.4},
                    {"word": "on", "start": 18.5, "end": 20.0},
                ],
            }
            self._write_analysis(job_dir, [line])
            (job_dir / "vocals.wav").write_bytes(b"not-a-real-wav-but-present")

            fake_timing = [
                {
                    "inter_word_gaps": [],
                    "vocal_periods": [],
                    "tail": {
                        "classification": "false_long_tail",
                        "word_index": 3,
                        "audio_evidence": {"voiced_ratio": 0.09},
                    },
                }
            ]

            with patch("scripts.s06_generate_ass.build_audio_activity_map", return_value={}):
                with patch("scripts.s06_generate_ass.build_audio_backed_timing", return_value=fake_timing):
                    exit_code = self._run_stage06(job_dir, "--preset", "single-style-kf")

            self.assertEqual(exit_code, 0)
            manifest = json.loads((job_dir / "output.ass.manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["timing_audio_layers"]["available"])
            self.assertEqual(manifest["timing_audio_layers"]["applied_tail_extensions"], 0)
            self.assertEqual(manifest["timing_audio_layers"]["applied_tail_trims"], 1)
            ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
            self.assertIn("\\kf60}on", ass_content)

    def test_stage06_real_wav_extends_written_melisma_in_final_ass(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            lines = [
                {
                    "text": "Oooo wooow",
                    "start": 0.50,
                    "end": 1.20,
                    "style": "intro",
                    "effect": "highlight",
                    "words": [
                        {"word": "Oooo", "start": 0.50, "end": 0.82},
                        {"word": "wooow", "start": 0.94, "end": 1.20},
                    ],
                },
                {
                    "text": "Still",
                    "start": 3.20,
                    "end": 3.60,
                    "style": "verse",
                    "effect": "highlight",
                    "words": [{"word": "Still", "start": 3.20, "end": 3.60}],
                },
            ]
            self._write_analysis(job_dir, lines)
            self._write_sine_window(job_dir / "vocals.wav", duration_s=4.0, active_start_s=0.50, active_end_s=2.20)

            exit_code = self._run_stage06(job_dir, "--preset", "single-style-kf")

            self.assertEqual(exit_code, 0)
            manifest = json.loads((job_dir / "output.ass.manifest.json").read_text(encoding="utf-8"))
            ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
            self.assertEqual(manifest["timing_audio_layers"]["summary"]["tails"]["written_melisma_extension"], 1)
            self.assertGreaterEqual(manifest["timing_audio_layers"]["applied_tail_extensions"], 1)
            self.assertIn("\\kf111}ooo", ass_content)

    def test_stage06_real_wav_trims_false_long_tail_in_final_ass(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            line = {
                "text": "I must carry on",
                "start": 0.50,
                "end": 7.25,
                "style": "outro",
                "effect": "highlight",
                "words": [
                    {"word": "I", "start": 0.50, "end": 0.55},
                    {"word": "must", "start": 1.00, "end": 1.40},
                    {"word": "carry", "start": 1.80, "end": 2.20},
                    {"word": "on", "start": 2.25, "end": 7.25},
                ],
            }
            self._write_analysis(job_dir, [line])
            self._write_sine_window(job_dir / "vocals.wav", duration_s=8.0, active_start_s=0.50, active_end_s=2.20)

            exit_code = self._run_stage06(job_dir, "--preset", "single-style-kf")

            self.assertEqual(exit_code, 0)
            manifest = json.loads((job_dir / "output.ass.manifest.json").read_text(encoding="utf-8"))
            ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
            self.assertEqual(manifest["timing_audio_layers"]["summary"]["tails"]["false_long_tail"], 1)
            self.assertEqual(manifest["timing_audio_layers"]["applied_tail_extensions"], 0)
            self.assertEqual(manifest["timing_audio_layers"]["applied_tail_trims"], 1)
            self.assertIn("\\kf60}on", ass_content)
            self.assertNotIn("\\kf500}on", ass_content)

    def test_stage06_manifest_keeps_review_only_audio_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            line = {
                "text": "Lights go low",
                "start": 223.28,
                "end": 233.68,
                "style": "bridge",
                "effect": "highlight",
                "words": [
                    {"word": "Lights", "start": 223.28, "end": 227.24},
                    {"word": "go", "start": 232.52, "end": 232.64},
                    {"word": "low", "start": 233.12, "end": 233.68},
                ],
            }
            self._write_analysis(job_dir, [line])
            (job_dir / "vocals.wav").write_bytes(b"not-a-real-wav-but-present")
            fake_timing = [
                {
                    "line_classification": "review_only_backing_or_drift",
                    "diagnostic_tags": ["possible_backing_vocal_not_in_lyrics"],
                    "confidence": "high",
                    "recommended_fallback": "manual_review_or_local_realign",
                    "sound_suggestion": {
                        "sound_type": "possible_backing_vocal_not_in_lyrics",
                        "suggested_caption": "[vocal de apoio]",
                        "suggested_user_action": "review_backing_vocal_or_local_realign",
                    },
                    "inter_word_gaps": [{"classification": "bad_gap"}],
                    "vocal_periods": [],
                    "tail": {"classification": "none"},
                }
            ]

            with patch("scripts.s06_generate_ass.build_audio_activity_map", return_value={}):
                with patch("scripts.s06_generate_ass.build_audio_backed_timing", return_value=fake_timing):
                    exit_code = self._run_stage06(job_dir, "--preset", "single-style-kf")

            self.assertEqual(exit_code, 0)
            manifest = json.loads((job_dir / "output.ass.manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["timing_audio_layers"]["diagnostics"],
                [
                    {
                        "line_index": 0,
                        "line_classification": "review_only_backing_or_drift",
                        "diagnostic_tags": ["possible_backing_vocal_not_in_lyrics"],
                        "confidence": "high",
                        "recommended_fallback": "manual_review_or_local_realign",
                        "sound_suggestion": {
                            "sound_type": "possible_backing_vocal_not_in_lyrics",
                            "suggested_caption": "[vocal de apoio]",
                            "suggested_user_action": "review_backing_vocal_or_local_realign",
                        },
                    }
                ],
            )

    def test_stage06_does_not_apply_review_only_tail_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            line = {
                "text": "Lights go low",
                "start": 223.28,
                "end": 233.68,
                "style": "bridge",
                "effect": "highlight",
                "words": [
                    {"word": "Lights", "start": 223.28, "end": 227.24},
                    {"word": "go", "start": 232.52, "end": 232.64},
                    {"word": "low", "start": 233.12, "end": 233.68},
                ],
            }
            self._write_analysis(job_dir, [line])
            (job_dir / "vocals.wav").write_bytes(b"not-a-real-wav-but-present")
            fake_timing = [
                {
                    "line_classification": "review_only_backing_or_drift",
                    "diagnostic_tags": ["possible_backing_vocal_not_in_lyrics"],
                    "confidence": "high",
                    "recommended_fallback": "manual_review_or_local_realign",
                    "sound_suggestion": {
                        "sound_type": "possible_backing_vocal_not_in_lyrics",
                        "suggested_caption": "[vocal de apoio]",
                        "suggested_user_action": "review_backing_vocal_or_local_realign",
                    },
                    "inter_word_gaps": [{"classification": "bad_gap"}],
                    "vocal_periods": [],
                    "tail": {
                        "classification": "probable_unwritten_vowel_extension",
                        "word_index": 2,
                        "audio_evidence": {"end_s": 234.80, "voiced_ratio": 0.91},
                    },
                }
            ]

            with patch("scripts.s06_generate_ass.build_audio_activity_map", return_value={}):
                with patch("scripts.s06_generate_ass.build_audio_backed_timing", return_value=fake_timing):
                    exit_code = self._run_stage06(job_dir, "--preset", "single-style-kf")

            self.assertEqual(exit_code, 0)
            manifest = json.loads((job_dir / "output.ass.manifest.json").read_text(encoding="utf-8"))
            ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
            self.assertEqual(manifest["timing_audio_layers"]["applied_tail_extensions"], 0)
            self.assertEqual(manifest["timing_audio_layers"]["summary"]["tails"]["probable_unwritten_vowel_extension"], 1)
            self.assertEqual(len(manifest["timing_audio_layers"]["diagnostics"]), 1)
            self.assertEqual(
                manifest["timing_audio_layers"]["diagnostics"][0]["sound_suggestion"]["suggested_caption"],
                "[vocal de apoio]",
            )
            self.assertIn("\\kf56}low", ass_content)
            self.assertNotIn("\\kf168}low", ass_content)

    def test_stage06_manifest_keeps_tail_sound_suggestions_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            lines = [
                {
                    "text": "I won't fall",
                    "start": 294.18,
                    "end": 298.64,
                    "style": "outro",
                    "effect": "highlight",
                    "words": [
                        {"word": "I", "start": 294.18, "end": 294.23},
                        {"word": "won't", "start": 294.24, "end": 294.52},
                        {"word": "fall", "start": 294.70, "end": 298.64},
                    ],
                }
            ]
            self._write_analysis(job_dir, lines)
            (job_dir / "vocals.wav").write_bytes(b"not-a-real-wav-but-present")
            fake_timing = [
                {
                    "inter_word_gaps": [],
                    "vocal_periods": [],
                    "tail": {
                        "classification": "unwritten_interline_melisma",
                        "confidence": "medium",
                        "recommended_fallback": "flag_review_or_create_extension_bar",
                        "word": "fall",
                        "audio_evidence": {
                            "active": True,
                            "start_s": 298.64,
                            "end_s": 300.12,
                            "duration_s": 1.48,
                            "voiced_ratio": 0.88,
                            "rms": 0.05,
                            "threshold": 0.02,
                        },
                        "sound_suggestion": {
                            "sound_type": "unwritten_vocal_melisma",
                            "suggested_caption": "[vocalizacao]",
                            "suggested_user_action": "review_or_add_non_lyric_vocal_caption",
                        },
                    },
                }
            ]

            with patch("scripts.s06_generate_ass.build_audio_activity_map", return_value={}):
                with patch("scripts.s06_generate_ass.build_audio_backed_timing", return_value=fake_timing):
                    exit_code = self._run_stage06(job_dir, "--preset", "single-style-kf")

            self.assertEqual(exit_code, 0)
            manifest = json.loads((job_dir / "output.ass.manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["timing_audio_layers"]["diagnostics"],
                [
                    {
                        "line_index": 0,
                        "tail_classification": "unwritten_interline_melisma",
                        "confidence": "medium",
                        "recommended_fallback": "flag_review_or_create_extension_bar",
                        "audio_evidence": {
                            "active": True,
                            "start_s": 298.64,
                            "end_s": 300.12,
                            "duration_s": 1.48,
                            "voiced_ratio": 0.88,
                            "rms": 0.05,
                            "threshold": 0.02,
                        },
                        "sound_suggestion": {
                            "sound_type": "unwritten_vocal_melisma",
                            "suggested_caption": "[vocalizacao]",
                            "suggested_user_action": "review_or_add_non_lyric_vocal_caption",
                        },
                    }
                ],
            )

    def test_stage06_manifest_keeps_structural_pause_override_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            lines = [
                {
                    "text": "Past the fear",
                    "start": 160.14,
                    "end": 161.24,
                    "style": "prechorus",
                    "effect": "highlight",
                    "words": [
                        {"word": "Past", "start": 160.14, "end": 160.48},
                        {"word": "the", "start": 160.54, "end": 160.62},
                        {"word": "fear", "start": 160.72, "end": 161.24},
                    ],
                }
            ]
            self._write_analysis(job_dir, lines)
            (job_dir / "vocals.wav").write_bytes(b"not-a-real-wav-but-present")
            fake_timing = [
                {
                    "inter_word_gaps": [],
                    "vocal_periods": [],
                    "tail": {
                        "classification": "probable_unwritten_vowel_extension",
                        "confidence": "high",
                        "structural_tail_classification": "instrumental_pause",
                        "review_flags": ["structural_pause_overridden_by_audio_tail"],
                        "audio_evidence": {
                            "active": True,
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
                    },
                }
            ]

            with patch("scripts.s06_generate_ass.build_audio_activity_map", return_value={}):
                with patch("scripts.s06_generate_ass.build_audio_backed_timing", return_value=fake_timing):
                    exit_code = self._run_stage06(job_dir, "--preset", "single-style-kf")

            self.assertEqual(exit_code, 0)
            manifest = json.loads((job_dir / "output.ass.manifest.json").read_text(encoding="utf-8"))
            diagnostic = manifest["timing_audio_layers"]["diagnostics"][0]
            self.assertEqual(diagnostic["tail_classification"], "probable_unwritten_vowel_extension")
            self.assertEqual(diagnostic["structural_tail_classification"], "instrumental_pause")
            self.assertEqual(diagnostic["review_flags"], ["structural_pause_overridden_by_audio_tail"])
            self.assertEqual(diagnostic["audio_evidence"]["end_s"], 166.48)

    def test_stage06_manifest_uses_manual_run_id_when_status_json_is_not_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir, [self._sample_line()])
            (job_dir / "status.json").write_text("[]", encoding="utf-8")

            exit_code = self._run_stage06(job_dir, "--preset", "section-coded")

            self.assertEqual(exit_code, 0)
            manifest = json.loads(
                (job_dir / "output.ass.manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["run_id"], "manual")

    def test_stage06_ass_written_event_includes_manifest_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_analysis(job_dir, [self._sample_line()])

            exit_code = self._run_stage06(job_dir, "--preset", "section-coded")

            self.assertEqual(exit_code, 0)
            manifest_path = job_dir / "output.ass.manifest.json"
            events = read_events(job_dir)
            ass_written = next(
                event for event in events
                if event["event"] == "stage06.ass_written"
            )
            self.assertEqual(
                ass_written["details"].get("manifest_path"),
                str(manifest_path),
            )
            self.assertEqual(
                ass_written["details"].get("manifest_sha256"),
                file_sha256(manifest_path),
            )

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
