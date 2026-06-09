from __future__ import annotations

import json
import wave
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
DEFAULT_TIMELINE_BAR_COUNT = 96
DEFAULT_MINI_WAVEFORM_BAR_COUNT = 24
MAX_WAV_FRAMES_PER_BAR = 4096
MIN_WAVEFORM_BAR_HEIGHT_PCT = 8
MAX_WAVEFORM_BAR_HEIGHT_PCT = 96
WAVEFORM_BAR_HEIGHT_RANGE_PCT = MAX_WAVEFORM_BAR_HEIGHT_PCT - MIN_WAVEFORM_BAR_HEIGHT_PCT
MIN_MARKER_WIDTH_PCT = 1.2
TIMELINE_LYRIC_MARKER_LIMIT = 6
TIMELINE_ISSUE_MARKER_LIMIT = 12
TIMELINE_ISSUE_PRIORITY_THRESHOLD = 0.5
REVIEW_WINDOW_PADDING_S = 0.35
MIN_REVIEW_WINDOW_DURATION_S = 0.2
TIMELINE_WAV_ARTIFACTS = [
    {"id": "vocals", "label": "Vocals", "name": "vocals.wav"},
    {"id": "instrumental", "label": "Instrumental", "name": "instrumental.wav"},
]


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
    # No status means no job is selected — all stages start as pending
    if not status:
        return [
            {"id": d["id"], "label": d["label"], "state": "pending", "progress": 0, "error": ""}
            for d in STAGE_DEFINITIONS
        ]

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


def cockpit_service_summary(jobs: list[dict[str, Any]]) -> dict[str, str]:
    total = len(jobs)
    running = sum(1 for job in jobs if _status_stage(job.get("status", {})) not in {"done", "failed"})
    failed = sum(1 for job in jobs if _status_stage(job.get("status", {})) == "failed")
    return {
        "label": f"{total} project{'s' if total != 1 else ''} indexed",
        "state": f"{running} running / {failed} failed",
    }


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
        "language_label": str(job.get("language") or job.get("language_label") or "--"),
        "preset": str(job.get("preset") or ""),
        "duration_label": _duration_label(job.get("duration_s"), precise=True),
        "pipeline_label": _stage_label(status),
        "progress": int(status.get("progress", 0) or 0),
        "error": str(status.get("error", "") or ""),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _position_payload(start_s: float, end_s: float, duration_s: float) -> dict[str, float]:
    if duration_s <= 0:
        return {"left_pct": 0.0, "width_pct": 0.0}
    start = max(0.0, min(duration_s, start_s))
    end = max(start, min(duration_s, end_s))
    left_pct = (start / duration_s) * 100
    width_pct = (
        max(MIN_MARKER_WIDTH_PCT, ((end - start) / duration_s) * 100)
        if end > start
        else MIN_MARKER_WIDTH_PCT
    )
    return {"left_pct": round(left_pct, 3), "width_pct": round(width_pct, 3)}


def _pcm_peak(raw: bytes, sample_width: int) -> int:
    if not raw:
        return 0
    if sample_width == 1:
        return max(abs(byte - 128) for byte in raw)

    peak = 0
    step = sample_width
    usable = len(raw) - (len(raw) % step)
    for index in range(0, usable, step):
        sample = int.from_bytes(raw[index:index + step], "little", signed=True)
        amplitude = abs(sample)
        if amplitude > peak:
            peak = amplitude
    return peak


def _wav_peak_bars(
    path: Path,
    *,
    bar_count: int = DEFAULT_TIMELINE_BAR_COUNT,
    start_s: float | None = None,
    end_s: float | None = None,
) -> tuple[list[dict[str, int]], float]:
    if not path.exists() or bar_count <= 0:
        return [], 0.0
    try:
        with wave.open(str(path), "rb") as wav:
            frame_count = wav.getnframes()
            framerate = wav.getframerate() or 1
            sample_width = wav.getsampwidth()
            duration_s = frame_count / framerate if frame_count else 0.0
            start_frame = 0 if start_s is None else max(0, int(start_s * framerate))
            end_frame = frame_count if end_s is None else min(frame_count, int(end_s * framerate))
            if end_frame <= start_frame:
                return [], duration_s
            span = end_frame - start_frame
            read_frames = max(1, min(MAX_WAV_FRAMES_PER_BAR, span // bar_count or 1))
            peaks: list[int] = []
            for index in range(bar_count):
                frame_pos = start_frame + int((span * index) / bar_count)
                if frame_pos >= end_frame:
                    peaks.append(0)
                    continue
                wav.setpos(frame_pos)
                raw = wav.readframes(min(read_frames, end_frame - frame_pos))
                peaks.append(_pcm_peak(raw, sample_width))
    except (OSError, wave.Error, EOFError):
        return [], 0.0

    max_peak = max(peaks) if peaks else 0
    if max_peak <= 0:
        return [{"height": MIN_WAVEFORM_BAR_HEIGHT_PCT, "value": 0} for _ in peaks], duration_s
    bars = [
        {
            "height": max(
                MIN_WAVEFORM_BAR_HEIGHT_PCT,
                min(
                    MAX_WAVEFORM_BAR_HEIGHT_PCT,
                    int(round(MIN_WAVEFORM_BAR_HEIGHT_PCT + ((peak / max_peak) * WAVEFORM_BAR_HEIGHT_RANGE_PCT))),
                ),
            ),
            "value": int(peak),
        }
        for peak in peaks
    ]
    return bars, duration_s


def _timeline_lane(job_dir: Path, artifact: dict[str, str], bar_count: int) -> dict[str, Any]:
    path = job_dir / artifact["name"]
    bars, duration_s = _wav_peak_bars(path, bar_count=bar_count)
    return {
        "id": artifact["id"],
        "label": artifact["label"],
        "artifact": artifact["name"],
        "bars": bars,
        "duration_s": duration_s,
        "state": "ok" if bars else "missing",
    }


def _mix_lane(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    source_bars = [lane["bars"] for lane in lanes if lane.get("bars")]
    duration_s = max([float(lane.get("duration_s") or 0.0) for lane in lanes] or [0.0])
    if not source_bars:
        return {
            "id": "mix",
            "label": "Mix",
            "artifact": "derived",
            "bars": [],
            "duration_s": duration_s,
            "state": "missing",
        }

    bar_count = min(len(bars) for bars in source_bars)
    mixed = []
    for index in range(bar_count):
        heights = [int(bars[index]["height"]) for bars in source_bars]
        values = [int(bars[index]["value"]) for bars in source_bars]
        mixed.append({"height": int(round(sum(heights) / len(heights))), "value": max(values)})
    return {
        "id": "mix",
        "label": "Mix",
        "artifact": "derived",
        "bars": mixed,
        "duration_s": duration_s,
        "state": "ok",
    }


def _distributed_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(items) <= limit:
        return items
    if limit <= 1:
        return items[:1]
    step = (len(items) - 1) / (limit - 1)
    return [items[int(round(index * step))] for index in range(limit)]


def _analysis_lyrics(
    job_dir: Path,
    duration_s: float,
    *,
    limit: int = TIMELINE_LYRIC_MARKER_LIMIT,
) -> list[dict[str, Any]]:
    analysis = _read_json(job_dir / "analysis.json")
    candidates = []
    lines = analysis.get("lines", [])
    if not isinstance(lines, list):
        return []
    for line in lines:
        if not isinstance(line, dict):
            continue
        start = _float_or_none(line.get("start"))
        end = _float_or_none(line.get("end"))
        text = str(line.get("text") or "").strip()
        if start is None or end is None or not text:
            continue
        candidates.append(
            {
                "text": text,
                "start_s": start,
                "end_s": end,
                **_position_payload(start, end, duration_s),
            }
        )
    return _distributed_items(candidates, limit)


def _timeline_issues(review_points: list[Any], duration_s: float) -> list[dict[str, Any]]:
    rows = []
    open_points = [
        point
        for point in review_points
        if str(getattr(point, "status", "open")) not in REVIEWED_STATUSES
        and (
            str(getattr(point, "level", "")) == "issue"
            or str(getattr(point, "severity", "info")) != "info"
            or float(getattr(point, "priority", 0.0)) >= TIMELINE_ISSUE_PRIORITY_THRESHOLD
        )
    ]
    open_points.sort(key=lambda point: (float(getattr(point, "start_s", 0.0)), -float(getattr(point, "priority", 0.0))))
    for point in open_points[:TIMELINE_ISSUE_MARKER_LIMIT]:
        start = float(getattr(point, "start_s", 0.0))
        end = float(getattr(point, "end_s", start))
        text = str(getattr(point, "text", "") or getattr(point, "level", "issue"))
        rows.append(
            {
                "id": str(getattr(point, "id", "")),
                "text": text,
                "severity": str(getattr(point, "severity", "info") or "info"),
                "level": str(getattr(point, "level", "")),
                "start_s": start,
                "end_s": end,
                **_position_payload(start, end, duration_s),
            }
        )
    return rows


def _confidence_segments(issues: list[dict[str, Any]], duration_s: float) -> list[dict[str, Any]]:
    if duration_s <= 0:
        return []
    if not issues:
        return [{"left_pct": 0.0, "width_pct": 100.0, "state": "clear"}]
    return [
        {
            "left_pct": issue["left_pct"],
            "width_pct": issue["width_pct"],
            "state": "review",
        }
        for issue in issues
    ]


def build_cockpit_timeline(
    job_dir: Path | None,
    review_points: list[Any] | None = None,
    *,
    bar_count: int = DEFAULT_TIMELINE_BAR_COUNT,
) -> dict[str, Any]:
    if not job_dir:
        return {
            "has_audio": False,
            "duration_s": 0.0,
            "duration_label": "--:--",
            "lanes": [],
            "lyrics": [],
            "issues": [],
            "confidence_segments": [],
        }

    audio_lanes = [_timeline_lane(job_dir, artifact, bar_count) for artifact in TIMELINE_WAV_ARTIFACTS]
    lanes = [_mix_lane(audio_lanes), *audio_lanes]
    duration_s = max([float(lane.get("duration_s") or 0.0) for lane in lanes] or [0.0])
    lyrics = _analysis_lyrics(job_dir, duration_s)
    if duration_s <= 0 and lyrics:
        duration_s = max(float(line["end_s"]) for line in lyrics)
        lyrics = _analysis_lyrics(job_dir, duration_s)
    issues = _timeline_issues(review_points or [], duration_s)
    return {
        "has_audio": any(lane["state"] == "ok" for lane in lanes),
        "duration_s": duration_s,
        "duration_label": _duration_label(duration_s, precise=True),
        "lanes": lanes,
        "lyrics": lyrics,
        "issues": issues,
        "confidence_segments": _confidence_segments(issues, duration_s),
    }


def review_window_waveform(
    job_dir: Path | None,
    point: dict[str, Any] | None,
    *,
    bar_count: int = DEFAULT_MINI_WAVEFORM_BAR_COUNT,
) -> list[dict[str, int]]:
    if not job_dir or not point:
        return []
    start = _float_or_none(point.get("start_s")) or 0.0
    end = _float_or_none(point.get("end_s")) or start
    window_start = max(0.0, start - REVIEW_WINDOW_PADDING_S)
    window_end = max(window_start + MIN_REVIEW_WINDOW_DURATION_S, end + REVIEW_WINDOW_PADDING_S)
    for artifact in ("vocals.wav", "instrumental.wav"):
        bars, _duration = _wav_peak_bars(job_dir / artifact, bar_count=bar_count, start_s=window_start, end_s=window_end)
        if bars:
            return bars
    return []


def _point_dict(point: Any) -> dict[str, Any]:
    if hasattr(point, "to_dict"):
        return point.to_dict()
    return dict(point)


def build_quick_review(
    job_id: str,
    project: Any | None,
    review_points: list[Any],
    *,
    mini_waveform: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
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
        "mini_waveform": mini_waveform or [],
        "export_allowed": bool(export_decision.allowed) if export_decision else False,
        "export_reason": export_decision.reason if export_decision else "no_project_selected",
    }
