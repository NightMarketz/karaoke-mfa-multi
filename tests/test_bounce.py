"""Unit tests para karaoke.bounce. Sem I/O de audio, sem subprocess."""
import re
import wave

import numpy as np
import pytest

from karaoke.bounce import build_sendcmd, onsets_from_wav


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
