from __future__ import annotations

from typing import Any


_EMPTY_STAGE = {
    "total": 0,
    "approved": 0,
    "pending": 0,
    "risk_accepted": 0,
    "edited": 0,
}


def _field(point: Any, name: str) -> Any:
    if isinstance(point, dict):
        return point.get(name)
    return getattr(point, name, None)


def _stage_bucket(summary: dict[str, Any], stage_id: str) -> dict[str, int]:
    by_stage = summary["by_stage"]
    if stage_id not in by_stage:
        by_stage[stage_id] = dict(_EMPTY_STAGE)
    return by_stage[stage_id]


def review_export_summary(points: list[Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total": len(points),
        "approved": 0,
        "pending": 0,
        "risk_accepted": 0,
        "edited": 0,
        "by_stage": {},
    }

    for point in points:
        stage_id = str(_field(point, "stage_id") or "unknown")
        status = str(_field(point, "status") or "open")
        stage = _stage_bucket(summary, stage_id)
        stage["total"] += 1

        if status == "approved":
            summary["approved"] += 1
            stage["approved"] += 1
        elif status == "skipped_with_risk":
            summary["risk_accepted"] += 1
            stage["risk_accepted"] += 1
        elif status == "edited":
            summary["edited"] += 1
            stage["edited"] += 1
        else:
            summary["pending"] += 1
            stage["pending"] += 1

    return summary
