from __future__ import annotations

from dataclasses import replace
from time import time

from scripts.review_wizard.contracts import EditOperation, Issue, Project


def _find_open_issue(project: Project, issue_id: str) -> Issue:
    for issue in project.issues:
        if issue.id == issue_id:
            if issue.status != "open":
                raise ValueError(f"Issue is not open: {issue_id}")
            return issue
    raise ValueError(f"Unknown issue: {issue_id}")


def _replace_issue(project: Project, updated_issue: Issue, operation: EditOperation) -> Project:
    issues = [updated_issue if issue.id == updated_issue.id else issue for issue in project.issues]
    return replace(project, issues=issues, edit_operations=[*project.edit_operations, operation])


def approve_issue_risk(project: Project, issue_id: str, approved_by: str, reason: str) -> Project:
    if not reason.strip():
        raise ValueError("Risk approval requires a reason.")
    issue = _find_open_issue(project, issue_id)
    operation = EditOperation(
        id=f"op-{len(project.edit_operations) + 1}",
        operation="approve_issue_risk",
        target_id=issue_id,
        created_by=approved_by,
        created_at=time(),
        details={"reason": reason.strip(), "issue_type": issue.type},
    )
    return _replace_issue(project, replace(issue, status="risk_approved"), operation)


def apply_issue_suggestion(project: Project, issue_id: str, applied_by: str) -> Project:
    issue = _find_open_issue(project, issue_id)
    operation = EditOperation(
        id=f"op-{len(project.edit_operations) + 1}",
        operation="apply_issue_suggestion",
        target_id=issue_id,
        created_by=applied_by,
        created_at=time(),
        details={"suggested_action": issue.suggested_action, "issue_type": issue.type},
    )
    return _replace_issue(project, replace(issue, status="suggestion_applied"), operation)
