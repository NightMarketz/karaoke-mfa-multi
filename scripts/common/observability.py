from __future__ import annotations

import json
import time
from pathlib import Path
from types import TracebackType
from typing import Any


EVENTS_FILE = "events.jsonl"
SUMMARY_FILE = "observability_summary.json"


def _job_id(job_dir: Path) -> str:
    meta_path = job_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("job_id"):
                return str(meta["job_id"])
        except Exception:
            pass
    return job_dir.name


def write_event(
    job_dir: Path,
    event: str,
    stage: str,
    level: str = "info",
    message: str = "",
    details: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    artifact: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": _job_id(job_dir),
        "timestamp": time.time(),
        "event": event,
        "stage": stage,
        "level": level,
        "message": message,
        "details": details or {},
    }
    if duration_ms is not None:
        payload["duration_ms"] = max(0, int(duration_ms))
    if artifact is not None:
        payload["artifact"] = artifact

    job_dir.mkdir(parents=True, exist_ok=True)
    with (job_dir / EVENTS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return payload


def read_events(job_dir: Path) -> list[dict[str, Any]]:
    path = job_dir / EVENTS_FILE
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            events.append(loaded)
    return events


class StageTimer:
    def __init__(
        self,
        job_dir: Path,
        stage: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.job_dir = job_dir
        self.stage = stage
        self.message = message
        self.details = details or {}
        self.started_at = 0.0

    def __enter__(self) -> "StageTimer":
        self.started_at = time.perf_counter()
        write_event(
            self.job_dir,
            "stage_started",
            self.stage,
            message=self.message,
            details=self.details,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        duration_ms = int((time.perf_counter() - self.started_at) * 1000)
        if exc is None:
            write_event(
                self.job_dir,
                "stage_finished",
                self.stage,
                duration_ms=duration_ms,
                details=self.details,
            )
            return False

        write_event(
            self.job_dir,
            "stage_failed",
            self.stage,
            level="error",
            message=str(exc),
            duration_ms=duration_ms,
            details={**self.details, "exception_type": exc_type.__name__ if exc_type else ""},
        )
        return False


def record_artifact(job_dir: Path, stage: str, path: Path, required: bool = True) -> dict[str, Any]:
    exists = path.exists()
    details: dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "exists": exists,
        "required": required,
        "size_bytes": path.stat().st_size if exists and path.is_file() else 0,
    }
    level = "info" if exists or not required else "error"
    event = "artifact_recorded" if exists else "artifact_missing"
    message = f"{path.name} {'exists' if exists else 'missing'}"
    write_event(
        job_dir,
        event,
        stage,
        level=level,
        message=message,
        details=details,
        artifact=path.name,
    )
    return details


def build_observability_summary(job_dir: Path) -> dict[str, Any]:
    events = read_events(job_dir)
    failures = [
        {
            "event": event.get("event"),
            "stage": event.get("stage"),
            "message": event.get("message", ""),
            "details": event.get("details", {}),
        }
        for event in events
        if event.get("level") == "error" and event.get("event") != "stage_command_finished"
    ]
    warnings = [
        {
            "event": event.get("event"),
            "stage": event.get("stage"),
            "message": event.get("message", ""),
            "details": event.get("details", {}),
        }
        for event in events
        if event.get("level") == "warning"
    ]

    artifacts: dict[str, Any] = {}
    durations: dict[str, int] = {}
    for event in events:
        artifact = event.get("artifact")
        if artifact:
            artifacts[str(artifact)] = event.get("details", {})
        if event.get("event") in {"stage_finished", "stage_command_finished"} and "duration_ms" in event:
            durations[str(event.get("stage", "unknown"))] = int(event["duration_ms"])

    summary = {
        "job_id": _job_id(job_dir),
        "total_events": len(events),
        "latest_event": events[-1] if events else None,
        "failures": failures,
        "warnings": warnings,
        "artifacts": artifacts,
        "stage_durations_ms": durations,
    }
    (job_dir / SUMMARY_FILE).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary
