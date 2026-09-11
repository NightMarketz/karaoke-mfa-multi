import io

import pytest
from flask import Flask

from server_score_addendum import MODES, REF_ID_RE, make_score_route


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    make_score_route(app)
    return app.test_client()


def test_modo_fora_da_lista_fechada_da_400(client):
    r = client.post("/api/score", data={
        "mode": "sabotagem",
        "ref": "mimic_gab_01",
        "take": (io.BytesIO(b"\x00" * 100), "take.webm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400, f"veio {r.status_code}"
    assert "mode" in r.get_json()["error"]


def test_ref_com_travessia_de_caminho_da_400(client):
    """Nunca interpolar ref em caminho: ../ tem que morrer na fronteira."""
    r = client.post("/api/score", data={
        "mode": "karaoke",
        "ref": "../../etc/passwd",
        "take": (io.BytesIO(b"\x00" * 100), "take.webm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "ref" in r.get_json()["error"]


def test_upload_ausente_da_400(client):
    r = client.post("/api/score", data={"mode": "mimic", "ref": "abc"},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "take" in r.get_json()["error"]


def test_upload_grande_demais_da_413(client):
    from server_score_addendum import MAX_UPLOAD_BYTES
    grande = io.BytesIO(b"\x00" * (MAX_UPLOAD_BYTES + 1))
    r = client.post("/api/score", data={
        "mode": "mimic", "ref": "abc", "take": (grande, "take.webm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 413, f"veio {r.status_code}"


def test_audio_indecodificavel_da_400_nao_500(client):
    """ffmpeg falhando e erro do cliente, nao estouro do servidor."""
    lixo = io.BytesIO(b"isto nao e audio" * 10)
    r = client.post("/api/score", data={
        "mode": "mimic", "ref": "abc", "take": (lixo, "take.webm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400, f"veio {r.status_code}: {r.data[:200]}"


def test_lista_de_modos_e_fechada():
    assert MODES == frozenset({"mimic", "karaoke"})
    assert len(MODES) == 2, f"MODES tem {len(MODES)} entradas"


@pytest.mark.parametrize("mau", ["../x", "a/b", "x" * 65, "", "a;b", "a b"])
def test_regex_de_ref_rejeita_entradas_ruins(mau):
    assert REF_ID_RE.match(mau) is None, f"{mau!r} passou pela regex"


@pytest.mark.parametrize("bom", ["mimic_gab_01", "abc-123", "A", "x" * 64])
def test_regex_de_ref_aceita_entradas_boas(bom):
    assert REF_ID_RE.match(bom) is not None, f"{bom!r} foi rejeitado"
