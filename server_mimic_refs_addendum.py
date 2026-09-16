"""
server_mimic_refs_addendum.py — Rotas GET/POST /api/mimic_refs e DELETE /api/mimic_refs/<id>.
Molde: server_score_addendum.py (funcao make_*_route(app) chamada pelo server.py).

Upload entra por fronteira de confianca: extensao, tamanho, decodificacao via ffmpeg e a
mesma regra de curadoria medida em scripts/fetch_mimic_refs.py (MIN_ATAQUES/MIN_DUR_S) —
aqui promovida de aviso (FRAGIL) a rejeicao dura (422), porque o clipe vira parte da
biblioteca em vez de um caso avulso que quem monta o pack decide manter.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
import tempfile

import soundfile as sf
from flask import jsonify, request

from karaoke.scorer import track_from_audio
from server_score_addendum import FfmpegAusente, MIMIC_REF_DIR, REF_ID_RE, _webm_para_wav

ALLOWED_UPLOAD_EXT = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}  # mesma lista de ALLOWED_AUDIO_EXT (server.py)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # folgado pra um som curto de biblioteca
CLIP_MAX_S = 15                      # clipe de biblioteca e curto por natureza, nao e take de rodada (30s)
MIN_ATAQUES = 6                      # mesma regua de scripts/fetch_mimic_refs.py
MIN_DUR_S = 1.5


def _erro(msg: str, status: int):
    return jsonify({"error": msg}), status


def _slug(nome: str) -> str:
    """Nome de arquivo ou rotulo -> [A-Za-z0-9_-], o alfabeto que REF_ID_RE exige."""
    base = Path(nome).stem.strip()
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", base)[:64]
    return slug or "clip"


def _dedup_id(slug: str) -> str:
    """slug livre -> slug-2, slug-3... se ja existir um wav com esse nome."""
    if not (MIMIC_REF_DIR / f"{slug}.wav").exists():
        return slug
    n = 2
    while True:
        sufixo = f"-{n}"
        candidato = slug[:64 - len(sufixo)] + sufixo
        if not (MIMIC_REF_DIR / f"{candidato}.wav").exists():
            return candidato
        n += 1


def make_mimic_refs_route(app) -> None:
    @app.route("/api/mimic_refs", methods=["GET"])
    def api_mimic_refs_list():
        MIMIC_REF_DIR.mkdir(parents=True, exist_ok=True)
        clipes = []
        for wav in sorted(MIMIC_REF_DIR.glob("*.wav")):
            try:
                info = sf.info(str(wav))
                dur = round(info.frames / info.samplerate, 2)
            except Exception:
                dur = 0.0
            clipes.append({"id": wav.stem, "label": wav.stem, "duration_s": dur})
        return jsonify(clipes)

    @app.route("/api/mimic_refs", methods=["POST"])
    def api_mimic_refs_upload():
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return _erro("arquivo ausente: envie o audio no campo 'file'", 400)

        ext = os.path.splitext(upload.filename)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXT:
            return _erro(f"extensao '{ext}' nao permitida", 400)

        blob = upload.read(MAX_UPLOAD_BYTES + 1)
        if len(blob) > MAX_UPLOAD_BYTES:
            return _erro(f"arquivo maior que {MAX_UPLOAD_BYTES} bytes", 413)
        if not blob:
            return _erro("arquivo vazio", 400)

        label = (request.form.get("label") or "").strip()
        slug_base = _slug(label or upload.filename)

        MIMIC_REF_DIR.mkdir(parents=True, exist_ok=True)
        ref_id = _dedup_id(slug_base)
        if REF_ID_RE.match(ref_id) is None:
            return _erro("id gerado invalido a partir do nome/rotulo", 400)

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / f"upload{ext}"
            src.write_bytes(blob)
            dst = MIMIC_REF_DIR / f"{ref_id}.wav"
            try:
                ok = _webm_para_wav(src, dst, max_s=CLIP_MAX_S)
            except FfmpegAusente:
                return _erro("ffmpeg indisponivel no servidor", 503)
            if not ok:
                dst.unlink(missing_ok=True)
                return _erro("arquivo nao pudemos decodificar como audio", 400)

            samples, sr = sf.read(dst, dtype="float32")
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            if samples.size == 0:
                dst.unlink(missing_ok=True)
                return _erro("clipe sem amostras de audio", 400)

            track = track_from_audio(samples, sr)
            if len(track.onsets) < MIN_ATAQUES or track.duration < MIN_DUR_S:
                dst.unlink(missing_ok=True)
                return _erro(
                    f"clipe fraco demais para o ritmo (<{MIN_ATAQUES} ataques ou <{MIN_DUR_S}s: "
                    "vira ruido, nao entra na biblioteca)",
                    422,
                )

        return jsonify({
            "id": ref_id,
            "label": ref_id,  # igual ao GET: o rotulo livre nao e persistido
            "duration_s": round(track.duration, 2),
        }), 201

    @app.route("/api/mimic_refs/<ref_id>", methods=["DELETE"])
    def api_mimic_refs_delete(ref_id):
        if REF_ID_RE.match(ref_id) is None:
            return _erro("id invalido: use [A-Za-z0-9_-], no maximo 64 caracteres", 400)
        wav = MIMIC_REF_DIR / f"{ref_id}.wav"
        if not wav.exists():
            return _erro(f"clipe {ref_id} nao existe", 404)
        wav.unlink()
        return jsonify({"deleted": ref_id})
