"""
Converte onsets de audio no script de comandos do filtro sendcmd do FFmpeg.

O crop e comandado em runtime: no onset ele encolhe (zoom in), e logo depois
volta ao tamanho cheio. O `scale` que vem DEPOIS do crop na cadeia e o que
mantem a resolucao de saida fixa — sem ele o comando nao produz efeito visivel.

Sintaxe do arquivo sendcmd (verificada no ffmpeg 8.1):
    TEMPO alvo comando valor, alvo comando valor;
"""
import wave
from pathlib import Path

import numpy as np

# Espelha scripts/05c_onset_dtw_align.py — mesma deteccao, mesmo comportamento.
ONSET_THRESHOLD = 0.008
MIN_GAP = 0.08
ENERGY_MIN = 0.02
WINDOW_MS = 25
HOP_MS = 10


def _par(n: float) -> int:
    """Arredonda para baixo ate um inteiro par (libx264 rejeita impar)."""
    return int(n) // 2 * 2


def build_sendcmd(onsets, base_w: int, base_h: int,
                  pulse: float = 0.03, decay: float = 0.18) -> str:
    """
    Texto do arquivo sendcmd: um pulso por onset, com retorno ao tamanho cheio.

    pulse: fracao de encolhimento do crop no onset (0.03 = 3%).
    decay: segundos ate voltar ao tamanho cheio.
    """
    if len(onsets) == 0:
        raise ValueError(
            "nenhum onset detectado — sendcmd vazio nao produz movimento nenhum"
        )

    pw, ph = _par(base_w * (1 - pulse)), _par(base_h * (1 - pulse))
    fw, fh = _par(base_w), _par(base_h)

    eventos = []
    ordenados = sorted(float(t) for t in onsets)
    for i, t in enumerate(ordenados):
        eventos.append((t, pw, ph))
        volta = t + decay
        # ponytail: se o proximo onset chega antes do retorno, o retorno e
        # descartado — o proximo pulso ja reassume. Mantem os comandos em ordem
        # crescente, que e o que o sendcmd exige.
        if i + 1 >= len(ordenados) or volta < ordenados[i + 1]:
            eventos.append((volta, fw, fh))

    return "".join(f"{t:.3f} crop w {w}, crop h {h};\n" for t, w, h in eventos)


def onsets_from_wav(wav_path: Path) -> list:
    """RMS frame a frame + derivada, igual ao 05c_onset_dtw_align.py."""
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        canais = wf.getnchannels()
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    audio = audio.astype(np.float32)
    if canais > 1:
        # O buffer traz as amostras intercaladas (L,R,L,R...): sao
        # nframes*canais valores, mas hop/win saem so do sample rate. Sem o
        # downmix cada indice de frame vale `canais` vezes o tempo real. O
        # no_vocals.wav do Demucs — a unica entrada que esta funcao recebe —
        # e estereo (01_media_prep.py grava com -ac 2), entao TODO onset
        # saia com o dobro do tempo certo.
        sobra = len(audio) % canais
        if sobra:
            audio = audio[:-sobra]     # frame parcial no fim do buffer
        audio = audio.reshape(-1, canais).mean(axis=1)
    audio /= np.abs(audio).max() + 1e-8

    hop = int(sr * HOP_MS / 1000)
    win = int(sr * WINDOW_MS / 1000)
    rms = np.array([
        float(np.sqrt(np.mean(audio[i:i + win] ** 2)))
        for i in range(0, len(audio) - win, hop)
    ])
    frame_dur = hop / sr

    onsets, last = [], -1.0
    for i, d in enumerate(np.diff(rms)):
        t = i * frame_dur
        if d > ONSET_THRESHOLD and rms[i + 1] > ENERGY_MIN and (t - last) > MIN_GAP:
            onsets.append(t)
            last = t
    return onsets
