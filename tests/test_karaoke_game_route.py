import json

import numpy as np
import pytest
import soundfile as sf
from flask import Flask

import server_karaoke_game_addendum as mod
from karaoke import paths as kpaths
from karaoke.lyrics_cleaner import clean_lyrics_strict, normalise_lyrics

LETRA = [" ".join(f"p{i}_{k}" for k in range(6)) for i in range(6)]


def _alinha(linhas, dur=1.0):
    """Como o pipeline real: alinha normalise_lyrics(clean_lyrics_strict(letra))."""
    texto = normalise_lyrics(clean_lyrics_strict("\n".join(linhas)))
    t, out = 0.0, []
    for tok in texto.split():
        out.append({"word": tok, "start": t, "end": t + dur, "score": 1.0})
        t += dur
    return out


def _wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.zeros(16000, dtype="float32"), 16000)


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(kpaths, "repos_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "JOBS_DIR", tmp_path / "work" / "jobs")
    estado = {}
    monkeypatch.setattr(mod.state_store, "get_job", lambda jid: estado.get(jid))

    def cria(job_id, sem=None, palavras=None):
        sem = sem or ()
        if "word_timing" not in sem:
            p = kpaths.word_timing_json(job_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            dados = _alinha(LETRA) if palavras is None else palavras
            p.write_text(json.dumps(dados), encoding="utf-8")
        if "vocals" not in sem:
            _wav(kpaths.vocals_raw(job_id))
        if "instrumental" not in sem:
            _wav(kpaths.instrumental(job_id))
        if "lyrics" not in sem:
            p = kpaths.lyrics_path(job_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("\n".join(LETRA), encoding="utf-8")

    cria.estado = estado
    return cria


@pytest.fixture
def client(jobs):
    app = Flask(__name__)
    app.config["TESTING"] = True
    mod.make_karaoke_game_route(app)
    return app.test_client()


def test_lista_so_jogaveis(jobs, client):
    jobs("ok")
    jobs("sem_base", sem=("instrumental",))
    jobs("sem_letra", sem=("lyrics",))
    r = client.get("/api/karaoke/songs")
    assert r.status_code == 200
    assert [s["id"] for s in r.json] == ["ok"]
    assert r.json[0]["duracao_s"] == 1.0


@pytest.mark.parametrize("lixo", [b"", b"nao e um wav"])
def test_lista_pula_instrumental_ilegivel(jobs, client, lixo):
    jobs("ok")
    jobs("quebrado")
    kpaths.instrumental("quebrado").write_bytes(lixo)
    r = client.get("/api/karaoke/songs")
    assert r.status_code == 200
    assert [s["id"] for s in r.json] == ["ok"]


def test_lista_vazia_sem_pasta_de_jobs(client):
    assert client.get("/api/karaoke/songs").json == []


def test_titulo_vem_do_audio_name_e_cai_no_id(jobs, client):
    jobs("ok")
    jobs("outro")
    jobs.estado["ok"] = {"audio_name": "Minha Musica.mp3"}
    por_id = {s["id"]: s["titulo"] for s in client.get("/api/karaoke/songs").json}
    assert por_id["ok"] == "Minha Musica"
    assert por_id["outro"] == "outro"


def test_trechos_devolve_lista(jobs, client):
    jobs("ok")
    r = client.get("/api/karaoke/ok/trechos")
    assert r.status_code == 200
    assert isinstance(r.json, list) and r.json
    assert {"inicio", "fim", "versos"} <= set(r.json[0])


def test_trechos_letra_inconsistente_da_422(jobs, client):
    jobs("ok", palavras=_alinha(LETRA)[:-1])
    r = client.get("/api/karaoke/ok/trechos")
    assert r.status_code == 422
    assert "tokens" in r.json["error"]


def test_trechos_word_timing_json_invalido_da_422(jobs, client):
    jobs("ok")
    kpaths.word_timing_json("ok").write_text("{nao e json", encoding="utf-8")
    r = client.get("/api/karaoke/ok/trechos")
    assert r.status_code == 422
    assert "error" in r.json


def test_trechos_letra_nao_utf8_da_422(jobs, client):
    jobs("ok")
    kpaths.lyrics_path("ok").write_bytes(b"\xff\xfe\xfa letra latin-1 \xe7")
    r = client.get("/api/karaoke/ok/trechos")
    assert r.status_code == 422
    assert "error" in r.json


def test_trechos_letra_com_tags_e_adlibs_nao_da_422(jobs, client):
    letra = ["[Refrão]"] + [f"{l} (oh oh)" for l in LETRA[:3]] + ["", "[Verso]"] + LETRA[3:]
    jobs("ok", palavras=_alinha(letra))
    kpaths.lyrics_path("ok").write_text("\n".join(letra), encoding="utf-8")
    r = client.get("/api/karaoke/ok/trechos")
    assert r.status_code == 200
    assert r.json[0]["versos"][0]["texto"] == LETRA[0]


def test_base_serve_wav(jobs, client):
    jobs("ok")
    r = client.get("/api/karaoke/ok/base")
    assert r.status_code == 200
    assert r.mimetype == "audio/wav"


@pytest.mark.parametrize("rota", ["trechos", "base"])
def test_job_inexistente_da_404(client, rota):
    assert client.get(f"/api/karaoke/nao_existe/{rota}").status_code == 404


@pytest.mark.parametrize("rota", ["trechos", "base"])
@pytest.mark.parametrize("mau", ["..", "a.b", "x" * 65])
def test_job_invalido_da_400(client, rota, mau):
    r = client.get(f"/api/karaoke/{mau}/{rota}")
    assert r.status_code == 400
