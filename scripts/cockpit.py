from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from scripts.review_wizard.export_gate import can_export_final


STAGE_DEFINITIONS = [
    {"id": "s01", "label": "Input", "keys": {"queued", "preparing"}},
    {"id": "s02", "label": "Demix", "keys": {"demixing", "demix"}},
    {"id": "s03", "label": "Lyrics Align", "keys": {"aligning_lyrics", "transcribing"}},
    {"id": "s04", "label": "Align", "keys": {"aligning"}},
    {"id": "s05", "label": "Analyze", "keys": {"analyzing"}},
    {"id": "s06", "label": "ASS", "keys": {"generating"}},
    {"id": "s07", "label": "Render", "keys": {"rendering"}},
    {"id": "s08", "label": "Validate", "keys": {"validating", "done"}},
]

EXPECTED_ARTIFACTS = [
    "vocals.wav",
    "instrumental.wav",
    "lyrics.txt",
    "transcript.json",
    "aligned.json",
    "analysis.json",
    "output.ass",
    "output.mp4",
]

REVIEWED_STATUSES = {"approved", "edited", "skipped_with_risk", "suggestion_applied"}


def _status_stage(status: dict[str, Any] | None) -> str:
    return str((status or {}).get("stage", "queued") or "queued")


def _stage_index(stage: str) -> int:
    if stage == "failed":
        return -1
    for index, definition in enumerate(STAGE_DEFINITIONS):
        if stage in definition["keys"]:
            return index
    return 0


def cockpit_stage_rows(status: dict[str, Any] | None) -> list[dict[str, Any]]:
    stage = _status_stage(status)
    error = str((status or {}).get("error", "") or "")
    progress = int((status or {}).get("progress", 0) or 0)

    if stage == "done":
        active_index = len(STAGE_DEFINITIONS) - 1
    else:
        active_index = _stage_index(stage)

    rows: list[dict[str, Any]] = []
    for index, definition in enumerate(STAGE_DEFINITIONS):
        if stage == "done":
            state = "done"
        elif stage == "failed" and index == 0:
            state = "failed"
        elif index < active_index:
            state = "done"
        elif index == active_index:
            state = "failed" if stage == "failed" else "running"
        else:
            state = "pending"
        rows.append(
            {
                "id": definition["id"],
                "label": definition["label"],
                "state": state,
                "progress": progress if index == active_index else (100 if state == "done" else 0),
                "error": error if state == "failed" else "",
            }
        )
    return rows


def artifact_rows(job_dir: Path | None) -> list[dict[str, Any]]:
    rows = []
    for name in EXPECTED_ARTIFACTS:
        exists = bool(job_dir and (job_dir / name).exists())
        rows.append({"name": name, "exists": exists, "state": "ok" if exists else "missing"})
    return rows


def _duration_label(duration_s: Any, *, precise: bool = False) -> str:
    try:
        duration = float(duration_s)
    except (TypeError, ValueError):
        return "--:--"
    minutes = int(duration // 60)
    seconds = duration - (minutes * 60)
    if precise:
        return f"{minutes:02d}:{seconds:06.3f}"
    return f"{minutes:02d}:{int(seconds):02d}"


def _stage_label(status: dict[str, Any] | None) -> str:
    stage = _status_stage(status)
    if stage == "done":
        return "DONE"
    if stage == "failed":
        return "FAILED"
    return stage.replace("_", " ").upper()


def recent_project_cards(jobs: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    cards = []
    for job in jobs[:limit]:
        job_id = str(job.get("job_id", ""))
        quoted_job_id = quote(job_id, safe="")
        status = job.get("status", {}) or {}
        cards.append(
            {
                "job_id": job_id,
                "title": str(job.get("song_name") or "Untitled"),
                "preset": str(job.get("preset") or ""),
                "duration_label": _duration_label(job.get("duration_s")),
                "stage_label": _stage_label(status),
                "progress": int(status.get("progress", 0) or 0),
                "state": _status_stage(status),
                "href": f"/?job={quoted_job_id}",
                "review_href": f"/?job={quoted_job_id}&mode=review",
                "detail_href": f"/job/{quoted_job_id}",
            }
        )
    return cards


def selected_job_summary(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    status = job.get("status", {}) or {}
    return {
        "job_id": str(job.get("job_id", "")),
        "title": str(job.get("song_name") or "Unsaved Project"),
        "preset": str(job.get("preset") or ""),
        "duration_label": _duration_label(job.get("duration_s"), precise=True),
        "pipeline_label": _stage_label(status),
        "progress": int(status.get("progress", 0) or 0),
        "error": str(status.get("error", "") or ""),
    }


def _point_dict(point: Any) -> dict[str, Any]:
    if hasattr(point, "to_dict"):
        return point.to_dict()
    return dict(point)


def build_quick_review(job_id: str, project: Any | None, review_points: list[Any]) -> dict[str, Any]:
    open_points = [
        point
        for point in review_points
        if str(getattr(point, "status", "open")) not in REVIEWED_STATUSES
    ]
    open_points.sort(
        key=lambda point: (
            -float(getattr(point, "priority", 0.0)),
            float(getattr(point, "start_s", 0.0)),
            str(getattr(point, "id", "")),
        )
    )
    active = open_points[0] if open_points else None
    active_payload = _point_dict(active) if active else None
    quoted_job_id = quote(job_id, safe="")
    if active:
        point_id = quote(str(getattr(active, "id", "")), safe="")
        stage = quote(str(getattr(active, "stage_id", "alignment")), safe="")
        wizard_href = f"/job/{quoted_job_id}/review?stage={stage}&point={point_id}"
        approve_action = f"/job/{quoted_job_id}/review/points/{point_id}/approve"
        apply_action = f"/job/{quoted_job_id}/review/points/{point_id}/apply-suggestion"
        risk_action = f"/job/{quoted_job_id}/review/points/{point_id}/skip-risk"
    else:
        wizard_href = f"/job/{quoted_job_id}/review"
        approve_action = ""
        apply_action = ""
        risk_action = ""

    export_decision = can_export_final(project) if project is not None else None
    return {
        "active_point": active_payload,
        "queue": [_point_dict(point) for point in open_points[:8]],
        "open_count": len(open_points),
        "wizard_href": wizard_href,
        "approve_action": approve_action,
        "apply_action": apply_action,
        "risk_action": risk_action,
        "export_allowed": bool(export_decision.allowed) if export_decision else False,
        "export_reason": export_decision.reason if export_decision else "no_project_selected",
    }
