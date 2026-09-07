from __future__ import annotations

import json
import math
import tempfile
import unittest
import wave
from pathlib import Path

from scripts import s03b_lyrics_align


class InnerBeastGoldenTests(unittest.TestCase):
    def test_clean_lyrics_match_reference_lines(self) -> None:
        root = Path(__file__).parent / "golden" / "inner-beast"
        lyrics_lines = s03b_lyrics_align._parse_lyrics(root / "lyrics.txt")
        reference_lines = json.loads((root / "reference_timestamps.json").read_text(encoding="utf-8"))["lines"]

        self.assertEqual([line["text"] for line in lyrics_lines], [line["text"] for line in reference_lines])

    def test_reference_retiming_pins_line_starts_and_preserves_order(self) -> None:
        segments = [
            {
                "text": "first line",
                "start": 1.0,
                "end": 12.0,
                "words": [
                    {"word": "first", "start": 1.0, "end": 10.0},
                    {"word": "line", "start": 10.2, "end": 12.0},
                ],
            },
            {
                "text": "next line",
                "start": 13.0,
                "end": 14.0,
                "words": [{"word": "next", "start": 13.0, "end": 14.0}],
            },
        ]

        retimed = s03b_lyrics_align._retime_segments_to_reference_starts(segments, [70.5, 72.0])

        self.assertEqual(retimed[0]["start"], 70.5)
        self.assertEqual(retimed[1]["start"], 72.0)
        self.assertLess(retimed[0]["words"][0]["start"], retimed[0]["words"][0]["end"])
        self.assertLessEqual(retimed[0]["words"][0]["end"], retimed[0]["words"][1]["start"])
        self.assertLess(retimed[0]["end"], retimed[1]["start"])

    def test_vocal_regions_artifact_records_regions_and_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "vocals.wav"
            self._write_sine_window(wav_path, duration_s=5.0, active_start_s=1.0, active_end_s=2.4)

            artifact = s03b_lyrics_align._build_vocal_regions_artifact(wav_path)

            self.assertTrue(artifact["regions"])
            self.assertTrue(artifact["non_vocal_gaps"])

    def _write_sine_window(self, path: Path, *, duration_s: float, active_start_s: float, active_end_s: float) -> None:
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
                payload.extend(int(max(-1.0, min(1.0, amp)) * 32767).to_bytes(2, "little", signed=True))
            handle.writeframes(bytes(payload))


if __name__ == "__main__":
    unittest.main()
