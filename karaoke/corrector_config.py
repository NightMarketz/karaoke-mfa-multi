"""
corrector_config.py — Tunable parameters for the MusicGapCorrector.

All values chosen for "real music karaoke" (metal, electronic, pop).
Override via constructor or external config if needed.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class CorrectorConfig:
    """Configuration for VAD + MusicGapCorrector."""

    # ── Line splitting ───────────────────────────────────────────────────
    max_gap_sec: float = 1.5
    """Gap between words > this → insert line break (instrumental break)."""

    # ── Word duration clamping ───────────────────────────────────────────
    max_word_sec_voice: float = 4.0
    """Max word duration when word overlaps mostly with voice activity.
    (Relatively relaxed for sustained musical notes)"""

    max_word_sec_silence: float = 2.0
    """Max word duration when word is mostly outside voice activity.
    (Clamped to prevent drift across silence)"""

    voice_overlap_threshold: float = 0.5
    """Minimum fraction of word's duration that must overlap VAD-active
    regions for it to be considered 'in voice'."""

    # ── VAD tuning ───────────────────────────────────────────────────────
    vad_pad_ms: int = 160
    """Pad voice regions ±N ms to avoid cutting vocal tails."""

    vad_energy_db: float = -24.0
    """RMS energy floor (dB) below which a frame is silence."""

    vad_frame_ms: int = 20
    """Frame size in ms for energy computation."""

    vad_hop_ms: int = 10
    """Hop size in ms for energy computation."""

    vad_min_speech_ms: int = 250
    """Discard speech blips shorter than this."""

    vad_min_silence_ms: int = 400
    """Close silence gaps shorter than this (merge adjacent speech)."""
