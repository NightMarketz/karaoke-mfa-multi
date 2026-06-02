from __future__ import annotations

from dataclasses import replace
from time import time
from typing import Any

from scripts.review_wizard.contracts import AlignmentTake, EditOperation, Project


def create_aggressive_candidate(
    project: Project,
    parent_take_id: str,
    selected_range: tuple[float, float],
) -> Project:
    if not any(take.id == parent_take_id for take in project.alignment_takes):
        raise ValueError(f"Unknown parent take: {parent_take_id}")

    candidate = AlignmentTake(
        id=f"{parent_take_id}-aggressive-{len(project.alignment_takes) + 1}",
        kind="aggressive_candidate",
        status="needs_review",
        line_ids=[],
        parent_take_id=parent_take_id,
    )
    operation = EditOperation(
        id=f"op-aggressive-{len(project.edit_operations) + 1}",
        operation="create_aggressive_candidate",
        target_id=parent_take_id,
        created_by="system",
        details={
            "start_s": selected_range[0],
            "end_s": selected_range[1],
            "candidate_take_id": candidate.id,
        },
        created_at=time(),
    )

    return replace(
        project,
        alignment_takes=[*project.alignment_takes, candidate],
        edit_operations=[*project.edit_operations, operation],
    )


def add_edit_operation(
    project: Project,
    operation: str,
    target_id: str,
    created_by: str,
    details: dict[str, Any],
) -> Project:
    edit = EditOperation(
        id=f"op-{len(project.edit_operations) + 1}",
        operation=operation,
        target_id=target_id,
        created_by=created_by,
        details=details,
        created_at=time(),
    )
    return project.with_edit_operation(edit)


def promote_take(project: Project, take_id: str) -> Project:
    if not any(take.id == take_id for take in project.alignment_takes):
        raise ValueError(f"Unknown take: {take_id}")
    return replace(project, approved_take_id=take_id)
