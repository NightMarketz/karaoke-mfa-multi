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

# Deriva (Ken Burns): fracao do quadro reservada para a varredura de x/y, e de
# quanto em quanto tempo um novo par x/y e comandado. 1s da ~210 comandos numa
# musica de 3m30 — barato, e o movimento fica imperceptivel passo a passo, que
# e exatamente o ponto de uma deriva lenta.
DRIFT_MARGIN = 0.04
DRIFT_STEP_SECONDS = 1.0


def _par(n: float) -> int:
    """Arredonda para baixo ate um inteiro par (libx264 rejeita impar)."""
    return int(n) // 2 * 2


def build_sendcmd(onsets, base_w: int, base_h: int,
                  pulse: float = 0.03, decay: float = 0.18,
                  duration: float = None) -> str:
    """
    Texto do arquivo sendcmd: um pulso por onset, com retorno ao tamanho cheio,
    mais — se `duration` vier — uma deriva lenta de `crop x`/`crop y`.

    pulse:    fracao de encolhimento do crop no onset (0.03 = 3%).
    decay:    segundos ate voltar ao tamanho cheio.
    duration: duracao total do video, em segundos. None = sem deriva; o crop
              fica centralizado pelo default do filtro, igual a antes.

    Deriva e pulso saem do MESMO crop de proposito — empilhar zoompan poria
    dois zooms concorrentes na cadeia. Com deriva ligada o crop de repouso
    encolhe DRIFT_MARGIN para abrir a folga que x/y varrem; sem essa folga x
    teria de ficar preso em 0, porque o crop de repouso ja seria a fonte
    inteira (base_w x base_h == WORK_W x WORK_H).
    """
    if len(onsets) == 0:
        raise ValueError(
            "nenhum onset detectado — sendcmd vazio nao produz movimento nenhum"
        )

    deriva = duration is not None and duration > 0
    if deriva:
        fw, fh = _par(base_w * (1 - DRIFT_MARGIN)), _par(base_h * (1 - DRIFT_MARGIN))
    else:
        fw, fh = _par(base_w), _par(base_h)
    pw, ph = _par(fw * (1 - pulse)), _par(fh * (1 - pulse))

    eventos = []   # (tempo, [(propriedade, valor), ...])
    ordenados = sorted(float(t) for t in onsets)
    for i, t in enumerate(ordenados):
        eventos.append((t, [("w", pw), ("h", ph)]))
        volta = t + decay
        # ponytail: se o proximo onset chega antes do retorno, o retorno e
        # descartado — o proximo pulso ja reassume. Mantem os comandos em ordem
        # crescente, que e o que o sendcmd exige.
        if i + 1 >= len(ordenados) or volta < ordenados[i + 1]:
            eventos.append((volta, [("w", fw), ("h", fh)]))

    if deriva:
        # O filtergraph entra em crop=WORK_W:WORK_H (ver render_cmd.py), ou
        # seja, a janela cheia. Sem este comando em t=0 a deriva comanda x/y
        # contra ela ate o PRIMEIRO onset: medido em
        # build_sendcmd([12,40,80], 1408, 792, duration=210), o primeiro w/h
        # so caia no indice 12 e 4 dos 12 comandos anteriores estouravam
        # x + w > WORK_W em 2px. O ffmpeg satura x/y por quadro em vez de
        # falhar, entao o sintoma era deriva presa na intro, sem erro nenhum.
        # insert(0): o sort abaixo e estavel, entao com onset em t=0.0 o pulso
        # continua vindo depois e reassume, como antes.
        eventos.insert(0, (0.0, [("w", fw), ("h", fh)]))

        # Folga medida contra o crop de REPOUSO, que e o maior comandado; o
        # crop do pulso e menor, entao cabe por consequencia.
        max_x, max_y = base_w - fw, base_h - fh
        passos = max(1, int(duration / DRIFT_STEP_SECONDS))
        for k in range(passos + 1):
            t = min(k * DRIFT_STEP_SECONDS, float(duration))
            frac = t / duration
            eventos.append((t, [("x", min(_par(max_x * frac), max_x)),
                                ("y", min(_par(max_y * frac), max_y))]))

    eventos.sort(key=lambda e: e[0])
    return "".join(
        f"{t:.3f} " + ", ".join(f"crop {prop} {v}" for prop, v in cmds) + ";\n"
        for t, cmds in eventos
    )


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
