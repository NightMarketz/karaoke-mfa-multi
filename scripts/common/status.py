from __future__ import annotations

import json
import time
from pathlib import Path

from scripts.common.contracts import JobStatus


def read_status(job_dir: Path) -> JobStatus:
    path = job_dir / "status.json"
    if not path.exists():
        return JobStatus(stage="queued", progress=0, error="")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return JobStatus(
            stage=str(data.get("stage", "unknown")),
            progress=int(data.get("progress", 0)),
            error=str(data.get("error", "")),
            updated_at=data.get("updated_at"),
        )
    except Exception:
        return JobStatus(stage="unknown", progress=0, error="")


def write_status(job_dir: Path, stage: str, progress: int, error: str = "") -> None:
    payload = {
        "stage": stage,
        "progress": max(0, min(100, int(progress))),
        "error": error,
        "updated_at": time.time(),
    }
    tmp = job_dir / "status.json.tmp"
    final = job_dir / "status.json"
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(final)
