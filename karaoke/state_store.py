import os
import json
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

_state_lock = threading.Lock()


def get_state_path():
    app_data = os.environ.get("APPDATA")
    if app_data:
        base_dir = os.path.join(app_data, "antigravity-karaoke")
    else:
        base_dir = os.path.join(os.getcwd(), ".karaoke_state")
    if not os.path.exists(base_dir):
        os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "state.json")


def _load_state_unlocked():
    path = get_state_path()
    if not os.path.exists(path):
        return {"schema_version": 1, "jobs": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load state: {e}")
        return {"schema_version": 1, "jobs": {}}


def load_state():
    with _state_lock:
        return _load_state_unlocked()


def load_jobs():
    state = load_state()
    return state.get("jobs", {})


def _save_state_unlocked(state):
    path = get_state_path()
    tmp  = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass


def save_state(state):
    with _state_lock:
        _save_state_unlocked(state)


def upsert_job(job_id, audio_name, audio_hash, lyrics_hash, config_hash, lang, tool_versions):
    """Adds or updates a job (transactional). Returns the job data dict.
    
    FIX: Previously had no return statement → returned None → resume_planner
    received None as job_data → all steps re-ran on every restart (no caching).
    """
    with _state_lock:
        state = _load_state_unlocked()
        if job_id not in state["jobs"]:
            state["jobs"][job_id] = {
                "id": job_id,
                "created_at": datetime.now().isoformat(),
                "steps": {}
            }
        job = state["jobs"][job_id]
        job["audio_name"]    = audio_name
        job["audio_hash"]    = audio_hash
        job["lyrics_hash"]   = lyrics_hash
        job["config_hash"]   = config_hash
        job["lang"]          = lang
        job["tool_versions"] = tool_versions
        job["updated_at"]    = datetime.now().isoformat()
        _save_state_unlocked(state)
        return job  # ← was missing: server.py passes this to _run_pipeline_thread


def update_step_status(job_id, step_name, status, outputs=None, metrics=None, error=None):
    """Updates the status and metadata for a specific pipeline step.

    FIX: Param order was (job_id, step_name, status, error, progress, outputs).
    server.py calls: update_step(job_id, name, "ok", step["outputs"], metrics)
    so outputs and metrics landed in the error/progress params → outputs never saved.
    Corrected order: (job_id, step_name, status, outputs=None, metrics=None, error=None)
    """
    with _state_lock:
        state = _load_state_unlocked()
        if job_id not in state["jobs"]:
            return
        job = state["jobs"][job_id]
        if step_name not in job["steps"]:
            job["steps"][step_name] = {}
        step = job["steps"][step_name]
        step["status"]     = status
        step["updated_at"] = datetime.now().isoformat()
        if error is not None:
            step["error"] = error
        if outputs is not None:
            # Normalize to strings — Path objects aren't JSON-serializable
            step["outputs"] = {k: str(v) for k, v in outputs.items()}
        if metrics is not None:
            step["metrics"] = metrics
        job["updated_at"] = datetime.now().isoformat()
        _save_state_unlocked(state)


# Alias: server.py calls update_step() — bridges the name mismatch
update_step = update_step_status


def set_job_completed(job_id, results_metadata=None):
    with _state_lock:
        state = _load_state_unlocked()
        if job_id in state["jobs"]:
            job = state["jobs"][job_id]
            job["status"]       = "completed"
            job["completed_at"] = datetime.now().isoformat()
            if results_metadata:
                job["results"] = results_metadata
            _save_state_unlocked(state)


def get_job(job_id):
    with _state_lock:
        state = _load_state_unlocked()
        return state["jobs"].get(job_id)