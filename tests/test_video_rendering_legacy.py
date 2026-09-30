"""09: o fim da cadeia de fontes de timing e o modo legacy (TextGrid do MFA).

main() tenta fixed, fused, word_timing, char_timing e por fim o TextGrid; cada
ramo precisa do seu caminho definido, senao os de baixo viram NameError.

O TextGrid nasce do song.lab: sem [Secao], contracoes expandidas (I'm -> i am).
A letra crua tem os cabecalhos e as contracoes. Casar as duas por posicao pura
desloca uma palavra por cabecalho.
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

from conftest import stdout_protegido
from karaoke.textgrid_parser import Interval, Tier, serialize_textgrid

_spec = importlib.util.spec_from_file_location(
    "video_rendering_legacy", Path(__file__).resolve().parent.parent / "scripts" / "09_video_rendering.py")
vr = importlib.util.module_from_spec(_spec)
with stdout_protegido():                 # o 09 sequestra sys.stdout ao importar
    _spec.loader.exec_module(vr)


def test_sem_nenhuma_fonte_de_timing_sai_com_erro_legivel(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vr.kpaths, "repos_root", lambda: tmp_path)
    letra = vr.kpaths.lyrics_path("j")
    letra.parent.mkdir(parents=True)
    letra.write_text("I'm still here\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["09", "--job-id", "j"])

    with pytest.raises(SystemExit) as saida:
        vr.main()

    assert saida.value.code == 1
    assert "Nenhuma fonte de timing" in capsys.readouterr().out


def _textgrid(tmp_path, *palavras):
    """Uma palavra por segundo a partir de 10 s (0,5 s cada), "sp" entre elas, como o MFA grava."""
    iv = []
    for i, w in enumerate(palavras):
        iv += [Interval(10.0 + i, 10.5 + i, w), Interval(10.5 + i, 11.0 + i, "sp")]
    tg = tmp_path / "song.TextGrid"
    tg.write_text(serialize_textgrid([Tier("words", iv)], 0.0, 10.0 + len(palavras)), encoding="utf-8")
    return tg


def _linhas(eventos):
    """(texto visivel, inicio, fim) de cada Dialogue."""
    campos = [ev.split(",", 9) for ev in eventos]
    return [(re.sub(r"\{[^}]*\}", "", c[9]), c[1], c[2]) for c in campos]


def test_cabecalho_e_contracao_nao_deslocam_as_palavras(tmp_path):
    # Linhas como o main() entrega: cruas, sem as vazias.
    tg = _textgrid(tmp_path, "i", "am", "still", "here", "i", "will", "not", "fall")
    eventos, _ = vr.build_ass_from_textgrid(
        tg, ["[Verse]", "I'm still here", "[Chorus]", "I won't fall"])

    assert _linhas(eventos) == [
        ("I'm still here", "0:00:09.00", "0:00:14.00"),   # i(10,0) - 1 .. here(13,5) + 0,5
        ("I won't fall",   "0:00:13.00", "0:00:18.00"),   # i(14,0) - 1 .. fall(17,5) + 0,5
    ]
    # "I'm" dura de "i" ate "am"; "won't" de "will" ate "not".
    kf = re.findall(r"\\kf(\d+)[^}]*\}([^{\s]+)", "\n".join(eventos))
    assert kf == [("150", "I'm"), ("50", "still"), ("50", "here"),
                  ("50", "I"), ("150", "won't"), ("50", "fall")]


def test_hifen_partido_pelo_alinhador_casa_por_texto(tmp_path):
    # song.lab guarda "half-time"; o alinhador pode devolver duas palavras.
    tg = _textgrid(tmp_path, "half", "time", "show", "go")
    eventos, _ = vr.build_ass_from_textgrid(tg, ["Half-time show", "Go"])

    assert _linhas(eventos) == [("Half-time show", "0:00:09.00", "0:00:13.00"),
                                ("Go",             "0:00:12.00", "0:00:14.00")]


def test_palavra_que_nao_bate_cai_na_posicao_e_avisa(tmp_path, capsys):
    # MFA sem a palavra no dicionario: "<unk>" no lugar de "here". A chave
    # "unk" e mais curta que "here", entao a busca por texto engoliria o "go".
    tg = _textgrid(tmp_path, "i", "am", "<unk>", "go")
    eventos, _ = vr.build_ass_from_textgrid(tg, ["I'm here", "Go"])

    assert _linhas(eventos) == [("I'm here", "0:00:09.00", "0:00:13.00"),
                                ("Go",       "0:00:12.00", "0:00:14.00")]
    assert "2 de 3 palavras" in capsys.readouterr().out
