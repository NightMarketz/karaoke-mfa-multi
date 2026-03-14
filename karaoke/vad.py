"""
vad.py — Simple Voice Activity Detection based on energy and percentile adaptive threshold.
Optimized for clean vocals_raw.wav (stems from separator).
"""
from __future__ import annotations
import wave
import struct
import math
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class VADConfig:
    """Tunable parameters for voice activity detection."""
    vad_hop_ms:          int = 10      # Window hop in milliseconds
    vad_win_ms:          int = 30      # Window size in milliseconds
    vad_energy_db:       float = -45.0 # Baseline floor in dB
    vad_min_speech_ms:   int = 150     # Min duration for speech segment
    vad_min_silence_ms:  int = 200     # Min duration for silence between speech
    vad_pad_ms:          int = 100     # Padding around detected segments


@dataclass
class VADSegment:
    """A time interval where voice activity was detected."""
    start: float
    end:   float

    @property
    def duration(self) -> float:
        return self.end - self.start


def voice_overlap_ratio(start: float, end: float, vad_segments: List[VADSegment]) -> float:
    """Calculate what ratio of the [start, end] interval is covered by voice."""
    word_dur = end - start
    if word_dur <= 0:
        return 0.0
        
    overlap = 0.0
    for seg in vad_segments:
        ov_start = max(start, seg.start)
        ov_end   = min(end,   seg.end)
        if ov_end > ov_start:
            overlap += ov_end - ov_start

    return min(1.0, overlap / word_dur)


def _get_rms(samples: list[int]) -> float:
    """Calculate Root Mean Square energy."""
    if not samples:
        return 0.0
    sum_squares = sum(s*s for s in samples)
    return math.sqrt(sum_squares / len(samples))


def _rms_to_db(rms: float) -> float:
    """Convert RMS energy to decibels (relative to 32768 full scale)."""
    if rms <= 0:
        return -100.0
    # Ref 32768 for 16-bit PCM
    return 20 * math.log10(rms / 32768.0)


def detect_voice(wav_path: str, config: VADConfig | None = None) -> Tuple[List[VADSegment], dict]:
    """
    Perform VAD using energy tracking and adaptive percentile thresholding.
    Returns (segments, stats_dict).
    """
    if config is None:
        config = VADConfig()

    with wave.open(wav_path, "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        n_frames = wf.getnframes()
        total_duration = n_frames / sample_rate
        
        # Read all frames at once (assuming small VOCAL files)
        raw_data = wf.readframes(n_frames)
        # Assuming 16-bit PCM
        samples = list(struct.unpack(f"<{n_frames * n_channels}h", raw_data))
        
        # If stereo, mix to mono
        if n_channels == 2:
            mono_samples = []
            for i in range(0, len(samples), 2):
                mono_samples.append((samples[i] + samples[i+1]) // 2)
            samples = mono_samples

    # Step 1: Calculate energy per window
    win_size = int(sample_rate * (config.vad_win_ms / 1000.0))
    hop_size = int(sample_rate * (config.vad_hop_ms / 1000.0))
    
    energies = []
    for i in range(0, len(samples) - win_size, hop_size):
        win = samples[i : i + win_size]
        energies.append(_rms_to_db(_get_rms(win)))
        
    if not energies:
        return [], {}

    # Step 2: Adaptive Threshold
    # We look at the energy distribution to find the floor.
    energies_sorted = sorted(energies)
    p10 = energies_sorted[int(len(energies) * 0.10)]
    p50 = energies_sorted[int(len(energies) * 0.50)]
    p90 = energies_sorted[int(len(energies) * 0.90)]
    avg = sum(energies) / len(energies)

    # For bass-heavy/drone tracks (metal, industrial), p10 can be high (-20dB)
    # because the instrument floor is elevated. The old formula (p10 + 8dB) would
    # push the threshold above actual vocal energy → false silences.
    #
    # New strategy: use the LOWER of two candidates:
    #   A. fixed floor + small margin (config.vad_energy_db + 4dB)
    #   B. p10 + 6dB  (noise-adaptive)
    # Then cap at p50 to avoid masking quieter vocal sections.
    candidate_a    = config.vad_energy_db + 4.0
    candidate_b    = p10 + 6.0
    dynamic_thresh = min(candidate_a, candidate_b)
    dynamic_thresh = min(dynamic_thresh, p50)      # never above median energy

    stats = {
        "p10_db":        round(p10, 2),
        "p50_db":        round(p50, 2),
        "p90_db":        round(p90, 2),
        "avg_db":        round(avg, 2),
        "fixed_thresh":  config.vad_energy_db,
        "applied_thresh": round(dynamic_thresh, 2),
    }

    # Step 3: Boolean Mask
    mask = [e > dynamic_thresh for e in energies]

    # Step 4: Smoothing (Moron filter style)
    mask = _smooth_mask(
        mask, config.vad_hop_ms, config.vad_min_speech_ms, config.vad_min_silence_ms
    )

    # Step 5: convert to segments with padding
    segments = _mask_to_segments(
        mask, config.vad_hop_ms, config.vad_pad_ms, total_duration
    )

    return segments, stats


def _smooth_mask(mask: list[bool], hop_ms: int, min_speech_ms: int, min_silence_ms: int) -> list[bool]:
    """Remove short spikes and fill short gaps."""
    min_speech_frames = max(1, min_speech_ms // hop_ms)
    min_silence_frames = max(1, min_silence_ms // hop_ms)
    
    result = list(mask)
    
    # Fill gaps
    i = 0
    while i < len(result):
        if result[i] is True:
            # find next true
            j = i + 1
            while j < len(result) and result[j] is False:
                j += 1
            if j < len(result) and (j - i - 1) <= min_silence_frames:
                for k in range(i + 1, j):
                    result[k] = True
            i = j
        else:
            i += 1
            
    # Remove spikes
    i = 0
    while i < len(result):
        if result[i] is True:
            j = i
            while j < len(result) and result[j] is True:
                j += 1
            if (j - i) < min_speech_frames:
                for k in range(i, j):
                    result[k] = False
            i = j
        else:
            i += 1
            
    return result


def _mask_to_segments(
    mask: list[bool],
    hop_ms: int,
    pad_ms: int,
    total_duration: float,
) -> List[VADSegment]:
    """Convert boolean mask to time-based VADSegments with padding."""
    hop_sec = hop_ms / 1000.0
    pad_sec = pad_ms / 1000.0
    segments: List[VADSegment] = []
    
    i = 0
    while i < len(mask):
        if mask[i]:
            start_idx = i
            while i < len(mask) and mask[i]:
                i += 1
            end_idx = i

            start_t = max(0.0, start_idx * hop_sec - pad_sec)
            end_t   = min(total_duration, end_idx * hop_sec + pad_sec)

            # Merge with previous segment if overlapping after padding
            if segments and start_t <= segments[-1].end:
                segments[-1] = VADSegment(segments[-1].start, end_t)
            else:
                segments.append(VADSegment(start_t, end_t))
        else:
            i += 1

    return segments