import pytest

from karaoke.trechos import normaliza, trechos_da_letra, versos_da_letra


def _alinha(linhas, dur=1.0):
    t, out = 0.0, []
    for linha in linhas:
        for tok in linha.split():
            out.append({"word": tok, "start": t, "end": t + dur, "score": 1.0})
            t += dur
    return out


REFRAO = [
    "Amor, amor, meu amor que vai",
    "Sempre volta sem pedir sua licenca",
    "um dois tres quatro cinco seis",
    "sete oito nove dez onze doze",
    "a b c d e f",
    "g h i j k l",
    "",
    "amor amor meu amor que vai!",
    "Sempre volta sem pedir sua licenca",
    "",
    "m n o p q r",
    "s t u v w x",
]

SEM_REPETICAO = [
    " ".join(f"p{i}_{k}" for k in range(6)) for i in range(12)
]


def test_versos_seguem_linhas_e_estrofes():
    versos = versos_da_letra(REFRAO, _alinha(REFRAO))
    assert len(versos) == len([x for x in REFRAO if x.strip()])
    assert versos[0]["inicio"] == 0.0
    assert versos[0]["fim"] == 6.0
    assert [v["estrofe"] for v in versos] == [0] * 6 + [1] * 2 + [2] * 2
    assert versos[0]["palavras"][0]["texto"] == "Amor,"


def test_contagem_divergente_e_erro():
    with pytest.raises(ValueError, match=r"\d+ tokens.*\d+ palavras"):
        versos_da_letra(REFRAO, _alinha(REFRAO)[:-1])


def test_normaliza_ignora_caixa_acento_pontuacao():
    assert normaliza("Amor, AMÔR!  meu") == normaliza("amor amor meu")


def test_refrao_vem_primeiro():
    t = trechos_da_letra(REFRAO, _alinha(REFRAO))
    assert t[0]["refrao"] is True
    alvos = {
        normaliza("Sempre volta sem pedir sua licenca"),
        normaliza("amor amor meu amor que vai"),
    }
    textos = {normaliza(v["texto"]) for v in t[0]["versos"]}
    assert alvos & textos
    flags = [x["refrao"] for x in t]
    assert flags == sorted(flags, reverse=True)
    assert [x["id"] for x in t] == list(range(len(t)))


def test_sem_repeticao_cai_na_reserva():
    t = trechos_da_letra(SEM_REPETICAO, _alinha(SEM_REPETICAO))
    assert t
    assert all(x["refrao"] is False for x in t)
    for x in t:
        assert 20.0 <= x["fim"] - x["inicio"] <= 30.0
    for a in t:
        for b in t:
            if a is not b:
                assert a["fim"] <= b["inicio"] or b["fim"] <= a["inicio"]


def test_verso_longo_vira_trecho_marcado():
    linhas = [" ".join(f"w{i}" for i in range(40))]
    t = trechos_da_letra(linhas, _alinha(linhas))
    longos = [x for x in t if x["longo"] is True]
    assert longos and len(longos[0]["versos"]) == 1


def test_letra_curta_devolve_vazio():
    linhas = ["a b c d e f", "g h i j k l"]
    assert trechos_da_letra(linhas, _alinha(linhas)) == []
