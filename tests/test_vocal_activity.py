import math
import tempfile
import unittest
import wave
from pathlib import Path

from tests._optional_imports import import_or_skip

import_or_skip("numpy")
from scripts.review_wizard.vocal_activity import VocalActivityProbe
from scripts.review_wizard.timing_layers import build_audio_activity_map, build_audio_backed_timing


def _write_sine_window(path: Path, *, duration_s: float, active_start_s: float, active_end_s: float) -> None:
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


class VocalActivityProbeTests(unittest.TestCase):
    def test_finds_contiguous_voiced_regions_inside_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "vocals.wav"
            _write_sine_window(wav_path, duration_s=5.0, active_start_s=1.0, active_end_s=2.4)

            probe = VocalActivityProbe.from_wav(wav_path)
            regions = probe.voiced_regions(0.5, 3.0)

            self.assertEqual(len(regions), 1)
            self.assertAlmostEqual(regions[0]["start_s"], 1.0, delta=0.12)
            self.assertAlmostEqual(regions[0]["end_s"], 2.4, delta=0.12)
            self.assertGreater(regions[0]["voiced_ratio"], 0.80)

    def test_ignores_short_vocal_noise_regions(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "vocals.wav"
            _write_sine_window(wav_path, duration_s=3.0, active_start_s=1.0, active_end_s=1.08)

            probe = VocalActivityProbe.from_wav(wav_path)
            regions = probe.voiced_regions(0.5, 2.0, min_duration_s=0.20)

            self.assertEqual(regions, [])

    def test_detects_voiced_interval_from_vocals_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "vocals.wav"
            _write_sine_window(wav_path, duration_s=2.0, active_start_s=0.5, active_end_s=1.2)

            probe = VocalActivityProbe.from_wav(wav_path)
            voiced = probe.interval_stats(0.55, 1.1)
            silent = probe.interval_stats(1.45, 1.8)

            self.assertTrue(voiced["active"])
            self.assertGreater(voiced["voiced_ratio"], 0.8)
            self.assertFalse(silent["active"])
            self.assertLess(silent["voiced_ratio"], 0.2)

    def test_detects_continuous_synthetic_vocal_without_silent_noise_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "vocals.wav"
            _write_sine_window(wav_path, duration_s=2.0, active_start_s=0.0, active_end_s=2.0)

            probe = VocalActivityProbe.from_wav(wav_path)
            voiced = probe.interval_stats(0.2, 1.8)

            self.assertTrue(voiced["active"])
            self.assertGreater(voiced["voiced_ratio"], 0.8)

    def test_audio_activity_map_detects_tail_voice_after_word_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "vocals.wav"
            _write_sine_window(wav_path, duration_s=3.0, active_start_s=0.9, active_end_s=2.1)
            lines = [
                {
                    "text": "About to snap",
                    "style": "prechorus",
                    "words": [{"word": "snap", "start": 0.5, "end": 0.8}],
                },
                {
                    "text": "So burn it all",
                    "style": "chorus",
                    "start": 2.4,
                    "words": [{"word": "So", "start": 2.4, "end": 2.6}],
                },
            ]

            activity = build_audio_activity_map(lines, wav_path)
            timing = build_audio_backed_timing(lines, audio_activity=activity)[0]

            self.assertTrue(activity[("tail", 0)]["active"])
            self.assertEqual(timing["tail"]["classification"], "probable_unwritten_vowel_extension")


if __name__ == "__main__":
    unittest.main()
