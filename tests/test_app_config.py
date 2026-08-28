import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.common.config import load_app_config


class AppConfigTests(unittest.TestCase):
    def test_load_app_config_reads_pipeline_toml_server_and_ui_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pipeline.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[general]",
                        'jobs_dir = "custom-jobs"',
                        'log_level = "DEBUG"',
                        "[server]",
                        'host = "127.0.0.1"',
                        "port = 5055",
                        'secret_key = "configured-secret"',
                        "max_upload_mb = 123",
                        "[ui]",
                        'default_style_preset = "section-coded"',
                        "[generate]",
                        'style_preset = "single-style-kf"',
                        'resolution = "1280x720"',
                        "fade_in_ms = 250",
                        "fade_out_ms = 450",
                        "[output]",
                        'audio_codec = "opus"',
                        'audio_bitrate = "160k"',
                        "vocals_volume = 0.8",
                        "instrumental_volume = 0.9",
                        'framerate = "24"',
                        "ffmpeg_timeout_s = 321",
                        "[transcribe]",
                        'model_size = "medium"',
                        'language = "pt"',
                        "low_confidence_threshold = 0.2",
                        "[align]",
                        'hubertfa_dir = "vendor/custom-hubertfa"',
                        'checkpoint = "models/custom.onnx"',
                        'language = "por"',
                        "hubertfa_timeout_s = 222",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_app_config(config_path)

        self.assertEqual(config.jobs_dir, Path("custom-jobs"))
        self.assertEqual(config.log_level, "DEBUG")
        self.assertEqual(config.server_host, "127.0.0.1")
        self.assertEqual(config.server_port, 5055)
        self.assertEqual(config.secret_key, "configured-secret")
        self.assertEqual(config.max_upload_bytes, 123 * 1024 * 1024)
        self.assertEqual(config.default_style_preset_id, "section-coded")
        self.assertEqual(config.generate_style_preset_id, "single-style-kf")
        self.assertEqual(config.generate_resolution, "1280x720")
        self.assertEqual(config.generate_fade_in_ms, 250)
        self.assertEqual(config.generate_fade_out_ms, 450)
        self.assertEqual(config.output_audio_codec, "opus")
        self.assertEqual(config.output_audio_bitrate, "160k")
        self.assertEqual(config.output_vocals_volume, 0.8)
        self.assertEqual(config.output_instrumental_volume, 0.9)
        self.assertEqual(config.output_framerate, "24")
        self.assertEqual(config.output_ffmpeg_timeout_s, 321)
        self.assertEqual(config.transcribe_model_size, "medium")
        self.assertEqual(config.transcribe_language, "pt")
        self.assertEqual(config.transcribe_low_confidence_threshold, 0.2)
        self.assertEqual(config.align_hubertfa_dir, Path("vendor/custom-hubertfa"))
        self.assertEqual(config.align_checkpoint, Path("models/custom.onnx"))
        self.assertEqual(config.align_language, "por")
        self.assertEqual(config.align_hubertfa_timeout_s, 222)

    def test_load_app_config_prefers_environment_over_pipeline_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pipeline.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[general]",
                        'jobs_dir = "toml-jobs"',
                        'log_level = "DEBUG"',
                        "[server]",
                        "port = 5055",
                        "[ui]",
                        'default_style_preset = "section-coded"',
                        "[generate]",
                        'style_preset = "toml-style"',
                        'resolution = "1280x720"',
                        "fade_in_ms = 250",
                        "fade_out_ms = 450",
                        "[output]",
                        'audio_codec = "opus"',
                        'audio_bitrate = "160k"',
                        "vocals_volume = 0.8",
                        "instrumental_volume = 0.9",
                        'framerate = "24"',
                        "ffmpeg_timeout_s = 321",
                        "[transcribe]",
                        'model_size = "medium"',
                        'language = "pt"',
                        "low_confidence_threshold = 0.2",
                        "[align]",
                        'hubertfa_dir = "vendor/custom-hubertfa"',
                        'checkpoint = "models/custom.onnx"',
                        'language = "por"',
                        "hubertfa_timeout_s = 222",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "KARAOKE_JOBS_DIR": "env-jobs",
                    "KARAOKE_LOG_LEVEL": "ERROR",
                    "KARAOKE_SERVER_PORT": "6066",
                    "KARAOKE_DEFAULT_STYLE_PRESET": "single-style-kf",
                    "KARAOKE_GENERATE_STYLE_PRESET": "env-style",
                    "KARAOKE_GENERATE_RESOLUTION": "3840x2160",
                    "KARAOKE_GENERATE_FADE_IN_MS": "350",
                    "KARAOKE_GENERATE_FADE_OUT_MS": "550",
                    "KARAOKE_OUTPUT_AUDIO_CODEC": "flac",
                    "KARAOKE_OUTPUT_AUDIO_BITRATE": "320k",
                    "KARAOKE_OUTPUT_VOCALS_VOLUME": "0.7",
                    "KARAOKE_OUTPUT_INSTRUMENTAL_VOLUME": "0.6",
                    "KARAOKE_OUTPUT_FRAMERATE": "60",
                    "KARAOKE_OUTPUT_FFMPEG_TIMEOUT_S": "654",
                    "KARAOKE_TRANSCRIBE_MODEL_SIZE": "small",
                    "KARAOKE_TRANSCRIBE_LANGUAGE": "ja",
                    "KARAOKE_TRANSCRIBE_LOW_CONFIDENCE_THRESHOLD": "0.15",
                    "KARAOKE_ALIGN_HUBERTFA_DIR": "vendor/env-hubertfa",
                    "KARAOKE_ALIGN_CHECKPOINT": "models/env.onnx",
                    "KARAOKE_ALIGN_LANGUAGE": "jpn",
                    "KARAOKE_ALIGN_HUBERTFA_TIMEOUT_S": "333",
                },
                clear=False,
            ):
                config = load_app_config(config_path)

        self.assertEqual(config.jobs_dir, Path("env-jobs"))
        self.assertEqual(config.log_level, "ERROR")
        self.assertEqual(config.server_port, 6066)
        self.assertEqual(config.default_style_preset_id, "single-style-kf")
        self.assertEqual(config.generate_style_preset_id, "env-style")
        self.assertEqual(config.generate_resolution, "3840x2160")
        self.assertEqual(config.generate_fade_in_ms, 350)
        self.assertEqual(config.generate_fade_out_ms, 550)
        self.assertEqual(config.output_audio_codec, "flac")
        self.assertEqual(config.output_audio_bitrate, "320k")
        self.assertEqual(config.output_vocals_volume, 0.7)
        self.assertEqual(config.output_instrumental_volume, 0.6)
        self.assertEqual(config.output_framerate, "60")
        self.assertEqual(config.output_ffmpeg_timeout_s, 654)
        self.assertEqual(config.transcribe_model_size, "small")
        self.assertEqual(config.transcribe_language, "ja")
        self.assertEqual(config.transcribe_low_confidence_threshold, 0.15)
        self.assertEqual(config.align_hubertfa_dir, Path("vendor/env-hubertfa"))
        self.assertEqual(config.align_checkpoint, Path("models/env.onnx"))
        self.assertEqual(config.align_language, "jpn")
        self.assertEqual(config.align_hubertfa_timeout_s, 333)

    def test_load_app_config_reads_stage_tool_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pipeline.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[demix]",
                        'model = "custom-demucs"',
                        'python = "C:/tools/demucs/python.exe"',
                        "timeout_s = 1200",
                        "[analyze]",
                        'ollama_url = "http://127.0.0.1:11435"',
                        'language = "pt"',
                        "temperature = 0.2",
                        "timeout_s = 700",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_app_config(config_path)

        self.assertEqual(config.demucs_model, "custom-demucs")
        self.assertEqual(config.demucs_python, "C:/tools/demucs/python.exe")
        self.assertEqual(config.demucs_timeout_s, 1200)
        self.assertEqual(config.ollama_url, "http://127.0.0.1:11435")
        self.assertEqual(config.analyze_language, "pt")
        self.assertEqual(config.ollama_temperature, 0.2)
        self.assertEqual(config.ollama_timeout_s, 700)

    def test_load_app_config_reads_new_timeout_fields(self):
        with patch.dict(
            os.environ,
            {
                "KARAOKE_S01_FFPROBE_TIMEOUT_S": "99",
                "KARAOKE_S01_FFMPEG_TIMEOUT_S": "999",
                "KARAOKE_INPUT_FFMPEG_TIMEOUT_S": "77",
                "KARAOKE_GENERATE_ASS_TIMEOUT_S": "88",
                "KARAOKE_VALIDATE_TIMEOUT_S": "66",
            },
            clear=False,
        ):
            cfg = load_app_config()

        self.assertEqual(cfg.s01_ffprobe_timeout_s, 99)
        self.assertEqual(cfg.s01_ffmpeg_timeout_s, 999)
        self.assertEqual(cfg.input_ffmpeg_timeout_s, 77)
        self.assertEqual(cfg.generate_ass_timeout_s, 88)
        self.assertEqual(cfg.validate_timeout_s, 66)

    def test_load_app_config_reads_alignment_display_fields(self):
        with patch.dict(
            os.environ,
            {
                "KARAOKE_CREPE_BATCH_SIZE": "256",
                "KARAOKE_GENERATE_ASS_PREROLL_MS": "150",
                "KARAOKE_GENERATE_ASS_POSTROLL_MS": "400",
                "KARAOKE_GENERATE_ASS_GAP_MS": "30",
            },
            clear=False,
        ):
            cfg = load_app_config()

        self.assertEqual(cfg.crepe_batch_size, 256)
        self.assertEqual(cfg.generate_ass_preroll_ms, 150)
        self.assertEqual(cfg.generate_ass_postroll_ms, 400)
        self.assertEqual(cfg.generate_ass_gap_ms, 30)

    def test_load_app_config_prefers_environment_for_stage_tool_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pipeline.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[demix]",
                        'model = "toml-demucs"',
                        'python = "C:/toml/python.exe"',
                        "timeout_s = 1200",
                        "[analyze]",
                        'ollama_url = "http://toml-host:11434"',
                        'language = "pt"',
                        "temperature = 0.2",
                        "timeout_s = 700",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "KARAOKE_DEMUCS_MODEL": "env-demucs",
                    "KARAOKE_DEMUCS_PYTHON": "C:/env/python.exe",
                    "KARAOKE_DEMUCS_TIMEOUT_S": "1801",
                    "KARAOKE_OLLAMA_URL": "http://env-host:11434",
                    "KARAOKE_ANALYZE_LANGUAGE": "ja",
                    "KARAOKE_OLLAMA_TEMPERATURE": "0.4",
                    "KARAOKE_OLLAMA_TIMEOUT_S": "701",
                },
                clear=False,
            ):
                config = load_app_config(config_path)

        self.assertEqual(config.demucs_model, "env-demucs")
        self.assertEqual(config.demucs_python, "C:/env/python.exe")
        self.assertEqual(config.demucs_timeout_s, 1801)
        self.assertEqual(config.ollama_url, "http://env-host:11434")
        self.assertEqual(config.analyze_language, "ja")
        self.assertEqual(config.ollama_temperature, 0.4)
        self.assertEqual(config.ollama_timeout_s, 701)

    def test_load_app_config_backdrop_toml_false_is_honoured(self):
        # This is the case that would silently break if _env_or_value / _bool_value
        # were reordered: False is a legitimate override, not an absent value.
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pipeline.toml"
            config_path.write_text(
                "\n".join(["[generate]", "backdrop = false"]),
                encoding="utf-8",
            )

            config = load_app_config(config_path)

        self.assertIs(config.generate_backdrop, False)

    def test_load_app_config_backdrop_defaults_to_true_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pipeline.toml"
            config_path.write_text(
                "\n".join(["[generate]", 'style_preset = "single-style-kf"']),
                encoding="utf-8",
            )

            config = load_app_config(config_path)

        self.assertIs(config.generate_backdrop, True)

    def test_load_app_config_backdrop_env_overrides_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pipeline.toml"
            config_path.write_text(
                "\n".join(["[generate]", "backdrop = true"]),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ, {"KARAOKE_GENERATE_BACKDROP": "false"}, clear=False
            ):
                config = load_app_config(config_path)

        self.assertIs(config.generate_backdrop, False)

    def test_load_app_config_backdrop_speed_from_toml_is_a_float(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pipeline.toml"
            config_path.write_text(
                "\n".join(["[generate]", "backdrop_speed = 0.05"]),
                encoding="utf-8",
            )

            config = load_app_config(config_path)

        self.assertEqual(config.generate_backdrop_speed, 0.05)
        self.assertIsInstance(config.generate_backdrop_speed, float)


if __name__ == "__main__":
    unittest.main()
