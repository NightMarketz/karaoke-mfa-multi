import os
import sys
import json
import queue
import time, re
import threading
import subprocess
import shutil
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, Response, send_file

# ── Worker Python Selection ──────────────────────────────────────────────────
def _find_worker_python():
    root = Path(__file__).resolve().parent
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        root.parent / ".venv" / "Scripts" / "python.exe",
        root / "venv" / "Scripts" / "python.exe",
    ]
    for venv_py in candidates:
        if venv_py.exists():
            return str(venv_py)
    return sys.executable

WORKER_PYTHON = _find_worker_python()

from karaoke.lyrics_cleaner import clean_lyrics_strict
from karaoke import state_store, resume_planner, paths as kpaths
from server_preview_addendum import write_preview_config, make_promote_route
from server_score_addendum import make_score_route

try:
    _res_cuda = subprocess.run(
        [WORKER_PYTHON, "-c", "import torch; print(torch.cuda.is_available())"],
        capture_output=True, text=True
    )
    _HAS_CUDA = (_res_cuda.stdout.strip() == "True")
except Exception:
    _HAS_CUDA = False

app = Flask(__name__, static_folder="web", static_url_path="/static")
make_score_route(app)

# ── Security ─────────────────────────────────────────────────────────────────
app.config["MAX_CONTENT_LENGTH"] = 1000 * 1024 * 1024  # 1 GB
ALLOWED_AUDIO_EXT = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}

# ── Global state ─────────────────────────────────────────────────────────────
job_states = {}   # job_id -> {"state", "error", "step", "steps_total"}
job_queues = {}   # job_id -> list[queue.Queue]
jobs_lock  = threading.Lock()

# ── Error Handling ───────────────────────────────────────────────────────────
class APIError(Exception):
    def __init__(self, message, status_code=400, code="BAD_REQUEST", details=None):
        super().__init__()
        self.message     = message
        self.status_code = status_code
        self.code        = code
        self.details     = details or {}

    def to_dict(self):
        return {"error": self.message, "code": self.code, "details": self.details}

@app.errorhandler(APIError)
def handle_api_error(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response

@app.errorhandler(Exception)
def handle_unexpected_error(error):
    import traceback
    traceback.print_exc()
    response = jsonify({
        "error": "Internal Server Error",
        "code": "INTERNAL_ERROR",
        "details": {"message": str(error)}
    })
    response.status_code = 500
    return response


def _p(*parts, job_id=None) -> str:
    if job_id:
        return str(Path("work", "jobs", job_id).joinpath(*parts).resolve())
    return str(Path(*parts).resolve())


# ── Step definitions ──────────────────────────────────────────────────────────
def _build_steps(audio_path, lang, job_id, preview_mode=False, aligner="mfa"):
    python = WORKER_PYTHON
    steps = [
        {
            "id": 1, "name": "Media Preparation",
            "cmd": [python, _p("scripts", "01_media_prep.py"), "--job-id", job_id],
            "outputs": {"wav": str(kpaths.song_wav(job_id).resolve())},
            "timeout": 300,
        },
        {
            "id": 2, "name": "Vocal Isolation",
            "cmd": [python, _p("scripts", "02_vocal_isolation.py"), "--job-id", job_id],
            "outputs": {
                "vocals_raw":    str(kpaths.vocals_raw(job_id).resolve()),
                "vocals_listen": str(kpaths.vocals_listen(job_id).resolve()),
            },
            "timeout": 3600,
        },
        {
            "id": 3, "name": "Vocal Cleaning",
            "cmd": [python, _p("scripts", "03_vocal_cleaning.py"), "--job-id", job_id],
            "outputs": {"vocals_clean": str(kpaths.vocals_raw(job_id).resolve())},
            "timeout": 300,
        }
    ]

    # --- ALIGNMENT PATH ---
    if aligner == "sofa":
        steps.extend([
            {
                "id": 4, "name": "SOFA Alignment",
                "cmd": [python, _p("scripts", "run_sofa.py"), "--job-id", job_id],
                "outputs": {"sofa_tg": str(kpaths.sofa_textgrid(job_id).resolve())},
                "timeout": 600,
            },
            {
                "id": 5, "name": "ROSVOT Inference",
                "cmd": [python, _p("scripts", "run_rosvot.py"), "--job-id", job_id],
                "outputs": {"rosvot_json": str(kpaths.rosvot_json(job_id).resolve())},
                "timeout": 600,
            },
            {
                "id": 6, "name": "Sync & Fuse",
                "cmd": [python, _p("scripts", "fuse_sofa_rosvot.py"), "--job-id", job_id],
                "outputs": {"word_timing": str(kpaths.word_timing_json(job_id).resolve())},
                "timeout": 300,
            }
        ])
    else: # Default: MFA
        steps.append({
            "id": 4, "name": "MFA Forced Alignment",
            "cmd": [python, _p("scripts", "04_mfa_alignment.py"), "--job-id", job_id],
            "outputs": {"textgrid": str(kpaths.mfa_textgrid(job_id).resolve())},
            "timeout": 600,
        })

    # --- POST-ALIGNMENT / RESCUE ---
    steps.extend([
        {
            "id": 7, "name": "Gap Analysis & Transition",
            "cmd": [python, _p("scripts", "05_gap_analysis.py"), "--job-id", job_id],
            "outputs": {"word_timing": str(kpaths.word_timing_json(job_id).resolve())},
            "timeout": 300,
        },
        {
            "id": 8, "name": "Alignment Rescue",
            "cmd": [python, _p("scripts", "06_alignment_rescue.py"), "--job-id", job_id],
            "outputs": {"word_timing": str(kpaths.word_timing_json(job_id).resolve())},
            "timeout": 300,
        },
        {
            "id": 9, "name": "Gemini Alignment",
            "cmd": [python, _p("scripts", "07_gemini_alignment.py"), "--job-id", job_id],
            "outputs": {"refined_timing": str(kpaths.word_timing_json(job_id).resolve())},
            "timeout": 600,
        },
        {
            "id": 10, "name": "Onset DTW Alignment",
            "cmd": [python, _p("scripts", "08_onset_dtw.py"), "--job-id", job_id],
            "outputs": {"word_timing_fixed": str(kpaths.word_timing_json(job_id).resolve())},
            "timeout": 300,
        },
        {
            "id": 11, "name": "Background Illustration",
            "cmd": [python, _p("scripts", "08b_background_image.py"), "--job-id", job_id],
            "outputs": {"background": str(kpaths.background_png(job_id).resolve())},
            "timeout": 600,
        },
        {
            "id": 12, "name": "Video Rendering",
            "cmd": [python, _p("scripts", "09_video_rendering.py"), "--job-id", job_id],
            "outputs": {"video": str(kpaths.final_video(job_id).resolve())},
            "timeout": 3600,
        },
        {
            "id": 12, "name": "Quality Assurance",
            "cmd": [python, _p("scripts", "10_quality_assurance.py"), "--job-id", job_id],
            "outputs": {"qc": str((kpaths.ass_dir(job_id) / "qc.json").resolve())},
            "timeout": 300,
        },
        {
            "id": 13, "name": "System Cleanup",
            "cmd": [python, _p("scripts", "11_system_cleanup.py"), "--job-id", job_id],
            "outputs": {"cleanup": "done"},
            "timeout": 120,
        },
        {
            "id": 14, "name": "User Notification",
            "cmd": [python, _p("scripts", "12_user_notification.py"), "--job-id", job_id],
            "outputs": {"notified": "done"},
            "timeout": 60,
        },
        {
            "id": 15, "name": "Process Conclusion",
            "cmd": [python, _p("scripts", "13_process_conclusion.py"), "--job-id", job_id],
            "outputs": {"completed": "true"},
            "timeout": 60,
        }
    ])

    # Handle CUDA availability for Primay Alignment if necessary
    # (Optional: the script 04_mfa_alignment.py already handles CPU, but we can set flags here if needed)

    # Re-normalize IDs just in case
    for i, s in enumerate(steps):
        s["id"] = i + 1

    return steps


    return steps


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
@app.route("/process/<job_id>")
@app.route("/karaoke/<job_id>")
def index(job_id=None):
    return send_from_directory("web", "index.html")


# FIX: favicon retornava 500 — handler explícito com 204 No Content
@app.route("/favicon.ico")
def favicon():
    return Response(status=204)


@app.route("/api/status")
def api_status():
    job_id = request.args.get("job_id")
    if not job_id:
        raise APIError("Missing job_id parameter", status_code=400, code="MISSING_PARAM")
    with jobs_lock:
        if job_id in job_states:
            return jsonify(job_states[job_id])
    jobs = state_store.load_jobs()
    if job_id in jobs:
        st = jobs[job_id].get("status", "idle")
        if st in ("done", "error"):
            return jsonify({"state": st, "step": 12, "error": None})
    return jsonify({"state": "idle", "error": "Job not found", "step": 0})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    audio_file  = request.files.get("audio")
    lyrics_text = request.form.get("lyrics", "")
    lang        = request.form.get("lang", "en")
    stems_preloaded = request.form.get("stems_preloaded") == "true"
    preview_mode     = request.form.get("preview_mode") == "true"
    preview_duration = float(request.form.get("preview_duration", "60"))
    preview_start    = float(request.form.get("preview_start", "0"))

    aligner     = request.form.get("aligner", "mfa")

    if not audio_file:
        raise APIError("Áudio não enviado", status_code=400, code="MISSING_AUDIO")
    if not lyrics_text.strip():
        raise APIError("Letra vazia", status_code=400, code="MISSING_LYRICS")

    ext = os.path.splitext(audio_file.filename)[1].lower()
    if ext not in ALLOWED_AUDIO_EXT:
        raise APIError(f"Extensão '{ext}' não permitida.", status_code=400, code="INVALID_EXTENSION",
                       details={"allowed": list(ALLOWED_AUDIO_EXT)})

    os.makedirs("work/jobs", exist_ok=True)
    temp_audio_path = str(kpaths.job_root("temp_upload").joinpath(f"raw{ext}").resolve())
    os.makedirs(os.path.dirname(temp_audio_path), exist_ok=True)
    audio_file.save(temp_audio_path)

    duration_sec = 0
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", temp_audio_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        duration_sec = float(result.stdout.strip())
        if duration_sec > 900:
            if os.path.exists(temp_audio_path): os.remove(temp_audio_path)
            raise APIError(
                f"Áudio excede limite de 15 minutos (detectado: {duration_sec:.1f}s)",
                status_code=400, code="AUDIO_TOO_LONG",
                details={"duration": duration_sec, "limit": 900}
            )
    except APIError:
        raise
    except Exception:
        if os.path.exists(temp_audio_path): os.remove(temp_audio_path)
        raise APIError("Falha ao validar arquivo de áudio (formato inválido ou corrompido)",
                       status_code=400, code="INVALID_AUDIO_FORMAT")

    config = {
        "mfa_lang":         lang,
        "pipeline_version": "1.2.0",
        "preview_mode":     preview_mode,
        "preview_duration": preview_duration if preview_mode else None,
    }
    # Prefer raw lyrics (with parentheticals for adlib hints) over pre-cleaned text
    lyrics_raw = request.form.get("lyrics_raw", "")
    lyrics_to_save = lyrics_raw if lyrics_raw else lyrics_text

    job_id = resume_planner.calculate_job_id(temp_audio_path, lyrics_to_save, lang, config)

    input_dir = kpaths.input_dir(job_id)
    input_dir.mkdir(parents=True, exist_ok=True)

    audio_path = str(input_dir / f"song{ext}")
    if os.path.exists(audio_path):
        os.remove(temp_audio_path)
    else:
        os.rename(temp_audio_path, audio_path)

    lyrics_path = str(kpaths.lyrics_path(job_id))
    with open(lyrics_path, "w", encoding="utf-8") as f:
        f.write(lyrics_to_save)

    with jobs_lock:
        if job_id in job_states and job_states[job_id]["state"] == "running":
            raise APIError("Pipeline já está em execução para este arquivo",
                           status_code=409, code="ALREADY_RUNNING", details={"job_id": job_id})
        job_states[job_id] = {
            "state": "running", "error": None, "step": 0,
            "steps_total": 13,
            "preview_mode": preview_mode,
        }
        if job_id not in job_queues:
            job_queues[job_id] = []

    tool_versions = {"pipeline_version": "1.1.0", "python": sys.version.split()[0]}

    # ── Stems opcionais no mesmo request ─────────────────────────────────
    stem_vocals = request.files.get("stem_vocals")
    if stem_vocals:
        stems_dir  = kpaths.step_output(job_id, "02_stems") / "htdemucs_ft" / "song"
        vocals_dir = kpaths.separation_dir(job_id)
        stems_dir.mkdir(parents=True, exist_ok=True)
        vocals_dir.mkdir(parents=True, exist_ok=True)

        for key, dest_name in [("stem_drums", "drums"), ("stem_bass", "bass"), ("stem_other", "other")]:
            f = request.files.get(key)
            if f:
                tmp = stems_dir / f"tmp_{dest_name}{Path(f.filename).suffix}"
                f.save(str(tmp))
                out = stems_dir / f"{dest_name}.wav"
                subprocess.run([
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(tmp), "-ar", "44100", "-ac", "2",
                    "-c:a", "pcm_s16le", str(out)
                ], check=True)
                tmp.unlink(missing_ok=True)

        tmp_v = stems_dir / f"tmp_vocals{Path(stem_vocals.filename).suffix}"
        stem_vocals.save(str(tmp_v))

        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(tmp_v), "-ar", "16000", "-ac", "1",
            "-af", "highpass=f=80",
            str(vocals_dir / "vocals_raw.wav")], check=True)

        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(tmp_v), "-ar", "44100", "-ac", "2",
            "-af", "highpass=f=120,lowpass=f=12000,afftdn=nf=-25:nr=6:nt=c,loudnorm=I=-16:TP=-1.5",
            str(vocals_dir / "vocals_listen.wav")], check=True)

        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(tmp_v), "-ar", "44100", "-ac", "2",
            "-c:a", "pcm_s16le", str(stems_dir / "vocals.wav")], check=True)

        tmp_v.unlink(missing_ok=True)
        stems_preloaded = True

    job_data = state_store.upsert_job(
        job_id,
        audio_file.filename,
        resume_planner.get_file_hash(audio_path),
        resume_planner.get_text_hash(lyrics_text.strip()),
        resume_planner.get_text_hash(json.dumps(config, sort_keys=True)),
        lang,
        tool_versions
    )

    # ── Preview config ────────────────────────────────────────────────
    if preview_mode:
        write_preview_config(job_id, preview_duration, preview_start)

    t = threading.Thread(
        target=_run_pipeline_thread,
        args=(audio_path, lang, job_id, job_data, stems_preloaded, preview_mode, aligner),
        daemon=True,
    )
    t.start()

    return jsonify({
        "status": "started",
        "job_id": job_id,
        "stems_preloaded": stems_preloaded,
        "preview_mode": preview_mode,
        "preview_duration": preview_duration if preview_mode else None
    })


@app.route("/api/clean_lyrics", methods=["POST"])
def api_clean_lyrics():
    data = request.get_json()
    if not data or "lyrics" not in data:
        raise APIError("No lyrics provided", status_code=400, code="MISSING_LYRICS")
    cleaned = clean_lyrics_strict(data["lyrics"])
    return jsonify({"cleaned": cleaned})


@app.route("/api/clear_cache", methods=["POST"])
def api_clear_cache():
    try:
        with jobs_lock:
            running_jobs = [jid for jid, st in job_states.items() if st.get("state") == "running"]
            if running_jobs:
                raise APIError(
                    f"Não é possível limpar cache enquanto jobs estão rodando: {running_jobs}",
                    status_code=409, code="PIPELINE_RUNNING"
                )
        for folder in ["work", "input", "url", "yt"]:
            if os.path.exists(folder):
                shutil.rmtree(folder, ignore_errors=True)
        state_path = state_store.get_state_path()
        if os.path.exists(state_path) and os.path.isfile(state_path):
            try: os.remove(state_path)
            except Exception: pass
        with jobs_lock:
            job_states.clear()
            job_queues.clear()
        return jsonify({"success": True})
    except APIError:
        raise
    except Exception as e:
        raise APIError(str(e), status_code=500, code="INTERNAL_ERROR")


@app.route("/api/progress")
def api_progress():
    job_id = request.args.get("job_id")
    if not job_id:
        raise APIError("Missing job_id", status_code=400, code="MISSING_PARAM")

    q = queue.Queue()
    with jobs_lock:
        if job_id not in job_queues:
            job_queues[job_id] = []
        job_queues[job_id].append(q)

    def stream():
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("state") in ("done", "error"):
                        break
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"
                    with jobs_lock:
                        st = job_states.get(job_id, {}).get("state")
                        if st in ("done", "error"):
                            yield f"data: {json.dumps({'type': 'final', 'state': st})}\n\n"
                            break
        finally:
            with jobs_lock:
                if job_id in job_queues and q in job_queues[job_id]:
                    job_queues[job_id].remove(q)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/result/ass")
def api_result_ass():
    job_id = request.args.get("job_id")
    if not job_id:
        raise APIError("Missing job_id", status_code=400, code="MISSING_PARAM")
    ass_path = _p("06_ass", "karaoke.ass", job_id=job_id)
    if os.path.exists(ass_path):
        return send_file(ass_path, mimetype="text/plain", as_attachment=True, download_name="karaoke.ass")
    raise APIError("ASS file not found", status_code=404, code="NOT_FOUND")


@app.route("/api/result/lyrics")
def api_result_lyrics():
    job_id = request.args.get("job_id")
    if not job_id:
        raise APIError("Missing job_id", status_code=400, code="MISSING_PARAM")
    path = Path("input", "jobs", job_id) / "lyrics.txt"
    if os.path.exists(path):
        return send_file(str(path), mimetype="text/plain", as_attachment=True, download_name="lyrics.txt")
    raise APIError("Lyrics not found", status_code=404, code="NOT_FOUND")


@app.route("/api/result/audio")
def api_result_audio():
    job_id = request.args.get("job_id")
    if not job_id:
        raise APIError("Missing job_id", status_code=400, code="MISSING_PARAM")
    input_job_dir = Path("input", "jobs", job_id)
    for ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a"]:
        p = input_job_dir / f"song{ext}"
        if p.exists():
            mime = {
                ".mp3": "audio/mpeg", ".wav": "audio/wav",
                ".ogg": "audio/ogg",  ".flac": "audio/flac", ".m4a": "audio/mp4",
            }.get(ext, "audio/mpeg")
            return send_file(str(p), mimetype=mime)
    raise APIError("Audio not found", status_code=404, code="NOT_FOUND")


@app.route("/api/result/word_timing")
def api_result_word_timing():
    job_id = request.args.get("job_id")
    if not job_id:
        raise APIError("Missing job_id", status_code=400, code="MISSING_PARAM")
    path = _p("05_alignment", "word_timing.json", job_id=job_id)
    if os.path.exists(path):
        return send_file(path, mimetype="application/json")
    # Tenta resgatar da etapa 07 ou 08 se houver
    path_fixed = _p("07_dtw", "word_timing_fixed.json", job_id=job_id)
    if os.path.exists(path_fixed):
        return send_file(path_fixed, mimetype="application/json")
    raise APIError("Not found", status_code=404, code="NOT_FOUND")


@app.route("/api/karaoke/data")
def api_karaoke_data():
    job_id = request.args.get("job_id")
    if not job_id:
        raise APIError("Missing job_id", status_code=400, code="MISSING_PARAM")
    
    # Verifica se o áudio existe
    audio_url = f"/api/result/audio?job_id={job_id}"
    
    # Pega a letra
    lyrics = ""
    lp = Path("input", "jobs", job_id) / "lyrics.txt"
    if os.path.exists(lp):
        with open(lp, "r", encoding="utf-8", errors="replace") as f:
            lyrics = f.read()

    # Tenta pegar timings
    timings = None
    tp = _p("05_alignment", "word_timing.json", job_id=job_id)
    if not os.path.exists(tp):
        tp = _p("07_dtw", "word_timing_fixed.json", job_id=job_id)
    
    if os.path.exists(tp):
        with open(tp, "r", encoding="utf-8") as f:
            timings = json.load(f)

    return jsonify({
        "job_id": job_id,
        "audio_url": audio_url,
        "lyrics": lyrics,
        "timings": timings,
        "ass_url": f"/api/result/ass?job_id={job_id}"
    })


# FIX: rota estava sem @app.route — nunca era registrada no Flask
@app.route("/api/result/confidence")
def api_result_confidence():
    job_id = request.args.get("job_id")
    if not job_id:
        raise APIError("Missing job_id", status_code=400, code="MISSING_PARAM")
    path = _p("05_alignment", "confidence_report.json", job_id=job_id)
    if os.path.exists(path):
        return send_file(path, mimetype="application/json")
    return jsonify([])  # Sem GPU não gera confidence_report — retorna vazio sem 404


@app.route("/api/result/check")
def api_result_check():
    job_id = request.args.get("job_id")
    if not job_id:
        raise APIError("Missing job_id", status_code=400, code="MISSING_PARAM")
    ass_exists   = os.path.exists(_p("06_ass", "karaoke.ass", job_id=job_id))
    audio_exists = any(
        os.path.exists(Path("input", "jobs", job_id) / f"song{ext}")
        for ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a"]
    )
    lyrics_text = ""
    lp = Path("input", "jobs", job_id) / "lyrics.txt"
    if os.path.exists(lp):
        with open(lp, "r", encoding="utf-8", errors="replace") as f:
            lyrics_text = f.read()
    return jsonify({
        "job_id": job_id,
        "has_results": ass_exists and audio_exists,
        "has_audio":   audio_exists,
        "lyrics":      lyrics_text,
    })


@app.route("/api/jassub/<path:filename>")
def serve_jassub(filename):
    """Serve JASSUB worker files localmente para evitar CORS."""
    return send_from_directory(os.path.join("web", "lib", "jassub"), filename)


# ── Pipeline runner ──────────────────────────────────────────────────────────

def _emit(job_id, step_id, step_name, status, detail=""):
    event = {
        "type": "step", "step": step_id, "name": step_name,
        "status": status, "detail": detail, "state": "running",
    }
    with jobs_lock:
        if job_id in job_states:
            job_states[job_id]["step"] = step_id
        if job_id in job_queues:
            for q in job_queues[job_id]:
                q.put(event)


def _set_status(job_id, state, error=None):
    with jobs_lock:
        if job_id in job_states:
            job_states[job_id]["state"] = state
            job_states[job_id]["error"] = error


def _parse_subprocess_error(output_text):
    output_text = output_text or ""
    if "DictionaryError" in output_text or ("Could not parse" in output_text and "dictionary" in output_text.lower()):
        return "MFA_DICT_ERROR", "Erro de dicionário do MFA. O texto contém palavras não mapeadas ou símbolos inválidos."
    if "OutOfMemoryError" in output_text or "OOM" in output_text:
        return "OUT_OF_MEMORY", "Falta de memória durante o processamento. Tente fechar outras aplicações."
    if "Exception: Failed to align" in output_text or ("AssertionError" in output_text and "align" in output_text.lower()):
        return "ALIGNMENT_FAILED", "Falha catastrófica de alinhamento. O áudio e a letra são incompatíveis ou o áudio está muito ruidoso."
    if "No such file or directory" in output_text and "ffmpeg" in output_text.lower():
        return "FFMPEG_FILE_NOT_FOUND", "O FFmpeg não encontrou o arquivo de áudio necessário."
    if "Invalid data found when processing input" in output_text:
        return "FFMPEG_INVALID_INPUT", "O arquivo de áudio possui um formato inválido ou está corrompido."
    if "CUDA out of memory" in output_text or "RuntimeError: CUDA" in output_text:
        return "CUDA_OOM", "Falta de VRAM na GPU durante separação Demucs."
    return "SUBPROCESS_ERROR", "Erro de execução de script. Verifique os detalhes do log abaixo."


def _run_pipeline_thread(audio_path, lang, job_id, job_data, stems_preloaded=False, preview_mode=False, aligner="mfa"):
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"]            = "utf-8"
        env["PYTHONUTF8"]                  = "1"
        env["PYTHONLEGACYWINDOWSSTDIO"]    = "0"

        steps = _build_steps(audio_path, lang, job_id, preview_mode, aligner)

        if stems_preloaded:
            for s in steps:
                if s["id"] in (1, 2):
                    s["skipped"] = "Provided"

        steps_to_skip = resume_planner.get_resume_plan(job_data, steps)
        print(f"[Resume] Skipping steps: {steps_to_skip}")

        log_dir = _p("00_logs", job_id=job_id)
        os.makedirs(log_dir, exist_ok=True)

        for step in steps:
            if step["name"] in steps_to_skip:
                _emit(job_id, step["id"], step["name"], "skipped", "Cached")
                continue

            if step.get("skipped"):
                _emit(job_id, step["id"], step["name"], "skipped", step["skipped"])
                continue

            _emit(job_id, step["id"], step["name"], "running")
            try:
                process = subprocess.Popen(
                    step["cmd"], env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace"
                )

                timeout_hit = []
                def watchdog(p, t_sec):
                    start = time.time()
                    while p.poll() is None:
                        if time.time() - start > t_sec:
                            timeout_hit.append(True)
                            try: p.kill()
                            except: pass
                            break
                        time.sleep(1)

                w_thread = threading.Thread(target=watchdog, args=(process, step["timeout"]), daemon=True)
                w_thread.start()

                output_log = []
                while True:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if line:
                        clean_line = line.strip()
                        output_log.append(clean_line)
                        if "PROGRESS:" in clean_line:
                            m = re.search(r"PROGRESS:\s*(\d+)(?:\s*\|\s*(.*))?", clean_line)
                            if m:
                                pct = m.group(1)
                                sub = m.group(2).strip() if m.group(2) else ""
                                _emit(job_id, step["id"], step["name"], "running",
                                      f"[{pct}%] {sub}" if sub else f"[{pct}%]")

                result_code = process.wait()

                if timeout_hit:
                    raise subprocess.TimeoutExpired(step["cmd"], step["timeout"], output="\n".join(output_log))

                combined = "\n".join(output_log).strip()

                safe_name = step["name"].lower().replace(" ", "_").replace("→", "to")
                log_path  = os.path.join(log_dir, f"step_{step['id']}_{safe_name}.log")
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(f"=== OUTPUT ===\n{combined}\n")

                if result_code != 0:
                    print(f"[{job_id}] Step {step['id']} FAILED — head:\n{combined[:500]}")
                    print(f"[{job_id}] Step {step['id']} FAILED — tail:\n{combined[-1000:]}")

                    err_code, parsed_msg = _parse_subprocess_error(combined)
                    structured_error = {
                        "message":   parsed_msg,
                        "code":      err_code,
                        "exit_code": result_code,
                        "script":    step["cmd"][1] if len(step["cmd"]) > 1 else step["name"],
                        "raw_tail":  combined[-1000:]
                    }
                    _emit(job_id, step["id"], step["name"], "error", structured_error)
                    state_store.update_step(job_id, step["name"], "fail")
                    _set_status(job_id, "error", f"Falha na etapa {step['id']}: {step['name']} ({err_code})")
                    with jobs_lock:
                        if job_id in job_queues:
                            for q in job_queues[job_id]:
                                q.put({"type": "final", "state": "error",
                                       "error": job_states[job_id]["error"], "detail": structured_error})
                    return
                else:
                    if combined:
                        print(f"[{job_id}] Step {step['id']} tail:\n{combined[-500:]}")

                _emit(job_id, step["id"], step["name"], "done")

                metrics = {}
                # Pelo nome, nao pelo indice: os ids sao renormalizados no
                # fim de _build_steps, entao qualquer estagio inserido antes
                # (08b) ou o caminho SOFA (3 etapas no lugar de 1) desloca o
                # numero do Quality Assurance.
                if step["name"] == "Quality Assurance":
                    qc_path = step["outputs"].get("qc")
                    if qc_path and os.path.exists(qc_path):
                        try:
                            with open(qc_path, "r", encoding="utf-8") as f:
                                metrics = json.load(f).get("metrics", {})
                        except Exception:
                            pass

                state_store.update_step(job_id, step["name"], "ok", step["outputs"], metrics)

            except subprocess.TimeoutExpired:
                timeout_min      = step["timeout"] // 60
                structured_error = {
                    "message":   f"O passo excedeu o tempo limite de {timeout_min} minutos.",
                    "code":      "TIMEOUT",
                    "exit_code": -1,
                    "script":    step["name"]
                }
                _emit(job_id, step["id"], step["name"], "error", structured_error)
                state_store.update_step(job_id, step["name"], "fail")
                _set_status(job_id, "error", f"Timeout na etapa {step['id']}: {step['name']}")
                with jobs_lock:
                    if job_id in job_queues:
                        for q in job_queues[job_id]:
                            q.put({"type": "final", "state": "error",
                                   "error": job_states[job_id]["error"], "detail": structured_error})
                return

        _set_status(job_id, "done")
        with jobs_lock:
            if job_id in job_queues:
                for q in job_queues[job_id]:
                    q.put({"type": "final", "state": "done"})

    except Exception as e:
        _set_status(job_id, "error", str(e))
        with jobs_lock:
            if job_id in job_queues:
                for q in job_queues[job_id]:
                    q.put({"type": "final", "state": "error", "error": str(e)})


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import datetime
    print(f"🎤 Karaoke Studio [{datetime.now().strftime('%H:%M:%S')}]")
    print(f"🔗 Server Python : {sys.executable}")
    print(f"🛠️  Worker Python : {WORKER_PYTHON}")
    print(f"⚡ CUDA           : {'yes' if _HAS_CUDA else 'no (CPU mode)'}")
    print(f"🚀 URL            : http://127.0.0.1:5000")
    make_promote_route(app, jobs_lock, job_states, job_queues, state_store, _run_pipeline_thread)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
