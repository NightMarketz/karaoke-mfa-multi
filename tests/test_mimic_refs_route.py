import io

import numpy as np
import pytest
import soundfile as sf
from flask import Flask

from karaoke.audio_fixtures import SR, bursts
from server_mimic_refs_addendum import make_mimic_refs_route

# 6 ataques, ~2,5s de duracao apos recorte por voz — passa MIN_ATAQUES=6/MIN_DUR_S=1.5
BOM_TIMES = [0.3, 0.8, 1.3, 1.8, 2.3, 2.8]
BOM_FREQS = [220.0, 247.0, 262.0, 294.0, 330.0, 349.0]


def _wav_bytes(samples: np.ndarray, sr: int = SR) -> io.BytesIO:
    buf = io.BytesIO()
    sf.write(buf, samples, sr, format="WAV")
    buf.seek(0)
    return buf


def _clipe_bom() -> io.BytesIO:
    return _wav_bytes(bursts(BOM_TIMES, BOM_FREQS))


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    make_mimic_refs_route(app)
    return app.test_client()


@pytest.fixture
def refs_dir(tmp_path, monkeypatch):
    import server_mimic_refs_addendum as mod
    monkeypatch.setattr(mod, "MIMIC_REF_DIR", tmp_path)
    return tmp_path


def test_lista_vazia_de_inicio(client, refs_dir):
    r = client.get("/api/mimic_refs")
    assert r.status_code == 200
    assert r.get_json() == []


def test_upload_valido_aparece_na_lista(client, refs_dir):
    r = client.post("/api/mimic_refs", data={
        "file": (_clipe_bom(), "meu_clipe.wav"),
    }, content_type="multipart/form-data")
    assert r.status_code == 201, f"veio {r.status_code}: {r.data[:200]}"
    criado = r.get_json()
    assert criado["id"] == "meu_clipe"
    assert criado["duration_s"] > 1.5

    r = client.get("/api/mimic_refs")
    lista = r.get_json()
    assert [c["id"] for c in lista] == ["meu_clipe"], f"lista: {lista}"
    assert lista[0]["duration_s"] > 1.5


def test_extensao_invalida_da_400(client, refs_dir):
    r = client.post("/api/mimic_refs", data={
        "file": (io.BytesIO(b"lixo"), "clipe.exe"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400, f"veio {r.status_code}"
    assert "extens" in r.get_json()["error"]


def test_arquivo_grande_demais_da_413(client, refs_dir):
    from server_mimic_refs_addendum import MAX_UPLOAD_BYTES
    grande = io.BytesIO(b"\x00" * (MAX_UPLOAD_BYTES + 1))
    r = client.post("/api/mimic_refs", data={
        "file": (grande, "clipe.wav"),
    }, content_type="multipart/form-data")
    assert r.status_code == 413, f"veio {r.status_code}"


def test_clipe_fraco_rejeitado_pela_curadoria(client, refs_dir):
    """Silencio: 0 ataques (<6) e duracao 0 (<1,5s) — a mesma regua de
    scripts/fetch_mimic_refs.py, so que aqui e' rejeicao dura (422), nao aviso."""
    mudo = _wav_bytes(np.zeros(int(2.0 * SR), dtype="float32"))
    r = client.post("/api/mimic_refs", data={
        "file": (mudo, "mudo.wav"),
    }, content_type="multipart/form-data")
    assert r.status_code == 422, f"veio {r.status_code}: {r.data[:200]}"
    assert not (refs_dir / "mudo.wav").exists(), "clipe reprovado nao deveria sobrar em disco"


def test_delete_remove_arquivo(client, refs_dir):
    client.post("/api/mimic_refs", data={
        "file": (_clipe_bom(), "apagar_me.wav"),
    }, content_type="multipart/form-data")
    assert (refs_dir / "apagar_me.wav").exists()

    r = client.delete("/api/mimic_refs/apagar_me")
    assert r.status_code == 200, f"veio {r.status_code}"
    assert not (refs_dir / "apagar_me.wav").exists()


def test_delete_id_invalido_da_400(client, refs_dir):
    """'/../' num segmento de URL e' normalizado pelo roteador antes de chegar
    na view (vira 404, nao 400) — o caso que a REGEX precisa pegar e' um id de
    UM segmento com caractere fora do alfabeto, tipo ';'."""
    r = client.delete("/api/mimic_refs/a;b")
    assert r.status_code == 400
    assert "id" in r.get_json()["error"]


def test_delete_com_travessia_de_caminho_da_404_via_roteador(client, refs_dir):
    """Documenta a mecanica acima: o Flask nunca entrega '../../etc/passwd' pra
    view — colapsa a URL e nao acha rota de 3 segmentos, 404 antes da regex."""
    r = client.delete("/api/mimic_refs/../../etc/passwd")
    assert r.status_code == 404


def test_delete_inexistente_da_404(client, refs_dir):
    r = client.delete("/api/mimic_refs/nao_existe_xyz")
    assert r.status_code == 404


def test_nome_colidindo_gera_sufixo(client, refs_dir):
    r1 = client.post("/api/mimic_refs", data={
        "file": (_clipe_bom(), "duplicado.wav"),
    }, content_type="multipart/form-data")
    r2 = client.post("/api/mimic_refs", data={
        "file": (_clipe_bom(), "duplicado.wav"),
    }, content_type="multipart/form-data")
    assert r1.get_json()["id"] == "duplicado"
    assert r2.get_json()["id"] == "duplicado-2", f"veio {r2.get_json()}"
    assert (refs_dir / "duplicado.wav").exists()
    assert (refs_dir / "duplicado-2.wav").exists()


def test_rotulo_opcional_vira_id_no_lugar_do_nome_do_arquivo(client, refs_dir):
    r = client.post("/api/mimic_refs", data={
        "file": (_clipe_bom(), "recording_2024_final_v3.wav"),
        "label": "grito de vitoria!",
    }, content_type="multipart/form-data")
    assert r.status_code == 201, f"veio {r.status_code}: {r.data[:200]}"
    assert r.get_json()["id"] == "grito_de_vitoria_", f"veio {r.get_json()}"
