from __future__ import annotations

from dataclasses import dataclass, replace
from time import time
from typing import Any

from scripts.review_wizard.contracts import Project


ALLOWED_PREVIEW_SCOPES = {"critical_snippets", "full_preview"}
REQUIRED_PREVIEW_EVIDENCE_FIELDS = (
    "artifact_path",
    "artifact_sha256",
    "artifact_size_bytes",
    "take_id",
    "quality_report_id",
    "quality_status",
)


@dataclass(frozen=True)
class ExportDecision:
    allowed: bool
    reason: str


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _latest_report(project: Project) -> Any | None:
    if not project.quality_reports:
        return None
    return project.quality_reports[-1]


def _latest_report_status(project: Project) -> str:
    report = _latest_report(project)
    if report is None:
        return "review_suggested"
    return str(_field(report, "status", "review_suggested"))


def _validate_preview_evidence(scope: str, evidence: dict[str, Any]) -> None:
    for field in REQUIRED_PREVIEW_EVIDENCE_FIELDS:
        if not evidence.get(field):
            raise ValueError(f"preview evidence missing: {field}")
    if int(evidence.get("artifact_size_bytes", 0)) <= 0:
        raise ValueError("preview evidence artifact_size_bytes must be positive")
    if evidence.get("scope") not in (None, scope):
        raise ValueError("preview evidence scope mismatch")


def approve_preview(
    project: Project,
    approved_by: str,
    scope: str,
    evidence: dict[str, Any] | None = None,
) -> Project:
    if scope not in ALLOWED_PREVIEW_SCOPES:
        raise ValueError(f"invalid preview scope: {scope}")
    evidence = dict(evidence or {})
    _validate_preview_evidence(scope, evidence)

    render = {
        "id": f"preview-{len(project.preview_renders) + 1}",
        "scope": scope,
        "approved": True,
        "approved_by": approved_by,
        "approved_at": time(),
        **evidence,
    }
    return replace(project, preview_renders=[*project.preview_renders, render])


def _is_auditable_for_latest_report(render: dict[str, Any], project: Project) -> bool:
    report = _latest_report(project)
    if report is None:
        return False
    if not render.get("approved"):
        return False
    if render.get("quality_report_id") != _field(report, "id"):
        return False
    if render.get("take_id") != _field(report, "take_id"):
        return False
    if render.get("quality_status") != _field(report, "status"):
        return False
    try:
        _validate_preview_evidence(str(render.get("scope")), render)
    except ValueError:
        return False
    return True


def can_export_final(project: Project) -> ExportDecision:
    if not project.quality_reports:
        return ExportDecision(allowed=False, reason="quality_review_required")

    status = _latest_report_status(project)
    if status == "ready":
        return ExportDecision(allowed=True, reason="ready")

    full_preview_approved = any(
        render.get("approved") and render.get("scope") == "full_preview"
        and _is_auditable_for_latest_report(render, project)
        for render in project.preview_renders
    )
    partial_preview_approved = any(
        render.get("approved") and render.get("scope") == "critical_snippets"
        and _is_auditable_for_latest_report(render, project)
        for render in project.preview_renders
    )
    if status == "needs_fix" and not full_preview_approved:
        if partial_preview_approved:
            return ExportDecision(allowed=False, reason="full_preview_required")
        return ExportDecision(allowed=False, reason="preview_required")
    if full_preview_approved:
        return ExportDecision(allowed=True, reason="full_preview_approved_with_risk")

    return ExportDecision(allowed=True, reason="review_suggested")
