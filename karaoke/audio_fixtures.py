"""
audio_fixtures.py — Gerador de audio sintetico determinístico para teste do scorer.
Logica pura. Mora em karaoke/ (nao em tests/) porque e usado por tests/test_onset.py,
tests/test_scorer.py e pelo notebook de calibracao.
"""
from __future__ import annotations

import numpy as np

SR = 16000


def bursts(times: list[float], freqs: list[float], dur: float = 0.25,
           sr: int = SR) -> np.ndarray:
    """Sequencia de bursts senoidais com ataque seco e decaimento.

    Verdade de terreno conhecida: um ataque por instante em `times`, f0 igual ao
    `freqs` correspondente. E o que permite testar o scorer sem microfone.
    """
    if len(times) != len(freqs):
        raise ValueError(f"times ({len(times)}) e freqs ({len(freqs)}) diferem")
    if not times:
        raise ValueError("times vazio: fixture sem conteudo nao valida nada")
    total = max(times) + dur + 0.3
    out = np.zeros(int(total * sr), dtype=np.float32)
    for t, f in zip(times, freqs):
        i0 = int(t * sr)
        k = int(dur * sr)
        tt = np.arange(k) / sr
        env = np.minimum(1.0, np.exp(-3 * tt) + 0.15)
        out[i0:i0 + k] += (0.6 * env * np.sin(2 * np.pi * f * tt)).astype(np.float32)
    return np.clip(out, -1.0, 1.0)
