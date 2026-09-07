"""Unit tests para karaoke.bounce. Sem I/O de audio, sem subprocess."""
import re
import wave

import numpy as np
import pytest

from karaoke.bounce import build_sendcmd, onsets_from_wav
from karaoke.render_cmd import WORK_H, WORK_W


def test_uma_dupla_de_comandos_por_onset():
    onsets = [0.5, 1.25, 2.0]
    txt = build_sendcmd(onsets, 1408, 792)
    linhas = [l for l in txt.splitlines() if l.strip()]
    # cada onset gera 2 linhas: o pulso e o retorno
    assert len(linhas) == len(onsets) * 2, (
        f"{len(linhas)} linhas para {len(onsets)} onsets"
    )


def test_lista_vazia_e_erro_nao_arquivo_vazio():
    # sendcmd vazio renderiza verde e nao faz nada — falso positivo silencioso
    with pytest.raises(ValueError, match="nenhum onset"):
        build_sendcmd([], 1408, 792)


def test_pulso_encolhe_o_crop_e_o_retorno_restaura():
    txt = build_sendcmd([1.0], 1408, 792, pulse=0.05)
    linhas = [l for l in txt.splitlines() if l.strip()]
    assert linhas[0].startswith("1.000 ")
    assert "crop w 1336" in linhas[0]      # 1408*0.95 = 1337.6 -> par para baixo
    assert "crop h 752" in linhas[0]       # 792*0.95  = 752.4  -> par para baixo
    assert "crop w 1408" in linhas[1]      # retorno ao tamanho cheio
    assert "crop h 792" in linhas[1]


def test_dimensoes_do_pulso_sao_pares():
    # libx264 rejeita dimensao impar em yuv420p
    txt = build_sendcmd([0.5, 1.0, 1.5], 1408, 792, pulse=0.037)
    pares = re.findall(r"crop w (\d+), crop h (\d+)", txt)
    assert pares, "nenhum comando de crop encontrado — teste inutil"
    for w, h in pares:
        assert int(w) % 2 == 0, f"largura impar: {w}"
        assert int(h) % 2 == 0, f"altura impar: {h}"


def test_onsets_muito_proximos_nao_se_sobrepoem():
    # decay=0.18: o retorno de 1.0 cairia em 1.18, depois do onset 1.05
    txt = build_sendcmd([1.0, 1.05], 1408, 792, decay=0.18)
    tempos = [float(l.split(" ", 1)[0]) for l in txt.splitlines() if l.strip()]
    assert tempos == sorted(tempos), f"comandos fora de ordem: {tempos}"


def _wav_com_cliques(path, cliques, canais, sr=8000, dur=4.0):
    """WAV com estouros de 100ms plantados nos tempos pedidos.

    `canais` sai literal no header: 2 e o que o pipeline de fato entrega
    (01_media_prep.py grava com -ac 2, entao o no_vocals.wav do Demucs — a
    UNICA entrada que onsets_from_wav recebe — e estereo).
    """
    audio = np.zeros(int(sr * dur), dtype=np.float32)
    burst = int(sr * 0.1)
    for t in cliques:
        audio[int(sr * t):int(sr * t) + burst] = 1.0
    pcm = (audio * 32767).astype(np.int16)
    if canais > 1:
        pcm = np.repeat(pcm, canais)      # intercalado L,R,L,R...
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(canais)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return path


@pytest.mark.parametrize("canais", [1, 2])
def test_onsets_from_wav_acha_os_cliques_no_tempo_certo(tmp_path, canais):
    """Contagem E tempo. So a contagem passava com o buffer estereo lido como
    mono: os indices dobravam (0.5s virava ~1.0s) e nada acusava."""
    cliques = [0.5, 1.5, 2.5, 3.5]
    wav = _wav_com_cliques(tmp_path / f"cliques_{canais}ch.wav", cliques, canais)

    onsets = onsets_from_wav(wav)
    assert len(onsets) == len(cliques), (
        f"{canais} canal(is): {len(onsets)} onsets detectados, "
        f"{len(cliques)} cliques plantados -> {[round(t, 2) for t in onsets]}"
    )
    for esperado, medido in zip(cliques, onsets):
        assert abs(medido - esperado) < 0.05, (
            f"{canais} canal(is): clique em {esperado}s detectado em "
            f"{medido:.3f}s (erro {medido - esperado:+.3f}s)"
        )


def test_deriva_move_x_e_y_e_respeita_o_limite_da_fonte():
    """F5: sem duration nao ha deriva; com duration, x/y varrem e nunca
    estouram a fonte — nem com o crop ja encolhido pelo pulso."""
    dur = 60.0
    txt = build_sendcmd([1.0, 2.0, 3.0], WORK_W, WORK_H, duration=dur)
    def _prop(nome):
        out = []
        for linha in txt.splitlines():
            m = re.search(rf"crop {nome} (\d+)", linha)
            if m:
                out.append((float(linha.split(" ", 1)[0]), int(m.group(1))))
        return out

    xs, ys = _prop("x"), _prop("y")
    assert len(xs) > 1 and len(ys) > 1, (
        f"deriva ausente: {len(xs)} comandos de x, {len(ys)} de y"
    )

    # O primeiro comando emitido tem de FIXAR a janela (w/h). Enquanto ele nao
    # vem, o crop ainda e o WORK_W:WORK_H do filtergraph e qualquer x > 0 ja
    # estoura a fonte.
    primeira = [l for l in txt.splitlines() if l.strip()][0]
    assert "crop w" in primeira and "crop h" in primeira, (
        f"primeiro comando nao estabelece a janela: {primeira!r}"
    )
    assert primeira.startswith("0.000 "), (
        f"a janela de repouso tem de ser comandada em t=0: {primeira!r}"
    )
    assert xs[0][1] != xs[-1][1], f"x nao se moveu em {len(xs)} comandos: {xs[0]} -> {xs[-1]}"
    assert ys[0][1] != ys[-1][1], f"y nao se moveu em {len(ys)} comandos: {ys[0]} -> {ys[-1]}"

    # Clamp nas duas pontas E em todos os passos, contra a MAIOR largura
    # comandada (a de repouso; a do pulso e menor e cabe por consequencia).
    ws = [int(w) for w in re.findall(r"crop w (\d+)", txt)]
    hs = [int(h) for h in re.findall(r"crop h (\d+)", txt)]
    assert ws and hs, "nenhum comando de w/h — teste inutil"
    w_max, h_max = max(ws), max(hs)
    for _, x in xs:
        assert 0 <= x and x + w_max <= WORK_W, f"x={x} + w={w_max} estoura {WORK_W}"
    for _, y in ys:
        assert 0 <= y and y + h_max <= WORK_H, f"y={y} + h={h_max} estoura {WORK_H}"
    assert xs[-1][0] <= dur, f"comando de deriva depois do fim: {xs[-1][0]} > {dur}"


def test_sem_duration_nao_emite_deriva():
    # Callers antigos (duration=None) tem de continuar identicos: so w/h.
    txt = build_sendcmd([1.0, 2.0], WORK_W, WORK_H)
    assert "crop x" not in txt and "crop y" not in txt, txt


def test_comandos_em_ordem_crescente_com_deriva():
    txt = build_sendcmd([1.0, 2.0, 3.0], WORK_W, WORK_H, duration=10.0)
    tempos = [float(l.split(" ", 1)[0]) for l in txt.splitlines() if l.strip()]
    assert len(tempos) > 3, f"so {len(tempos)} comandos"
    assert tempos == sorted(tempos), f"comandos fora de ordem: {tempos}"


def _varre_estado(txt):
    """Reexecuta o script sendcmd comando a comando, como o ffmpeg faria.

    Estado inicial = o que o filtergraph monta antes de qualquer comando:
    `crop=WORK_W:WORK_H` (render_cmd.py), x/y em 0. Devolve
    [(indice, tempo, w, h, x, y)] apos cada linha.
    """
    linhas = [l for l in txt.splitlines() if l.strip()]
    w, h, x, y = WORK_W, WORK_H, 0, 0
    estados = []
    for i, linha in enumerate(linhas):
        pares = re.findall(r"crop ([whxy]) (\d+)", linha)
        assert pares, f"linha {i} sem nenhum comando de crop: {linha!r}"
        for prop, val in pares:
            w, h, x, y = {
                "w": (int(val), h, x, y), "h": (w, int(val), x, y),
                "x": (w, h, int(val), y), "y": (w, h, x, int(val)),
            }[prop]
        estados.append((i, float(linha.split(" ", 1)[0]), w, h, x, y))
    return estados


@pytest.mark.parametrize("onsets,dur", [
    ([12.0, 40.0, 80.0], 210.0),   # intro longa: 12 comandos de deriva antes do 1o onset
    ([0.5, 1.0, 90.0], 180.0),
    ([1.0, 2.0, 3.0], 10.0),
])
def test_a_janela_do_crop_nunca_estoura_a_fonte_em_nenhum_comando(onsets, dur):
    """A cerca que teria pego o defeito: o invariante em TODO ponto do script,
    nao so nos extremos.

    O teste anterior media x contra `max(crop w)` do arquivo inteiro, o que
    supoe que o w ja foi comandado. Ate o primeiro onset ele NAO foi: o crop
    valia WORK_W e a deriva ja mandava x. Medido antes da correcao com
    onsets=[12,40,80], dur=210: 4 dos 217 comandos com x + w = 1410 > 1408.
    """
    estados = _varre_estado(build_sendcmd(onsets, WORK_W, WORK_H, duration=dur))
    assert len(estados) > 10, f"so {len(estados)} comandos varridos — teste fraco"
    estouros = [e for e in estados
                if e[4] + e[2] > WORK_W or e[5] + e[3] > WORK_H or e[4] < 0 or e[5] < 0]
    assert not estouros, (
        f"{len(estouros)} de {len(estados)} comandos estouram a fonte "
        f"{WORK_W}x{WORK_H}; primeiro: idx={estouros[0][0]} t={estouros[0][1]} "
        f"w={estouros[0][2]} h={estouros[0][3]} x={estouros[0][4]} y={estouros[0][5]} "
        f"(x+w={estouros[0][4] + estouros[0][2]}, y+h={estouros[0][5] + estouros[0][3]})"
    )
