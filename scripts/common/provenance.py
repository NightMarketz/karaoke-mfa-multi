from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class ProvenanceError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        raise ProvenanceError(f"manifest missing or empty: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProvenanceError(f"manifest is invalid JSON: {path.name}") from exc
    if not isinstance(data, dict):
        raise ProvenanceError(f"manifest must be an object: {path.name}")
    return data


def validate_file_hash(path: Path, expected_sha256: str) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise ProvenanceError(f"artifact missing or empty: {path.name}")
    actual = file_sha256(path)
    if actual != expected_sha256:
        raise ProvenanceError(
            f"artifact hash mismatch for {path.name}: {actual} != {expected_sha256}"
        )


def write_manifest(
    path: Path,
    manifest: dict[str, Any],
    *,
    output_paths: dict[str, Path] | None = None,
) -> Path:
    payload = dict(manifest)
    payload.setdefault("created_at", time.time())
    if output_paths:
        outputs = dict(payload.get("outputs", {}))
        for name, artifact_path in output_paths.items():
            item = dict(outputs.get(name, {}))
            item.setdefault("path", artifact_path.name)
            item["sha256"] = file_sha256(artifact_path)
            item["size_bytes"] = artifact_path.stat().st_size
            outputs[name] = item
        payload["outputs"] = outputs
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path
