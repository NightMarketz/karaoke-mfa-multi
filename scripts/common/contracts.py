from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobMeta:
    job_id: str
    song_name: str
    preset: str
    created_at: float
    duration_s: float | None
    has_lyrics: bool
    source: str

    @classmethod
    def read(cls, job_dir: Path) -> "JobMeta":
        data = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
        return cls(**data)

    def write(self, job_dir: Path) -> None:
        (job_dir / "meta.json").write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


@dataclass(frozen=True)
class JobStatus:
    stage: str
    progress: int
    error: str = ""
    updated_at: float | None = None
