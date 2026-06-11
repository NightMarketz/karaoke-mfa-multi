from __future__ import annotations

import os
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np


@dataclass(frozen=True)
class VocalActivityProbe:
    frame_times_s: np.ndarray
    frame_rms: np.ndarray
    threshold: float

    @classmethod
    def from_wav(
        cls,
        path: Path,
        *,
        frame_s: float = 0.04,
        hop_s: float = 0.02,
    ) -> "VocalActivityProbe":
        samples, sample_rate = _read_wav_mono(path)
        frame_size = max(1, int(sample_rate * frame_s))
        hop_size = max(1, int(sample_rate * hop_s))
        if len(samples) < frame_size:
            samples = np.pad(samples, (0, frame_size - len(samples)))

        rms_values = []
        times = []
        for start in range(0, max(1, len(samples) - frame_size + 1), hop_size):
            frame = samples[start : start + frame_size]
            rms_values.append(float(np.sqrt(np.mean(frame * frame))))
            times.append((start + frame_size / 2) / sample_rate)

        frame_rms = np.asarray(rms_values, dtype=np.float32)
        threshold = _activity_threshold(frame_rms)
        return cls(
            frame_times_s=np.asarray(times, dtype=np.float32),
            frame_rms=frame_rms,
            threshold=threshold,
        )

    def interval_stats(self, start_s: float, end_s: float) -> dict[str, Any]:
        start_s = max(0.0, float(start_s))
        end_s = max(start_s, float(end_s))
        mask = (self.frame_times_s >= start_s) & (self.frame_times_s <= end_s)
        if not bool(np.any(mask)):
            return {
                "start_s": round(start_s, 3),
                "end_s": round(end_s, 3),
                "duration_s": round(end_s - start_s, 3),
                "voiced_ratio": 0.0,
                "rms": 0.0,
                "threshold": round(float(self.threshold), 8),
                "active": False,
            }

        rms = self.frame_rms[mask]
        voiced_ratio = float(np.mean(rms >= self.threshold))
        interval_rms = float(np.sqrt(np.mean(rms * rms)))
        return {
            "start_s": round(start_s, 3),
            "end_s": round(end_s, 3),
            "duration_s": round(end_s - start_s, 3),
            "voiced_ratio": round(voiced_ratio, 3),
            "rms": round(interval_rms, 8),
            "threshold": round(float(self.threshold), 8),
            "active": voiced_ratio >= 0.45,
        }

    def voiced_regions(
        self,
        start_s: float,
        end_s: float,
        *,
        min_duration_s: float = 0.20,
        merge_gap_s: float = 0.12,
    ) -> list[dict[str, float | bool]]:
        start_s = max(0.0, float(start_s))
        end_s = max(start_s, float(end_s))
        if end_s <= start_s:
            return []

        frame_count = min(len(self.frame_times_s), len(self.frame_rms))
        if frame_count == 0:
            return []

        frame_times = self.frame_times_s[:frame_count]
        frame_rms = self.frame_rms[:frame_count]
        window_mask = (frame_times >= start_s) & (frame_times <= end_s)
        frame_indices = np.flatnonzero(window_mask)
        if frame_indices.size == 0:
            return []

        if frame_count > 1:
            frame_hop_s = float(np.median(np.diff(frame_times)))
        else:
            frame_hop_s = 0.0
        half_frame_s = max(0.0, frame_hop_s / 2.0)

        active_spans: list[tuple[int, int]] = []
        span_start: int | None = None
        for frame_index in frame_indices:
            is_active = bool(frame_rms[frame_index] >= self.threshold)
            if is_active and span_start is None:
                span_start = int(frame_index)
            elif not is_active and span_start is not None:
                active_spans.append((span_start, int(frame_index)))
                span_start = None
        if span_start is not None:
            active_spans.append((span_start, int(frame_indices[-1]) + 1))

        merged: list[tuple[int, int]] = []
        for span_start_frame, span_end_frame in active_spans:
            if not merged:
                merged.append((span_start_frame, span_end_frame))
                continue

            previous_start, previous_end = merged[-1]
            gap_s = float(frame_times[span_start_frame] - frame_times[previous_end - 1])
            if gap_s > merge_gap_s:
                merged.append((span_start_frame, span_end_frame))
            else:
                merged[-1] = (previous_start, span_end_frame)

        regions: list[dict[str, float | bool]] = []
        for span_start_frame, span_end_frame in merged:
            region_start = max(start_s, float(frame_times[span_start_frame]) - half_frame_s)
            region_end = min(end_s, float(frame_times[span_end_frame - 1]) + half_frame_s)
            duration = max(0.0, region_end - region_start)
            if duration < min_duration_s:
                continue
            stats = self.interval_stats(region_start, region_end)
            regions.append(
                {
                    "start_s": round(region_start, 3),
                    "end_s": round(region_end, 3),
                    "duration_s": round(duration, 3),
                    "voiced_ratio": stats["voiced_ratio"],
                    "rms": stats["rms"],
                    "threshold": stats["threshold"],
                    "active": bool(stats["active"]),
                }
            )
        return regions


def _activity_threshold(frame_rms: np.ndarray) -> float:
    if frame_rms.size == 0:
        return 1e-5
    noise_floor = float(np.percentile(frame_rms, 20))
    strong = float(np.percentile(frame_rms, 95))
    noise_based = min(noise_floor * 3.0, strong * 0.50)
    return max(1e-5, noise_based, strong * 0.08)


def _read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())

    if sample_width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data.astype(np.float32), sample_rate
