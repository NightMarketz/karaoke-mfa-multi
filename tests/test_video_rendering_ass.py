"""build_ass_from_ctc: cada linha do ASS leva o texto e o tempo das SUAS palavras.

O timing (word_timing*.json, fused, char_timing) vem do song.lab: sem [Secao],
contracoes expandidas (I'm -> i am). A letra crua tem os cabecalhos e as
contracoes. Casar as duas por posicao pura desloca uma palavra por cabecalho.
Casar pelo texto deixa local o estrago de uma palavra que o alinhador pulou,
duplicou ou trocou por <unk>.
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
I won't fall (For that!)"""

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


def test_unk_do_mfa_fica_no_lugar_da_palavra_e_avisa(capsys):
    # MFA sem a palavra no dicionario: "<unk>" no lugar de "here".
    eventos, _ = vr.build_ass_from_ctc(_timing("i", "am", "<unk>", "go"),
                                       ["I'm here", "Go"])
    t = vr.format_ass_time
    assert _linhas(eventos) == [("I'm here", t(9.0), t(12.5 + 0.5)),
                                ("Go", t(12.0), t(13.5 + 0.5))]
    assert "2 de 3 palavras" in capsys.readouterr().out


def test_palavra_pulada_pelo_alinhador_nao_desloca_o_resto():
    # O rescue (modo full) descarta palavra sem start/end: aqui sumiu o "é".
    eventos, _ = vr.build_ass_from_ctc(
        _timing("eu", "sei", "que", "assim", "você", "vem", "vai", "embora"),
        ["Eu sei que é assim", "Você vem", "Vai embora"])
    t = vr.format_ass_time
    assert _linhas(eventos) == [("Eu sei que é assim", t(9.0), t(13.5 + 0.5)),
                                ("Você vem", t(13.0), t(15.5 + 0.5)),
                                ("Vai embora", t(15.0), t(17.5 + 0.5))]


def test_entrada_a_mais_fica_de_fora_e_avisa(capsys):
    # "still" duplicado no timing: sobra uma entrada e nada desloca.
    eventos, _ = vr.build_ass_from_ctc(_timing("i", "am", "still", "still", "here", "go"),
                                       ["I'm still here", "Go"])
    t = vr.format_ass_time
    assert _linhas(eventos) == [("I'm still here", t(9.0), t(14.5 + 0.5)),
                                ("Go", t(14.0), t(15.5 + 0.5))]
    assert "1 de 6 entradas" in capsys.readouterr().out


def test_pontuacao_solta_continua_na_tela():
    eventos, _ = vr.build_ass_from_ctc(_timing("rock", "roll", "oh", "i", "know", "wait"),
                                       ["Rock & roll", "Oh — I know", "... wait"])
    assert [linha[0] for linha in _linhas(eventos)] == ["Rock & roll", "Oh — I know", "... wait"]


def test_refrao_repetido_com_duas_faltas_nao_pula_uma_repeticao():
    # Duas entradas a menos num trecho periodico: casar pelo maior bloco igual
    # (difflib) empurrava linhas uma repeticao para frente e descartava o fim.
    letra = ["Hold on"] + ["I won't fall", "for that"] * 3
    falado = "hold on" + " i will not fall for that" * 3
    completo = _timing(*falado.split())
    faltando = [e for k, e in enumerate(completo) if k not in (0, 7)]   # "hold" e o 1o "that"
    eventos, _ = vr.build_ass_from_ctc(faltando, letra)
    t = vr.format_ass_time
    # (1a, ultima) entrada com tempo de cada linha, em indices de `completo`
    faixas = [(1, 1), (2, 5), (6, 6), (8, 11), (12, 13), (14, 17), (18, 19)]
    assert _linhas(eventos) == [(txt, t(9.0 + a), t(10.5 + b + 0.5))
                                for txt, (a, b) in zip(letra, faixas)]
