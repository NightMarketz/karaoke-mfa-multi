import json

import pytest

from scripts.analyze_human_takes import agrupa_por_condicao, carrega_registros, resume


def _grava(tmp_path, nome, **campos):
    (tmp_path / f"{nome}.json").write_text(json.dumps(campos), encoding="utf-8")


def test_carrega_registros_le_todos_os_json(tmp_path):
    _grava(tmp_path, "a", total=90.0, condicao="silencio")
    _grava(tmp_path, "b", total=50.0, condicao="ruido")
    (tmp_path / "nota.wav").write_bytes(b"\x00")  # nao e' registro, tem que ser ignorado

    registros = carrega_registros(tmp_path)
    assert len(registros) == 2, f"esperava 2 registros, achei {len(registros)}"
    assert {r["total"] for r in registros} == {90.0, 50.0}


def test_carrega_registros_diretorio_vazio_da_lista_vazia(tmp_path):
    assert carrega_registros(tmp_path) == []


def test_agrupa_por_condicao_agrupa_certo():
    registros = [
        {"condicao": "silencio", "total": 90},
        {"condicao": "ruido", "total": 40},
        {"condicao": "silencio", "total": 80},
    ]
    grupos = agrupa_por_condicao(registros)
    assert set(grupos) == {"silencio", "ruido"}
    assert len(grupos["silencio"]) == 2
    assert len(grupos["ruido"]) == 1


def test_agrupa_por_condicao_usa_rotulo_pra_ausente():
    grupos = agrupa_por_condicao([{"condicao": "", "total": 1}, {"total": 2}])
    assert set(grupos) == {"(sem condicao)"}
    assert len(grupos["(sem condicao)"]) == 2


def test_resume_calcula_media_mediana_min_max():
    grupo = [
        {"total": 80.0, "melody": 90.0, "rhythm": 70.0, "attacks": 60.0},
        {"total": 100.0, "melody": 90.0, "rhythm": 90.0, "attacks": 100.0},
    ]
    r = resume(grupo)
    assert r["n"] == 2
    assert r["total"]["media"] == 90.0
    assert r["total"]["mediana"] == 90.0
    assert r["total"]["min"] == 80.0
    assert r["total"]["max"] == 100.0


def test_resume_em_grupo_vazio_e_falha_nao_sucesso():
    """Cardinalidade antes do veredito: n=0 tem que ser visivel, nunca virar
    media/mediana de populacao vazia (NaN silencioso lido como numero real)."""
    r = resume([])
    assert r == {"n": 0}, f"grupo vazio nao pode fingir ter estatistica: {r}"
