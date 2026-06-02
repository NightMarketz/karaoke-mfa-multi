from __future__ import annotations

from dataclasses import replace
from time import time
from typing import Any

from scripts.review_wizard.contracts import EditOperation, Issue


REVIEW_WIZARD_STEPS = [
    "import",
    "text_review",
    "alignment_processing",
    "quality_review",
    "preview_approval",
    "export",
]

_FINISHED_STATUSES = {"approved", "skipped_with_risk"}


def _require_known_step(step: str) -> None:
    if step not in REVIEW_WIZARD_STEPS:
        raise ValueError(f"Unknown review wizard step: {step}")


def _wizard_steps(project: Any) -> dict[str, dict[str, Any]]:
    return {key: dict(value) for key, value in getattr(project, "wizard_steps", {}).items()}


def _with_step(project: Any, step: str, payload: dict[str, Any]) -> Any:
    steps = _wizard_steps(project)
    steps[step] = payload
    return replace(project, wizard_steps=steps)


def approve_step(project: Any, step: str, approved_by: str) -> Any:
    _require_known_step(step)
    return _with_step(
        project,
        step,
        {
            "status": "approved",
            "approved_by": approved_by,
            "approved_at": time(),
        },
    )


def skip_step_with_risk(project: Any, step: str, skipped_by: str, risk_note: str) -> Any:
    _require_known_step(step)
    if not risk_note.strip():
        raise ValueError("Risk note is required when skipping a review wizard step")
    updated = _with_step(
        project,
        step,
        {
            "status": "skipped_with_risk",
            "skipped_by": skipped_by,
            "skipped_at": time(),
            "risk_note": risk_note,
        },
    )
    issue = Issue(
        id=f"wizard-risk-{step}",
        type="wizard_step_skipped",
        severity="medium",
        perceptual_impact=0.7,
        confidence=1.0,
        priority_score=0.7,
        start_s=0.0,
        end_s=0.0,
        affected_ids=[step],
        suggested_action="preview_before_export",
    )
    return replace(updated, issues=[*getattr(updated, "issues", []), issue])


def next_step(project: Any) -> str | None:
    steps = _wizard_steps(project)
    for step in REVIEW_WIZARD_STEPS:
        if steps.get(step, {}).get("status") not in _FINISHED_STATUSES:
            return step
    return None


def _append_operation(
    project: Any,
    operation: str,
    target_id: str,
    created_by: str,
    details: dict[str, Any],
) -> Any:
    edit = EditOperation(
        id=f"op-{len(getattr(project, 'edit_operations', [])) + 1}",
        operation=operation,
        target_id=target_id,
        created_by=created_by,
        created_at=time(),
        details=details,
    )
    return replace(project, edit_operations=[*getattr(project, "edit_operations", []), edit])


def approve_review_point(project: Any, point_id: str, approved_by: str) -> Any:
    return _append_operation(project, "approve_review_point", point_id, approved_by, {})


def skip_review_point_with_risk(
    project: Any,
    point_id: str,
    skipped_by: str,
    risk_note: str,
) -> Any:
    if not risk_note.strip():
        raise ValueError("Risk note is required when skipping a review point")
    return _append_operation(
        project,
        "skip_review_point_with_risk",
        point_id,
        skipped_by,
        {"risk_note": risk_note.strip()},
    )


def adjust_review_point_timing(
    project: Any,
    point_id: str,
    edited_by: str,
    start_s: float,
    end_s: float,
) -> Any:
    if end_s <= start_s:
        raise ValueError("Review point end_s must be greater than start_s")
    return _append_operation(
        project,
        "adjust_review_point_timing",
        point_id,
        edited_by,
        {"start_s": float(start_s), "end_s": float(end_s)},
    )
