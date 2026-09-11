"""
server_score_addendum.py — Rota POST /api/score.
Molde: server_preview_addendum.py (funcao make_*_route(app) chamada pelo server.py).

Aqui vive todo o I/O do scorer: upload, ffmpeg, leitura de disco. karaoke/scorer.py
segue puro.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from flask import jsonify, request

from karaoke import paths as kpaths
from karaoke.scorer import score, track_from_audio, track_from_word_timing

MAX_UPLOAD_BYTES = 8 * 1024 * 1024          # take de uma rodada nao passa disso
MODES = frozenset({"mimic", "karaoke"})     # lista FECHADA
REF_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MIMIC_REF_DIR = Path("input") / "mimic_refs"


def _erro(msg: str, status: int):
    return jsonify({"error": msg}), status


def _webm_para_wav(src: Path, dst: Path) -> bool:
    """16k mono, mesmo padrao de scripts/03_vocal_cleaning.py — incluindo o mkdir
    do diretorio de saida, cuja ausencia foi bug real naquele script."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)],
        capture_output=True,
    )
    return proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0


def make_score_route(app) -> None:
    @app.route("/api/score", methods=["POST"])
    def api_score():
        mode = (request.form.get("mode") or "").strip()
        if mode not in MODES:
            return _erro(f"mode invalido: esperado um de {sorted(MODES)}", 400)

        ref_id = (request.form.get("ref") or "").strip()
        if REF_ID_RE.match(ref_id) is None:
            return _erro("ref invalido: use [A-Za-z0-9_-], no maximo 64 caracteres", 400)

        upload = request.files.get("take")
        if upload is None:
            return _erro("take ausente: envie o audio gravado no campo 'take'", 400)

        blob = upload.read(MAX_UPLOAD_BYTES + 1)
        if len(blob) > MAX_UPLOAD_BYTES:
            return _erro(f"take maior que {MAX_UPLOAD_BYTES} bytes", 413)
        if not blob:
            return _erro("take vazio", 400)

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            src = tmpdir / "take.upload"
            src.write_bytes(blob)
            wav = tmpdir / "take.wav"
            if not _webm_para_wav(src, wav):
                return _erro("take nao pudemos decodificar como audio", 400)

            take_samples, sr = sf.read(wav, dtype="float32")
            if take_samples.ndim > 1:
                take_samples = take_samples.mean(axis=1)
            take = track_from_audio(take_samples, sr)

            if mode == "karaoke":
                wt = kpaths.word_timing_json(ref_id)
                vocals = kpaths.vocals_raw(ref_id)
                if not wt.exists() or not vocals.exists():
                    return _erro(f"job {ref_id} nao tem gabarito alinhado", 404)
                words = json.loads(wt.read_text(encoding="utf-8"))
                ref_samples, ref_sr = sf.read(vocals, dtype="float32")
                try:
                    ref = track_from_word_timing(words, ref_samples, ref_sr)
                except ValueError as exc:
                    return _erro(f"gabarito invalido: {exc}", 422)
            else:
                clip = MIMIC_REF_DIR / f"{ref_id}.wav"
                if not clip.exists():
                    return _erro(f"clipe de referencia {ref_id} nao existe", 404)
                ref_samples, ref_sr = sf.read(clip, dtype="float32")
                if ref_samples.ndim > 1:
                    ref_samples = ref_samples.mean(axis=1)
                ref = track_from_audio(ref_samples, ref_sr)

        report = score(ref, take)
        return jsonify({
            "melody": round(report.melody, 1),
            "rhythm": round(report.rhythm, 1),
            "attacks": round(report.attacks, 1),
            "total": round(report.total, 1),
            "n_onsets_ref": report.n_onsets_ref,
            "n_onsets_take": report.n_onsets_take,
            "n_frames_compared": report.n_frames_compared,
            "rhythm_tol_s": round(report.rhythm_tol_s, 4),
            "n_octave_suspect_ref": ref.n_octave_suspect,
            "n_voiced_ref": ref.n_voiced,
        })
