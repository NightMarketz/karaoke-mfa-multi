"""
server_result_addendum.py — rotas /api/result/* que o player (web/karaoke-player.js)
consome: .ass, letra, audio e word_timing de um job. Caminhos so via kpaths e job_id
validado pela REF_ID_RE antes de virar caminho.
Molde: server_score_addendum.py (make_*_route(app) chamada pelo server.py).
"""
from __future__ import annotations

from flask import request, send_file

from karaoke import paths as kpaths
from server_score_addendum import REF_ID_RE, _erro

AUDIO_MIME = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
    ".flac": "audio/flac", ".m4a": "audio/mp4",
}


def _job_id():
    """(job_id, None) se ok; (None, resposta de erro) se ausente ou invalido."""
    job_id = request.args.get("job_id")
    if not job_id:
        return None, _erro("job_id ausente", 400)
    if REF_ID_RE.match(job_id) is None:
        return None, _erro("job invalido: use [A-Za-z0-9_-], no maximo 64 caracteres", 400)
    return job_id, None


def make_result_route(app) -> None:
    @app.route("/api/result/ass")
    def api_result_ass():
        job_id, erro = _job_id()
        if erro:
            return erro
        p = kpaths.final_ass(job_id)
        if not p.exists():
            return _erro("ASS nao encontrado", 404)
        return send_file(str(p), mimetype="text/plain", as_attachment=True,
                         download_name="karaoke.ass")

    @app.route("/api/result/lyrics")
    def api_result_lyrics():
        job_id, erro = _job_id()
        if erro:
            return erro
        p = kpaths.lyrics_path(job_id)
        if not p.exists():
            return _erro("letra nao encontrada", 404)
        return send_file(str(p), mimetype="text/plain", as_attachment=True,
                         download_name="lyrics.txt")

    @app.route("/api/result/audio")
    def api_result_audio():
        job_id, erro = _job_id()
        if erro:
            return erro
        for ext, mime in AUDIO_MIME.items():
            p = kpaths.input_dir(job_id) / f"song{ext}"
            if p.exists():
                return send_file(str(p), mimetype=mime)
        return _erro("audio nao encontrado", 404)

    @app.route("/api/result/word_timing")
    def api_result_word_timing():
        job_id, erro = _job_id()
        if erro:
            return erro
        p = kpaths.word_timing_json(job_id)
        if not p.exists():
            return _erro("word_timing nao encontrado", 404)
        return send_file(str(p), mimetype="application/json")
