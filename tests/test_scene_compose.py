"""Compositor da cena. Loops sinteticos de cor chapada via ffmpeg lavfi."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from karaoke import scene_compose as sc

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")

W, H, FPS, LOOP_S = 64, 36, 8, 3
CORES = {"calmo.mp4": "red", "tensao.mp4": "lime", "climax.mp4": "blue", "escuro.mp4": "black"}


def _loop(p: Path, cor: str, w=W, h=H, fps=FPS, dur=LOOP_S):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"color=c={cor}:s={w}x{h}:r={fps}:d={dur}",
                    "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(p)], check=True)


def _pacote(pasta: Path, **troca):
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, cor in CORES.items():
        _loop(pasta / nome, cor, **troca.get(nome, {}))
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"color=c=black:s={W}x{H}:d=1", "-frames:v", "1",
                    str(pasta / "fogo_mask.png")], check=True)
    (pasta / "scene.json").write_text(json.dumps({}), encoding="utf-8")
    return pasta


def _quadros(mp4: Path):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, np.uint8).reshape(-1, H, W, 3)


def test_misturar_e_convexa_e_aplica_ganho_so_na_mascara():
    q = np.zeros((4, 2, 2, 3), np.uint8)
    q[0] = 200
    q[3] = 0
    masc = np.array([[1, 0], [0, 0]], np.float32)
    out = sc.misturar(q, np.array([0.5, 0, 0, 0.5]), 1.25, masc)
    assert out[1, 1, 0] == 100
    assert out[0, 0, 0] == 125
    sat = sc.misturar(q, np.array([1.0, 0, 0, 0]), 1.5, masc)
    assert sat[0, 0, 0] == 255, "estouro satura, nao da a volta no uint8"


def test_pacote_carrega_na_ordem_certa(tmp_path):
    loops, masc, fps, meta = sc.carregar_pacote(_pacote(tmp_path / "c"))
    assert len(loops) == 4 and fps == FPS and meta == {}
    assert masc.shape == (H, W)
    medias = [l[0].reshape(-1, 3).mean(0).round() for l in loops]
    assert medias[0][0] > 200 and medias[1][1] > 200 and medias[2][2] > 200
    assert medias[3].max() < 10


def test_arquivo_faltando_e_nomeado(tmp_path):
    pasta = _pacote(tmp_path / "c")
    (pasta / "climax.mp4").unlink()
    with pytest.raises(FileNotFoundError, match="climax.mp4"):
        sc.carregar_pacote(pasta)


def test_loop_divergente_e_nomeado(tmp_path):
    pasta = _pacote(tmp_path / "c", **{"tensao.mp4": {"w": 32}})
    with pytest.raises(ValueError, match="tensao.mp4"):
        sc.carregar_pacote(pasta)


def test_contagem_divergente_nomeia_o_arquivo_que_difere(tmp_path):
    # escuro mais LONGO: o de menor contagem seria calmo, mas o que difere e escuro
    pasta = _pacote(tmp_path / "c", **{"escuro.mp4": {"dur": 4}})
    # ^: a mensagem cita todas as contagens; o nome culpado vem no inicio
    with pytest.raises(ValueError, match=r"^escuro\.mp4"):
        sc.carregar_pacote(pasta)


def test_compor_da_a_volta_e_tem_a_duracao_da_musica(tmp_path):
    loops, masc, fps, _ = sc.carregar_pacote(_pacote(tmp_path / "c"))
    n = 5 * FPS                                   # 5 s > loop de 3 s
    w = np.zeros((n, 4))
    w[: n // 2, 0] = 1.0                          # calmo (vermelho)
    w[n // 2:, 3] = 1.0                           # escuro (preto)
    saida = tmp_path / "bg.mp4"
    faixa = sc.compor(loops, masc, w, np.ones(n), fps, saida)
    q = _quadros(saida)
    assert len(q) == n, f"{len(q)} quadros, esperado {n}"
    assert len(faixa) == n
    assert q[2].reshape(-1, 3).mean(0)[0] > 200, "inicio deveria ser o loop calmo"
    assert q[n - 2].max() < 16, "fim deveria ser o loop escuro"
    assert not list(tmp_path.glob("*.tmp*")), "sobrou temporario"


def test_falha_no_meio_nao_deixa_mp4(tmp_path):
    loops, masc, fps, _ = sc.carregar_pacote(_pacote(tmp_path / "c"))
    saida = tmp_path / "bg.mp4"
    with pytest.raises(Exception):
        # ganho mais curto que os pesos: IndexError no quadro 5, com o encoder ja aberto
        sc.compor(loops, masc, np.tile([1.0, 0, 0, 0], (10, 1)), np.ones(5), fps, saida)
    assert not saida.exists()
    assert not list(tmp_path.glob("*.tmp*"))


def _job(tmp_path, sidecar="guts_camp", cena_mp4=True, png=True):
    audio = tmp_path / "no_vocals.wav"
    audio.write_bytes(b"x")
    mp4 = tmp_path / "background_scene.mp4"
    if cena_mp4:
        mp4.write_bytes(b"x")
        mp4.with_suffix(".json").write_text(json.dumps({"scene": sidecar}), encoding="utf-8")
    bg = tmp_path / "background.png"
    if png:
        bg.write_bytes(b"x")
    return mp4, bg, audio


def test_fundo_do_job_usa_cena_quando_nome_e_mtime_batem(tmp_path):
    mp4, bg, audio = _job(tmp_path)
    assert sc.fundo_do_job(mp4, bg, "guts_camp", audio) == (mp4, "cena guts_camp")


def test_fundo_do_job_sem_scene_usa_png(tmp_path):
    mp4, bg, audio = _job(tmp_path)
    assert sc.fundo_do_job(mp4, bg, None, audio) == (bg, "ilustracao")


def test_fundo_do_job_sidecar_de_outra_cena_cai_no_png(tmp_path):
    mp4, bg, audio = _job(tmp_path, sidecar="outra_cena")
    p, rotulo = sc.fundo_do_job(mp4, bg, "guts_camp", audio)
    assert p == bg and rotulo.startswith("ilustracao") and "ignorada" in rotulo, rotulo


def test_fundo_do_job_cena_mais_velha_que_o_audio_cai_no_png(tmp_path):
    mp4, bg, audio = _job(tmp_path)
    t = audio.stat().st_mtime
    os.utime(mp4, (t - 3600, t - 3600))
    p, rotulo = sc.fundo_do_job(mp4, bg, "guts_camp", audio)
    assert p == bg and "ignorada" in rotulo, rotulo


def test_fundo_do_job_sem_nada_e_chapado(tmp_path):
    mp4, bg, audio = _job(tmp_path, cena_mp4=False, png=False)
    assert sc.fundo_do_job(mp4, bg, None, audio) == (None, "chapado #08090f")
