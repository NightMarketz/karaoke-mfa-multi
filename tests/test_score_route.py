import io
import json

import numpy as np
import pytest
import soundfile as sf
from flask import Flask

from karaoke.audio_fixtures import SR, bursts
from server_score_addendum import MODES, PITCH_DEFAULT, REF_ID_RE, make_score_route

# 5 ataques reais — o mesmo par usado em tests/test_scorer.py, so pra ter um
# take que passa pelo ffmpeg de verdade e produz um ScoreReport de verdade.
TIMES = [0.3, 0.9, 1.5, 2.4, 3.0]
FREQS = [220.0, 247.0, 262.0, 294.0, 330.0]


def _wav_bytes(samples, sr=SR):
    buf = io.BytesIO()
    sf.write(buf, samples, sr, format="WAV")
    buf.seek(0)
    return buf


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


def test_audio_indecodificavel_da_400_nao_500(client, monkeypatch, tmp_path):
    """ffmpeg falhando e erro do cliente, nao estouro do servidor."""
    import numpy as np
    import soundfile as sf
    import server_score_addendum as mod
    monkeypatch.setattr(mod, "MIMIC_REF_DIR", tmp_path)
    sf.write(tmp_path / "abc.wav", np.zeros(1600, dtype="float32"), 16000)
    lixo = io.BytesIO(b"isto nao e audio" * 10)
    r = client.post("/api/score", data={
        "mode": "mimic", "ref": "abc", "take": (lixo, "take.webm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400, f"veio {r.status_code}: {r.data[:200]}"


def test_wav_valido_sem_amostras_da_400_nao_500(client, monkeypatch, tmp_path):
    """Container valido com ZERO amostras: ffmpeg aceita e escreve so o header,
    sf.read devolve shape (0,), e track_from_audio estouraria em np.abs(x).max().
    Achado na revisao da Task 5 (2026-09-11): dava 500. Fronteira nunca da 500."""
    import numpy as np
    import soundfile as sf
    import server_score_addendum as mod
    monkeypatch.setattr(mod, "MIMIC_REF_DIR", tmp_path)
    sf.write(tmp_path / "abc.wav", np.zeros(1600, dtype="float32"), 16000)
    vazio = io.BytesIO()
    sf.write(vazio, np.zeros(0, dtype="float32"), 16000, format="WAV")
    vazio.seek(0)
    r = client.post("/api/score", data={
        "mode": "mimic", "ref": "abc", "take": (vazio, "take.wav"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400, f"veio {r.status_code}: {r.data[:200]}"
    assert "amostra" in r.get_json()["error"]


# ── GET /api/score/ref ───────────────────────────────────────────────────────
def test_ref_audio_modo_invalido_da_400(client):
    r = client.get("/api/score/ref?mode=sabotagem&ref=abc")
    assert r.status_code == 400
    assert "mode" in r.get_json()["error"]


def test_ref_audio_travessia_da_400(client):
    r = client.get("/api/score/ref?mode=karaoke&ref=../../etc/passwd")
    assert r.status_code == 400
    assert "ref" in r.get_json()["error"]


def test_ref_audio_inexistente_da_404(client):
    r = client.get("/api/score/ref?mode=mimic&ref=nao_existe_xyz")
    assert r.status_code == 404
    assert "nao_existe_xyz" in r.get_json()["error"]


def test_ref_audio_mimic_serve_wav(client, tmp_path, monkeypatch):
    """Caminho feliz sem depender de work/ (gitignored): aponta MIMIC_REF_DIR para um
    tmp com um WAV real de 0,1s e confere que volta 200 audio/wav com bytes."""
    import numpy as np
    import soundfile as sf
    import server_score_addendum as mod
    monkeypatch.setattr(mod, "MIMIC_REF_DIR", tmp_path)
    sf.write(tmp_path / "abc.wav", np.zeros(1600, dtype="float32"), 16000)
    r = client.get("/api/score/ref?mode=mimic&ref=abc")
    assert r.status_code == 200, f"veio {r.status_code}: {r.data[:120]}"
    assert r.mimetype == "audio/wav"
    assert len(r.data) > 44, f"corpo com {len(r.data)} bytes — menor que um header WAV"


def test_ffmpeg_ausente_da_503_nao_500(client, monkeypatch, tmp_path):
    """Ambiente sem ffmpeg e falha do servidor, nao do cliente: 503 com motivo."""
    import numpy as np
    import soundfile as sf
    import server_score_addendum as mod
    monkeypatch.setattr(mod, "MIMIC_REF_DIR", tmp_path)
    sf.write(tmp_path / "abc.wav", np.zeros(1600, dtype="float32"), 16000)

    def _sem_ffmpeg(*a, **k):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(mod.subprocess, "run", _sem_ffmpeg)
    r = client.post("/api/score", data={
        "mode": "mimic", "ref": "abc", "take": (io.BytesIO(b"x" * 100), "take.webm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 503, f"veio {r.status_code}: {r.data[:120]}"
    assert "ffmpeg" in r.get_json()["error"]


def test_ffmpeg_recebe_corte_de_duracao(client, monkeypatch, tmp_path):
    """-t MAX_TAKE_S tem que estar no argv: 8 MB de Opus sao ~3 h sem isso."""
    import numpy as np
    import soundfile as sf
    import server_score_addendum as mod
    monkeypatch.setattr(mod, "MIMIC_REF_DIR", tmp_path)
    sf.write(tmp_path / "abc.wav", np.zeros(1600, dtype="float32"), 16000)
    visto = {}

    def _captura(cmd, **k):
        visto["cmd"] = cmd
        raise FileNotFoundError("parar aqui")
    monkeypatch.setattr(mod.subprocess, "run", _captura)
    client.post("/api/score", data={
        "mode": "mimic", "ref": "abc", "take": (io.BytesIO(b"x" * 100), "take.webm"),
    }, content_type="multipart/form-data")
    cmd = visto.get("cmd")
    assert cmd is not None, "ffmpeg nao foi invocado"
    assert "-t" in cmd and str(mod.MAX_TAKE_S) in cmd, f"argv sem corte: {cmd}"
    assert cmd.index("-t") + 1 == cmd.index(str(mod.MAX_TAKE_S)), f"-t sem valor colado: {cmd}"


def test_lista_de_modos_e_fechada():
    assert MODES == frozenset({"mimic", "karaoke"})
    assert len(MODES) == 2, f"MODES tem {len(MODES)} entradas"


def test_nivel_de_afinacao_padrao_por_modo():
    """Karaoke cobra o tom (ignora oitava); imitar som cru so cobra a melodia."""
    assert PITCH_DEFAULT == {"karaoke": "oitava", "mimic": "relativo"}


def _post_mimic(client, monkeypatch, tmp_path, **extra):
    import server_score_addendum as mod
    monkeypatch.setattr(mod, "MIMIC_REF_DIR", tmp_path)
    sf.write(tmp_path / "abc.wav", bursts(TIMES, FREQS), SR)
    alto = bursts(TIMES, [f * 2 ** (3 / 12) for f in FREQS])
    return client.post("/api/score", data={
        "mode": "mimic", "ref": "abc", **extra,
        "take": (_wav_bytes(alto), "take.wav"),
    }, content_type="multipart/form-data")


def test_pitch_ausente_usa_o_padrao_do_modo(client, monkeypatch, tmp_path):
    r = _post_mimic(client, monkeypatch, tmp_path)
    assert r.status_code == 200, f"veio {r.status_code}: {r.data[:200]}"
    body = r.get_json()
    assert body["pitch"] == "relativo"
    assert body["melody"] >= 85.0, f"mimic transposto +3 deu melodia {body['melody']}"


def test_pitch_explicito_e_respeitado(client, monkeypatch, tmp_path):
    r = _post_mimic(client, monkeypatch, tmp_path, pitch="estrito")
    assert r.status_code == 200, f"veio {r.status_code}: {r.data[:200]}"
    body = r.get_json()
    assert body["pitch"] == "estrito"
    assert body["melody"] <= 15.0, f"estrito com +3 semitons deu melodia {body['melody']}"


def test_pitch_fora_da_lista_fechada_da_400(client, monkeypatch, tmp_path):
    r = _post_mimic(client, monkeypatch, tmp_path, pitch="facil")
    assert r.status_code == 400
    assert "pitch" in r.get_json()["error"]


@pytest.mark.parametrize("mau", ["../x", "a/b", "x" * 65, "", "a;b", "a b"])
def test_regex_de_ref_rejeita_entradas_ruins(mau):
    assert REF_ID_RE.match(mau) is None, f"{mau!r} passou pela regex"


@pytest.mark.parametrize("bom", ["mimic_gab_01", "abc-123", "A", "x" * 64])
def test_regex_de_ref_aceita_entradas_boas(bom):
    assert REF_ID_RE.match(bom) is not None, f"{bom!r} foi rejeitado"


# ── Coleta de take humano para pesquisa (save=1) ─────────────────────────────
# Objetivo: calibrar VOICE_FRAC/VOICE_PAD_MS/limiares de onset contra microfone
# de verdade em vez de stem do Demucs fazendo o papel de take (spec 2026-09-10,
# secao "Fica aberto"). Por padrao NADA e gravado — e opt-in por design, pra
# uma partida normal do jogo de festa nao acumular arquivo.

def test_sem_save_nao_grava_nada(client, monkeypatch, tmp_path):
    import server_score_addendum as mod
    monkeypatch.setattr(mod, "MIMIC_REF_DIR", tmp_path)
    monkeypatch.setattr(mod, "HUMAN_TAKES_DIR", tmp_path / "human_takes")
    sf.write(tmp_path / "abc.wav", bursts(TIMES, FREQS), SR)

    r = client.post("/api/score", data={
        "mode": "mimic", "ref": "abc",
        "take": (_wav_bytes(bursts(TIMES, FREQS)), "take.wav"),
    }, content_type="multipart/form-data")
    assert r.status_code == 200, f"veio {r.status_code}: {r.data[:200]}"
    assert not (tmp_path / "human_takes").exists(), "sem save=1, nao deveria existir nem o diretorio"


def test_save_truthy_grava_wav_e_json(client, monkeypatch, tmp_path):
    import server_score_addendum as mod
    monkeypatch.setattr(mod, "MIMIC_REF_DIR", tmp_path)
    takes_dir = tmp_path / "human_takes"
    monkeypatch.setattr(mod, "HUMAN_TAKES_DIR", takes_dir)
    sf.write(tmp_path / "abc.wav", bursts(TIMES, FREQS), SR)

    r = client.post("/api/score", data={
        "mode": "mimic", "ref": "abc", "save": "1",
        "participante": "ana", "condicao": "quarto silencioso",
        "take": (_wav_bytes(bursts(TIMES, FREQS)), "take.wav"),
    }, content_type="multipart/form-data")
    assert r.status_code == 200, f"veio {r.status_code}: {r.data[:200]}"

    wavs = list(takes_dir.glob("*.wav"))
    jsons = list(takes_dir.glob("*.json"))
    assert len(wavs) == 1, f"esperava 1 wav salvo, achei {len(wavs)}"
    assert len(jsons) == 1, f"esperava 1 json salvo, achei {len(jsons)}"

    meta = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert meta["mode"] == "mimic"
    assert meta["ref"] == "abc"
    assert meta["participante"] == "ana"
    assert meta["condicao"] == "quarto silencioso"
    assert meta["total"] == r.get_json()["total"], "json salvo tem que bater com a resposta HTTP"
    assert "timestamp" in meta

    # o wav salvo e' o take JA convertido (16k mono) — decodavel de volta sem ffmpeg
    saved_samples, saved_sr = sf.read(wavs[0])
    assert saved_sr == 16000
    assert len(saved_samples) > 0


def test_save_truthy_mas_scoring_falhou_nao_grava(client, monkeypatch, tmp_path):
    """save=1 nao deve gravar nada se o take nem chegou a ser pontuado (404 de
    referencia inexistente) — nao ha ScoreReport pra descrever."""
    import server_score_addendum as mod
    monkeypatch.setattr(mod, "MIMIC_REF_DIR", tmp_path)
    takes_dir = tmp_path / "human_takes"
    monkeypatch.setattr(mod, "HUMAN_TAKES_DIR", takes_dir)

    r = client.post("/api/score", data={
        "mode": "mimic", "ref": "nao_existe", "save": "1",
        "take": (_wav_bytes(bursts(TIMES, FREQS)), "take.wav"),
    }, content_type="multipart/form-data")
    assert r.status_code == 404
    assert not takes_dir.exists()


# ── Trecho [start, end] no karaoke ───────────────────────────────────────────
from karaoke import paths as kpaths
from karaoke.trechos import TRECHO_MAX_S


@pytest.fixture
def job_karaoke(monkeypatch, tmp_path):
    """Job falso de 10 s: 5 palavras em 0-3,25 s, silencio depois."""
    monkeypatch.setattr(kpaths, "repos_root", lambda: tmp_path)
    job = "job_trecho"
    wt = kpaths.word_timing_json(job)
    wt.parent.mkdir(parents=True, exist_ok=True)
    words = [{"word": f"w{i}", "start": t, "end": t + 0.25, "score": 1.0}
             for i, t in enumerate(TIMES)]
    wt.write_text(json.dumps(words), encoding="utf-8")
    voz = np.zeros(10 * SR, dtype="float32")
    b = bursts(TIMES, FREQS)
    voz[:len(b)] = b[:len(voz)]
    voc = kpaths.vocals_raw(job)
    voc.parent.mkdir(parents=True, exist_ok=True)
    sf.write(voc, voz, SR)
    return job


def _post_karaoke(client, job, **extra):
    return client.post("/api/score", data={
        "mode": "karaoke", "ref": job, **extra,
        "take": (_wav_bytes(bursts(TIMES, FREQS)), "take.wav"),
    }, content_type="multipart/form-data")


def test_max_take_cobre_trecho_mais_pre_roll():
    import server_score_addendum as mod
    assert mod.MAX_TAKE_S >= TRECHO_MAX_S + 2 + 0.5  # pre-roll + pos-roll de karaoke-vez.js


@pytest.mark.parametrize("start,end", [("-1", "5"), ("5", "5"), ("6", "2"), ("0", "31"),
                                       ("0", "99"), ("a", "5"), ("5", "")])
def test_trecho_invalido_da_400(client, monkeypatch, job_karaoke, start, end):
    import server_score_addendum as mod
    chamadas = []
    monkeypatch.setattr(mod, "_webm_para_wav", lambda *a, **k: chamadas.append(a) or False)
    r = _post_karaoke(client, job_karaoke, start=start, end=end)
    assert r.status_code == 400, f"veio {r.status_code}: {r.data[:200]}"
    assert "trecho" in r.get_json()["error"]
    assert not chamadas, "ffmpeg foi chamado antes de validar o trecho"


def test_trecho_so_start_da_400(client, monkeypatch, job_karaoke):
    import server_score_addendum as mod
    chamadas = []
    monkeypatch.setattr(mod, "_webm_para_wav", lambda *a, **k: chamadas.append(a) or False)
    r = _post_karaoke(client, job_karaoke, start="1")
    assert r.status_code == 400
    assert "trecho" in r.get_json()["error"]
    assert not chamadas


def test_trecho_sem_palavras_da_422(client, job_karaoke):
    r = _post_karaoke(client, job_karaoke, start="9.0", end="9.9")
    assert r.status_code == 422, f"veio {r.status_code}: {r.data[:200]}"


def test_trecho_valido_pontua(client, job_karaoke):
    r = _post_karaoke(client, job_karaoke, start="0", end="4")
    assert r.status_code == 200, f"veio {r.status_code}: {r.data[:200]}"
    assert isinstance(r.get_json()["total"], (int, float))
