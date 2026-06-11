from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewStage:
    id: str
    label: str
    description: str


REVIEW_STAGES = [
    ReviewStage("import", "Import", "Audio assets, stems, lyrics source, and pipeline inputs."),
    ReviewStage("lyrics", "Lyrics", "Original and prepared lyric structure."),
    ReviewStage("alignment", "Alignment", "Line, word, syllable, and melisma timing."),
    ReviewStage("quality", "Quality", "Prioritized issues and focused timestamp checks."),
    ReviewStage("preview", "Preview", "Snippet and full-song preview approval."),
    ReviewStage("export", "Export", "ASS/MP4 readiness and remaining risk summary."),
]

_STAGE_IDS = {stage.id for stage in REVIEW_STAGES}
_STEP_TO_STAGE = {
    "import": "import",
    "text_review": "lyrics",
    "alignment_processing": "alignment",
    "quality_review": "quality",
    "preview_approval": "preview",
    "export": "export",
}
_STAGE_TO_STEP = {stage: step for step, stage in _STEP_TO_STAGE.items()}
_FINISHED_STATUSES = {"approved", "skipped_with_risk"}


def active_stage_id(project: Any, requested_stage: str | None = None) -> str:
    if requested_stage in _STAGE_IDS:
        return str(requested_stage)

    steps = getattr(project, "wizard_steps", {}) or {}
    for stage in REVIEW_STAGES:
        step_id = _STAGE_TO_STEP[stage.id]
        if steps.get(step_id, {}).get("status") not in _FINISHED_STATUSES:
            return stage.id
    return "export"


def stage_status(project: Any, stage_id: str) -> str:
    step_id = _STAGE_TO_STEP[stage_id]
    payload = (getattr(project, "wizard_steps", {}) or {}).get(step_id, {})
    return str(payload.get("status", "needs_review"))


def _display_status(status: str) -> str:
    labels = {
        "needs_review": "REVIEW REQUIRED",
        "approved": "APPROVED",
        "skipped_with_risk": "RISK ACCEPTED",
    }
    return labels.get(status, status.replace("_", " ").upper())


def _display_meta(stage_id: str, total: int, open_count: int) -> str:
    if total == 0:
        labels = {
            "import": "ASSETS CHECK",
            "lyrics": "TEXT REVIEW",
            "quality": "NO OPEN ISSUES",
            "preview": "APPROVAL GATE",
            "export": "FINAL CHECK",
        }
        return labels.get(stage_id, "NO REVIEW POINTS")
    reviewed = total - open_count
    if open_count == 0:
        return f"{reviewed} REVIEWED"
    return f"{open_count} OPEN OF {total}"


def _field(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        return value.get(field_name)
    return getattr(value, field_name, None)


def stage_view_models(
    project: Any, active_stage: str, review_points: list[Any]
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    open_counts: dict[str, int] = {}

    for point in review_points:
        stage_id = _field(point, "stage_id")
        if not stage_id:
            continue
        counts[stage_id] = counts.get(stage_id, 0) + 1
        if _field(point, "status") == "open":
            open_counts[stage_id] = open_counts.get(stage_id, 0) + 1

    view_models = []
    for stage in REVIEW_STAGES:
        status = stage_status(project, stage.id)
        total = counts.get(stage.id, 0)
        open_count = open_counts.get(stage.id, 0)
        view_models.append(
            {
                "id": stage.id,
                "label": stage.label,
                "description": stage.description,
                "status": status,
                "display_status": _display_status(status),
                "display_meta": _display_meta(stage.id, total, open_count),
                "active": stage.id == active_stage,
                "review_point_count": total,
                "open_review_point_count": open_count,
            }
        )
    return view_models
