import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import hw_detect


class HardwareDetectConfigTests(unittest.TestCase):
    def _write_config(self, path: Path, profile: str = "auto") -> None:
        path.write_text(
            "\n".join(
                [
                    "[hardware]",
                    f'profile = "{profile}"',
                    "[hardware.z13]",
                    'demix_device = "directml"',
                    'demix_compute = "float16"',
                    "demix_segment = 5",
                    "demix_jobs = 1",
                    'transcribe_device = "cpu"',
                    'transcribe_compute = "int8"',
                    "transcribe_beam_size = 1",
                    "transcribe_vad = false",
                    'align_device = "directml"',
                    "align_batch_size = 12",
                    'ollama_model = "configured-z13-model"',
                    "ollama_num_ctx = 3072",
                    "ollama_num_thread = 5",
                    'ffmpeg_vcodec = "h264_amf"',
                    "ffmpeg_quality = 21",
                    "[hardware.cpu_only]",
                    'demix_device = "cpu"',
                    'demix_compute = "float32"',
                    "demix_segment = 9",
                    "demix_jobs = 2",
                    'transcribe_device = "cpu"',
                    'transcribe_compute = "int8"',
                    "transcribe_beam_size = 1",
                    "transcribe_vad = false",
                    'align_device = "cpu"',
                    "align_batch_size = 6",
                    'ollama_model = "configured-cpu-model"',
                    "ollama_num_ctx = 1024",
                    "ollama_num_thread = 7",
                    'ffmpeg_vcodec = "libx264"',
                    "ffmpeg_quality = 24",
                ]
            ),
            encoding="utf-8",
        )

    def test_detect_reads_forced_z13_profile_from_pipeline_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pipeline.toml"
            self._write_config(config_path, profile="z13")

            with patch("scripts.hw_detect._check_directml", return_value=False), patch(
                "scripts.hw_detect._check_amf", return_value=False
            ):
                profile = hw_detect.detect(config_path=config_path)

        self.assertEqual(profile.demix_device, "directml")
        self.assertEqual(profile.demix_segment, 5)
        self.assertEqual(profile.align_batch_size, 12)
        self.assertEqual(profile.ollama_model, "configured-z13-model")
        self.assertEqual(profile.ollama_num_ctx, 3072)
        self.assertEqual(profile.ffmpeg_vcodec, "h264_amf")
        self.assertTrue(profile.directml_available)
        self.assertTrue(profile.amf_available)

    def test_detect_auto_uses_cpu_safe_values_when_gpu_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "pipeline.toml"
            self._write_config(config_path, profile="auto")

            with patch("scripts.hw_detect._check_directml", return_value=False), patch(
                "scripts.hw_detect._check_amf", return_value=False
            ):
                profile = hw_detect.detect(config_path=config_path)

        self.assertEqual(profile.demix_device, "cpu")
        self.assertEqual(profile.demix_segment, 9)
        self.assertEqual(profile.align_device, "cpu")
        self.assertEqual(profile.align_batch_size, 6)
        self.assertEqual(profile.ollama_model, "configured-z13-model")
        self.assertEqual(profile.ffmpeg_vcodec, "libx264")
        self.assertEqual(profile.ffmpeg_quality, 24)
        self.assertFalse(profile.directml_available)
        self.assertFalse(profile.amf_available)


if __name__ == "__main__":
    unittest.main()
