from __future__ import annotations

import json
from pathlib import Path

from scripts.review_wizard.contracts import Project


def project_path(job_dir: Path) -> Path:
    return job_dir / "review_wizard.json"


def save_project(job_dir: Path, project: Project) -> None:
    tmp = job_dir / "review_wizard.json.tmp"
    tmp.write_text(
        json.dumps(project.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(project_path(job_dir))


def load_project(job_dir: Path) -> Project:
    return Project.from_dict(json.loads(project_path(job_dir).read_text(encoding="utf-8")))
