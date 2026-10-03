"""
Partitura da cena reativa: energia do instrumental -> estado, pesos dos 4
loops e ganho da fogueira, quadro a quadro. Logica pura, sem I/O.

Spec: docs/superpowers/specs/2026-09-30-cena-reativa-design.md
"""
from __future__ import annotations

import numpy as np

CALMO, TENSAO, CLIMAX, ESCURO = 0, 1, 2, 3

SUAVIZA_S = 1.5
LIMIAR_TENSAO, SUST_TENSAO_S, MIN_CALMO_S = 0.45, 1.0, 4.0
LIMIAR_CLIMAX, SUST_CLIMAX_S, MIN_TENSAO_S = 0.75, 2.0, 4.0
LIMIAR_DISSIPA, SUST_DISSIPA_S = 0.30, 3.0
LIMIAR_QUEDA, MIN_CLIMAX_S, TETO_CLIMAX_S = 0.55, 3.0, 20.0
DUR_ESCURO_S = 2.5

RAMPA_S, RAMPA_ESCURO_S, RAMPA_CALMO_S = 1.2, 0.6, 2.0
TENSAO_BASE, TENSAO_GANHO = 0.4, 0.6

FOGO_PULSO, FOGO_DECAI_S = 0.25, 0.3


def envelope(rms, frame_dur, fps, duracao):
    n = int(round(duracao * fps))
    rms = np.asarray(rms, dtype=np.float64)
    if n <= 0 or len(rms) == 0:
        return np.zeros(max(n, 0))
    janela = max(1, int(round(SUAVIZA_S / frame_dur)))
    liso = np.convolve(rms, np.ones(janela) / janela, mode="same")
    p10, p90 = np.percentile(liso, [10, 90])
    if p90 - p10 < 1e-6:
        return np.zeros(n)
    idx = np.minimum((np.arange(n) / fps / frame_dur).astype(int), len(liso) - 1)
    return np.clip((liso[idx] - p10) / (p90 - p10), 0.0, 1.0)


def estados(e, fps):
    q = lambda s: int(round(s * fps))  # noqa: E731 — segundos -> quadros
    out = np.empty(len(e), dtype=int)
    s, t_est, t_alto, t_baixo = CALMO, 0, 0, 0
    for i, x in enumerate(e):
        out[i] = s
        t_est += 1
        prox = s
        if s == CALMO:
            t_alto = t_alto + 1 if x > LIMIAR_TENSAO else 0
            if t_alto >= q(SUST_TENSAO_S) and t_est >= q(MIN_CALMO_S):
                prox = TENSAO
        elif s == TENSAO:
            t_alto = t_alto + 1 if x > LIMIAR_CLIMAX else 0
            t_baixo = t_baixo + 1 if x < LIMIAR_DISSIPA else 0
            if t_alto >= q(SUST_CLIMAX_S) and t_est >= q(MIN_TENSAO_S):
                prox = CLIMAX
            elif t_baixo >= q(SUST_DISSIPA_S):
                prox = CALMO
        elif s == CLIMAX:
            if t_est >= q(MIN_CLIMAX_S) and (x < LIMIAR_QUEDA or t_est >= q(TETO_CLIMAX_S)):
                prox = ESCURO
        elif t_est >= q(DUR_ESCURO_S):
            prox = CALMO
        if prox != s:
            s, t_est, t_alto, t_baixo = prox, 0, 0, 0
    return out


def pesos(est, e, fps):
    """Persegue o alvo do estado com rampa linear. Interpolacao convexa entre
    vetores que somam 1 continua somando 1 — por isso nao se limita componente
    a componente."""
    w = np.zeros((len(est), 4))
    atual = np.eye(4)[CALMO]
    for i, s in enumerate(est):
        if s == TENSAO:
            r = TENSAO_BASE + TENSAO_GANHO * float(e[i])
            alvo = np.array([1 - r, r, 0.0, 0.0])
        else:
            alvo = np.eye(4)[s]
        rampa = RAMPA_ESCURO_S if s == ESCURO else RAMPA_CALMO_S if s == CALMO else RAMPA_S
        dist = float(np.abs(alvo - atual).max())
        passo = 1.0 / (rampa * fps)
        atual = alvo.copy() if dist <= passo else atual + (passo / dist) * (alvo - atual)
        w[i] = atual
    return w


def ganho_fogo(onsets, fps, n):
    pulso = np.zeros(n)
    for t in onsets:
        k = int(t * fps)
        if 0 <= k < n:
            pulso[k] = 1.0
    decai = float(np.exp(-1.0 / (FOGO_DECAI_S * fps)))
    v, out = 0.0, np.empty(n)
    for i in range(n):
        v = max(pulso[i], v * decai)
        out[i] = 1.0 + FOGO_PULSO * v
    return out


def score(rms, frame_dur, onsets, fps, duracao):
    e = envelope(rms, frame_dur, fps, duracao)
    est = estados(e, fps)
    return est, pesos(est, e, fps), ganho_fogo(onsets, fps, len(e))
