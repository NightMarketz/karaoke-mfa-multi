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

import dataclasses
import argparse
from collections import Counter
import hashlib
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

from scripts.cockpit import (
    artifact_rows,
    build_cockpit_timeline,
    build_quick_review,
    cockpit_service_summary,
    cockpit_stage_rows,
    recent_project_cards,
    review_window_waveform,
    selected_job_summary,
)
from scripts.common.config import load_app_config
from scripts.common.paths import is_safe_archive_member, resolve_job_dir, validate_job_id
from scripts.common.observability import build_observability_summary, read_events, write_event
from scripts.common.provenance import ProvenanceError, file_sha256, load_manifest, validate_file_hash
from scripts.common.status import read_status, write_status
from scripts.karaoke_styles.library import get_preset, list_preset_metadata
from scripts.pipeline_runner import PipelineRunner
from scripts.review_wizard.audio_timeline import build_audio_timeline
from scripts.review_wizard.artifacts import (
    issues_from_artifact_summary,
    summarize_pipeline_artifacts,
    take_and_report_from_summary,
)
from scripts.review_wizard.contracts import Project
from scripts.review_wizard.export_gate import approve_preview, can_export_final
from scripts.review_wizard.export_summary import review_export_summary
from scripts.review_wizard.highlight_velocity import build_word_highlight_segments
from scripts.review_wizard.issue_resolution import approve_issue_risk, apply_issue_suggestion
from scripts.review_wizard.review_points import (
    build_review_points,
    filtered_review_points,
    next_open_point_after,
    next_open_point,
    point_navigation,
    points_for_stage,
    review_point_window,
)
from scripts.review_wizard.stage_summaries import build_stage_summaries
from scripts.review_wizard.stages import active_stage_id, stage_view_models
from scripts.review_wizard.store import load_project, project_path, save_project
from scripts.review_wizard.text_prep import prepare_text_for_review
from scripts.review_wizard.wizard import (
    adjust_review_point_timing,
    apply_review_point_suggestion,
    approve_review_point,
    skip_review_point_with_risk,
)

# ── Config ────────────────────────────────────────────────────────────────────
APP_CONFIG = load_app_config()
JOBS_DIR = APP_CONFIG.jobs_dir
SCRIPTS = Path("scripts")
JOBS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = APP_CONFIG.secret_key
app.config["MAX_CONTENT_LENGTH"] = APP_CONFIG.max_upload_bytes
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Track running pipelines: job_id → thread
_running: dict[str, threading.Thread] = {}


DEFAULT_STYLE_PRESET_ID = APP_CONFIG.default_style_preset_id


def _write_server_event(event: str, level: str = "info", message: str = "", **details: Any) -> None:
    write_event(
        JOBS_DIR / "_server",
        event,
        "server",
        level=level,
        message=message,
        details=details,
    )


def _style_preset_options() -> list[dict[str, Any]]:
    return list_preset_metadata()


def _validate_style_preset(preset_id: str) -> str:
    try:
        return get_preset(preset_id).id
    except KeyError as exc:
        raise ValueError(f"Unknown style preset: {preset_id}") from exc


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


def _ensure_review_project(job_dir: Path, job_id: str) -> Project:
    if project_path(job_dir).exists():
        return load_project(job_dir)

    lyrics_path = job_dir / "lyrics.txt"
    raw_lyrics = lyrics_path.read_text(encoding="utf-8") if lyrics_path.exists() else ""
    prepared_text, issues = prepare_text_for_review(raw_lyrics, language="pt")
    project = Project.new(project_id=f"review-{job_id}", job_id=job_id)
    artifact_summary = summarize_pipeline_artifacts(job_dir)
    artifact_issues = issues_from_artifact_summary(artifact_summary)
    take, report = take_and_report_from_summary(artifact_summary, [*issues, *artifact_issues])
    project = dataclasses.replace(
        project,
        prepared_text=prepared_text,
        evidence_bundle=artifact_summary,
        alignment_takes=[take],
        issues=[*issues, *artifact_issues],
        quality_reports=[report],
    )
    save_project(job_dir, project)
    return project


def _list_jobs() -> list[dict[str, Any]]:
    jobs = []
    if not JOBS_DIR.exists():
        return []
    for d in sorted(JOBS_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        if not validate_job_id(d.name):
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


def _find_listed_job(jobs: list[dict[str, Any]], job_id: str | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    for job in jobs:
        if job.get("job_id") == job_id:
            return job
    return None


def _get_wav_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return None


def _lyrics_sections_for_review(sections: list[Any]) -> list[dict[str, Any]]:
    label_totals = Counter(str(section.label) for section in sections)
    label_counts: Counter[str] = Counter()
    payloads: list[dict[str, Any]] = []
    for section in sections:
        payload = section.to_dict()
        label = str(payload.get("label", "Section"))
        if label_totals[label] > 1:
            label_counts[label] += 1
            payload["display_label"] = f"{label} {label_counts[label]}"
        else:
            payload["display_label"] = label
        payloads.append(payload)
    return payloads


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


def _manifest_sha(manifest: dict[str, Any], section: str, artifact: str) -> str:
    entries = manifest.get(section)
    if not isinstance(entries, dict):
        raise ProvenanceError(f"manifest missing {section}")
    details = entries.get(artifact)
    if not isinstance(details, dict):
        raise ProvenanceError(f"manifest missing {artifact} entry")
    sha256 = details.get("sha256")
    if not isinstance(sha256, str) or not sha256:
        raise ProvenanceError(f"manifest missing {artifact} sha256")
    return sha256


def _ass_dialogue_count(path: Path) -> int:
    return path.read_text(encoding="utf-8-sig", errors="replace").count("\nDialogue:")


def _artifact_graph_valid(job_dir: Path) -> tuple[bool, str | None]:
    ass_path = job_dir / "output.ass"
    mp4_path = job_dir / "output.mp4"
    if not ass_path.exists() or not mp4_path.exists():
        return False, "missing_output_artifact"

    try:
        ass_manifest_path = job_dir / "output.ass.manifest.json"
        ass_manifest = load_manifest(ass_manifest_path)
        validate_file_hash(ass_path, _manifest_sha(ass_manifest, "outputs", "output.ass"))
        if ass_manifest.get("renderer_mode") != "single_layer_kf":
            return False, "ass_renderer_mode_mismatch"

        metrics = ass_manifest.get("metrics")
        if not isinstance(metrics, dict):
            return False, "ass_manifest_metrics_missing"
        if metrics.get("dialogue_count") != _ass_dialogue_count(ass_path):
            return False, "ass_dialogue_count_mismatch"

        analysis_path = job_dir / "analysis.json"
        inputs = ass_manifest.get("inputs")
        if isinstance(inputs, dict) and "analysis.json" in inputs:
            validate_file_hash(analysis_path, _manifest_sha(ass_manifest, "inputs", "analysis.json"))
            if analysis_path.exists():
                analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
                if isinstance(analysis, dict):
                    lines = analysis.get("lines", [])
                    if metrics.get("analysis_line_count") != len(lines):
                        return False, "analysis_line_count_mismatch"

        mp4_manifest = load_manifest(job_dir / "output.mp4.manifest.json")
        validate_file_hash(mp4_path, _manifest_sha(mp4_manifest, "outputs", "output.mp4"))
        if _manifest_sha(mp4_manifest, "inputs", "output.ass") != file_sha256(ass_path):
            return False, "mp4_input_ass_mismatch"

        mp4_inputs = mp4_manifest.get("inputs")
        if isinstance(mp4_inputs, dict):
            ass_input = mp4_inputs.get("output.ass")
            if isinstance(ass_input, dict):
                manifest_sha256 = ass_input.get("manifest_sha256")
                if isinstance(manifest_sha256, str) and manifest_sha256:
                    validate_file_hash(ass_manifest_path, manifest_sha256)
    except (OSError, json.JSONDecodeError, ProvenanceError) as exc:
        return False, str(exc)

    return True, None


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runner
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline(job_id: str) -> None:
    job_dir = resolve_job_dir(JOBS_DIR, job_id)
    write_event(job_dir, "pipeline_thread_started", "running", details={"job_id": job_id})
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
    selected_job = _find_listed_job(jobs, request.args.get("job"))
    selected_job_dir: Path | None = None
    project = None
    review_points = []
    mode = request.args.get("mode", "new")
    if mode not in {"new", "review"}:
        mode = "new"

    if selected_job:
        try:
            selected_job_dir = resolve_job_dir(JOBS_DIR, selected_job["job_id"])
        except ValueError:
            selected_job_dir = None

    if mode == "review" and selected_job and selected_job_dir and selected_job_dir.exists():
        project = _ensure_review_project(selected_job_dir, selected_job["job_id"])
        review_points = build_review_points(selected_job_dir, project)
    elif selected_job and selected_job_dir and selected_job_dir.exists() and project_path(selected_job_dir).exists():
        project = load_project(selected_job_dir)
        review_points = build_review_points(selected_job_dir, project)

    quick_review = (
        build_quick_review(selected_job["job_id"], project, review_points)
        if selected_job and mode == "review"
        else None
    )
    if quick_review and selected_job_dir:
        quick_review["mini_waveform"] = review_window_waveform(selected_job_dir, quick_review.get("active_point"))

    style_presets = _style_preset_options()
    preset_label_by_id = {p["id"]: p["label"] for p in style_presets}
    default_preset_label = preset_label_by_id.get(DEFAULT_STYLE_PRESET_ID, DEFAULT_STYLE_PRESET_ID)

    _sel_summary = selected_job_summary(selected_job)
    if _sel_summary:
        raw_preset_id = _sel_summary.get("preset", "")
        _sel_summary = dict(_sel_summary, preset=preset_label_by_id.get(raw_preset_id, raw_preset_id))

    return render_template(
        "cockpit.html",
        mode=mode,
        jobs=jobs,
        recent_projects=recent_project_cards(jobs),
        selected_job=_sel_summary,
        stage_rows=cockpit_stage_rows((selected_job or {}).get("status", {})),
        artifact_rows=artifact_rows(selected_job_dir),
        timeline=build_cockpit_timeline(selected_job_dir, review_points),
        quick_review=quick_review,
        service_summary=cockpit_service_summary(jobs),
        style_presets=style_presets,
        default_preset_id=DEFAULT_STYLE_PRESET_ID,
        default_preset_label=default_preset_label,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Routes — New job
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/job/new", methods=["GET"])
def new_job_form():
    active = [jid for jid, t in list(_running.items()) if t.is_alive()]
    return render_template(
        "new_job.html",
        style_presets=_style_preset_options(),
        default_preset_id=DEFAULT_STYLE_PRESET_ID,
        server_busy=len(active) >= APP_CONFIG.max_concurrent_jobs,
        running_job_id=active[0] if active else None,
    )


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
                    write_event(
                        job_dir,
                        "zip_member_rejected",
                        "preparing",
                        level="error",
                        message=f"Unsafe ZIP member rejected: {name}",
                        details={"member": name, "reason": "unsafe_path"},
                    )
                    shutil.rmtree(stems_dir, ignore_errors=True)
                    return None, None
                audio_members.append(name)

            if not audio_members:
                logger.error("ZIP contains no audio files")
                write_event(
                    job_dir,
                    "zip_rejected",
                    "preparing",
                    level="error",
                    message="ZIP contains no audio files",
                )
                return None, None

            for member in audio_members:
                target = (stems_dir / member).resolve()
                try:
                    target.relative_to(stems_dir.resolve())
                except ValueError:
                    logger.error("ZIP member escapes stems dir: %s", member)
                    write_event(
                        job_dir,
                        "zip_member_rejected",
                        "preparing",
                        level="error",
                        message=f"ZIP member escapes stems dir: {member}",
                        details={"member": member, "reason": "resolved_escape"},
                    )
                    shutil.rmtree(stems_dir, ignore_errors=True)
                    return None, None
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            logger.info("ZIP extracted %d audio files: %s", len(audio_members), audio_members)
            write_event(
                job_dir,
                "zip_extracted",
                "preparing",
                details={"audio_member_count": len(audio_members), "audio_members": audio_members},
            )
    except Exception as e:
        logger.error("ZIP extraction failed: %s", e)
        write_event(
            job_dir,
            "zip_rejected",
            "preparing",
            level="error",
            message=f"ZIP extraction failed: {e}",
            details={"exception_type": type(e).__name__},
        )
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
    write_event(
        job_dir,
        "zip_stems_classified",
        "preparing",
        level="info" if vocals_path and instrumental_path else "error",
        details={
            "vocals": vocals_path.name if vocals_path else None,
            "instrumental": instrumental_path.name if instrumental_path else None,
            "unclassified": unclassified,
        },
    )
    return vocals_path, instrumental_path


@app.route("/job/new", methods=["POST"])
def new_job_submit():
    active = [jid for jid, t in list(_running.items()) if t.is_alive()]
    if len(active) >= APP_CONFIG.max_concurrent_jobs:
        return jsonify({
            "error": "A job is already running. Please wait for it to complete.",
            "running_job_id": active[0],
        }), 429

    lyrics_text = request.form.get("lyrics_text", "").strip()
    song_name   = request.form.get("song_name", "Untitled").strip() or "Untitled"
    requested_preset = request.form.get("preset", DEFAULT_STYLE_PRESET_ID)

    try:
        preset = _validate_style_preset(requested_preset)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not lyrics_text:
        return jsonify({"error": "Lyrics are required for the MVP forced-alignment flow."}), 400

    job_id  = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    write_event(
        job_dir,
        "job_request_received",
        "preparing",
        details={"song_name": song_name, "preset": preset, "has_lyrics": bool(lyrics_text)},
    )

    # ── Mode A: Suno ZIP upload ────────────────────────────────────────────
    suno_zip = request.files.get("suno_zip")
    if suno_zip and suno_zip.filename.lower().endswith(".zip"):
        write_event(
            job_dir,
            "suno_zip_received",
            "preparing",
            details={"filename": Path(suno_zip.filename).name},
        )
        zip_tmp = job_dir / "suno_stems.zip"
        suno_zip.save(zip_tmp)
        vocals_src, instrumental_src = _extract_suno_zip(zip_tmp, job_dir)
        zip_tmp.unlink(missing_ok=True)

        if not vocals_src or not instrumental_src:
            _write_server_event(
                "suno_zip_rejected",
                level="error",
                message="Could not identify vocal and instrumental stems in the ZIP.",
                job_id=job_id,
            )
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
            _write_server_event(
                "individual_stems_missing",
                level="error",
                message="Missing vocal or instrumental upload",
                job_id=job_id,
                has_vocals=bool(vocals_file),
                has_instrumental=bool(instrumental_file),
            )
            write_event(
                job_dir,
                "individual_stems_missing",
                "preparing",
                level="error",
                message="Missing vocal or instrumental upload",
                details={"has_vocals": bool(vocals_file), "has_instrumental": bool(instrumental_file)},
            )
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({
                "error": "Either upload a Suno ZIP, or provide both vocal and instrumental stems."
            }), 400

        write_event(
            job_dir,
            "individual_stems_received",
            "preparing",
            details={
                "vocals_filename": Path(vocals_file.filename).name,
                "instrumental_filename": Path(instrumental_file.filename).name,
            },
        )
        ext_v = Path(vocals_file.filename).suffix.lower() or ".wav"
        ext_i = Path(instrumental_file.filename).suffix.lower() or ".wav"
        vocals_src      = job_dir / f"vocals_orig{ext_v}"
        instrumental_src = job_dir / f"instrumental_orig{ext_i}"
        vocals_file.save(vocals_src)
        instrumental_file.save(instrumental_src)

    # ── Convert both stems to WAV ──────────────────────────────────────────
    write_event(job_dir, "stem_conversion_started", "preparing", details={"stem": "vocals"})
    if not _convert_to_wav(vocals_src, job_dir / "vocals.wav"):
        _write_server_event(
            "stem_conversion_failed",
            level="error",
            message="Failed to convert vocals to WAV",
            job_id=job_id,
            stem="vocals",
        )
        write_event(
            job_dir,
            "stem_conversion_failed",
            "preparing",
            level="error",
            message="Failed to convert vocals to WAV",
            details={"stem": "vocals"},
        )
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": "Failed to convert vocals to WAV. Is ffmpeg installed?"}), 500
    write_event(job_dir, "stem_conversion_finished", "preparing", details={"stem": "vocals"})

    write_event(job_dir, "stem_conversion_started", "preparing", details={"stem": "instrumental"})
    if not _convert_to_wav(instrumental_src, job_dir / "instrumental.wav"):
        _write_server_event(
            "stem_conversion_failed",
            level="error",
            message="Failed to convert instrumental to WAV",
            job_id=job_id,
            stem="instrumental",
        )
        write_event(
            job_dir,
            "stem_conversion_failed",
            "preparing",
            level="error",
            message="Failed to convert instrumental to WAV",
            details={"stem": "instrumental"},
        )
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": "Failed to convert instrumental to WAV. Is ffmpeg installed?"}), 500
    write_event(job_dir, "stem_conversion_finished", "preparing", details={"stem": "instrumental"})

    # Clean up originals after conversion.
    # For individual-stem uploads the originals are written as vocals_orig.*
    # and instrumental_orig.* — always delete them after conversion regardless
    # of extension to avoid 2× storage waste for WAV uploads (~70 MB each).
    # For ZIP mode, vocals_src lives in stems/ so it is a different object;
    # preserve the stems/ directory there as before.
    if vocals_src.parent.resolve() == job_dir.resolve() and vocals_src.exists():
        vocals_src.unlink(missing_ok=True)
    if instrumental_src.parent.resolve() == job_dir.resolve() and instrumental_src.exists():
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
    write_event(job_dir, "meta_written", "preparing", details=meta)
    _write_status(job_dir, "queued", 0)
    write_event(job_dir, "status_initialized", "queued", details={"stage": "queued", "progress": 0})

    t = threading.Thread(target=_run_pipeline, args=(job_id,), daemon=True)
    _running[job_id] = t
    write_event(job_dir, "pipeline_thread_queued", "queued", details={"job_id": job_id})
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

@app.route("/job/<job_id>/review")
def review_wizard(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists():
        return "Job not found", 404

    meta = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
    project = _ensure_review_project(job_dir, job_id)
    review_points = build_review_points(job_dir, project)
    stage_summaries = build_stage_summaries(job_dir, project, review_points)
    active_stage = active_stage_id(project, request.args.get("stage"))
    status_filter = request.args.get("status", "all")
    if status_filter not in {"all", "open", "reviewed"}:
        status_filter = "all"
    level_filter = request.args.get("level", "all")
    if level_filter not in {"all", "line", "word", "issue"}:
        level_filter = "all"
    unfiltered_stage_points = points_for_stage(review_points, active_stage)
    stage_points = filtered_review_points(review_points, active_stage, status_filter, level_filter)
    show_point_review = active_stage in {"alignment", "quality"} and bool(unfiltered_stage_points)
    requested_point_id = request.args.get("point")
    active_point = next((point for point in stage_points if point.id == requested_point_id), None)
    if active_point is None:
        active_point = next_open_point(stage_points, active_stage)
    if active_point is None and stage_points:
        active_point = stage_points[0]
    artifact_graph_ready, _artifact_graph_reason = _artifact_graph_valid(job_dir)
    navigation = point_navigation(stage_points, active_point.id if active_point else None)
    point_window = review_point_window(stage_points, active_point.id if active_point else None)
    timeline_points = []
    highlight_segments = []
    if active_stage == "alignment":
        timeline_points = [
            point
            for point in review_points
            if point.stage_id == "alignment" or (point.stage_id == "quality" and point.level == "issue")
        ]
        highlight_segments = _timeline_highlight_segments(job_dir)
    audio_timeline = build_audio_timeline(
        timeline_points,
        stage_summaries.get("import", {}).get("duration_s"),
        active_point.id if active_point else None,
        highlight_segments=highlight_segments,
    )
    lyrics_sections = project.prepared_text.sections
    lyrics_section_payloads = _lyrics_sections_for_review(lyrics_sections)
    requested_section = request.args.get("section")
    active_lyrics_section = next(
        (
            section
            for section in lyrics_section_payloads
            if section["label"] == requested_section
            or section["id"] == requested_section
            or section["display_label"] == requested_section
        ),
        lyrics_section_payloads[0] if lyrics_section_payloads else None,
    )
    return render_template(
        "review_wizard.html",
        meta=meta,
        project=project.to_dict(),
        export_decision=dataclasses.asdict(can_export_final(project)),
        technical_export_ready=artifact_graph_ready,
        has_full_preview=(job_dir / "preview_full.mp4").exists(),
        stages=stage_view_models(project, active_stage, review_points),
        active_stage=active_stage,
        review_points=[point.to_dict() for point in point_window["items"]],
        review_point_window={
            **point_window,
            "items": [point.to_dict() for point in point_window["items"]],
        },
        active_point=active_point.to_dict() if active_point else None,
        point_navigation=navigation,
        review_filters={"status": status_filter, "level": level_filter},
        show_point_review=show_point_review,
        review_summary=review_export_summary(review_points),
        stage_summaries=stage_summaries,
        active_stage_summary=stage_summaries.get(active_stage, {}),
        audio_timeline=audio_timeline,
        lyrics_sections=lyrics_section_payloads,
        active_lyrics_section=active_lyrics_section,
    )


def _timeline_highlight_segments(job_dir: Path) -> list[dict[str, Any]]:
    analysis_path = job_dir / "analysis.json"
    if not analysis_path.exists() or analysis_path.stat().st_size == 0:
        return []
    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    segments: list[dict[str, Any]] = []
    for line_index, line in enumerate(analysis.get("lines", []), start=1):
        words = line.get("words", [])
        if not isinstance(words, list):
            continue
        for word_index, word in enumerate(words, start=1):
            if not isinstance(word, dict) or "start" not in word or "end" not in word:
                continue
            word_id = f"line-{line_index}:word-{word_index}"
            word_payload = {**word, "id": word_id}
            for segment_index, segment in enumerate(build_word_highlight_segments(word_payload), start=1):
                segments.append(
                    {
                        **segment,
                        "id": f"{word_id}:hv-{segment_index}",
                        "stage_id": "alignment",
                        "status": "generated",
                        "severity": "info",
                    }
                )
    return segments


def _review_filter_args_from_form() -> dict[str, str]:
    args: dict[str, str] = {}
    status_filter = request.form.get("status", "all")
    level_filter = request.form.get("level", "all")
    if status_filter in {"open", "reviewed"}:
        args["status"] = status_filter
    if level_filter in {"line", "word", "issue"}:
        args["level"] = level_filter
    return args


@app.post("/job/<job_id>/review/points/<point_id>/approve")
def review_wizard_approve_point(job_id: str, point_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists() or not project_path(job_dir).exists():
        return "Job not found", 404

    project = approve_review_point(load_project(job_dir), point_id, approved_by="local-user")
    save_project(job_dir, project)
    points = build_review_points(job_dir, project)
    current = next((point for point in points if point.id == point_id), None)
    stage = current.stage_id if current else request.form.get("stage", "alignment")
    filter_args = _review_filter_args_from_form()
    filtered_points = filtered_review_points(
        points,
        stage,
        filter_args.get("status", "all"),
        filter_args.get("level", "all"),
    )
    next_point = next_open_point_after(filtered_points, point_id)
    args = {"stage": stage, **filter_args}
    if next_point is not None:
        args["point"] = next_point.id
    return redirect(url_for("review_wizard", job_id=job_id, **args))


@app.post("/job/<job_id>/review/points/<point_id>/apply-suggestion")
def review_wizard_apply_point_suggestion(job_id: str, point_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists() or not project_path(job_dir).exists():
        return "Job not found", 404

    project = load_project(job_dir)
    points = build_review_points(job_dir, project)
    current = next((point for point in points if point.id == point_id), None)
    if current is None:
        return "Review point not found", 404
    project = apply_review_point_suggestion(
        project,
        point_id,
        applied_by="local-user",
        details={
            "source": current.source,
            "text": current.text,
            "suggested_action": current.suggested_action,
            "affected_ids": current.affected_ids,
        },
    )
    save_project(job_dir, project)
    points = build_review_points(job_dir, project)
    stage = current.stage_id
    filter_args = _review_filter_args_from_form()
    filtered_points = filtered_review_points(
        points,
        stage,
        filter_args.get("status", "all"),
        filter_args.get("level", "all"),
    )
    next_point = next_open_point_after(filtered_points, point_id)
    args = {"stage": stage, **filter_args}
    if next_point is not None:
        args["point"] = next_point.id
    return redirect(url_for("review_wizard", job_id=job_id, **args))


@app.post("/job/<job_id>/review/points/<point_id>/skip-risk")
def review_wizard_skip_point_risk(job_id: str, point_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists() or not project_path(job_dir).exists():
        return "Job not found", 404

    reason = request.form.get("reason", "")
    try:
        project = skip_review_point_with_risk(
            load_project(job_dir),
            point_id,
            skipped_by="local-user",
            risk_note=reason,
        )
    except ValueError as exc:
        return str(exc), 400
    save_project(job_dir, project)
    points = build_review_points(job_dir, project)
    current = next((point for point in points if point.id == point_id), None)
    stage = current.stage_id if current else request.form.get("stage", "alignment")
    filter_args = _review_filter_args_from_form()
    filtered_points = filtered_review_points(
        points,
        stage,
        filter_args.get("status", "all"),
        filter_args.get("level", "all"),
    )
    next_point = next_open_point_after(filtered_points, point_id)
    args = {"stage": stage, **filter_args}
    if next_point is not None:
        args["point"] = next_point.id
    return redirect(url_for("review_wizard", job_id=job_id, **args))


@app.post("/job/<job_id>/review/points/<point_id>/timing")
def review_wizard_adjust_point_timing(job_id: str, point_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists() or not project_path(job_dir).exists():
        return "Job not found", 404

    try:
        project = adjust_review_point_timing(
            load_project(job_dir),
            point_id,
            edited_by="local-user",
            start_s=float(request.form["start_s"]),
            end_s=float(request.form["end_s"]),
        )
    except (KeyError, ValueError) as exc:
        return str(exc), 400
    save_project(job_dir, project)
    return redirect(
        url_for(
            "review_wizard",
            job_id=job_id,
            stage=request.form.get("stage", "alignment"),
            point=point_id,
            **_review_filter_args_from_form(),
        )
    )


@app.post("/job/<job_id>/review/issues/<issue_id>/approve-risk")
def review_wizard_approve_issue_risk(job_id: str, issue_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists() or not project_path(job_dir).exists():
        return "Job not found", 404

    project = load_project(job_dir)
    reason = request.form.get("reason", "")
    try:
        project = approve_issue_risk(project, issue_id, approved_by="local-user", reason=reason)
    except ValueError as exc:
        return str(exc), 400
    save_project(job_dir, project)
    return redirect(url_for("review_wizard", job_id=job_id, stage="quality"))


@app.post("/job/<job_id>/review/issues/<issue_id>/apply-suggestion")
def review_wizard_apply_issue_suggestion(job_id: str, issue_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists() or not project_path(job_dir).exists():
        return "Job not found", 404

    project = load_project(job_dir)
    try:
        project = apply_issue_suggestion(project, issue_id, applied_by="local-user")
    except ValueError as exc:
        return str(exc), 400
    save_project(job_dir, project)
    return redirect(url_for("review_wizard", job_id=job_id, stage="quality"))


def _approve_review_preview(job_id: str, scope: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists() or not project_path(job_dir).exists():
        return "Job not found", 404

    project = load_project(job_dir)
    try:
        project = approve_preview(
            project,
            approved_by="local-user",
            scope=scope,
            evidence=_preview_approval_evidence(job_dir, project, scope),
        )
    except ValueError as exc:
        return str(exc), 400
    save_project(job_dir, project)
    return redirect(url_for("review_wizard", job_id=job_id, stage="preview"))


def _render_full_review_preview(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists() or not project_path(job_dir).exists():
        return "Job not found", 404

    source = job_dir / "output.mp4"
    preview = job_dir / "preview_full.mp4"
    if not source.exists():
        return "Preview source missing: output.mp4", 400
    graph_valid, graph_reason = _artifact_graph_valid(job_dir)
    if not graph_valid:
        return f"Preview blocked: artifact_graph_invalid: {graph_reason}", 400

    shutil.copy2(source, preview)
    project = load_project(job_dir)
    render = {
        "id": f"preview-{len(project.preview_renders) + 1}",
        "scope": "full_preview",
        "approved": False,
        "render_status": "ready",
        "artifact_path": preview.name,
        "artifact_sha256": _sha256_file(preview),
        "artifact_size_bytes": preview.stat().st_size,
        "rendered_at": time.time(),
    }
    project = dataclasses.replace(project, preview_renders=[*project.preview_renders, render])
    save_project(job_dir, project)
    return redirect(url_for("review_wizard", job_id=job_id, stage="preview"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preview_approval_evidence(job_dir: Path, project: Project, scope: str) -> dict[str, Any]:
    if not project.quality_reports:
        raise ValueError("quality review required")

    report = project.quality_reports[-1]
    primary_artifact_name = "preview_full.mp4" if scope == "full_preview" else "output.mp4"
    primary_artifact = job_dir / primary_artifact_name
    if not primary_artifact.exists():
        raise ValueError(f"preview artifact missing: {primary_artifact_name}")
    artifact_fingerprints: dict[str, dict[str, Any]] = {}
    artifact_names = ["output.mp4", "output.ass"]
    if scope == "full_preview":
        artifact_names.insert(0, "preview_full.mp4")
    for artifact_name in artifact_names:
        artifact_path = job_dir / artifact_name
        if artifact_path.exists():
            artifact_fingerprints[artifact_name] = {
                "sha256": _sha256_file(artifact_path),
                "size_bytes": artifact_path.stat().st_size,
            }

    report_issue_ids = set(report.issue_ids)
    open_issue_ids = [
        issue.id for issue in project.issues
        if issue.id in report_issue_ids and issue.status == "open"
    ]
    evidence: dict[str, Any] = {
        "scope": scope,
        "artifact_path": primary_artifact.name,
        "artifact_sha256": artifact_fingerprints["output.mp4"]["sha256"],
        "artifact_size_bytes": artifact_fingerprints["output.mp4"]["size_bytes"],
        "artifact_fingerprints": artifact_fingerprints,
        "take_id": report.take_id,
        "quality_report_id": report.id,
        "quality_status": report.status,
        "issue_ids_at_approval": list(report.issue_ids),
        "open_issue_ids_at_approval": open_issue_ids,
    }
    if scope == "full_preview":
        evidence["covers_full_timeline"] = True
    else:
        evidence["covered_issue_ids"] = open_issue_ids
        evidence["snippet_windows"] = [
            {"issue_id": issue.id, "start_s": issue.start_s, "end_s": issue.end_s}
            for issue in project.issues
            if issue.id in open_issue_ids
        ]
    return evidence


def _blocked_final_export_reason(job_dir: Path) -> str | None:
    if not project_path(job_dir).exists():
        graph_valid, graph_reason = _artifact_graph_valid(job_dir)
        return None if graph_valid else f"artifact_graph_invalid: {graph_reason}"
    project = load_project(job_dir)
    decision = can_export_final(project)
    if decision.allowed:
        approved_full_preview = next(
            (
                render for render in reversed(project.preview_renders)
                if render.get("approved") and render.get("scope") == "full_preview"
            ),
            None,
        )
        if approved_full_preview is not None:
            fingerprints = approved_full_preview.get("artifact_fingerprints") or {
                str(approved_full_preview.get("artifact_path", "")): {
                    "sha256": approved_full_preview.get("artifact_sha256"),
                }
            }
            for artifact_name, fingerprint in fingerprints.items():
                artifact = job_dir / str(artifact_name)
                if not artifact.exists():
                    return "artifact_missing"
                if _sha256_file(artifact) != fingerprint.get("sha256"):
                    return "artifact_changed"
        graph_valid, graph_reason = _artifact_graph_valid(job_dir)
        if not graph_valid:
            return f"artifact_graph_invalid: {graph_reason}"
        return None
    return decision.reason


@app.post("/job/<job_id>/review/preview/critical-snippets/approve")
def review_wizard_approve_critical_preview(job_id: str):
    return _approve_review_preview(job_id, "critical_snippets")


@app.post("/job/<job_id>/review/preview/full/render")
def review_wizard_render_full_preview(job_id: str):
    return _render_full_review_preview(job_id)


@app.route("/job/<job_id>/review/preview/full.mp4")
def review_wizard_full_preview_mp4(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Not found", 404
    path = job_dir / "preview_full.mp4"
    if not path.exists():
        return "Not found", 404
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.post("/job/<job_id>/review/preview/full/approve")
def review_wizard_approve_full_preview(job_id: str):
    return _approve_review_preview(job_id, "full_preview")


@app.route("/job/<job_id>/stream")
def job_stream(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists():
        return "Job not found", 404

    def generate():
        while True:
            status = _read_status(job_dir)
            stage  = status.get("stage", "")
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
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Not found", 404
    block_reason = _blocked_final_export_reason(job_dir)
    if block_reason:
        return f"Export blocked: {block_reason}", 403
    path = job_dir / "output.mp4"
    if not path.exists():
        return "Not found", 404
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.route("/job/<job_id>/output.ass")
def job_output_ass(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Not found", 404
    block_reason = _blocked_final_export_reason(job_dir)
    if block_reason:
        return f"Export blocked: {block_reason}", 403
    path = job_dir / "output.ass"
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


def _sanitize_observability_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower == "command":
                sanitized[key] = f"{len(item) if isinstance(item, list) else 1} args redacted"
            elif key_lower in {"path", "input", "output", "missing_job_dir"} or key_lower.endswith("_path"):
                sanitized[key] = Path(str(item)).name
            else:
                sanitized[key] = _sanitize_observability_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_observability_value(item) for item in value]
    return value


@app.route("/job/<job_id>/events")
def job_events_api(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return jsonify({"error": "job not found"}), 404
    if not job_dir.exists():
        return jsonify({"error": "job not found"}), 404

    summary_path = job_dir / "observability_summary.json"
    summary: dict[str, Any] = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {"error": "summary unreadable"}

    events = [_sanitize_observability_value(event) for event in read_events(job_dir)]
    limit = request.args.get("limit", default=80, type=int)
    limit = max(1, min(limit, 300))
    return jsonify(
        {
            "job_id": job_id,
            "events": events[-limit:],
            "summary": _sanitize_observability_value(summary),
        }
    )


@app.route("/job/<job_id>/delete", methods=["POST"])
def job_delete(job_id: str):
    if job_id in _running:
        try:
            job_dir = resolve_job_dir(JOBS_DIR, job_id)
            if job_dir.exists():
                write_event(
                    job_dir,
                    "running_job_deletion_blocked",
                    "running",
                    level="warning",
                    message="Cannot delete a running job.",
                )
            else:
                _write_server_event(
                    "running_job_deletion_blocked",
                    level="warning",
                    message="Cannot delete a running job.",
                    job_id=job_id,
                    stale_registry=True,
                )
        except ValueError:
            pass
        return jsonify({"error": "Cannot delete a running job."}), 409
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if job_dir.exists():
        shutil.rmtree(job_dir)
    return redirect(url_for("index"))


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Retry validation
# ─────────────────────────────────────────────────────────────────────────────

def _run_retry_validate(job_id: str) -> None:
    job_dir = resolve_job_dir(JOBS_DIR, job_id)
    write_event(job_dir, "retry_validate_started", "validating", details={"job_id": job_id})
    meta = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
    runner = PipelineRunner(
        job_dir=job_dir,
        python_exe=sys.executable,
        preset=meta.get("preset", "cyberpunk"),
        running_registry=_running,
        job_id=job_id,
    )
    try:
        cmd = [
            sys.executable, str(SCRIPTS / "s08_validate.py"),
            "--job-dir", str(job_dir),
            "--overlap-tolerance", str(APP_CONFIG.validate_overlap_tolerance_s),
        ]
        ok = runner.run_command(cmd, "validating", 95, timeout=120)
        if ok:
            runner._write_status("done", 100)
            write_event(job_dir, "pipeline_finished", "done", message="validation passed on retry")
        build_observability_summary(job_dir)
    finally:
        _running.pop(job_id, None)


@app.route("/job/<job_id>/retry-validate", methods=["POST"])
def job_retry_validate(job_id: str):
    if job_id in _running and _running[job_id].is_alive():
        return jsonify({"error": "Job is currently running."}), 409
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists():
        return "Job not found", 404

    status = _read_status(job_dir)
    if status.get("stage") != "failed" or int(status.get("progress") or 0) != 95:
        return jsonify({"error": "Job did not fail at the validation stage."}), 409

    t = threading.Thread(target=_run_retry_validate, args=(job_id,), daemon=True)
    _running[job_id] = t
    t.start()

    referrer = request.referrer
    if referrer:
        return redirect(referrer)
    return redirect(url_for("job_detail", job_id=job_id))


# ─────────────────────────────────────────────────────────────────────────────

_TERMINAL_STAGES = {"done", "failed"}


def _recover_orphan_jobs() -> None:
    """Mark jobs stuck in running or queued state as failed on server startup."""
    if not JOBS_DIR.exists():
        return
    for d in JOBS_DIR.iterdir():
        if not d.is_dir() or not validate_job_id(d.name):
            continue
        if not (d / "meta.json").exists():
            continue
        job_id = d.name
        if job_id in _running:
            continue
        try:
            status = _read_status(d)
        except Exception:
            continue
        if status["stage"] in _TERMINAL_STAGES:
            continue
        progress = status.get("progress", 0)
        _write_status(d, "failed", progress, "Server restarted while job was running. Please resubmit.")
        write_event(
            d,
            "server_restart_recovery",
            "failed",
            level="error",
            message="Server restarted while job was running. Please resubmit.",
            details={"recovered_stage": status["stage"], "recovered_progress": progress},
        )


def _server_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Karaoke MFA Multi local server.")
    parser.add_argument("--host", default=APP_CONFIG.server_host)
    parser.add_argument("--port", type=int, default=APP_CONFIG.server_port)
    return parser.parse_args()


if __name__ == "__main__":
    args = _server_cli_args()
    _recover_orphan_jobs()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
