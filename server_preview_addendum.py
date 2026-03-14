import json
import threading
from pathlib import Path


# ── Utilitário: grava preview_config.json ─────────────────────────────────────

def write_preview_config(job_id: str, duration: float, start: float = 0.0):
    cfg = {"duration": duration, "start": start, "trimmed": False}
    p   = Path("work", "jobs", job_id, "preview_config.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"  [preview] config gravado: {duration}s a partir de {start}s")


# ── Rota de promoção: POST /api/promote_preview ───────────────────────────────
# Cole essa função no server.py e adicione @app.route("/api/promote_preview", methods=["POST"])

def make_promote_route(app, jobs_lock, job_states, job_queues, state_store, _run_pipeline_thread):
    """
    Registra a rota /api/promote_preview no app Flask existente.
    Chame essa função após criar o app:

        from server_preview_addendum import make_promote_route
        make_promote_route(app, jobs_lock, job_states, job_queues,
                           state_store, _run_pipeline_thread)
    """
    from flask import request, jsonify

    @app.route("/api/promote_preview", methods=["POST"])
    def api_promote_preview():
        data   = request.get_json() or {}
        job_id = data.get("job_id")
        if not job_id:
            return jsonify({"error": "Missing job_id"}), 400

        job_root    = Path("work", "jobs", job_id)
        config_path = job_root / "preview_config.json"

        if not config_path.exists():
            return jsonify({"error": "Este job não é um preview"}), 400

        with jobs_lock:
            if job_states.get(job_id, {}).get("state") == "running":
                return jsonify({"error": "Pipeline ainda em execução"}), 409

        # 1. Restaura arquivos _full.wav → arquivo original
        restored = []
        for wav in job_root.rglob("*_full.wav"):
            original = wav.with_name(wav.name.replace("_full.wav", ".wav"))
            wav.rename(original)
            restored.append(original.name)
        print(f"  [promote] {len(restored)} arquivos restaurados: {restored}")

        # 2. Remove preview_config para pipeline rodar completo
        config_path.unlink(missing_ok=True)

        # 3. Remove artefatos do preview para forçar reprocessamento
        for pattern in [
            "05_alignment/*.json",
            "06_ass/*.ass", "06_ass/qc.json",
            "07_video/*.mp4", "08_mixed/*.mp3",
        ]:
            for f in job_root.glob(pattern):
                f.unlink(missing_ok=True)
                print(f"  [promote] removido: {f.name}")

        # 4. Localiza áudio original
        input_job_dir = Path("input", "jobs", job_id)
        audio_path = None
        for ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a"]:
            p = input_job_dir / f"song{ext}"
            if p.exists():
                audio_path = str(p)
                break

        if not audio_path:
            return jsonify({"error": "Arquivo de áudio original não encontrado"}), 404

        # 5. Detecta lang do config original
        jobs = state_store.load_jobs()
        lang = jobs.get(job_id, {}).get("lang", "en")

        # 6. Reinicia pipeline no modo full (stems_preloaded=True — Demucs não roda de novo)
        with jobs_lock:
            job_states[job_id] = {
                "state": "running", "error": None, "step": 0,
                "steps_total": 12, "preview_mode": False,
            }
            if job_id not in job_queues:
                job_queues[job_id] = []

        job_data = jobs.get(job_id, {})
        t = threading.Thread(
            target=_run_pipeline_thread,
            args=(audio_path, lang, job_id, job_data, True, False, False), # Pass False for preview_mode
            daemon=True,
        )
        t.start()

        return jsonify({
            "status":   "promoted",
            "job_id":   job_id,
            "restored": restored,
            "message":  f"{len(restored)} stems restaurados. Pipeline full iniciado.",
        })

    return api_promote_preview
