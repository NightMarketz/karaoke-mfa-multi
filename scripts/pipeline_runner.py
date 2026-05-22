from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from scripts.common.observability import build_observability_summary, write_event
from scripts.common.status import write_status


SCRIPTS_DIR = Path("scripts")


@dataclass(frozen=True)
class Stage:
    name: str
    command: list[str]
    progress: int


def build_stage_plan(
    job_dir: Path,
    preset: str,
    python_exe: str | None = None,
    scripts_dir: Path = SCRIPTS_DIR,
) -> list[Stage]:
    py = python_exe or sys.executable
    lyrics_path = job_dir / "lyrics.txt"

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
            )
        ]
    else:
        stages = [
            Stage(
                "transcribing",
                [py, str(scripts_dir / "s03_transcribe.py"), "--job-dir", str(job_dir)],
                5,
            )
        ]

    stages.extend(
        [
            Stage("aligning", [py, str(scripts_dir / "s04_align.py"), "--job-dir", str(job_dir)], 25),
            Stage("analyzing", [py, str(scripts_dir / "s05_analyze.py"), "--job-dir", str(job_dir)], 50),
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
            ),
            Stage("rendering", [py, str(scripts_dir / "s07_output.py"), "--job-dir", str(job_dir)], 85),
            Stage(
                "validating",
                [py, str(scripts_dir / "s08_validate.py"), "--job-dir", str(job_dir)],
                95,
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
    ) -> None:
        self.job_dir = job_dir
        self.python_exe = python_exe or sys.executable
        self.preset = preset
        self.running_registry = running_registry
        self.job_id = job_id

    def run_command(
        self,
        command: list[str],
        stage_name: str,
        progress: int,
        timeout: int = 900,
    ) -> bool:
        write_status(self.job_dir, stage_name, progress)
        started_at = time.perf_counter()
        write_event(
            self.job_dir,
            "stage_command_started",
            stage_name,
            details={
                "command": _sanitize_command(command),
                "timeout": timeout,
                "progress": progress,
            },
        )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
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
                details={"timeout": timeout, "progress": progress},
            )
            write_status(self.job_dir, "failed", progress, f"{stage_name} timed out after {timeout}s")
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
                details={"progress": progress, "exception_type": type(exc).__name__},
            )
            write_status(self.job_dir, "failed", progress, str(exc))
            return False

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        write_event(
            self.job_dir,
            "stage_command_finished",
            stage_name,
            level="info" if result.returncode == 0 else "error",
            message=f"return code {result.returncode}",
            duration_ms=duration_ms,
            details={"returncode": result.returncode, "progress": progress},
        )
        if result.returncode != 0:
            output = (result.stderr or result.stdout or "unknown error")[-1200:]
            write_event(
                self.job_dir,
                "stage_failed",
                stage_name,
                level="error",
                message=output,
                duration_ms=duration_ms,
                details={"returncode": result.returncode, "output_tail": output},
            )
            write_status(self.job_dir, "failed", progress, output)
            return False
        return True

    def run(self) -> bool:
        try:
            write_status(self.job_dir, "running", 1)
            stages = build_stage_plan(self.job_dir, self.preset, self.python_exe)
            write_event(
                self.job_dir,
                "pipeline_started",
                "running",
                details={"stage_names": [stage.name for stage in stages]},
            )
            for stage in stages:
                if not self.run_command(stage.command, stage.name, stage.progress):
                    write_event(
                        self.job_dir,
                        "pipeline_finished",
                        "failed",
                        level="error",
                        message=f"{stage.name} failed",
                    )
                    build_observability_summary(self.job_dir)
                    return False
            write_status(self.job_dir, "done", 100)
            write_event(self.job_dir, "pipeline_finished", "done", message="pipeline complete")
            build_observability_summary(self.job_dir)
            return True
        finally:
            if self.running_registry is not None and self.job_id:
                self.running_registry.pop(self.job_id, None)
                write_event(
                    self.job_dir,
                    "running_registry_cleanup",
                    "done",
                    details={"job_id": self.job_id},
                )
                build_observability_summary(self.job_dir)


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
