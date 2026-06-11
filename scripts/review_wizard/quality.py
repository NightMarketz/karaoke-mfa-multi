from __future__ import annotations

from dataclasses import replace

from scripts.review_wizard.contracts import Issue


SEVERITY_WEIGHT = {
    "low": 0.1,
    "medium": 0.2,
    "high": 0.3,
    "critical": 0.4,
}


def _priority(issue: Issue) -> float:
    duration = max(0.0, issue.end_s - issue.start_s)
    duration_weight = min(duration / 10.0, 0.15)
    uncertainty_weight = (1.0 - issue.confidence) * 0.15
    severity_weight = SEVERITY_WEIGHT.get(issue.severity, 0.2)
    return round(
        min(
            1.0,
            issue.perceptual_impact * 0.6
            + severity_weight
            + uncertainty_weight
            + duration_weight,
        ),
        4,
    )


def prioritize_issues(issues: list[Issue]) -> list[Issue]:
    scored = [replace(issue, priority_score=_priority(issue)) for issue in issues]
    return sorted(scored, key=lambda item: item.priority_score, reverse=True)


def quality_status(score: float, critical_open_issues: int) -> str:
    if critical_open_issues > 0:
        return "needs_fix"
    if score >= 0.95:
        return "ready"
    if score >= 0.85:
        return "review_suggested"
    return "needs_fix"
