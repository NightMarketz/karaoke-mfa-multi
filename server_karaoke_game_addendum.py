"""
server_karaoke_game_addendum.py — rotas do modo Karaoke do jogo de festa:
lista de musicas jogaveis, trechos cantaveis e base instrumental.
Molde: server_score_addendum.py (make_*_route(app) chamada pelo server.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import soundfile as sf
from flask import jsonify, send_file

from karaoke import paths as kpaths
from karaoke import state_store
from karaoke.trechos import trechos_da_letra
from server_score_addendum import REF_ID_RE, _erro

# Pasta que contem um subdiretorio por job. Modulo-level pra os testes trocarem.
JOBS_DIR = kpaths.repos_root() / "work" / "jobs"


def jogavel(job_id: str) -> bool:
    """Jogavel = gabarito alinhado + voz de referencia + base instrumental + letra
    (os trechos vem do lyrics.txt)."""
    return all(
        p.exists()
        for p in (
            kpaths.word_timing_json(job_id),
            kpaths.vocals_raw(job_id),
            kpaths.instrumental(job_id),
            kpaths.lyrics_path(job_id),
        )
    )


def _titulo(job_id: str) -> str:
    estado = state_store.get_job(job_id)
    if estado and estado.get("audio_name"):
        return Path(estado["audio_name"]).stem
    return job_id


def _valida(job_id: str):
    """None se ok; senao a resposta de erro (400 regex, depois 404)."""
    if REF_ID_RE.match(job_id) is None:
        return _erro("job invalido: use [A-Za-z0-9_-], no maximo 64 caracteres", 400)
    if not jogavel(job_id):
        return _erro(f"job {job_id} nao e jogavel", 404)
    return None


def make_karaoke_game_route(app) -> None:
    @app.route("/api/karaoke/songs", methods=["GET"])
    def api_karaoke_songs():
        # ponytail: varre o disco a cada chamada, sem cache; teto = algumas centenas
        # de jobs. Gatilho de upgrade: lista lenta com biblioteca grande.
        out = []
        if JOBS_DIR.is_dir():
            for d in JOBS_DIR.iterdir():
                if not d.is_dir() or REF_ID_RE.match(d.name) is None or not jogavel(d.name):
                    continue
                try:
                    dur = sf.info(str(kpaths.instrumental(d.name))).duration
                except (RuntimeError, OSError):
                    continue  # base vazia/corrompida (Demucs caiu): nao jogavel
                out.append({"id": d.name, "titulo": _titulo(d.name), "duracao_s": round(dur, 1)})
        out.sort(key=lambda s: s["titulo"])
        return jsonify(out)

    @app.route("/api/karaoke/<job>/trechos", methods=["GET"])
    def api_karaoke_trechos(job):
        erro = _valida(job)
        if erro:
            return erro
        linhas = kpaths.lyrics_path(job).read_text(encoding="utf-8").splitlines()
        palavras = json.loads(kpaths.word_timing_json(job).read_text(encoding="utf-8"))
        try:
            return jsonify(trechos_da_letra(linhas, palavras))
        except ValueError as exc:
            return _erro(f"letra inconsistente com o alinhamento: {exc}", 422)

    @app.route("/api/karaoke/<job>/base", methods=["GET"])
    def api_karaoke_base(job):
        erro = _valida(job)
        if erro:
            return erro
        return send_file(str(kpaths.instrumental(job)), mimetype="audio/wav")
