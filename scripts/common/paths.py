from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

JOB_ID_RE = re.compile(r"^[a-fA-F0-9]{12}$")


def validate_job_id(job_id: str) -> bool:
    return bool(JOB_ID_RE.fullmatch(job_id or ""))


def is_safe_archive_member(name: str) -> bool:
    if not name:
        return False
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute():
        return False
    return ".." not in path.parts


def resolve_job_dir(jobs_dir: Path, job_id: str) -> Path:
    if not validate_job_id(job_id):
        raise ValueError(f"Invalid job id: {job_id!r}")

    root = jobs_dir.resolve()
    job_dir = (root / job_id).resolve()
    try:
        job_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Job path escapes jobs dir: {job_id!r}") from exc
    return job_dir
