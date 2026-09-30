"""build_ass_from_ctc: cada linha do ASS leva o texto e o tempo das SUAS palavras.

O timing (word_timing*.json, fused, char_timing) vem do song.lab: sem [Secao],
contracoes expandidas (I'm -> i am). A letra crua tem os cabecalhos e as
contracoes. Casar as duas por posicao pura desloca uma palavra por cabecalho.
"""
import importlib.util
import re
from pathlib import Path

from conftest import stdout_protegido

_spec = importlib.util.spec_from_file_location(
    "video_rendering", Path(__file__).resolve().parent.parent / "scripts" / "09_video_rendering.py")
vr = importlib.util.module_from_spec(_spec)
with stdout_protegido():                 # o 09 sequestra sys.stdout ao importar
    _spec.loader.exec_module(vr)

LETRA = """[Verse]
I'm still here

[Chorus]
I won't fall"""

# Uma entrada por palavra do song.lab, na ordem: "i am still here / i will not fall".
FALADO = ["i", "am", "still", "here", "i", "will", "not", "fall"]
TIMING = [{"word": w, "start": 10.0 + i, "end": 10.5 + i} for i, w in enumerate(FALADO)]


def _linhas(eventos):
    """(texto visivel, inicio, fim) de cada Dialogue."""
    campos = [ev.split(",", 9) for ev in eventos]
    return [(re.sub(r"\{[^}]*\}", "", c[9]), c[1], c[2]) for c in campos]


def test_cabecalho_e_contracao_nao_deslocam_as_palavras():
    eventos, _ = vr.build_ass_from_ctc(TIMING, LETRA.splitlines())

    t = vr.format_ass_time
    assert _linhas(eventos) == [
        ("I'm still here", t(10.0 - 1.0), t(13.5 + 0.5)),   # i .. here
        ("I won't fall",   t(14.0 - 1.0), t(17.5 + 0.5)),   # i .. fall
    ]
    # "I'm" dura de "i" ate "am"; "won't" de "will" ate "not".
    kf = re.findall(r"\\kf(\d+)[^}]*\}([^{ ]+)", "".join(eventos))
    assert kf == [("150", "I'm"), ("50", "still"), ("50", "here"),
                  ("50", "I"), ("150", "won't"), ("50", "fall")]


def _timing(*palavras):
    return [{"word": w, "start": 10.0 + i, "end": 10.5 + i} for i, w in enumerate(palavras)]


def test_hifen_partido_pelo_rescue_casa_por_texto():
    # song.lab guarda "half-time"; o 06_alignment_rescue parte em duas entradas.
    eventos, _ = vr.build_ass_from_ctc(_timing("half", "time", "show", "go"),
                                       ["Half-time show", "Go"])
    t = vr.format_ass_time
    assert _linhas(eventos) == [("Half-time show", t(9.0), t(12.5 + 0.5)),
                                ("Go", t(12.0), t(13.5 + 0.5))]


def test_palavra_que_nao_bate_cai_na_posicao_e_avisa(capsys):
    # MFA sem a palavra no dicionario: "<unk>" no lugar de "here". A chave
    # "unk" e mais curta que "here", entao a busca por texto engoliria o "go".
    eventos, _ = vr.build_ass_from_ctc(_timing("i", "am", "<unk>", "go"),
                                       ["I'm here", "Go"])
    t = vr.format_ass_time
    assert _linhas(eventos) == [("I'm here", t(9.0), t(12.5 + 0.5)),
                                ("Go", t(12.0), t(13.5 + 0.5))]
    assert "2 de 3 palavras" in capsys.readouterr().out
