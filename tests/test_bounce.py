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


def test_onsets_from_wav_detecta_cliques_plantados(tmp_path):
    # 3 estouros de 100ms plantados em silencio; onsets_from_wav deve achar 1 por clique.
    sr = 8000
    audio = np.zeros(int(sr * 3.0), dtype=np.float32)
    cliques = [0.5, 1.5, 2.5]
    burst_len = int(sr * 0.1)
    for t in cliques:
        start = int(sr * t)
        audio[start:start + burst_len] = 1.0
    pcm = (audio * 32767).astype(np.int16)

    wav_path = tmp_path / "cliques.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())

    onsets = onsets_from_wav(wav_path)
    assert len(onsets) == len(cliques), (
        f"{len(onsets)} onsets detectados, {len(cliques)} cliques plantados"
    )
