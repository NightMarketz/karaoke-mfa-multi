from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReviewPoint:
    id: str
    stage_id: str
    level: str
    text: str
    start_s: float
    end_s: float
    parent_id: str | None = None
    source: str = "analysis"
    status: str = "open"
    priority: float = 0.0
    issue_ids: list[str] = field(default_factory=list)
    severity: str = "info"
    affected_ids: list[str] = field(default_factory=list)
    suggested_action: str = ""

    @property
    def duration_s(self) -> float:
        return round(max(0.0, self.end_s - self.start_s), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage_id": self.stage_id,
            "level": self.level,
            "text": self.text,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "duration_s": self.duration_s,
            "parent_id": self.parent_id,
            "source": self.source,
            "status": self.status,
            "priority": self.priority,
            "issue_ids": list(self.issue_ids),
            "severity": self.severity,
            "affected_ids": list(self.affected_ids),
            "suggested_action": self.suggested_action,
        }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _review_status(project: Any, point_id: str) -> str:
    for operation in reversed(getattr(project, "edit_operations", [])):
        if getattr(operation, "target_id", "") != point_id:
            continue
        operation_name = getattr(operation, "operation", "")
        if operation_name == "approve_review_point":
            return "approved"
        if operation_name == "skip_review_point_with_risk":
            return "skipped_with_risk"
        if operation_name == "adjust_review_point_timing":
            return "edited"
    return "open"


def _timing_override(project: Any, point_id: str) -> dict[str, float] | None:
    for operation in reversed(getattr(project, "edit_operations", [])):
        if getattr(operation, "target_id", "") != point_id:
            continue
        if getattr(operation, "operation", "") != "adjust_review_point_timing":
            continue
        details = getattr(operation, "details", {})
        try:
            start_s = float(details["start_s"])
            end_s = float(details["end_s"])
        except (KeyError, TypeError, ValueError):
            return None
        return {"start_s": start_s, "end_s": end_s}
    return None


def _apply_timing_edits(points: list[ReviewPoint], project: Any) -> list[ReviewPoint]:
    edited: list[ReviewPoint] = []
    for point in points:
        override = _timing_override(project, point.id)
        if override is None:
            edited.append(point)
            continue
        edited.append(replace(point, start_s=override["start_s"], end_s=override["end_s"]))
    return edited


def _issue_overlaps_point(issue: Any, point: ReviewPoint) -> bool:
    affected_ids = getattr(issue, "affected_ids", [])
    if point.id in affected_ids:
        return True
    return float(getattr(issue, "start_s", 0.0)) <= point.end_s and float(getattr(issue, "end_s", 0.0)) >= point.start_s


def _decorate_with_issues(points: list[ReviewPoint], project: Any) -> list[ReviewPoint]:
    decorated: list[ReviewPoint] = []
    for point in points:
        matching = [
            issue
            for issue in getattr(project, "issues", [])
            if getattr(issue, "status", "open") == "open" and _issue_overlaps_point(issue, point)
        ]
        if not matching:
            decorated.append(point)
            continue

        matching.sort(key=lambda issue: float(getattr(issue, "priority_score", 0.0)), reverse=True)
        top_issue = matching[0]
        decorated.append(
            replace(
                point,
                priority=max(point.priority, float(getattr(top_issue, "priority_score", 0.0))),
                issue_ids=[str(getattr(issue, "id", "")) for issue in matching],
                severity=str(getattr(top_issue, "severity", "info")),
                affected_ids=list(getattr(top_issue, "affected_ids", [])),
                suggested_action=str(getattr(top_issue, "suggested_action", "")),
            )
        )
    return decorated


def _readable_issue_text(issue: Any) -> str:
    issue_type = str(getattr(issue, "type", "")).replace("_", " ").strip()
    suggested_action = str(getattr(issue, "suggested_action", "")).replace("_", " ").strip()
    if issue_type and suggested_action:
        return f"{issue_type}: {suggested_action}"
    return issue_type or suggested_action


def _has_valid_issue_timestamp(issue: Any) -> bool:
    try:
        start_s = float(getattr(issue, "start_s", 0.0))
        end_s = float(getattr(issue, "end_s", 0.0))
    except (TypeError, ValueError):
        return False
    return end_s > start_s


def _quality_issue_points(project: Any) -> list[ReviewPoint]:
    points: list[ReviewPoint] = []
    for issue in getattr(project, "issues", []):
        if getattr(issue, "status", "open") != "open" or not _has_valid_issue_timestamp(issue):
            continue
        issue_id = str(getattr(issue, "id", ""))
        point_id = f"issue:{issue_id}"
        points.append(
            ReviewPoint(
                id=point_id,
                stage_id="quality",
                level="issue",
                text=_readable_issue_text(issue),
                start_s=float(getattr(issue, "start_s")),
                end_s=float(getattr(issue, "end_s")),
                source="issue",
                status=_review_status(project, point_id),
                priority=float(getattr(issue, "priority_score", 0.0)),
                issue_ids=[issue_id],
                severity=str(getattr(issue, "severity", "info")),
                affected_ids=list(getattr(issue, "affected_ids", [])),
                suggested_action=str(getattr(issue, "suggested_action", "")),
            )
        )
    return points


def build_review_points(job_dir: Path, project: Any) -> list[ReviewPoint]:
    analysis = _load_json(job_dir / "analysis.json")
    aligned = _load_json(job_dir / "aligned.json")
    aligned_words = aligned.get("words", [])
    if not isinstance(aligned_words, list):
        aligned_words = []
    points: list[ReviewPoint] = []

    for line_index, line in enumerate(analysis.get("lines", []), start=1):
        if "start" not in line or "end" not in line:
            continue
        line_id = f"line-{line_index}"
        points.append(
            ReviewPoint(
                id=line_id,
                stage_id="alignment",
                level="line",
                text=str(line.get("text", "")),
                start_s=float(line["start"]),
                end_s=float(line["end"]),
                priority=0.2,
                status=_review_status(project, line_id),
            )
        )

        words = line.get("words", [])
        word_source = "analysis"
        if not words:
            words = [
                word
                for word in aligned_words
                if "start" in word
                and "end" in word
                and float(word["start"]) >= float(line["start"])
                and float(word["end"]) <= float(line["end"])
            ]
            word_source = "aligned"

        for word_index, word in enumerate(words, start=1):
            if "start" not in word or "end" not in word:
                continue
            word_id = f"{line_id}:word-{word_index}"
            points.append(
                ReviewPoint(
                    id=word_id,
                    stage_id="alignment",
                    level="word",
                    text=str(word.get("word", "")),
                    start_s=float(word["start"]),
                    end_s=float(word["end"]),
                    parent_id=line_id,
                    source=word_source,
                    priority=0.1,
                    status=_review_status(project, word_id),
                )
            )

    decorated_points = _decorate_with_issues(points, project)
    return _apply_timing_edits(decorated_points + _quality_issue_points(project), project)


def points_for_stage(points: list[ReviewPoint], stage_id: str) -> list[ReviewPoint]:
    return [point for point in points if point.stage_id == stage_id]


def filtered_review_points(
    points: list[ReviewPoint],
    stage_id: str,
    status_filter: str = "all",
    level_filter: str = "all",
) -> list[ReviewPoint]:
    status_filter = status_filter if status_filter in {"all", "open", "reviewed"} else "all"
    level_filter = level_filter if level_filter in {"all", "line", "word", "issue"} else "all"
    filtered = points_for_stage(points, stage_id)
    if status_filter == "open":
        filtered = [point for point in filtered if point.status == "open"]
    elif status_filter == "reviewed":
        filtered = [point for point in filtered if point.status != "open"]
    if level_filter != "all":
        filtered = [point for point in filtered if point.level == level_filter]
    return filtered


def next_open_point(points: list[ReviewPoint], stage_id: str) -> ReviewPoint | None:
    candidates = [point for point in points if point.stage_id == stage_id and point.status == "open"]
    if not candidates:
        return None
    return sorted(candidates, key=lambda point: (-point.priority, point.start_s, point.id))[0]


def next_open_point_after(points: list[ReviewPoint], active_point_id: str | None) -> ReviewPoint | None:
    if not points:
        return None
    active_index = -1
    if active_point_id:
        for index, point in enumerate(points):
            if point.id == active_point_id:
                active_index = index
                break
    ordered = points[active_index + 1 :] + points[: active_index + 1]
    return next((point for point in ordered if point.status == "open"), None)


def point_navigation(points: list[ReviewPoint], active_point_id: str | None) -> dict[str, Any]:
    if not points:
        return {
            "position": 0,
            "total": 0,
            "previous_id": None,
            "next_id": None,
            "next_open_id": None,
        }
    active_index = 0
    if active_point_id:
        for index, point in enumerate(points):
            if point.id == active_point_id:
                active_index = index
                break
    next_open = next_open_point_after(points, points[active_index].id)
    return {
        "position": active_index + 1,
        "total": len(points),
        "previous_id": points[active_index - 1].id if active_index > 0 else None,
        "next_id": points[active_index + 1].id if active_index + 1 < len(points) else None,
        "next_open_id": next_open.id if next_open else None,
    }


def review_point_window(
    points: list[ReviewPoint],
    active_point_id: str | None,
    window_size: int = 12,
) -> dict[str, Any]:
    if not points:
        return {
            "items": [],
            "start": 0,
            "end": 0,
            "total": 0,
            "has_previous": False,
            "has_next": False,
        }
    window_size = max(1, window_size)
    active_index = 0
    if active_point_id:
        for index, point in enumerate(points):
            if point.id == active_point_id:
                active_index = index
                break
    half_window = window_size // 2
    start_index = max(0, active_index - half_window)
    end_index = min(len(points), start_index + window_size)
    start_index = max(0, end_index - window_size)
    return {
        "items": points[start_index:end_index],
        "start": start_index + 1,
        "end": end_index,
        "total": len(points),
        "has_previous": start_index > 0,
        "has_next": end_index < len(points),
    }
