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


# ── Knobs de nota ────────────────────────────────────────────────────────────
# Tolerancia de ritmo RELATIVA ao intervalo mediano da referencia, com piso
# absoluto. Medido em 2026-09-10: no modo karaoke o intervalo mediano entre
# palavras e 0,140s, entao uma tolerancia absoluta de 200ms seria maior que o
# proprio intervalo medido e a nota de ritmo ficaria vazia.
RHYTHM_TOL_RATIO = 0.35
RHYTHM_TOL_FLOOR_S = 0.050
WEIGHTS = {"melody": 0.45, "rhythm": 0.35, "attacks": 0.20}


@dataclass
class ScoreReport:
    melody: float           # 0..100
    rhythm: float           # 0..100
    attacks: float          # 0..100
    total: float            # 0..100
    n_onsets_ref: int
    n_onsets_take: int
    n_frames_compared: int  # zero e FALHA, nao sucesso
    rhythm_tol_s: float     # tolerancia efetivamente usada, para auditoria


def _resample(contour: np.ndarray, n: int = MELODY_POINTS) -> np.ndarray:
    return np.interp(np.linspace(0.0, 1.0, n),
                     np.linspace(0.0, 1.0, len(contour)),
                     contour)


def score(ref: ReferenceTrack, take: ReferenceTrack) -> ScoreReport:
    """Compara forma relativa, nunca alinhamento absoluto: um atraso global
    constante na captura nao altera nota nenhuma."""
    n_ref, n_take = len(ref.onsets), len(take.onsets)

    # ataques: quanto as contagens batem
    attacks = 100.0 * max(0.0, 1.0 - abs(n_ref - n_take) / max(n_ref, n_take, 1))

    # ritmo: intervalos ENTRE ataques, nao instantes
    tol = RHYTHM_TOL_FLOOR_S
    if n_ref >= 2 and n_take >= 2:
        iv_ref = np.diff(ref.onsets)
        iv_take = np.diff(take.onsets)
        tol = max(RHYTHM_TOL_FLOOR_S, RHYTHM_TOL_RATIO * float(np.median(iv_ref)))
        k = min(len(iv_ref), len(iv_take))
        mad = float(np.mean(np.abs(iv_ref[:k] - iv_take[:k])))
        rhythm = 100.0 * max(0.0, 1.0 - mad / tol)
    else:
        rhythm = 0.0

    # melodia: correlacao dos contornos centrados, reamostrados a tamanho comum
    if len(ref.semitones) >= MIN_VOICED_FRAMES and len(take.semitones) >= MIN_VOICED_FRAMES:
        r = float(np.corrcoef(_resample(ref.semitones), _resample(take.semitones))[0, 1])
        melody = 0.0 if np.isnan(r) else 100.0 * max(0.0, r)
        n_frames_compared = MELODY_POINTS
    else:
        melody = 0.0
        n_frames_compared = 0

    total = (WEIGHTS["melody"] * melody
             + WEIGHTS["rhythm"] * rhythm
             + WEIGHTS["attacks"] * attacks)

    return ScoreReport(
        melody=melody, rhythm=rhythm, attacks=attacks, total=total,
        n_onsets_ref=n_ref, n_onsets_take=n_take,
        n_frames_compared=n_frames_compared, rhythm_tol_s=tol,
    )


def track_from_word_timing(words: list[dict], samples: np.ndarray,
                           sr: int) -> ReferenceTrack:
    """Referencia do modo karaoke: ataques vem do gabarito alinhado
    (work/jobs/<id>/05_alignment/word_timing.json), contorno vem do audio vocal.

    Precisao medida do gabarito em 2026-09-10: 66% das palavras a <=100ms de um
    ataque detectado, contra 47% do acaso. A nota herda esse erro — o modo karaoke
    e "melhor que acaso", nao "correto".
    """
    if not words:
        raise ValueError("word_timing vazio: gabarito sem palavras nao produz referencia")

    starts = np.asarray([float(w["start"]) for w in words], dtype=np.float64)
    if np.any(np.diff(starts) < 0):
        fora = int(np.sum(np.diff(starts) < 0))
        raise ValueError(
            f"word_timing nao e monotonico: {fora} de {len(starts) - 1} pares fora de ordem"
        )

    base = track_from_audio(samples, sr)
    return ReferenceTrack(
        onsets=starts,
        semitones=base.semitones,
        frame_dur=base.frame_dur,
        duration=base.duration,
        n_voiced=base.n_voiced,
        n_frames=base.n_frames,
        n_octave_suspect=base.n_octave_suspect,
    )
