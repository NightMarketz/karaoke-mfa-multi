"""
server.py — Karaoke Pipeline Web Server

Flask backend for the karaoke pipeline UI.

Routes:
    GET  /                     — Jobs dashboard
    GET  /job/new              — Upload form
    POST /job/new              — Create job + run pipeline
    GET  /job/<id>             — Job detail (progress, player, metrics)
    GET  /job/<id>/stream      — SSE real-time progress
    GET  /job/<id>/output.mp4  — Serve rendered video
    GET  /job/<id>/output.ass  — Serve ASS subtitle file
    GET  /job/<id>/metrics     — JSON drift metrics (if reference exists)
    DELETE /job/<id>           — Delete job

Usage:
    conda activate karaoke_env
    python server.py
    # Open http://localhost:5000
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
import wave
import zipfile
from pathlib import Path
from typing import Any

from flask import (
    Flask, Response, jsonify, redirect, render_template,
    request, send_file, url_for,
)

from scripts.common.paths import is_safe_archive_member, resolve_job_dir
from scripts.common.status import read_status, write_status
from scripts.pipeline_runner import PipelineRunner

# ── Config ────────────────────────────────────────────────────────────────────
JOBS_DIR   = Path("jobs")
SCRIPTS    = Path("scripts")
JOBS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = "karaoke-local-dev"
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Track running pipelines: job_id → thread
_running: dict[str, threading.Thread] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _read_status(job_dir: Path) -> dict[str, Any]:
    status = read_status(job_dir)
    return {
        "stage": status.stage,
        "progress": status.progress,
        "error": status.error,
        "updated_at": status.updated_at,
    }


def _write_status(job_dir: Path, stage: str, progress: int, error: str = "") -> None:
    write_status(job_dir, stage, progress, error)


def _list_jobs() -> list[dict[str, Any]]:
    jobs = []
    if not JOBS_DIR.exists():
        return []
    for d in sorted(JOBS_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        status = _read_status(d)
        meta["status"] = status
        meta["has_output"] = (d / "output.mp4").exists()
        meta["has_ass"]    = (d / "output.ass").exists()
        jobs.append(meta)
    return jobs


def _get_wav_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return None


def _compute_drift_metrics(job_dir: Path) -> dict | None:
    ref_path = job_dir / "reference_mapping.json"
    transcript_path = job_dir / "transcript.json"
    if not ref_path.exists() or not transcript_path.exists():
        return None
    try:
        ref_data   = json.loads(ref_path.read_text(encoding="utf-8"))
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        ref_lines  = ref_data.get("lines", [])
        segs       = transcript.get("segments", [])
        matched    = min(len(segs), len(ref_lines))
        drifts = []
        outliers = []
        for i in range(matched):
            ctc = segs[i]["start"]
            ref = ref_lines[i]["reference_start_sec"]
            d   = abs(ctc - ref)
            drifts.append(d)
            if d > 3.0:
                outliers.append({
                    "idx":  i,
                    "text": segs[i].get("text", "")[:40],
                    "ref":  ref,
                    "ctc":  round(ctc, 2),
                    "drift": round(d, 2),
                    "annotation": ref_lines[i].get("annotation", ""),
                })

        def pct(vals, p):
            sv = sorted(vals); k = (len(sv)-1)*p/100
            lo, hi = int(k), min(int(k)+1, len(sv)-1)
            return round(sv[lo] + (sv[hi]-sv[lo])*(k-lo), 3)

        return {
            "matched":  matched,
            "mean":     round(sum(drifts)/len(drifts), 3),
            "p50":      pct(drifts, 50),
            "p95":      pct(drifts, 95),
            "within_3s": sum(1 for d in drifts if d <= 3.0),
            "outliers": outliers,
            "per_line": [{"idx": i, "drift": round(d, 3)} for i, d in enumerate(drifts)],
        }
    except Exception as e:
        logger.warning("Drift metrics failed: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runner
# ─────────────────────────────────────────────────────────────────────────────

def _run_stage(job_dir: Path, cmd: list[str], stage_name: str, progress_start: int) -> bool:
    logger.info("Stage: %s → %s", stage_name, " ".join(cmd))
    _write_status(job_dir, stage_name, progress_start)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=900,
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "unknown error")[-500:]
            logger.error("Stage %s failed:\n%s", stage_name, error)
            _write_status(job_dir, "failed", progress_start, error)
            return False
        return True
    except subprocess.TimeoutExpired:
        _write_status(job_dir, "failed", progress_start, "timeout after 15m")
        return False
    except Exception as e:
        _write_status(job_dir, "failed", progress_start, str(e))
        return False


def _run_pipeline(job_id: str) -> None:
    job_dir = resolve_job_dir(JOBS_DIR, job_id)
    meta = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
    preset = meta.get("preset", "cyberpunk")
    runner = PipelineRunner(
        job_dir=job_dir,
        python_exe=sys.executable,
        preset=preset,
        running_registry=_running,
        job_id=job_id,
    )
    if runner.run():
        logger.info("Job %s complete.", job_id)


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    jobs = _list_jobs()
    return render_template("index.html", jobs=jobs)


# ─────────────────────────────────────────────────────────────────────────────
# Routes — New job
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/job/new", methods=["GET"])
def new_job_form():
    return render_template("new_job.html")


def _convert_to_wav(src: Path, dst: Path) -> bool:
    """Convert any audio file to 16-bit PCM WAV using ffmpeg. Returns True on success."""
    if src.suffix.lower() == ".wav":
        import shutil
        shutil.copy2(src, dst)
        return True
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src),
             "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
             str(dst)],
            capture_output=True, timeout=120,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error("ffmpeg conversion failed: %s", e)
        return False


# Keywords used to identify vocal/instrumental stems by filename
_VOCAL_KEYWORDS = (
    "vocal", "voice", "vox", "sing", "lead",
)
_INSTRUMENTAL_KEYWORDS = (
    "instrumental", "instrument", "backing", "music",
    "accompan", "karaoke", "minus", "beat", "track",
)
_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"}


def _classify_stem(name: str) -> str | None:
    """
    Return 'vocals', 'instrumental', or None based on filename stem.
    Suno names vary: 'vocals.mp3', 'song_name_vocals.wav',
    'instrumentals.wav', 'song_name_no_vocals.mp3', etc.
    """
    n = Path(name).stem.lower()   # strip extension, lowercase

    # Exact Suno canonical names (check against stem without extension)
    if n in ("vocals", "vocal"):
        return "vocals"
    if n in ("instrumentals", "instrumental", "no_vocals", "novocals",
             "no-vocals", "backing", "music", "minus"):
        return "instrumental"

    # Negative patterns take priority: "no_vocals", "no-vocals" anywhere in name
    if "no_vocal" in n or "novocal" in n or "no-vocal" in n:
        return "instrumental"

    # Positive keyword scan
    for kw in _VOCAL_KEYWORDS:
        if kw in n:
            return "vocals"
    for kw in _INSTRUMENTAL_KEYWORDS:
        if kw in n:
            return "instrumental"
    return None


def _extract_suno_zip(zip_file, job_dir: Path) -> tuple[Path | None, Path | None]:
    """
    Extract a Suno stem ZIP into job_dir/stems/ and classify files.
    Returns (vocals_path, instrumental_path) — either may be None if not found.
    """
    stems_dir = job_dir / "stems"
    stems_dir.mkdir(exist_ok=True)

    try:
        with zipfile.ZipFile(zip_file, "r") as zf:
            audio_members = []
            for info in zf.infolist():
                name = info.filename
                if info.is_dir() or name.startswith("__MACOSX"):
                    continue
                if Path(name).suffix.lower() not in _AUDIO_EXTS:
                    continue
                if not is_safe_archive_member(name):
                    logger.error("Unsafe ZIP member rejected: %s", name)
                    shutil.rmtree(stems_dir, ignore_errors=True)
                    return None, None
                audio_members.append(name)

            if not audio_members:
                logger.error("ZIP contains no audio files")
                return None, None

            for member in audio_members:
                target = (stems_dir / member).resolve()
                try:
                    target.relative_to(stems_dir.resolve())
                except ValueError:
                    logger.error("ZIP member escapes stems dir: %s", member)
                    shutil.rmtree(stems_dir, ignore_errors=True)
                    return None, None
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            logger.info("ZIP extracted %d audio files: %s", len(audio_members), audio_members)
    except Exception as e:
        logger.error("ZIP extraction failed: %s", e)
        shutil.rmtree(stems_dir, ignore_errors=True)
        return None, None

    # Classify extracted files
    vocals_path = None
    instrumental_path = None
    unclassified = []

    for m in audio_members:
        p = stems_dir / m
        if not p.exists():
            # Might be nested — walk
            for found in stems_dir.rglob(Path(m).name):
                p = found; break

        stem_class = _classify_stem(p.name)
        if stem_class == "vocals" and vocals_path is None:
            vocals_path = p
        elif stem_class == "instrumental" and instrumental_path is None:
            instrumental_path = p
        else:
            unclassified.append(p.name)

    # Fallback for 2-file ZIPs where names are ambiguous:
    # If only 2 audio files and one unclassified, pair them up.
    if vocals_path is None or instrumental_path is None:
        all_audio = [stems_dir / m for m in audio_members
                     if (stems_dir / m).exists()]
        if len(all_audio) == 2:
            # Sort by size — vocals tend to be smaller than full instrumental mix
            all_audio.sort(key=lambda p: p.stat().st_size)
            if vocals_path is None:
                vocals_path = all_audio[0]
            if instrumental_path is None:
                instrumental_path = all_audio[1]
            logger.warning(
                "ZIP stem classification ambiguous, assigned by size: "
                "vocals=%s instrumental=%s",
                vocals_path.name, instrumental_path.name,
            )

    logger.info(
        "Stem classification: vocals=%s instrumental=%s",
        vocals_path.name if vocals_path else None,
        instrumental_path.name if instrumental_path else None,
    )
    return vocals_path, instrumental_path


@app.route("/job/new", methods=["POST"])
def new_job_submit():
    lyrics_text = request.form.get("lyrics_text", "").strip()
    song_name   = request.form.get("song_name", "Untitled").strip() or "Untitled"
    preset      = request.form.get("preset", "cyberpunk")

    if not lyrics_text:
        return jsonify({"error": "Lyrics are required for the MVP forced-alignment flow."}), 400

    job_id  = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)

    # ── Mode A: Suno ZIP upload ────────────────────────────────────────────
    suno_zip = request.files.get("suno_zip")
    if suno_zip and suno_zip.filename.lower().endswith(".zip"):
        zip_tmp = job_dir / "suno_stems.zip"
        suno_zip.save(zip_tmp)
        vocals_src, instrumental_src = _extract_suno_zip(zip_tmp, job_dir)
        zip_tmp.unlink(missing_ok=True)

        if not vocals_src or not instrumental_src:
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({
                "error": (
                    "Could not identify vocal and instrumental stems in the ZIP. "
                    "Expected files containing 'vocal' and 'instrumental' in their names."
                )
            }), 400

    # ── Mode B: individual file uploads ───────────────────────────────────
    else:
        vocals_file      = request.files.get("vocals")
        instrumental_file = request.files.get("instrumental")

        if not vocals_file or not instrumental_file:
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({
                "error": "Either upload a Suno ZIP, or provide both vocal and instrumental stems."
            }), 400

        ext_v = Path(vocals_file.filename).suffix.lower() or ".wav"
        ext_i = Path(instrumental_file.filename).suffix.lower() or ".wav"
        vocals_src      = job_dir / f"vocals_orig{ext_v}"
        instrumental_src = job_dir / f"instrumental_orig{ext_i}"
        vocals_file.save(vocals_src)
        instrumental_file.save(instrumental_src)

    # ── Convert both stems to WAV ──────────────────────────────────────────
    if not _convert_to_wav(vocals_src, job_dir / "vocals.wav"):
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": "Failed to convert vocals to WAV. Is ffmpeg installed?"}), 500
    if not _convert_to_wav(instrumental_src, job_dir / "instrumental.wav"):
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": "Failed to convert instrumental to WAV. Is ffmpeg installed?"}), 500

    # Clean up originals after conversion (keep stems/ dir for ZIP mode)
    if vocals_src.suffix.lower() != ".wav" and vocals_src.exists():
        vocals_src.unlink(missing_ok=True)
    if instrumental_src.suffix.lower() != ".wav" and instrumental_src.exists():
        instrumental_src.unlink(missing_ok=True)

    # ── Lyrics from textarea ───────────────────────────────────────────────
    if lyrics_text:
        (job_dir / "lyrics.txt").write_text(lyrics_text, encoding="utf-8")

    # ── Meta ───────────────────────────────────────────────────────────────
    dur = _get_wav_duration(job_dir / "instrumental.wav")
    meta = {
        "job_id":    job_id,
        "song_name": song_name,
        "preset":    preset,
        "created_at": time.time(),
        "duration_s": round(dur, 1) if dur else None,
        "has_lyrics": (job_dir / "lyrics.txt").exists(),
        "source": "zip" if suno_zip and suno_zip.filename else "files",
    }
    (job_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    _write_status(job_dir, "queued", 0)

    t = threading.Thread(target=_run_pipeline, args=(job_id,), daemon=True)
    _running[job_id] = t
    t.start()

    return redirect(url_for("job_detail", job_id=job_id))


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Job detail
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/job/<job_id>")
def job_detail(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists():
        return "Job not found", 404

    meta    = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
    status  = _read_status(job_dir)
    metrics = _compute_drift_metrics(job_dir)

    transcript_data = None
    tp = job_dir / "transcript.json"
    if tp.exists():
        try:
            t = json.loads(tp.read_text(encoding="utf-8"))
            transcript_data = {
                "alignment_mode": t.get("alignment_mode", "whisper"),
                "pitch_engine":   t.get("pitch_engine", "none"),
                "word_count":     t.get("word_count", 0),
                "segment_count":  t.get("segment_count", 0),
                "section_distribution": t.get("section_distribution", {}),
                "unknown_markers": t.get("unknown_section_markers", []),
            }
        except Exception:
            pass

    return render_template(
        "job.html",
        meta=meta,
        status=status,
        metrics=metrics,
        transcript=transcript_data,
        has_output=(job_dir / "output.mp4").exists(),
        has_ass=(job_dir / "output.ass").exists(),
        has_reference=(job_dir / "reference_mapping.json").exists(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Routes — SSE
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/job/<job_id>/stream")
def job_stream(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists():
        return "Job not found", 404

    def generate():
        prev_stage = None
        while True:
            status = _read_status(job_dir)
            stage  = status.get("stage", "")
            if stage != prev_stage:
                prev_stage = stage
                yield f"data: {json.dumps(status)}\n\n"
            else:
                yield f"data: {json.dumps(status)}\n\n"

            if stage in ("done", "failed"):
                break
            time.sleep(0.8)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Serve files
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/job/<job_id>/output.mp4")
def job_output_mp4(job_id: str):
    try:
        path = resolve_job_dir(JOBS_DIR, job_id) / "output.mp4"
    except ValueError:
        return "Not found", 404
    if not path.exists():
        return "Not found", 404
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.route("/job/<job_id>/output.ass")
def job_output_ass(job_id: str):
    try:
        path = resolve_job_dir(JOBS_DIR, job_id) / "output.ass"
    except ValueError:
        return "Not found", 404
    if not path.exists():
        return "Not found", 404
    return send_file(path, mimetype="text/plain")


@app.route("/job/<job_id>/metrics")
def job_metrics_api(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return jsonify({"error": "no reference data"}), 404
    metrics = _compute_drift_metrics(job_dir)
    if metrics is None:
        return jsonify({"error": "no reference data"}), 404
    return jsonify(metrics)


@app.route("/job/<job_id>/delete", methods=["POST"])
def job_delete(job_id: str):
    if job_id in _running:
        return jsonify({"error": "Cannot delete a running job."}), 409
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if job_dir.exists():
        shutil.rmtree(job_dir)
    return redirect(url_for("index"))


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
