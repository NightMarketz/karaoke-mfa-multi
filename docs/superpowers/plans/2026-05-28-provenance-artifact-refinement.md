# Provenance Artifact Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop mixed karaoke subtitle/render results by binding every derived artifact to the exact inputs, preset, renderer, and run that produced it.

**Architecture:** Add a small provenance layer used by Stage 06, Stage 07, Stage 08, and server export readiness. Stage 06 creates a manifest for `output.ass`; Stage 07 validates that manifest before rendering and creates a manifest for `output.mp4`; Stage 08 and the UI approve only provenance-valid artifacts. Preserve the golden "About to snap" behavior: forced timing plus sustained-vowel highlight segmentation in one visible ASS layer.

**Tech Stack:** Python stdlib, existing pipeline scripts, JSON manifests, unittest, Flask server routes.

---

## SDD Multi-Agent Operating Model

Each task is executed by one implementer agent and two reviewers:

- **Task Agent:** implements only the assigned task, writes/updates tests first, runs targeted verification, returns changed files and evidence.
- **Review Agent:** checks spec compliance only: required contracts, file names, provenance fields, refusal paths, and golden-example behavior.
- **Approve Agent:** checks engineering quality and final gate: no stale mutable reuse, no unrelated refactor, tests pass, no hidden bypass.

Controller rule:

1. Dispatch one Task Agent per task, sequentially for shared files.
2. Dispatch Review Agent after implementation.
3. If Review Agent finds gaps, return to same Task Agent.
4. Dispatch Approve Agent only after Review Agent approves.
5. Mark task complete only after Approve Agent approves.
6. Run final end-to-end validation after all tasks.

No implementation agents should run in parallel on shared files. Parallel research is allowed only before edits.

## Files And Responsibilities

- `scripts/common/provenance.py`: new shared helpers for SHA256, manifest writing, manifest loading, and validation errors.
- `scripts/common/observability.py`: add optional artifact SHA details to event payloads.
- `scripts/s06_generate_ass.py`: create and write `output.ass.manifest.json`; enforce single-layer renderer invariants.
- `scripts/s07_output.py`: require valid ASS manifest before rendering; write `output.mp4.manifest.json`.
- `scripts/s08_validate.py`: validate artifact graph, file hashes, stage event/file consistency, and stale outputs.
- `server.py`: make technical export readiness depend on provenance validation; require valid MP4 manifest for preview/export.
- `scripts/test_pipeline.py`: pass preset explicitly from `meta.json` or config and assert manifest graph.
- `tests/test_provenance_contracts.py`: new unit tests for manifest helpers.
- `tests/test_ass_generation.py`: extend Stage 06 manifest and single-layer tests.
- `tests/test_s07_observability.py`: extend Stage 07 manifest validation tests.
- `tests/test_validate_contracts.py`: extend Stage 08 artifact graph checks.
- `tests/test_server_contracts.py` or `tests/test_review_wizard_server.py`: prove UI/export blocks stale artifacts.
- `.Codex/tasks/artifact-reuse-audit.md`: source audit; do not edit unless documenting completed remediation.

---

### Task 1: Provenance Helper Module

**Agent Roles:**
- Task Agent: `provenance-helper-implementer`
- Review Agent: `provenance-contract-reviewer`
- Approve Agent: `provenance-quality-approver`

**Files:**
- Create: `scripts/common/provenance.py`
- Create: `tests/test_provenance_contracts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_provenance_contracts.py` with tests for:

```python
import json
import tempfile
import unittest
from pathlib import Path

from scripts.common.provenance import (
    ProvenanceError,
    file_sha256,
    load_manifest,
    validate_file_hash,
    write_manifest,
)


class ProvenanceContractsTests(unittest.TestCase):
    def test_file_sha256_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.txt"
            path.write_text("karaoke", encoding="utf-8")
            self.assertEqual(file_sha256(path), file_sha256(path))
            self.assertEqual(len(file_sha256(path)), 64)

    def test_write_manifest_records_output_hash_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            artifact = job_dir / "output.ass"
            artifact.write_text("[Script Info]\n", encoding="utf-8")
            manifest_path = write_manifest(
                job_dir / "output.ass.manifest.json",
                {
                    "stage": "stage06",
                    "run_id": "run-test",
                    "outputs": {"output.ass": {"path": "output.ass"}},
                },
                output_paths={"output.ass": artifact},
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["outputs"]["output.ass"]["sha256"], file_sha256(artifact))
            self.assertEqual(manifest["outputs"]["output.ass"]["size_bytes"], artifact.stat().st_size)

    def test_validate_file_hash_rejects_changed_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.ass"
            path.write_text("v1", encoding="utf-8")
            digest = file_sha256(path)
            path.write_text("v2", encoding="utf-8")
            with self.assertRaises(ProvenanceError):
                validate_file_hash(path, digest)

    def test_load_manifest_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProvenanceError):
                load_manifest(Path(tmp) / "missing.manifest.json")
```

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_provenance_contracts`

Expected: import failure for `scripts.common.provenance`.

- [ ] **Step 3: Implement helper**

Create `scripts/common/provenance.py` with:

```python
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
        raise ProvenanceError(f"artifact hash mismatch for {path.name}: {actual} != {expected_sha256}")


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
```

- [ ] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_provenance_contracts`

Expected: `OK`.

- [ ] **Step 5: Commit**

Commit message: `feat: add artifact provenance helpers`

---

### Task 2: Stage 06 ASS Manifest And Single-Layer Contract

**Agent Roles:**
- Task Agent: `stage06-manifest-implementer`
- Review Agent: `stage06-contract-reviewer`
- Approve Agent: `stage06-quality-approver`

**Files:**
- Modify: `scripts/s06_generate_ass.py`
- Modify: `tests/test_ass_generation.py`

- [ ] **Step 1: Write failing tests**

Add tests proving:

- `output.ass.manifest.json` is written.
- manifest input hash equals current `analysis.json`.
- manifest output hash equals current `output.ass`.
- `renderer_mode == "single_layer_kf"`.
- `dialogue_count == len(analysis["lines"])`.
- no `Base,,` appears in dialogue lines.

Representative assertion block:

```python
manifest = json.loads((job_dir / "output.ass.manifest.json").read_text(encoding="utf-8"))
self.assertEqual(manifest["stage"], "stage06")
self.assertEqual(manifest["renderer_mode"], "single_layer_kf")
self.assertEqual(manifest["metrics"]["dialogue_count"], 2)
self.assertEqual(manifest["metrics"]["analysis_line_count"], 2)
self.assertEqual(manifest["inputs"]["analysis.json"]["sha256"], file_sha256(job_dir / "analysis.json"))
self.assertEqual(manifest["outputs"]["output.ass"]["sha256"], file_sha256(job_dir / "output.ass"))
```

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_ass_generation.AssGenerationTests`

Expected: missing `output.ass.manifest.json`.

- [ ] **Step 3: Implement Stage 06 manifest**

Implementation requirements:

- Import `file_sha256` and `write_manifest`.
- After writing `output.ass`, calculate `ass_metrics`.
- Write `output.ass.manifest.json`.
- Include:
  - `stage`
  - `run_id` from `status.json` if present, else `"manual"`
  - `preset`
  - `renderer_mode: "single_layer_kf"`
  - `inputs.analysis.json.sha256`
  - `outputs.output.ass.sha256`
  - `metrics.analysis_line_count`
  - `metrics.dialogue_count`
  - `metrics.kf_count`
  - `style_distribution`
- Emit manifest path/hash in `stage06.ass_written`.

- [ ] **Step 4: Verify Stage 06 tests pass**

Run: `python -m unittest tests.test_ass_generation.AssGenerationTests`

Expected: `OK`.

- [ ] **Step 5: Commit**

Commit message: `feat: write stage06 ass provenance manifest`

---

### Task 3: Stage 07 Refuses Unprovenanced ASS And Writes MP4 Manifest

**Agent Roles:**
- Task Agent: `stage07-provenance-implementer`
- Review Agent: `stage07-contract-reviewer`
- Approve Agent: `stage07-quality-approver`

**Files:**
- Modify: `scripts/s07_output.py`
- Modify: `tests/test_s07_observability.py`

- [ ] **Step 1: Write failing tests**

Add tests that:

- Stage 07 fails when `output.ass.manifest.json` is missing.
- Stage 07 fails when manifest hash does not match `output.ass`.
- Stage 07 writes `output.mp4.manifest.json` after successful render.
- MP4 manifest includes `input_ass_sha256`.

Use patched `subprocess.run` as existing tests do, and create a minimal valid ASS plus manifest.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_s07_observability`

Expected: Stage 07 currently accepts ASS without manifest.

- [ ] **Step 3: Implement manifest validation**

Implementation requirements:

- Import `ProvenanceError`, `file_sha256`, `load_manifest`, `validate_file_hash`, `write_manifest`.
- Before ffmpeg:
  - load `output.ass.manifest.json`;
  - validate `outputs.output.ass.sha256`;
  - validate `inputs.analysis.json.sha256` still matches current `analysis.json` if it exists;
  - fail with `stage07.failed` if validation fails.
- After successful MP4:
  - write `output.mp4.manifest.json`;
  - include ASS manifest hash or full ASS output hash;
  - include audio input hashes;
  - include output MP4 hash/size.

- [ ] **Step 4: Verify Stage 07 tests pass**

Run: `python -m unittest tests.test_s07_observability`

Expected: `OK`.

- [ ] **Step 5: Commit**

Commit message: `feat: require ass provenance before render`

---

### Task 4: Stage 08 Artifact Graph Validation

**Agent Roles:**
- Task Agent: `stage08-provenance-validator`
- Review Agent: `validation-contract-reviewer`
- Approve Agent: `validation-quality-approver`

**Files:**
- Modify: `scripts/s08_validate.py`
- Modify: `tests/test_validate_contracts.py`

- [ ] **Step 1: Write failing tests**

Add tests for:

- missing `output.ass.manifest.json` fails when `output.ass` exists;
- changed `output.ass` fails validation;
- `output.mp4.manifest.json` ASS hash mismatch fails validation;
- valid graph passes.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_validate_contracts`

Expected: new provenance tests fail because validator does not check graph yet.

- [ ] **Step 3: Implement validator section**

Add a `validate_provenance(job_dir)` section that:

- loads `analysis.json`, `output.ass`, `output.ass.manifest.json`;
- validates file hashes;
- checks `renderer_mode == "single_layer_kf"`;
- checks dialogue count equals analysis line count;
- if `output.mp4` exists, requires and validates `output.mp4.manifest.json`;
- fails if `stage06.ass_written` event size disagrees with current ASS and no newer manifest explains it.

- [ ] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_validate_contracts`

Expected: `OK`.

- [ ] **Step 5: Commit**

Commit message: `feat: validate artifact provenance graph`

---

### Task 5: Server Export And Preview Gate Uses Provenance

**Agent Roles:**
- Task Agent: `server-provenance-gate-implementer`
- Review Agent: `server-contract-reviewer`
- Approve Agent: `server-quality-approver`

**Files:**
- Modify: `server.py`
- Modify: `tests/test_review_wizard_server.py`
- Modify: `tests/test_server_contracts.py` if needed

- [ ] **Step 1: Write failing tests**

Add tests that:

- job detail does not report technical export ready when manifests are missing;
- `/job/<id>/output.mp4` is blocked when MP4 manifest is stale;
- full preview render refuses stale `output.mp4`.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_review_wizard_server tests.test_server_contracts`

Expected: export readiness is still file-existence based.

- [ ] **Step 3: Implement server gate**

Implementation requirements:

- Add helper `_artifact_graph_valid(job_dir) -> tuple[bool, str | None]`.
- Use provenance helpers to validate ASS and MP4 manifests.
- Replace `technical_export_ready=(output.mp4 exists and output.ass exists)` with provenance validity.
- Make `_render_full_review_preview` refuse invalid graph.
- Keep existing review approval fingerprint behavior.

- [ ] **Step 4: Verify server tests pass**

Run: `python -m unittest tests.test_review_wizard_server tests.test_server_contracts`

Expected: `OK`.

- [ ] **Step 5: Commit**

Commit message: `feat: gate exports on artifact provenance`

---

### Task 6: Pipeline Runner Run ID And Downstream Invalidation

**Agent Roles:**
- Task Agent: `pipeline-runner-invalidation-implementer`
- Review Agent: `pipeline-contract-reviewer`
- Approve Agent: `pipeline-quality-approver`

**Files:**
- Modify: `scripts/pipeline_runner.py`
- Modify: `scripts/common/status.py` if needed
- Modify: `tests/test_pipeline_runner.py`

- [ ] **Step 1: Write failing tests**

Add tests proving:

- pipeline creates a `run_id`;
- status/events include `run_id`;
- rerunning from Stage 06 invalidates old `output.mp4` and `output.mp4.manifest.json`;
- rerunning from Stage 05 invalidates `analysis`, `ass`, `mp4` downstream artifacts.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_pipeline_runner`

Expected: no run id/downstream invalidation yet.

- [ ] **Step 3: Implement run id and invalidation**

Implementation requirements:

- Generate stable per-run id such as `run-YYYYMMDD-HHMMSS-<shortuuid>`.
- Write it to status and pipeline events.
- Before each stage, remove or quarantine downstream artifacts:
  - before Stage 05: `analysis.json`, `output.ass`, `output.ass.manifest.json`, `output.mp4`, `output.mp4.manifest.json`, previews;
  - before Stage 06: `output.ass`, `output.ass.manifest.json`, `output.mp4`, `output.mp4.manifest.json`, previews;
  - before Stage 07: `output.mp4`, `output.mp4.manifest.json`, previews.
- Record `artifact_invalidated` events.

- [ ] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_pipeline_runner`

Expected: `OK`.

- [ ] **Step 5: Commit**

Commit message: `feat: invalidate stale downstream artifacts`

---

### Task 7: Preserve Golden Highlight Behavior

**Agent Roles:**
- Task Agent: `golden-highlight-contract-implementer`
- Review Agent: `highlight-spec-reviewer`
- Approve Agent: `highlight-quality-approver`

**Files:**
- Modify: `tests/test_highlight_velocity.py`
- Modify: `tests/test_ass_generation.py`
- Modify: `scripts/review_wizard/highlight_velocity.py` only if tests reveal a gap

- [ ] **Step 1: Write golden tests**

Add tests proving the last "About to snap" standard:

```python
segments = build_word_highlight_segments({"word": "snap", "start": 275.42, "end": 282.02})
self.assertEqual([segment["text"] for segment in segments], ["sn", "a", "p"])
self.assertEqual(segments[1]["role"], "sustained_vowel")
self.assertGreater(segments[1]["end"] - segments[1]["start"], 6.0)
```

Add ASS-generation assertion:

```python
text = _build_karaoke_text(
    [
        {"word": "About", "start": 274.48, "end": 275.22},
        {"word": "to", "start": 275.26, "end": 275.31},
        {"word": "snap", "start": 275.42, "end": 282.02},
    ],
    274480,
    "highlight",
)
self.assertIn(r"\kf624}a", text)
self.assertNotIn("sn a p", text)
```

- [ ] **Step 2: Verify tests pass or fail honestly**

Run: `python -m unittest tests.test_highlight_velocity tests.test_ass_generation.AssGenerationTests`

Expected: should pass with current behavior; if not, fix only the highlight splitter/render bridge.

- [ ] **Step 3: Commit**

Commit message: `test: lock golden sustained highlight behavior`

---

### Task 8: Integration And Clean Struggle Regeneration

**Agent Roles:**
- Task Agent: `integration-regeneration-runner`
- Review Agent: `integration-evidence-reviewer`
- Approve Agent: `release-gate-approver`

**Files:**
- Modify: `scripts/test_pipeline.py`
- Optionally create: `.Codex/tasks/struggle-regeneration-report.md`

- [ ] **Step 1: Make test pipeline pass preset explicitly**

Modify `scripts/test_pipeline.py` so Stage 06 receives a preset from:

1. `meta.json["preset"]` if present;
2. else `pipeline.toml [generate].style_preset`;
3. else `"section-coded"`.

- [ ] **Step 2: Add integration checks**

After Stage 07 in `scripts/test_pipeline.py`, assert:

- `output.ass.manifest.json` exists;
- `output.mp4.manifest.json` exists;
- ASS dialogue count equals analysis line count;
- no `Base,,` dialogue exists;
- MP4 manifest references the current ASS hash.

- [ ] **Step 3: Run targeted test suite**

Run:

```powershell
python -m unittest tests.test_provenance_contracts tests.test_ass_generation tests.test_s07_observability tests.test_validate_contracts tests.test_pipeline_runner
```

Expected: `OK`.

- [ ] **Step 4: Restart stale server before manual verification**

Stop the old `server.py` process and start a fresh server from the current source tree.

- [ ] **Step 5: Regenerate Struggle from clean run**

Run the pipeline on a clean Struggle job. Do not reuse `struggle-karaoke-single-style` in place unless old derived artifacts are quarantined first.

- [ ] **Step 6: Write evidence report**

Create `.Codex/tasks/struggle-regeneration-report.md` with:

- run id;
- source hashes;
- manifest hashes;
- `About to snap` timings;
- ASS dialogue count;
- analysis line count;
- absence of `Base,,`;
- validation result.

- [ ] **Step 7: Commit**

Commit message: `test: enforce provenance in integration pipeline`

---

## Final Approval Gate

The release is approved only if all are true:

- `python -m unittest tests.test_provenance_contracts` passes.
- `python -m unittest tests.test_ass_generation` passes.
- `python -m unittest tests.test_s07_observability` passes.
- `python -m unittest tests.test_validate_contracts` passes.
- `python -m unittest tests.test_pipeline_runner` passes.
- Server/review wizard tests touched by export gating pass.
- A fresh Struggle run has:
  - `output.ass.manifest.json`;
  - `output.mp4.manifest.json`;
  - `Dialogue:` count equals `analysis.lines`;
  - no `Base,,`;
  - last `About to snap` uses the sustained vowel split;
  - Stage 08 provenance validation passes.

## Approval Routing

For each task:

```text
Task Agent DONE
  -> Review Agent APPROVED
    -> Approve Agent APPROVED
      -> controller marks task complete
```

If either review fails:

```text
Review/Approve Agent REJECTED
  -> same Task Agent fixes only listed issues
  -> same reviewer rechecks
```

If three review loops fail on the same task, stop and revisit the architecture before continuing.

