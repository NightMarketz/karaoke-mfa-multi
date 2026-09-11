"""
scorer.py — Pontuacao de imitacao e canto. Logica pura.
No subprocess, no file I/O.

Os dois modos do jogo (imitar som cru, cantar trecho com letra) convergem para
ReferenceTrack; score() nao sabe de qual modo o track veio.
"""
from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

from karaoke.onset import compute_rms, detect_onsets

# ── Knobs de calibracao ──────────────────────────────────────────────────────
MELODY_POINTS = 200        # contornos sao reamostrados para este tamanho comum
MIN_VOICED_FRAMES = 10     # abaixo disso nao ha contorno para comparar
F0_MIN_HZ = 65.0           # ~C2
F0_MAX_HZ = 1000.0         # ~B5


@dataclass
class ReferenceTrack:
    onsets: np.ndarray      # instantes de ataque, em segundos
    semitones: np.ndarray   # contorno de f0 em semitons centrado na mediana (so voiced)
    frame_dur: float        # hop do RMS/onsets (10 ms). NAO e a grade de `semitones`:
                            # pyin usa hop proprio (512/sr = 32 ms a 16 kHz).
                            # ponytail: passar hop_length=int(sr*HOP_MS/1000) ao pyin
                            # alinha as duas grades quando algo precisar de contorno
                            # indexado por tempo; hoje score() reamostra por indice.
    duration: float
    n_voiced: int           # denominador do contorno
    n_frames: int           # total de frames analisados pelo pyin
    n_octave_suspect: int   # frames com |semitom| > 11: suspeita de erro de oitava do pyin


def track_from_audio(samples: np.ndarray, sr: int) -> ReferenceTrack:
    """Extrai ataques e contorno de f0 de um audio mono."""
    samples = np.asarray(samples, dtype=np.float32)
    # Normaliza por pico ANTES de detectar: os limiares de karaoke/onset.py
    # (ENERGY_MIN, ONSET_THRESHOLD) sao absolutos em amplitude. Medido em
    # 2026-09-11 no vocals_raw.wav de 60s (pico a 0.316 do fundo de escala):
    # 163 ataques normalizado, 39 cru. Mic com ganho desconhecido seria pontuado
    # de forma inconsistente sem isto. Silencio absoluto fica silencio (1e-8).
    samples = samples / (np.abs(samples).max() + 1e-8)
    rms, frame_dur = compute_rms(samples, sr)
    onsets = detect_onsets(rms, frame_dur)

    f0, voiced, _ = librosa.pyin(samples, fmin=F0_MIN_HZ, fmax=F0_MAX_HZ, sr=sr)
    n_frames = int(len(f0))
    vals = f0[voiced]
    n_voiced = int(len(vals))
    if n_voiced >= MIN_VOICED_FRAMES:
        semitones = 12.0 * np.log2(vals / np.nanmedian(vals))
    else:
        semitones = np.empty(0, dtype=np.float64)
    semitones = np.asarray(semitones, dtype=np.float64)

    # Risco declarado no spec: pyin erra oitava em voz cantada separada pelo Demucs.
    # Medido em 2026-09-10 no material real: 59 de 1207 frames voiced (4.9%). Nao
    # corrigimos a oitava aqui — contamos, para que o erro seja VISIVEL em vez de
    # silenciosamente embutido na nota.
    n_octave_suspect = int(np.sum(np.abs(semitones) > 11.0)) if len(semitones) else 0

    return ReferenceTrack(
        onsets=onsets,
        semitones=semitones,
        frame_dur=frame_dur,
        duration=len(samples) / sr,
        n_voiced=n_voiced,
        n_frames=n_frames,
        n_octave_suspect=n_octave_suspect,
    )
