import pytest
from flask import Flask

import server_result_addendum as mod
from karaoke import paths as kpaths

ROTAS = ["ass", "lyrics", "audio", "word_timing"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(kpaths, "repos_root", lambda: tmp_path)
    app = Flask(__name__)
    mod.make_result_route(app)
    return app.test_client()


def _escreve(path, conteudo=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(conteudo)


def test_audio_acha_song_no_input_do_job(client):
    _escreve(kpaths.input_dir("j1") / "song.wav")
    r = client.get("/api/result/audio?job_id=j1")
    assert r.status_code == 200
    assert r.mimetype == "audio/wav"


def test_ass_le_08_ass_lyrics(client):
    _escreve(kpaths.final_ass("j1"), b"[Script Info]\n")
    r = client.get("/api/result/ass?job_id=j1")
    assert r.status_code == 200
    assert r.data == b"[Script Info]\n"


def test_lyrics_e_word_timing_do_job(client):
    _escreve(kpaths.lyrics_path("j1"), b"oi")
    _escreve(kpaths.word_timing_json("j1"), b"[]")
    assert client.get("/api/result/lyrics?job_id=j1").status_code == 200
    assert client.get("/api/result/word_timing?job_id=j1").status_code == 200


@pytest.mark.parametrize("rota", ROTAS)
def test_job_id_ausente_da_400(client, rota):
    assert client.get(f"/api/result/{rota}").status_code == 400


@pytest.mark.parametrize("mau", ["../x", "a/b", "x" * 65])
@pytest.mark.parametrize("rota", ROTAS)
def test_job_id_invalido_da_400(client, rota, mau):
    r = client.get(f"/api/result/{rota}", query_string={"job_id": mau})
    assert r.status_code == 400
    assert "error" in r.get_json()


@pytest.mark.parametrize("rota", ROTAS)
def test_arquivo_ausente_da_404(client, rota):
    assert client.get(f"/api/result/{rota}?job_id=j1").status_code == 404
