"""Unit tests para karaoke.scenes. Monta a lista de args, nao roda o encoder."""
from pathlib import Path

import pytest

from karaoke.scenes import build_scene_video_cmd, segmentos_de_secoes

A, B, C = Path("/tmp/a.png"), Path("/tmp/b.png"), Path("/tmp/c.png")
OUT = Path("/tmp/bg.mp4")


def _fc(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_uma_entrada_por_segmento_com_loop_e_duracao():
    cmd = build_scene_video_cmd([(A, 0.0), (B, 10.0), (C, 25.0)], OUT,
                                total_s=40.0, largura=1280, altura=720, fade_s=1.0)
    assert cmd.count("-loop") == 3, cmd
    duracoes = [float(cmd[i + 1]) for i, a in enumerate(cmd) if a == "-t"][:3]
    # trecho + fade: 10-0+1, 25-10+1, 40-25+1
    assert duracoes == [11.0, 16.0, 16.0], duracoes


def test_offsets_do_xfade_sao_os_inicios_absolutos():
    # A saida de cada xfade herda a linha de tempo da PRIMEIRA entrada, entao
    # o offset e o instante absoluto da virada. Errar isso desloca todas as
    # cenas seguintes sem nenhum erro do ffmpeg.
    fc = _fc(build_scene_video_cmd([(A, 0.0), (B, 10.0), (C, 25.0)], OUT,
                                   total_s=40.0, largura=1280, altura=720))
    assert "offset=10.000" in fc, fc
    assert "offset=25.000" in fc, fc


def test_todas_as_entradas_sao_normalizadas_antes_do_xfade():
    # xfade recusa streams de geometria diferente, e as cenas podem vir de
    # modelos com resolucoes distintas.
    fc = _fc(build_scene_video_cmd([(A, 0.0), (B, 10.0)], OUT, total_s=20.0,
                                   largura=1152, altura=648))
    assert fc.count("scale=1152:648") == 2, fc
    assert fc.count("setsar=1") == 2, fc


def test_um_segmento_so_nao_gera_xfade():
    cmd = build_scene_video_cmd([(A, 0.0)], OUT, total_s=30.0,
                                largura=1280, altura=720)
    assert "xfade" not in _fc(cmd)
    assert cmd[cmd.index("-map") + 1] == "[c0]"


def test_primeiro_segmento_tem_de_comecar_no_zero():
    # Comecar depois do zero deixaria o video sem fundo no inicio — e o
    # ffmpeg nao reclamaria, so entregaria preto.
    with pytest.raises(ValueError, match="tem de ser 0"):
        build_scene_video_cmd([(A, 3.0), (B, 10.0)], OUT, total_s=20.0,
                              largura=1280, altura=720)


def test_segmentos_fora_de_ordem_sao_erro():
    with pytest.raises(ValueError, match="fora de ordem"):
        build_scene_video_cmd([(A, 0.0), (B, 25.0), (C, 10.0)], OUT,
                              total_s=40.0, largura=1280, altura=720)


def test_lista_vazia_e_erro_nao_video_vazio():
    with pytest.raises(ValueError, match="nenhum segmento"):
        build_scene_video_cmd([], OUT, total_s=40.0, largura=1280, altura=720)


def test_total_menor_que_o_ultimo_inicio_e_erro():
    with pytest.raises(ValueError, match="nao cobre"):
        build_scene_video_cmd([(A, 0.0), (B, 50.0)], OUT, total_s=40.0,
                              largura=1280, altura=720)


def test_secoes_seguidas_na_mesma_cena_viram_um_segmento(tmp_path):
    for n in ("um.png", "dois.png"):
        (tmp_path / n).write_bytes(b"x")
    secoes = [("Intro", 0.0), ("Pre-Chorus", 10.0), ("Chorus", 17.0)]
    mapa = {"Intro": "um.png", "Pre-Chorus": "um.png", "Chorus": "dois.png"}
    segs = segmentos_de_secoes(secoes, mapa, tmp_path)
    # Intro e Pre-Chorus compartilham imagem: um crossfade da imagem para ela
    # mesma seria invisivel e ainda assim custaria encode.
    assert len(segs) == 2, segs
    assert segs[0][1] == 0.0 and segs[1][1] == 17.0


def test_secao_sem_cena_atribuida_e_erro(tmp_path):
    (tmp_path / "um.png").write_bytes(b"x")
    with pytest.raises(KeyError, match="Bridge"):
        segmentos_de_secoes([("Intro", 0.0), ("Bridge", 9.0)],
                            {"Intro": "um.png"}, tmp_path)


def test_cena_faltando_no_disco_e_erro(tmp_path):
    with pytest.raises(FileNotFoundError, match="Intro"):
        segmentos_de_secoes([("Intro", 0.0)], {"Intro": "sumiu.png"}, tmp_path)
