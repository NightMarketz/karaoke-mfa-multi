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
import time
from pathlib import Path

import soundfile as sf
from flask import jsonify, request, send_file

from karaoke import paths as kpaths
from karaoke.scorer import score, track_from_audio, track_from_word_timing

MAX_UPLOAD_BYTES = 8 * 1024 * 1024          # take de uma rodada nao passa disso
MAX_TAKE_S = 30                             # ffmpeg corta aqui: 8 MB de Opus sao ~3 h
FFMPEG_TIMEOUT_S = 60                       # container malformado nao pendura o worker
MODES = frozenset({"mimic", "karaoke"})     # lista FECHADA
REF_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Ancorado na raiz do repo como todos os acessores de kpaths. Relativo ao CWD,
# path.exists() e send_file() resolviam contra raizes DIFERENTES (CWD vs app.root_path).
MIMIC_REF_DIR = kpaths.repos_root() / "input" / "mimic_refs"
# Coleta pra calibrar contra microfone de verdade (spec 2026-09-10, "Fica aberto":
# todo numero existente vem do stem do Demucs fazendo papel de take). Opt-in via
# save=1 no POST — uma partida normal do jogo de festa nunca escreve aqui.
HUMAN_TAKES_DIR = kpaths.repos_root() / "input" / "human_takes"
_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]")


def _erro(msg: str, status: int):
    return jsonify({"error": msg}), status


def _salva_take_para_pesquisa(wav_bytes, mode, ref_id, participante, condicao, report):
    """Grava o take (ja convertido, 16k mono) + o ScoreReport ao lado, pra alimentar
    scripts/analyze_human_takes.py depois. ponytail: nome de arquivo so com timestamp
    em ms, sem dedup — coleta e manual, uma pessoa grava um take de cada vez; upgrade
    seria um contador atomico se isso um dia virar automatizado."""
    HUMAN_TAKES_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    partes = [str(ts), mode, ref_id]
    for campo in (participante, condicao):
        if campo:
            partes.append(_SLUG_RE.sub("_", campo.strip())[:40])
    base = "_".join(partes)
    (HUMAN_TAKES_DIR / f"{base}.wav").write_bytes(wav_bytes)
    meta = {
        "timestamp": ts,
        "mode": mode,
        "ref": ref_id,
        "participante": participante,
        "condicao": condicao,
        "melody": round(report.melody, 1),
        "rhythm": round(report.rhythm, 1),
        "attacks": round(report.attacks, 1),
        "total": round(report.total, 1),
        "n_onsets_ref": report.n_onsets_ref,
        "n_onsets_take": report.n_onsets_take,
        "n_matched": report.n_matched,
    }
    (HUMAN_TAKES_DIR / f"{base}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class FfmpegAusente(RuntimeError):
    """ffmpeg nao esta no PATH: falha de ambiente, nao do cliente."""


def _webm_para_wav(src: Path, dst: Path, max_s: int = MAX_TAKE_S) -> bool:
    """16k mono, mesmo padrao de scripts/03_vocal_cleaning.py — incluindo o mkdir
    do diretorio de saida, cuja ausencia foi bug real naquele script.
    -t limita a duracao decodificada (um take de rodada cabe em MAX_TAKE_S) e
    timeout impede que um container malformado pendure o worker. max_s e
    parametrizavel porque server_mimic_refs_addendum.py reusa esta funcao com
    um teto menor (clipe de biblioteca e curto por natureza, take de rodada nao)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-t", str(max_s),
             "-ar", "16000", "-ac", "1", str(dst)],
            capture_output=True, timeout=FFMPEG_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False
    except FileNotFoundError as exc:
        raise FfmpegAusente(str(exc)) from exc
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

        # Coleta pra pesquisa: opt-in, nao afeta o fluxo normal do jogo.
        salvar = (request.form.get("save") or "").strip().lower() in ("1", "true")
        participante = (request.form.get("participante") or "").strip()
        condicao = (request.form.get("condicao") or "").strip()

        upload = request.files.get("take")
        if upload is None:
            return _erro("take ausente: envie o audio gravado no campo 'take'", 400)

        blob = upload.read(MAX_UPLOAD_BYTES + 1)
        if len(blob) > MAX_UPLOAD_BYTES:
            return _erro(f"take maior que {MAX_UPLOAD_BYTES} bytes", 413)
        if not blob:
            return _erro("take vazio", 400)

        # Checa a referencia antes de pagar ffmpeg + pyin no take: 404 e barato.
        if mode == "karaoke":
            wt = kpaths.word_timing_json(ref_id)
            vocals = kpaths.vocals_raw(ref_id)
            if not wt.exists() or not vocals.exists():
                return _erro(f"job {ref_id} nao tem gabarito alinhado", 404)
        else:
            clip = MIMIC_REF_DIR / f"{ref_id}.wav"
            if not clip.exists():
                return _erro(f"clipe de referencia {ref_id} nao existe", 404)

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            src = tmpdir / "take.upload"
            src.write_bytes(blob)
            wav = tmpdir / "take.wav"
            try:
                ok = _webm_para_wav(src, wav)
            except FfmpegAusente:
                return _erro("ffmpeg indisponivel no servidor", 503)
            if not ok:
                return _erro("take nao pudemos decodificar como audio", 400)

            take_samples, sr = sf.read(wav, dtype="float32")
            if take_samples.ndim > 1:
                take_samples = take_samples.mean(axis=1)
            # Container valido com zero amostras passa pelo ffmpeg (header-only, tamanho > 0)
            # e estouraria em track_from_audio (np.abs(x).max() em array vazio) -> 500.
            if take_samples.size == 0:
                return _erro("take sem amostras de audio", 400)
            take = track_from_audio(take_samples, sr)

            # wav some quando o `with` fecha — se for salvar, o bytes tem que sair daqui.
            take_wav_bytes = wav.read_bytes() if salvar else None

            if mode == "karaoke":
                words = json.loads(wt.read_text(encoding="utf-8"))
                ref_samples, ref_sr = sf.read(vocals, dtype="float32")
                try:
                    ref = track_from_word_timing(words, ref_samples, ref_sr)
                except ValueError as exc:
                    return _erro(f"gabarito invalido: {exc}", 422)
            else:
                ref_samples, ref_sr = sf.read(clip, dtype="float32")
                if ref_samples.ndim > 1:
                    ref_samples = ref_samples.mean(axis=1)
                ref = track_from_audio(ref_samples, ref_sr)

        report = score(ref, take)
        if salvar:
            _salva_take_para_pesquisa(take_wav_bytes, mode, ref_id, participante, condicao, report)
        return jsonify({
            "melody": round(report.melody, 1),
            "rhythm": round(report.rhythm, 1),
            "attacks": round(report.attacks, 1),
            "total": round(report.total, 1),
            "n_onsets_ref": report.n_onsets_ref,
            "n_onsets_take": report.n_onsets_take,
            "n_matched": report.n_matched,
            "n_frames_compared": report.n_frames_compared,
            "rhythm_tol_s": round(report.rhythm_tol_s, 4),
            "n_octave_suspect_ref": ref.n_octave_suspect,
            "n_voiced_ref": ref.n_voiced,
            "n_voiced_take": take.n_voiced,
            "take_trim_start_s": round(take.trim_start_s, 2),
            "take_trim_end_s": round(take.trim_end_s, 2),
        })

    @app.route("/api/score/ref", methods=["GET"])
    def api_score_ref():
        """Audio de referencia que a pagina toca antes de gravar. Mesma fronteira do POST:
        mode em lista fechada, ref pela regex ANTES de tocar em caminho. Karaoke toca a
        MISTURA (song.wav do job) — o jogador canta junto da musica; a pontuacao usa
        vocals_raw. Decisao de 2026-09-11: o /api/result/audio existente le input/jobs/,
        nao work/jobs/, e interpola job_id sem validar."""
        mode = (request.args.get("mode") or "").strip()
        if mode not in MODES:
            return _erro(f"mode invalido: esperado um de {sorted(MODES)}", 400)
        ref_id = (request.args.get("ref") or "").strip()
        if REF_ID_RE.match(ref_id) is None:
            return _erro("ref invalido: use [A-Za-z0-9_-], no maximo 64 caracteres", 400)
        if mode == "karaoke":
            path = kpaths.song_wav(ref_id)
        else:
            path = MIMIC_REF_DIR / f"{ref_id}.wav"
        if not path.exists():
            return _erro(f"referencia {ref_id} nao encontrada", 404)
        return send_file(str(path), mimetype="audio/wav")
