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
from scripts.review_wizard.versioning import add_edit_operation
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


def _read_metrics_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Pipeline metrics could not read %s: %s", path.name, e)
        return None
    return payload if isinstance(payload, dict) else None


def _metrics_percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * percentile / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 3)


def _compute_pipeline_metrics(job_dir: Path) -> dict[str, Any]:
    safety = _read_metrics_json(job_dir / "ctc_window_safety_report.json")
    window_safety_rate = None
    long_gap_crossings = 0
    if safety:
        summary = safety.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        total_windows = summary.get("total_windows")
        safe_windows = summary.get("safe_windows")
        if total_windows is None:
            windows_payload = _read_metrics_json(job_dir / "alignment_windows.json")
            windows = windows_payload.get("windows", []) if windows_payload else []
            total_windows = len(windows) if isinstance(windows, list) else None
        if safe_windows is None and total_windows is not None:
            unsafe_windows = summary.get("unsafe_windows")
            if isinstance(unsafe_windows, (int, float)):
                safe_windows = max(0, int(total_windows) - int(unsafe_windows))
        if isinstance(total_windows, (int, float)) and total_windows > 0 and isinstance(safe_windows, (int, float)):
            window_safety_rate = round(float(safe_windows) / float(total_windows), 4)
        if isinstance(summary.get("long_gap_crossing_windows"), (int, float)):
            long_gap_crossings = int(summary["long_gap_crossing_windows"])

    syllable_payload = _read_metrics_json(job_dir / "syllable_alignment.json")
    syllables = syllable_payload.get("syllables", []) if syllable_payload else []
    syllables = syllables if isinstance(syllables, list) else []
    confidences: list[float] = []
    projected = 0
    fallbacks = 0
    for syllable in syllables:
        if not isinstance(syllable, dict):
            continue
        source = str(syllable.get("source") or "")
        projected += source == "phone_projection"
        fallbacks += "fallback" in source
        try:
            confidences.append(float(syllable["confidence"]))
        except (KeyError, TypeError, ValueError):
            pass

    total_syllables = len([item for item in syllables if isinstance(item, dict)])
    block_reason = _blocked_final_export_reason(job_dir)
    return {
        "window_safety_rate": window_safety_rate,
        "syllable_projection_rate": round(projected / total_syllables, 4) if total_syllables else None,
        "syllable_confidence_p50": _metrics_percentile(confidences, 50),
        "syllable_confidence_p05": _metrics_percentile(confidences, 5),
        "fallback_usage": round(fallbacks / total_syllables, 4) if total_syllables else None,
        "long_gap_crossings": long_gap_crossings,
        "final_export_allowed": block_reason is None,
        "final_export_block_reason": block_reason,
    }


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
            capture_output=True, timeout=APP_CONFIG.input_ffmpeg_timeout_s,
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
    (job_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
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
        job_id=job_id,
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


_SYLLABLE_BOUNDARY_EPS = 0.001


def _find_analysis_word(
    analysis: dict[str, Any], word_id: str, line_id: Any = None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    for line in analysis.get("lines", []) or []:
        if not isinstance(line, dict):
            continue
        if line_id not in (None, "") and str(line.get("id")) != str(line_id):
            continue
        for word in line.get("words", []) or []:
            if isinstance(word, dict) and str(word.get("id")) == str(word_id):
                return line, word
    return None, None


def _invalidate_downstream_outputs(job_dir: Path) -> list[str]:
    """Remove ass/mp4 + manifests so s06/s07 must regenerate (no orphan output)."""
    removed: list[str] = []
    for name in (
        "output.mp4",
        "output.mp4.manifest.json",
        "output.ass",
        "output.ass.manifest.json",
        "preview_full.mp4",
    ):
        path = job_dir / name
        if path.exists():
            path.unlink()
            removed.append(name)
    return removed


@app.post("/job/<job_id>/review/syllables/boundary")
def review_wizard_edit_syllable_boundary(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return jsonify({"error": "Job not found"}), 404
    if not job_dir.exists():
        return jsonify({"error": "Job not found"}), 404
    analysis_path = job_dir / "analysis.json"
    if not analysis_path.exists():
        return jsonify({"error": "analysis.json missing"}), 404

    payload: Any = request.get_json(silent=True)
    if payload is None:
        payload = request.form
    word_id = payload.get("word_id")
    line_id = payload.get("line_id")
    if not word_id:
        return jsonify({"error": "word_id is required"}), 400
    raw_segments = payload.get("segments")
    if isinstance(raw_segments, str):
        try:
            raw_segments = json.loads(raw_segments)
        except json.JSONDecodeError:
            return jsonify({"error": "segments must be a JSON list"}), 400
    if not isinstance(raw_segments, list) or not raw_segments:
        return jsonify({"error": "segments must be a non-empty list"}), 400

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    _line, word = _find_analysis_word(analysis, word_id, line_id)
    if word is None:
        return jsonify({"error": f"word not found: {word_id}"}), 404

    try:
        word_start = float(word.get("start", word.get("start_s")))
        word_end = float(word.get("end", word.get("end_s")))
    except (TypeError, ValueError):
        return jsonify({"error": "word has no valid span"}), 400

    # Validate every segment BEFORE mutating anything (§8: reject 400, don't write).
    segments: list[dict[str, Any]] = []
    cursor = word_start
    for index, seg in enumerate(raw_segments, start=1):
        if not isinstance(seg, dict):
            return jsonify({"error": "each segment must be an object"}), 400
        text = str(seg.get("text", "")).strip()
        if not text:
            return jsonify({"error": "segment text is required"}), 400
        try:
            start = float(seg.get("start", seg.get("start_s")))
            end = float(seg.get("end", seg.get("end_s")))
        except (TypeError, ValueError):
            return jsonify({"error": "segment start/end must be numbers"}), 400
        if start < word_start - _SYLLABLE_BOUNDARY_EPS or end > word_end + _SYLLABLE_BOUNDARY_EPS:
            return jsonify({"error": "segment boundary outside word span"}), 400
        if end <= start or start < cursor - _SYLLABLE_BOUNDARY_EPS:
            return jsonify({"error": "segments must be ordered and non-overlapping"}), 400
        cursor = end
        segments.append({
            "id": str(seg.get("id") or f"{word_id}_M{index:03d}"),
            "text": text,
            "start": round(start, 3),
            "end": round(end, 3),
            "role": str(seg.get("role", "syllable")),
            "source": "manual",
            "confidence": 1.0,
        })

    word["highlight_segments"] = segments
    analysis_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    invalidated = _invalidate_downstream_outputs(job_dir)

    project = add_edit_operation(
        _ensure_review_project(job_dir, job_id),
        operation="edit_syllable_boundaries",
        target_id=str(word_id),
        created_by="local-user",
        details={"line_id": line_id, "segments": segments, "invalidated": invalidated},
    )
    save_project(job_dir, project)

    write_event(
        job_dir,
        "syllable_boundary_edited",
        "review",
        details={
            "job_id": job_id,
            "word_id": word_id,
            "line_id": line_id,
            "segment_count": len(segments),
            "invalidated": invalidated,
        },
    )
    return jsonify({
        "word_id": word_id,
        "highlight_segments": segments,
        "invalidated": invalidated,
    })


def _seg_time(seg: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        if name in seg and seg[name] is not None:
            try:
                return float(seg[name])
            except (TypeError, ValueError):
                continue
    return default


def _syllable_pending_queue(
    job_dir: Path, threshold: float, include_all: bool = False
) -> list[dict[str, Any]]:
    """Editable words for the syllable review UI, sorted worst-confidence first.

    By default returns only words that need attention — derived syllables below
    ``threshold``, not manually locked. With ``include_all`` it returns every
    multi-syllable word (regardless of confidence) so the editor can be used to
    refine any word's boundaries on demand, not just flagged ones; each item
    carries an ``uncertain`` flag so the client can still highlight the pendings.
    """
    analysis = _read_metrics_json(job_dir / "analysis.json") or {}
    items: list[dict[str, Any]] = []
    for line in analysis.get("lines", []) or []:
        if not isinstance(line, dict):
            continue
        line_id = str(line.get("id") or "")
        for word in line.get("words", []) or []:
            if not isinstance(word, dict):
                continue
            manual = bool(word.get("highlight_segments"))
            raw = word.get("syllables") or []
            segments: list[dict[str, Any]] = []
            min_conf = 1.0
            for seg in raw:
                if not isinstance(seg, dict):
                    continue
                start = _seg_time(seg, "karaoke_start", "start", "start_s")
                end = _seg_time(seg, "karaoke_end", "end", "end_s", default=start)
                conf = float(seg.get("confidence", 1.0))
                min_conf = min(min_conf, conf)
                segments.append({
                    "id": str(seg.get("id") or seg.get("syllable_id") or ""),
                    "text": str(seg.get("text", "")),
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "confidence": round(conf, 4),
                })
            if manual or not segments:
                continue
            uncertain = min_conf < threshold
            if include_all:
                if len(segments) < 2:  # browse mode: only words with real boundaries to adjust
                    continue
            elif not uncertain:
                continue
            items.append({
                "line_id": line_id,
                "line_text": str(line.get("text", "")),
                "word_id": str(word.get("id") or ""),
                "word_text": str(word.get("word") or word.get("text") or ""),
                "word_start": round(_seg_time(word, "start", "start_s"), 3),
                "word_end": round(_seg_time(word, "end", "end_s"), 3),
                "min_confidence": round(min_conf, 4),
                "uncertain": uncertain,
                "segments": segments,
            })
    items.sort(key=lambda item: item["min_confidence"])
    return items


@app.route("/job/<job_id>/review/syllables/pending")
def review_wizard_syllable_pending(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return jsonify({"error": "Job not found"}), 404
    if not job_dir.exists():
        return jsonify({"error": "Job not found"}), 404
    threshold = APP_CONFIG.syllable_uncertain_threshold
    include_all = request.args.get("scope") == "all"
    items = _syllable_pending_queue(job_dir, threshold, include_all=include_all)
    return jsonify({
        "job_id": job_id,
        "threshold": threshold,
        "scope": "all" if include_all else "pending",
        "count": len(items),
        "uncertain_count": sum(1 for it in items if it.get("uncertain")),
        "pending": items,
    })


_AUDIO_STEMS = {"vocals": "vocals.wav", "instrumental": "instrumental.wav"}


@app.route("/job/<job_id>/audio/<stem>")
def job_audio(job_id: str, stem: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Not found", 404
    fname = _AUDIO_STEMS.get(stem)
    if fname is None:
        return "Not found", 404
    path = job_dir / fname
    if not path.exists():
        return "Not found", 404
    return send_file(path, mimetype="audio/wav", conditional=True)


def _wav_window_peaks(path: Path, start_s: float, end_s: float, buckets: int) -> dict[str, Any]:
    """Min/max peaks for a WAV time window, computed server-side so the browser
    never decodes the whole stem. Reads only the requested frame range."""
    import wave
    import numpy as np

    with wave.open(str(path), "rb") as wav:
        sr = wav.getframerate()
        nframes = wav.getnframes()
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        s0 = max(0, int(start_s * sr))
        s1 = min(nframes, int(end_s * sr))
        if s1 <= s0:
            return {"sample_rate": sr, "buckets": []}
        wav.setpos(s0)
        raw = wav.readframes(s1 - s0)

    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        return {"sample_rate": sr, "buckets": []}
    samples = np.frombuffer(raw, dtype=dtype)
    if channels > 1:
        samples = samples[::channels]  # first channel
    if samples.size == 0:
        return {"sample_rate": sr, "buckets": []}
    norm = samples.astype(np.float32) / float(np.iinfo(dtype).max)
    edges = np.linspace(0, norm.size, buckets + 1, dtype=int)
    out = []
    for k in range(buckets):
        seg = norm[edges[k]:edges[k + 1]]
        if seg.size:
            out.append([round(float(seg.min()), 4), round(float(seg.max()), 4)])
        else:
            out.append([0.0, 0.0])
    return {"sample_rate": sr, "buckets": out}


@app.route("/job/<job_id>/audio/vocals/peaks")
def job_audio_peaks(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return jsonify({"error": "Job not found"}), 404
    path = job_dir / "vocals.wav"
    if not path.exists():
        return jsonify({"error": "no vocals"}), 404
    try:
        start_s = max(0.0, float(request.args.get("start", 0.0)))
        end_s = max(start_s, float(request.args.get("end", start_s)))
        buckets = min(2000, max(50, int(request.args.get("buckets", 800))))
    except (TypeError, ValueError):
        return jsonify({"error": "bad params"}), 400
    try:
        return jsonify(_wav_window_peaks(path, start_s, end_s, buckets))
    except Exception as exc:  # malformed/float wav etc. — degrade gracefully
        return jsonify({"error": str(exc), "buckets": []}), 200


def _wav_window_onsets(path: Path, start_s: float, end_s: float, max_onsets: int = 48) -> dict[str, Any]:
    """Onset times for a WAV window via a spectral-flux envelope, computed at full
    sample resolution server-side (more precise than the client's bucket heuristic).

    Reads only the requested frame range — never decodes the whole stem — then STFTs
    the window, sums the positive spectral flux per frame, subtracts a local mean and
    peak-picks with a >=50ms minimum spacing. Returns onset times in seconds."""
    import wave
    import numpy as np

    with wave.open(str(path), "rb") as wav:
        sr = wav.getframerate()
        nframes = wav.getnframes()
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        s0 = max(0, int(start_s * sr))
        s1 = min(nframes, int(end_s * sr))
        if s1 <= s0:
            return {"sample_rate": sr, "onsets": []}
        wav.setpos(s0)
        raw = wav.readframes(s1 - s0)

    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        return {"sample_rate": sr, "onsets": []}
    samples = np.frombuffer(raw, dtype=dtype)
    if channels > 1:
        samples = samples[::channels]  # first channel
    if samples.size == 0:
        return {"sample_rate": sr, "onsets": []}
    x = samples.astype(np.float32) / float(np.iinfo(dtype).max)

    # STFT spectral-flux onset envelope (Hann window ~46ms, 4x overlap).
    win = 1 << int(max(6, min(11, round(float(np.log2(max(64.0, 0.046 * sr)))))))
    hop = max(1, win // 4)
    if x.size < win + hop:
        return {"sample_rate": sr, "onsets": []}
    window = np.hanning(win).astype(np.float32)
    n = 1 + (x.size - win) // hop
    flux = np.zeros(n, dtype=np.float32)
    prev = None
    for i in range(n):
        mag = np.abs(np.fft.rfft(x[i * hop:i * hop + win] * window))
        if prev is not None:
            flux[i] = float(np.sum(np.maximum(0.0, mag - prev)))
        prev = mag
    peak = float(flux.max())
    if n < 3 or peak <= 0:
        return {"sample_rate": sr, "onsets": []}
    flux /= peak

    # subtract a local mean, then pick prominent local maxima with min spacing
    wmean = max(3, int(0.08 * sr / hop))
    kernel = np.ones(wmean, dtype=np.float32) / wmean
    detect = flux - np.convolve(flux, kernel, mode="same")
    min_gap = max(1, int(round(0.05 * sr / hop)))  # >= ~50ms between onsets
    # ponytail: O(cand^2) spacing greedy — cand is tiny for a word-sized window
    cand = [(float(flux[i]), i) for i in range(1, n - 1)
            if detect[i] > 0.05 and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]]
    cand.sort(reverse=True)
    chosen: list[int] = []
    for _, i in cand:
        if len(chosen) >= max_onsets:
            break
        if all(abs(i - j) >= min_gap for j in chosen):
            chosen.append(i)
    chosen.sort()
    onsets = [round(start_s + (i * hop + win / 2) / sr, 3) for i in chosen]
    return {"sample_rate": sr, "onsets": onsets}


@app.route("/job/<job_id>/audio/vocals/onsets")
def job_audio_onsets(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return jsonify({"error": "Job not found"}), 404
    path = job_dir / "vocals.wav"
    if not path.exists():
        return jsonify({"error": "no vocals"}), 404
    try:
        start_s = max(0.0, float(request.args.get("start", 0.0)))
        end_s = max(start_s, float(request.args.get("end", start_s)))
    except (TypeError, ValueError):
        return jsonify({"error": "bad params"}), 400
    try:
        return jsonify(_wav_window_onsets(path, start_s, end_s))
    except Exception as exc:  # malformed/float wav etc. — degrade gracefully
        return jsonify({"error": str(exc), "onsets": []}), 200


@app.route("/job/<job_id>/review/syllables")
def review_wizard_syllable_editor(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists():
        return "Job not found", 404
    meta = {}
    meta_path = job_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    has_vocals = (job_dir / "vocals.wav").exists()
    return render_template(
        "syllable_editor.html",
        job_id=job_id,
        song_name=meta.get("song_name", job_id),
        has_vocals=has_vocals,
        uncertain_threshold=APP_CONFIG.syllable_uncertain_threshold,
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
    metrics["pipeline_metrics"] = _compute_pipeline_metrics(job_dir)
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
