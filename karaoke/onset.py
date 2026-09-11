"""
onset.py — Deteccao de ataques (onsets) por energia. Logica pura.
No subprocess, no file I/O.

Unico dono de compute_rms/detect_onsets. Nasceram em scripts/08_onset_dtw.py
(que nao e importavel: comeca com digito) e foram movidas para ca em 2026-09-11;
o script agora importa daqui. Os valores das constantes sao os originais.
"""
from __future__ import annotations

import numpy as np

WIN_MS = 25            # janela de analise
HOP_MS = 10            # passo entre janelas
ONSET_THRESHOLD = 0.008  # derivada minima do RMS para contar como ataque
MIN_GAP_S = 0.08       # gap minimo entre dois ataques
ENERGY_MIN = 0.02      # RMS minimo absoluto: evita ataque em ruido de fundo


def compute_rms(samples: np.ndarray, sr: int) -> tuple[np.ndarray, float]:
    """RMS janela a janela. Devolve (rms, duracao_do_frame_em_segundos)."""
    hop = int(sr * HOP_MS / 1000)
    win = int(sr * WIN_MS / 1000)
    rms = [
        float(np.sqrt(np.mean(samples[i:i + win] ** 2)))
        for i in range(0, len(samples) - win, hop)
    ]
    return np.asarray(rms, dtype=np.float64), hop / sr


def detect_onsets(rms: np.ndarray, frame_dur: float) -> np.ndarray:
    """Ataque = derivada do RMS acima do limiar, com energia suficiente e
    respeitando o gap minimo desde o ataque anterior."""
    if len(rms) < 2:
        return np.empty(0, dtype=np.float64)
    drms = np.diff(rms)
    onsets: list[float] = []
    last = -1.0
    for i, d in enumerate(drms):
        t = i * frame_dur
        if d > ONSET_THRESHOLD and rms[i + 1] > ENERGY_MIN and (t - last) > MIN_GAP_S:
            onsets.append(t)
            last = t
    return np.asarray(onsets, dtype=np.float64)
