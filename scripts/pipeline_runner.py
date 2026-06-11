from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]|\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI terminal escape sequences from subprocess output."""
    return _ANSI_RE.sub("", text)

from scripts.common.config import load_app_config
from scripts.common.observability import build_observability_summary, write_event
from scripts.common.status import write_status


SCRIPTS_DIR = Path("scripts")


@dataclass(frozen=True)
class Stage:
    name: str
    command: list[str]
    progress: int
    # Outer watchdog timeout (seconds). Must be >= the script's own internal
    # timeout or the process gets killed before its own error handling fires.
    # Defaults match the longest expected wall-clock time per stage.
    timeout: int = 900


def build_stage_plan(
    job_dir: Path,
    preset: str,
    python_exe: str | None = None,
    scripts_dir: Path = SCRIPTS_DIR,
) -> list[Stage]:
    py = python_exe or sys.executable
    lyrics_path = job_dir / "lyrics.txt"

    # Load per-stage timeouts from config so the watchdog never fires before
    # the script's own internal timeout (e.g. demucs = 1800s > default 900s).
    cfg = load_app_config()
    # Add a buffer so the script's error handling runs before we hard-kill it.
    _BUFFER_S = 60
    demix_timeout   = cfg.demucs_timeout_s + _BUFFER_S
    align_timeout   = cfg.align_hubertfa_timeout_s + _BUFFER_S
    analyze_timeout  = cfg.ollama_timeout_s + _BUFFER_S
    generate_timeout = cfg.generate_ass_timeout_s + _BUFFER_S
    validate_timeout = cfg.validate_timeout_s + _BUFFER_S

    if lyrics_path.exists():
        stages = [
            Stage(
                "aligning_lyrics",
                [
                    py,
                    str(scripts_dir / "s03b_lyrics_align.py"),
                    "--job-dir",
                    str(job_dir),
                    "--lyrics",
                    str(lyrics_path),
                ],
                5,
                timeout=align_timeout,
            )
        ]
    else:
        stages = [
            Stage(
                "transcribing",
                [py, str(scripts_dir / "s03_transcribe.py"), "--job-dir", str(job_dir)],
                5,
                timeout=600 + _BUFFER_S,
            )
        ]

    stages.extend(
        [
            Stage(
                "aligning",
                [py, str(scripts_dir / "s04_align.py"), "--job-dir", str(job_dir)],
                25,
                timeout=align_timeout,
            ),
            Stage(
                "analyzing",
                [py, str(scripts_dir / "s05_analyze.py"), "--job-dir", str(job_dir)],
                50,
                timeout=analyze_timeout,
            ),
            Stage(
                "generating",
                [
                    py,
                    str(scripts_dir / "s06_generate_ass.py"),
                    "--job-dir",
                    str(job_dir),
                    "--preset",
                    preset,
                ],
                70,
                timeout=generate_timeout,
            ),
            Stage(
                "rendering",
                [py, str(scripts_dir / "s07_output.py"), "--job-dir", str(job_dir)],
                85,
                timeout=cfg.output_ffmpeg_timeout_s + _BUFFER_S,
            ),
            Stage(
                "validating",
                [
                    py,
                    str(scripts_dir / "s08_validate.py"),
                    "--job-dir",
                    str(job_dir),
                    "--overlap-tolerance",
                    str(cfg.validate_overlap_tolerance_s),
                ],
                95,
                timeout=validate_timeout,
            ),
        ]
    )
    return stages

class PipelineRunner:
    def __init__(
        self,
        job_dir: Path,
        python_exe: str | None = None,
        preset: str = "cyberpunk",
        running_registry: dict[str, object] | None = None,
        job_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.job_dir = job_dir
        self.python_exe = python_exe or sys.executable
        self.preset = preset
        self.running_registry = running_registry
        self.job_id = job_id
        self.run_id = run_id or f"run-{uuid4().hex}"

    def run_command(
        self,
        command: list[str],
        stage_name: str,
        progress: int,
        timeout: int = 900,
    ) -> bool:
        self._write_status(stage_name, progress)
        started_at = time.perf_counter()
        write_event(
            self.job_dir,
            "stage_command_started",
            stage_name,
            details={
                "command": _sanitize_command(command),
                "timeout": timeout,
                "progress": progress,
                "run_id": self.run_id,
            },
        )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            write_event(
                self.job_dir,
                "stage_timeout",
                stage_name,
                level="error",
                message=f"{stage_name} timed out after {timeout}s",
                duration_ms=duration_ms,
                details={"timeout": timeout, "progress": progress, "run_id": self.run_id},
            )
            self._write_status("failed", progress, f"{stage_name} timed out after {timeout}s")
            return False
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            write_event(
                self.job_dir,
                "stage_failed",
                stage_name,
                level="error",
                message=str(exc),
                duration_ms=duration_ms,
                details={"progress": progress, "exception_type": type(exc).__name__, "run_id": self.run_id},
            )
            self._write_status("failed", progress, str(exc))
            return False

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        write_event(
            self.job_dir,
            "stage_command_finished",
            stage_name,
            level="info" if result.returncode == 0 else "error",
            message=f"return code {result.returncode}",
            duration_ms=duration_ms,
            details={"returncode": result.returncode, "progress": progress, "run_id": self.run_id},
        )
        if result.returncode != 0:
            output = _strip_ansi((result.stderr or result.stdout or "unknown error"))[-1200:]
            write_event(
                self.job_dir,
                "stage_failed",
                stage_name,
                level="error",
                message=output,
                duration_ms=duration_ms,
                details={"returncode": result.returncode, "output_tail": output, "run_id": self.run_id},
            )
            self._write_status("failed", progress, output)
            return False
        return True

    def run(self) -> bool:
        try:
            self._write_status("running", 1)
            stages = build_stage_plan(self.job_dir, self.preset, self.python_exe)
            write_event(
                self.job_dir,
                "pipeline_started",
                "running",
                details={"stage_names": [stage.name for stage in stages], "run_id": self.run_id},
            )
            for stage in stages:
                self._invalidate_before_stage(stage.name)
                if not self.run_command(stage.command, stage.name, stage.progress, timeout=stage.timeout):
                    write_event(
                        self.job_dir,
                        "pipeline_finished",
                        "failed",
                        level="error",
                        message=f"{stage.name} failed",
                        details={"run_id": self.run_id},
                    )
                    build_observability_summary(self.job_dir)
                    return False
            self._write_status("done", 100)
            write_event(
                self.job_dir,
                "pipeline_finished",
                "done",
                message="pipeline complete",
                details={"run_id": self.run_id},
            )
            build_observability_summary(self.job_dir)
            return True
        finally:
            if self.running_registry is not None and self.job_id:
                self.running_registry.pop(self.job_id, None)
                write_event(
                    self.job_dir,
                    "running_registry_cleanup",
                    "done",
                    details={"job_id": self.job_id, "run_id": self.run_id},
                )
                build_observability_summary(self.job_dir)

    def _write_status(self, stage: str, progress: int, error: str = "") -> None:
        write_status(self.job_dir, stage, progress, error)
        status_path = self.job_dir / "status.json"
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["run_id"] = self.run_id
        tmp = self.job_dir / "status.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(status_path)

    def _invalidate_before_stage(self, stage_name: str) -> None:
        targets = _INVALIDATION_TARGETS.get(stage_name)
        if not targets:
            return

        deleted: list[str] = []
        for artifact_name in targets:
            artifact_path = self.job_dir / artifact_name
            if artifact_path.exists() and artifact_path.is_file():
                artifact_path.unlink()
                deleted.append(artifact_name)

        if deleted:
            write_event(
                self.job_dir,
                "downstream_artifacts_invalidated",
                stage_name,
                details={
                    "run_id": self.run_id,
                    "stage": stage_name,
                    "deleted_artifacts": deleted,
                },
            )


def _sanitize_command(command: list[str]) -> list[str]:
    sanitized: list[str] = []
    for index, part in enumerate(command):
        if index == 0:
            sanitized.append(Path(part).name)
        elif part.endswith(".py") or "\\" in part or "/" in part:
            sanitized.append(Path(part).name)
        else:
            sanitized.append(part)
    return sanitized


_INVALIDATION_TARGETS = {
    "analyzing": (
        "analysis.json",
        "output.ass",
        "output.ass.manifest.json",
        "output.mp4",
        "output.mp4.manifest.json",
        "preview_full.mp4",
        "preview_full.manifest.json",
    ),
    "generating": (
        "output.ass",
        "output.ass.manifest.json",
        "output.mp4",
        "output.mp4.manifest.json",
        "preview_full.mp4",
        "preview_full.manifest.json",
    ),
    "rendering": (
        "output.mp4",
        "output.mp4.manifest.json",
        "preview_full.mp4",
        "preview_full.manifest.json",
    ),
}
