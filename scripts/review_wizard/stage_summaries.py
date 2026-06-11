from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.review_wizard.export_summary import review_export_summary


STAGE_IDS = ("import", "lyrics", "alignment", "quality", "preview", "export")
ASSET_NAMES = ("vocals.wav", "instrumental.wav", "output.mp4", "output.ass", "lyrics.txt")
REVIEWED_STATUSES = {"approved", "edited", "skipped_with_risk"}


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _load_meta(job_dir: Path) -> dict[str, Any]:
    path = job_dir / "meta.json"
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _duration_from_meta(meta: dict[str, Any]) -> float | None:
    duration = meta.get("duration_s", meta.get("duration_seconds"))
    if duration is None:
        return None
    try:
        return float(duration)
    except (TypeError, ValueError):
        return None


def _lyrics_summary(project: Any) -> dict[str, int]:
    prepared_text = _field(project, "prepared_text")
    sections = list(_field(prepared_text, "sections", []) or [])
    lines_count = 0
    words_count = 0

    for section in sections:
        lines = list(_field(section, "lines", []) or [])
        lines_count += len(lines)
        for line in lines:
            words_count += len(list(_field(line, "words", []) or []))

    return {
        "sections": len(sections),
        "lines": lines_count,
        "words": words_count,
    }


def _alignment_summary(review_points: list[Any]) -> dict[str, int]:
    alignment_points = [
        point for point in review_points if str(_field(point, "stage_id", "")) == "alignment"
    ]
    open_count = sum(1 for point in alignment_points if str(_field(point, "status", "open")) == "open")
    reviewed_count = sum(
        1 for point in alignment_points if str(_field(point, "status", "open")) in REVIEWED_STATUSES
    )
    return {
        "total": len(alignment_points),
        "open": open_count,
        "reviewed": reviewed_count,
    }


def _quality_summary(project: Any) -> dict[str, int]:
    open_issues = [
        issue for issue in list(_field(project, "issues", []) or []) if str(_field(issue, "status", "open")) == "open"
    ]
    return {
        "open_issues": len(open_issues),
        "critical": sum(1 for issue in open_issues if str(_field(issue, "severity", "")) == "critical"),
        "high": sum(1 for issue in open_issues if str(_field(issue, "severity", "")) == "high"),
    }


def build_stage_summaries(job_dir: Path, project: Any, review_points: list[Any]) -> dict[str, dict[str, Any]]:
    meta = _load_meta(job_dir)
    export_summary = review_export_summary(review_points)

    return {
        "import": {
            "assets": {name: (job_dir / name).exists() for name in ASSET_NAMES},
            "duration_s": _duration_from_meta(meta),
        },
        "lyrics": _lyrics_summary(project),
        "alignment": _alignment_summary(review_points),
        "quality": _quality_summary(project),
        "preview": {
            "has_full_preview": (job_dir / "preview_full.mp4").exists(),
        },
        "export": export_summary,
    }
