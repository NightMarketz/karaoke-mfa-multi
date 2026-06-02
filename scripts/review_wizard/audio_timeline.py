from __future__ import annotations

from typing import Any

LANES = (
    {"id": "line", "label": "LINE"},
    {"id": "word", "label": "WORD"},
    {"id": "highlight", "label": "HIGHLIGHT"},
    {"id": "issue", "label": "ISSUE"},
)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _clamp_pct(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 3)


def _duration(points: list[Any], duration_s: float | None) -> float:
    if duration_s and duration_s > 0:
        return float(duration_s)
    max_end = 0.0
    for point in points:
        try:
            max_end = max(max_end, float(_field(point, "end_s", 0.0)))
        except (TypeError, ValueError):
            continue
    return max(max_end, 1.0)


def _pct(seconds: float, duration_s: float) -> float:
    return _clamp_pct((seconds / duration_s) * 100.0)


def _format_seconds(seconds: float) -> str:
    if seconds == int(seconds):
        return f"{int(seconds)}s"
    return f"{seconds:.1f}s"


def _tick_interval(duration_s: float) -> float:
    if duration_s <= 12:
        return 2.0
    if duration_s <= 30:
        return 5.0
    if duration_s <= 90:
        return 10.0
    if duration_s <= 240:
        return 30.0
    return 60.0


def _ruler_ticks(duration_s: float) -> list[dict[str, Any]]:
    interval = _tick_interval(duration_s)
    ticks: list[dict[str, Any]] = []
    current = 0.0
    while current < duration_s:
        ticks.append(
            {
                "time_s": round(current, 3),
                "left_pct": _pct(current, duration_s),
                "label": _format_seconds(current),
            }
        )
        current += interval
    ticks.append(
        {
            "time_s": round(duration_s, 3),
            "left_pct": 100.0,
            "label": _format_seconds(duration_s),
        }
    )
    return ticks


def _lane_id(level: str) -> str:
    return level if level in {"line", "word", "highlight", "issue"} else "issue"


def _time_field(value: Any, primary: str, fallback: str, default: float = 0.0) -> float:
    try:
        return float(_field(value, primary, _field(value, fallback, default)))
    except (TypeError, ValueError):
        return default


def _waveform(points: list[Any], duration_s: float, buckets: int) -> list[int]:
    values: list[int] = []
    for index in range(buckets):
        center_s = ((index + 0.5) / buckets) * duration_s
        local_density = 0
        for point in points:
            try:
                start_s = float(_field(point, "start_s", 0.0))
                end_s = float(_field(point, "end_s", 0.0))
            except (TypeError, ValueError):
                continue
            if start_s <= center_s <= end_s:
                local_density += 1
        pulse = ((index * 7) % 13) / 12
        height = 18 + min(54, local_density * 12) + int(pulse * 28)
        values.append(max(12, min(92, height)))
    return values


def build_audio_timeline(
    points: list[Any],
    duration_s: float | None,
    active_point_id: str | None,
    highlight_segments: list[Any] | None = None,
    buckets: int = 48,
) -> dict[str, Any]:
    timeline_duration = _duration(points, duration_s)
    markers: list[dict[str, Any]] = []
    active_region: dict[str, Any] | None = None

    for point in points:
        point_id = str(_field(point, "id", ""))
        try:
            start_s = float(_field(point, "start_s", 0.0))
            end_s = float(_field(point, "end_s", start_s))
        except (TypeError, ValueError):
            continue
        left_pct = _pct(start_s, timeline_duration)
        end_pct = _pct(end_s, timeline_duration)
        level = str(_field(point, "level", "point")).lower()
        lane_id = _lane_id(level)
        marker = {
            "id": point_id,
            "stage_id": str(_field(point, "stage_id", "")),
            "label": level.upper(),
            "level": level,
            "lane_id": lane_id,
            "text": str(_field(point, "text", "")),
            "left_pct": left_pct,
            "width_pct": round(max(0.0, end_pct - left_pct), 3),
            "is_active": point_id == active_point_id,
            "status": str(_field(point, "status", "open")),
            "severity": str(_field(point, "severity", "info")),
            "issue_ids": list(_field(point, "issue_ids", []) or []),
            "affected_ids": list(_field(point, "affected_ids", []) or []),
            "start_s": round(start_s, 3),
            "end_s": round(end_s, 3),
        }
        markers.append(marker)
        if marker["is_active"]:
            active_region = {
                "start_pct": marker["left_pct"],
                "width_pct": marker["width_pct"],
                "start_s": start_s,
                "end_s": end_s,
            }

    for index, segment in enumerate(highlight_segments or [], start=1):
        segment_id = str(_field(segment, "id", f"highlight-{index}"))
        start_s = _time_field(segment, "start_s", "start", 0.0)
        end_s = _time_field(segment, "end_s", "end", start_s)
        if end_s < start_s:
            end_s = start_s
        left_pct = _pct(start_s, timeline_duration)
        end_pct = _pct(end_s, timeline_duration)
        marker = {
            "id": segment_id,
            "stage_id": str(_field(segment, "stage_id", "alignment")),
            "label": "HIGHLIGHT",
            "level": "highlight",
            "lane_id": "highlight",
            "text": str(_field(segment, "text", "")),
            "role": str(_field(segment, "role", "")),
            "left_pct": left_pct,
            "width_pct": round(max(0.0, end_pct - left_pct), 3),
            "is_active": segment_id == active_point_id,
            "status": str(_field(segment, "status", "generated")),
            "severity": str(_field(segment, "severity", "info")),
            "issue_ids": list(_field(segment, "issue_ids", []) or []),
            "affected_ids": list(_field(segment, "affected_ids", []) or []),
            "start_s": round(start_s, 3),
            "end_s": round(end_s, 3),
        }
        markers.append(marker)
        if marker["is_active"]:
            active_region = {
                "start_pct": marker["left_pct"],
                "width_pct": marker["width_pct"],
                "start_s": start_s,
                "end_s": end_s,
            }

    if active_region is None:
        active_region = {"start_pct": 0.0, "width_pct": 0.0, "start_s": 0.0, "end_s": 0.0}

    playhead = {
        "left_pct": active_region["start_pct"],
        "time_s": round(float(active_region["start_s"]), 3),
    }
    active_window = {
        "start_s": round(float(active_region["start_s"]), 3),
        "end_s": round(float(active_region["end_s"]), 3),
        "duration_s": round(max(0.0, float(active_region["end_s"]) - float(active_region["start_s"])), 3),
        "label": f'{float(active_region["start_s"]):.3f}s - {float(active_region["end_s"]):.3f}s',
    }

    return {
        "duration_s": round(timeline_duration, 3),
        "waveform": _waveform(points, timeline_duration, buckets),
        "ruler_ticks": _ruler_ticks(timeline_duration),
        "playhead": playhead,
        "active_window": active_window,
        "markers": markers,
        "lanes": [
            {
                **lane,
                "markers": [marker for marker in markers if marker["lane_id"] == lane["id"]],
            }
            for lane in LANES
        ],
        "active_region": active_region,
    }
