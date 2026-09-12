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
# Ritmo = F1 do casamento 1:1 entre ataques da referencia e do take, depois de
# estimar o deslocamento global. Tolerancia FIXA: relativa ao intervalo mediano
# virava 0,21s no sintetico e o acaso subia a p95 75 (medido 2026-09-12); 0,05s
# dava 60 a um humano com jitter +-40ms, a 8 pontos do acaso. MIREX usa 50ms.
MATCH_TOL_S = 0.080
XCORR_BIN_S = 0.010        # grade do trem de impulsos para o alinhamento global
WEIGHTS = {"melody": 0.45, "rhythm": 0.35, "attacks": 0.20}

# Folga em torno de [words[0].start, words[-1].end] no modo karaoke. O detector
# precisa ver o RMS SUBIR: recorte que comeca em cima do primeiro ataque perde
# esse ataque (medido em 2026-09-12: na fixture sintetica de 5 bursts, pad 0
# pega 4 de 5 (perde o primeiro); 0,05-0,2 pega 5 de 5). Tambem absorve parte
# do erro de ~200ms do MFA.
WINDOW_PAD_S = 0.1


@dataclass
class ScoreReport:
    melody: float           # 0..100
    rhythm: float           # 0..100
    attacks: float          # 0..100
    total: float            # 0..100
    n_onsets_ref: int
    n_onsets_take: int
    n_matched: int          # numerador do F1: pares casados dentro de rhythm_tol_s
    n_frames_compared: int  # zero e FALHA, nao sucesso
    rhythm_tol_s: float     # = MATCH_TOL_S, para auditoria


def _resample(contour: np.ndarray, n: int = MELODY_POINTS) -> np.ndarray:
    return np.interp(np.linspace(0.0, 1.0, n),
                     np.linspace(0.0, 1.0, len(contour)),
                     contour)


def _align_offset(on_ref: np.ndarray, on_take: np.ndarray) -> float:
    """Deslocamento global b tal que take ~ ref + b: pico da correlacao cruzada
    entre trens de impulso triangulares (largura MATCH_TOL_S) em grade XCORR_BIN_S.
    E o que torna o ritmo imune a latencia de captura e pre-roll SEM assumir
    sincronia: o offset e medido, nao suposto."""
    w = max(1, int(round(MATCH_TOL_S / XCORR_BIN_S)))
    n = int(max(float(on_ref.max()), float(on_take.max())) / XCORR_BIN_S) + w + 2

    def trem(on: np.ndarray) -> np.ndarray:
        tr = np.zeros(n, dtype=np.float64)
        for t in on:
            c = int(round(float(t) / XCORR_BIN_S))
            lo, hi = max(0, c - w), min(n - 1, c + w)
            k = np.arange(lo, hi + 1)
            tr[k] = np.maximum(tr[k], 1.0 - np.abs(k - c) / (w + 1))
        return tr

    xc = np.correlate(trem(on_take), trem(on_ref), mode="full")
    return (int(np.argmax(xc)) - (n - 1)) * XCORR_BIN_S


def _match_f1(on_ref: np.ndarray, on_take_alinhado: np.ndarray) -> tuple[float, int]:
    """Casamento 1:1 guloso por proximidade dentro de MATCH_TOL_S. Devolve
    (F1, n_pares). Recall = pares/n_ref; precisao = pares/n_take — a precisao e
    o que derruba o take denso (ruido: 251 ataques, precisao 0,35, medido)."""
    n_ref, n_take = len(on_ref), len(on_take_alinhado)
    if n_ref == 0 or n_take == 0:
        return 0.0, 0
    usado = np.zeros(n_take, dtype=bool)
    pares = 0
    for t in on_ref:
        d = np.abs(on_take_alinhado - t)
        d[usado] = np.inf
        j = int(np.argmin(d))
        if d[j] <= MATCH_TOL_S:
            usado[j] = True
            pares += 1
    recall, precisao = pares / n_ref, pares / n_take
    f1 = 2 * recall * precisao / (recall + precisao) if pares else 0.0
    return f1, pares


def score(ref: ReferenceTrack, take: ReferenceTrack) -> ScoreReport:
    """Compara forma relativa, nunca sincronia absoluta: um atraso global na
    captura e ESTIMADO (correlacao cruzada) e descontado, nao assumido."""
    n_ref, n_take = len(ref.onsets), len(take.onsets)

    # ataques: quanto as contagens batem
    attacks = 100.0 * max(0.0, 1.0 - abs(n_ref - n_take) / max(n_ref, n_take, 1))

    # ritmo: F1 do casamento de ataques apos alinhamento global (spec, emenda
    # 2026-09-12 (2)). Posicional dava 0.0 ao vocal inteiro, a sala e aos blocos
    # embaralhados — nao distinguia take bom de aleatorio.
    tol = MATCH_TOL_S
    if n_ref >= 2 and n_take >= 1:
        b = _align_offset(ref.onsets, take.onsets)
        f1, n_matched = _match_f1(ref.onsets, take.onsets - b)
        rhythm = 100.0 * f1
    else:
        rhythm, n_matched = 0.0, 0

    # melodia: correlacao dos contornos centrados, reamostrados a tamanho comum
    if len(ref.semitones) >= MIN_VOICED_FRAMES and len(take.semitones) >= MIN_VOICED_FRAMES:
        # ponytail: correlacao mede a DIRECAO do contorno, nao o tamanho dos
        # intervalos — cantar "flat" (intervalos x0.5) da melody ~100. Upgrade:
        # distancia RMS em semitons apos centragem, quando isso importar.
        with np.errstate(invalid="ignore"):
            r = float(np.corrcoef(_resample(ref.semitones), _resample(take.semitones))[0, 1])
        melody = 0.0 if np.isnan(r) else 100.0 * max(0.0, r)
        n_frames_compared = min(len(ref.semitones), len(take.semitones))
    else:
        melody = 0.0
        n_frames_compared = 0

    total = (WEIGHTS["melody"] * melody
             + WEIGHTS["rhythm"] * rhythm
             + WEIGHTS["attacks"] * attacks)

    return ScoreReport(
        melody=melody, rhythm=rhythm, attacks=attacks, total=total,
        n_onsets_ref=n_ref, n_onsets_take=n_take, n_matched=n_matched,
        n_frames_compared=n_frames_compared, rhythm_tol_s=tol,
    )


def track_from_word_timing(words: list[dict], samples: np.ndarray,
                           sr: int) -> ReferenceTrack:
    """Referencia do modo karaoke: `track_from_audio` sobre o RECORTE do vocal
    isolado em [words[0].start - WINDOW_PAD_S, words[-1].end + WINDOW_PAD_S].
    O gabarito (work/jobs/<id>/05_alignment/word_timing.json) so valida e janela.

    Decisao (a) do spec, emenda 2026-09-12: antes, ref.onsets eram INICIOS DE
    PALAVRA (71 no job de teste) contra ATAQUES do detector no take (163 no mesmo
    audio) — populacoes diferentes, self-score ~54 com ritmo morto. Agora os dois
    lados passam pela mesma extracao: no job real attacks 44 -> 99,4, mas total
    53,7 -> 53,1 (ritmo posicional e pre-vocal do take sao teto pre-existente;
    100,0 so janela contra a propria janela).

    Os onsets devolvidos sao RELATIVOS ao inicio da janela; score() compara
    intervalos e contagens, nunca instantes absolutos.

    ponytail: teto documentado, NAO desta funcao — take com 1 clique de botao da
    rhythm 38 porque track_from_audio normaliza por pico de amostra (39 de 164
    ataques sobrevivem), e o take inteiro perde melodia (73,8) porque o pre-vocal
    contamina o pyin. Os dois sao "o take tem coisa que a referencia nao tem":
    VAD no inicio do take, decisao de spec seguinte.
    """
    if not words:
        raise ValueError("word_timing vazio: gabarito sem palavras nao produz referencia")

    starts = np.asarray([float(w["start"]) for w in words], dtype=np.float64)
    if np.any(np.diff(starts) < 0):
        fora = int(np.sum(np.diff(starts) < 0))
        raise ValueError(
            f"word_timing nao e monotonico: {fora} de {len(starts) - 1} pares fora de ordem"
        )
    if "end" not in words[-1]:
        raise ValueError("word_timing sem 'end' na ultima palavra: nao da para janelar")

    dur = len(samples) / sr
    t0 = max(0.0, float(starts[0]) - WINDOW_PAD_S)
    t1 = min(dur, float(words[-1]["end"]) + WINDOW_PAD_S)
    if t1 <= t0:
        raise ValueError(
            f"janela do gabarito [{t0:.2f}s, {t1:.2f}s] vazia dentro de {dur:.2f}s de audio"
        )
    return track_from_audio(samples[int(t0 * sr):int(t1 * sr)], sr)
