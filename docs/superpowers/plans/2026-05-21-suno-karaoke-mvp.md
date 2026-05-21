# Suno Karaoke MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reliable local flow that accepts Suno stems plus lyrics and returns a validated MP4 with mixed audio and color-coded karaoke subtitles.

**Architecture:** Keep the existing file-based pipeline, but add shared contracts, safe path handling, a dedicated pipeline runner, and a final validation gate. Flask should own request/UI concerns; stage scripts should own audio/lyrics domain logic.

**Tech Stack:** Python, Flask, standard-library `unittest`, ffmpeg, existing pipeline scripts, Jinja templates, static JS/CSS.

---

## File Structure

- Create: `scripts/common/__init__.py`
- Create: `scripts/common/contracts.py`
- Create: `scripts/common/paths.py`
- Create: `scripts/common/status.py`
- Create: `scripts/common/validation.py`
- Create: `scripts/pipeline_runner.py`
- Create: `tests/__init__.py`
- Create: `tests/test_common_contracts.py`
- Create: `tests/test_safe_paths.py`
- Create: `tests/test_timestamp_validation.py`
- Create: `tests/test_pipeline_runner.py`
- Create: `tests/test_analysis_contract.py`
- Create: `tests/test_validate_contracts.py`
- Modify: `server.py`
- Modify: `scripts/s04_align.py`
- Modify: `scripts/s05_analyze.py`
- Modify: `scripts/s06_generate_ass.py`
- Modify: `scripts/s08_validate.py`
- Modify: `templates/job.html`
- Modify: `templates/new_job.html`
- Modify: `static/app.js`
- Modify: `static/app.css`
- Modify: `requirements.txt`

## Agent Ownership

- Agent A owns `scripts/common/*` and `tests/test_common_*`, `tests/test_safe_paths.py`.
- Agent B owns `scripts/pipeline_runner.py`, runner tests, and orchestration changes in `server.py`.
- Agent C owns `scripts/s04_align.py`, `scripts/s05_analyze.py`, `scripts/s08_validate.py`, `scripts/common/validation.py`, and validation tests.
- Agent D owns `scripts/s06_generate_ass.py` and ASS/style tests.
- Agent E owns `templates/*`, `static/*`, and UI behavior.

Do not edit another agent's owned files without coordination.

---

### Task 1: Shared Contracts And Safe Paths

**Files:**
- Create: `scripts/common/__init__.py`
- Create: `scripts/common/contracts.py`
- Create: `scripts/common/paths.py`
- Create: `scripts/common/status.py`
- Create: `tests/__init__.py`
- Create: `tests/test_common_contracts.py`
- Create: `tests/test_safe_paths.py`

- [ ] **Step 1: Write failing tests for contracts**

Create `tests/test_common_contracts.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from scripts.common.contracts import JobMeta, JobStatus
from scripts.common.status import read_status, write_status


class ContractTests(unittest.TestCase):
    def test_job_meta_round_trip_uses_meta_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            meta = JobMeta(
                job_id="abc123def456",
                song_name="Struggle",
                preset="section-coded",
                created_at=123.4,
                duration_s=210.0,
                has_lyrics=True,
                source="zip",
            )
            meta.write(job_dir)
            loaded = JobMeta.read(job_dir)
            self.assertEqual(loaded.job_id, "abc123def456")
            self.assertEqual(loaded.song_name, "Struggle")
            self.assertTrue((job_dir / "meta.json").exists())
            self.assertFalse((job_dir / "metadata.json").exists())

    def test_status_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            write_status(job_dir, "aligning", 25)
            status = read_status(job_dir)
            self.assertIsInstance(status, JobStatus)
            self.assertEqual(status.stage, "aligning")
            self.assertEqual(status.progress, 25)
            raw = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertIn("updated_at", raw)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Write failing tests for safe paths**

Create `tests/test_safe_paths.py`:

```python
import unittest
from pathlib import PurePosixPath

from scripts.common.paths import is_safe_archive_member, validate_job_id


class SafePathTests(unittest.TestCase):
    def test_job_id_accepts_uuid_prefix_style(self):
        self.assertTrue(validate_job_id("abc123def456"))

    def test_job_id_rejects_traversal(self):
        self.assertFalse(validate_job_id("../jobs/test"))
        self.assertFalse(validate_job_id("abc/def"))
        self.assertFalse(validate_job_id(""))

    def test_archive_member_rejects_traversal(self):
        self.assertFalse(is_safe_archive_member("../vocals.wav"))
        self.assertFalse(is_safe_archive_member("nested/../../vocals.wav"))
        self.assertFalse(is_safe_archive_member("/absolute/vocals.wav"))

    def test_archive_member_allows_nested_audio(self):
        self.assertTrue(is_safe_archive_member("stems/vocals.wav"))
        self.assertTrue(is_safe_archive_member(str(PurePosixPath("Suno") / "instrumental.mp3")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_common_contracts tests.test_safe_paths -v
```

Expected: fails because `scripts.common` modules do not exist.

- [ ] **Step 4: Implement common modules**

Create `scripts/common/contracts.py`:

```python
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
```

Create `scripts/common/paths.py`:

```python
from __future__ import annotations

import re
from pathlib import PurePosixPath

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
```

Extend this module during server integration with a `resolve_job_dir(jobs_dir, job_id)` helper that validates the id, resolves the final path, and confirms it remains inside `jobs_dir.resolve()`.

Create `scripts/common/status.py`:

```python
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
```

Create empty package files:

```python
# scripts/common/__init__.py
```

```python
# tests/__init__.py
```

- [ ] **Step 5: Run tests and verify pass**

Run:

```powershell
python -m unittest tests.test_common_contracts tests.test_safe_paths -v
```

Expected: all tests pass.

---

### Task 2: Pipeline Runner, Queue Policy, And Validation Gate

**Files:**
- Create: `scripts/pipeline_runner.py`
- Create: `tests/test_pipeline_runner.py`
- Modify: `server.py`

- [ ] **Step 1: Write failing runner tests**

Create `tests/test_pipeline_runner.py`:

```python
import tempfile
import unittest
from pathlib import Path

from scripts.pipeline_runner import build_stage_plan, PipelineRunner


class PipelineRunnerTests(unittest.TestCase):
    def test_build_stage_plan_uses_forced_alignment_when_lyrics_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "lyrics.txt").write_text("[Verse]\nhello", encoding="utf-8")
            stages = build_stage_plan(job_dir, "cyberpunk", "python")
            names = [s.name for s in stages]
            self.assertEqual(names[0], "aligning_lyrics")
            self.assertIn("validating", names)

    def test_runner_marks_failed_when_stage_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            runner = PipelineRunner(job_dir=job_dir, python_exe="python")
            ok = runner.run_command(["python", "-c", "import sys; sys.exit(3)"], "testing", 10, timeout=10)
            self.assertFalse(ok)
            self.assertIn("failed", (job_dir / "status.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify fail**

Run:

```powershell
python -m unittest tests.test_pipeline_runner -v
```

Expected: fails because `scripts.pipeline_runner` does not exist.

- [ ] **Step 3: Implement runner**

Create `scripts/pipeline_runner.py` with a `Stage` dataclass, `build_stage_plan`, and `PipelineRunner.run`.

Minimum behavior:

- Build stages `s03b` or `s03`, then `s04`, `s05`, `s06`, `s07`, and final `s08_validate`.
- Use `scripts.common.status.write_status`.
- Capture stage failure and store last 1200 chars of stderr/stdout.
- Mark final status `done` only after validation passes.
- Always remove finished/failed jobs from the in-memory running registry in `finally`.
- Do not delete a running job. Return a clear error until cancellation exists.

- [ ] **Step 4: Refactor server orchestration**

Modify `server.py`:

- Import `PipelineRunner`.
- Replace `_run_stage` and stage list assembly inside `_run_pipeline` with the runner.
- Keep route behavior unchanged.
- Add `app.config["MAX_CONTENT_LENGTH"]`.
- Use safe job id resolution in all `/job/<job_id>` routes.
- Replace unsafe ZIP `extractall` with member-by-member safe extraction.
- Add `data-job-id` to dashboard cards so `static/app.js` can bind SSE.

- [ ] **Step 5: Run runner tests**

Run:

```powershell
python -m unittest tests.test_pipeline_runner -v
```

Expected: all tests pass.

---

### Task 3: Timestamp Validation, Repair, And Analysis Contracts

**Files:**
- Create: `scripts/common/validation.py`
- Create: `tests/test_timestamp_validation.py`
- Create: `tests/test_analysis_contract.py`
- Modify: `scripts/s04_align.py`
- Modify: `scripts/s05_analyze.py`
- Modify: `scripts/s08_validate.py`

- [ ] **Step 1: Write failing timestamp tests**

Create `tests/test_timestamp_validation.py`:

```python
import unittest

from scripts.common.validation import normalize_words, find_timestamp_errors


class TimestampValidationTests(unittest.TestCase):
    def test_find_timestamp_errors_detects_inverted_word(self):
        words = [{"word": "of", "start": 2.0, "end": 1.5}]
        errors = find_timestamp_errors(words)
        self.assertEqual(len(errors), 1)
        self.assertIn("of", errors[0])

    def test_repair_word_timestamps_fixes_inverted_word_inside_segment(self):
        words = [
            {"word": "light", "start": 1.0, "end": 1.4},
            {"word": "of", "start": 2.0, "end": 1.5},
            {"word": "fire", "start": 2.2, "end": 2.8},
        ]
        repaired = normalize_words(words, segment_start=1.0, segment_end=3.0)
        self.assertLess(repaired[1]["start"], repaired[1]["end"])
        self.assertLessEqual(repaired[0]["end"], repaired[1]["start"])
        self.assertLessEqual(repaired[1]["end"], repaired[2]["start"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify fail**

Run:

```powershell
python -m unittest tests.test_timestamp_validation -v
```

Expected: fails because validation helpers do not exist.

- [ ] **Step 3: Implement validation helpers**

Create `scripts/common/validation.py`:

```python
from __future__ import annotations


def find_timestamp_errors(words: list[dict], min_duration: float = 0.001) -> list[str]:
    errors: list[str] = []
    prev_end: float | None = None
    for index, word in enumerate(words):
        label = str(word.get("word", f"#{index}"))
        start = float(word.get("start", 0.0))
        end = float(word.get("end", 0.0))
        if end - start < min_duration:
            errors.append(f"Word '{label}' invalid duration: {start:.4f} -> {end:.4f}")
        if prev_end is not None and start < prev_end:
            errors.append(f"Word '{label}' overlaps previous: {start:.4f} < {prev_end:.4f}")
        prev_end = max(prev_end or end, end)
    return errors


def normalize_words(
    words: list[dict],
    segment_start: float,
    segment_end: float,
    min_duration: float = 0.05,
) -> list[dict]:
    if not words:
        return words
    n = len(words)
    window = max(segment_end - segment_start, min_duration * n)
    slot = window / n
    repaired: list[dict] = []
    prev_end = segment_start
    for index, word in enumerate(words):
        copy = dict(word)
        start = float(copy.get("start", segment_start + index * slot))
        end = float(copy.get("end", start + min_duration))
        max_end = segment_end if index == n - 1 else min(segment_end, segment_start + (index + 1) * slot)
        if start < prev_end or start >= end:
            start = prev_end
            end = max(start + min_duration, min(max_end, start + slot))
        if end <= start:
            end = start + min_duration
        copy["start"] = round(start, 4)
        copy["end"] = round(end, 4)
        if copy is not word:
            copy["source"] = copy.get("source", "unknown")
        repaired.append(copy)
        prev_end = copy["end"]
    return repaired


def word_sequence(words: list[dict]) -> list[str]:
    return [str(w.get("word", "")).casefold() for w in words if str(w.get("word", "")).strip()]
```

- [ ] **Step 4: Apply normalization in Stage 04 before writing `aligned.json`**

Modify `scripts/s04_align.py` so each segment's words pass through `normalize_words` after HubertFA mapping/interpolation and before `all_aligned_words.extend(words)`.

- [ ] **Step 5: Make `s08_validate.py` share the same error detector**

Modify `scripts/s08_validate.py` to call `find_timestamp_errors` for `aligned.json` word checks.

- [ ] **Step 6: Validate analysis contract before writing**

Create `tests/test_analysis_contract.py` with cases for:

- Line missing `words` fails.
- Line with `end <= start` fails.
- Line start/end mismatching first/last word fails.
- Repeated words are compared in order or by multiset, never by plain `set`.

Modify `scripts/s05_analyze.py` so `_validate_analysis` checks every line, not only the first line.

- [ ] **Step 7: Run tests and sample validation**

Run:

```powershell
python -m unittest tests.test_timestamp_validation -v
python -m unittest tests.test_analysis_contract -v
python scripts\s08_validate.py --job-dir jobs\test-struggle
```

Expected: unit tests pass. The sample validation should no longer report inverted word timestamps after the pipeline regenerates `aligned.json`; existing stale artifacts may still fail until Stage 04 is rerun.

---

### Task 4: ASS Generation For Section-Coded Karaoke

**Files:**
- Modify: `scripts/s06_generate_ass.py`
- Create: `tests/test_ass_generation.py`

- [ ] **Step 1: Write failing ASS tests**

Create `tests/test_ass_generation.py`:

```python
import unittest

from scripts.s06_generate_ass import _build_karaoke_text


class AssGenerationTests(unittest.TestCase):
    def test_build_karaoke_text_escapes_braces(self):
        text = _build_karaoke_text(
            [{"word": "{bad}", "start": 1.0, "end": 1.5}],
            line_start_ms=1000,
            effect="highlight",
        )
        self.assertNotIn("{bad}", text)
        self.assertIn("bad", text)

    def test_inverted_word_gets_minimum_duration(self):
        text = _build_karaoke_text(
            [{"word": "fast", "start": 2.0, "end": 1.9}],
            line_start_ms=1900,
            effect="highlight",
        )
        self.assertIn("\\kf8", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify fail**

Run:

```powershell
python -m unittest tests.test_ass_generation -v
```

Expected: first test fails until ASS text escaping exists.

- [ ] **Step 3: Implement ASS text escaping**

Add helper in `scripts/s06_generate_ass.py`:

```python
def _escape_ass_text(text: str) -> str:
    return (
        text.replace("{", "")
            .replace("}", "")
            .replace("\\", "")
            .replace("\n", " ")
            .strip()
    )
```

Use `_escape_ass_text(str(word["word"]))` before appending visible word text in `_build_karaoke_text`.

- [ ] **Step 4: Add `section-coded` preset**

Extend preset mapping so section styles use distinct readable colors:

- `intro`: muted cyan.
- `verse`: white.
- `prechorus`: yellow.
- `chorus`: hot pink or cyan highlight.
- `bridge`: green.
- `drop`: orange.
- `outro`: muted blue.

- [ ] **Step 5: Run ASS tests**

Run:

```powershell
python -m unittest tests.test_ass_generation -v
```

Expected: all tests pass.

---

### Task 5: Product UI States

**Files:**
- Modify: `templates/new_job.html`
- Modify: `templates/job.html`
- Modify: `static/app.js`
- Modify: `static/app.css`

- [ ] **Step 1: Update preset options**

In `templates/new_job.html`, add a radio option:

```html
<label class="preset-option">
  <input type="radio" name="preset" value="section-coded">
  <div class="preset-label">
    <div class="preset-title">SECTION CODED</div>
    <div class="preset-desc">Verse, chorus, bridge and drop get distinct colors</div>
  </div>
</label>
```

- [ ] **Step 2: Make lyrics required for MVP**

For this product MVP, forced alignment is the reliable path. Add `required` to the `lyrics_text` textarea and change helper copy to say the MVP requires Suno lyrics.

- [ ] **Step 3: Improve failed job display**

In `templates/job.html`, render `status.error` in a visible failed-state panel when `status.stage == "failed"`.

- [ ] **Step 4: Improve done state**

In `templates/job.html`, when `has_output`, show:

- Video preview.
- Download MP4 button.
- Download ASS button.
- Validation summary if available.

- [ ] **Step 5: Keep SSE behavior but show failed reason**

In `static/app.js`, when stage is `failed`, update the UI with `data.error` if a `.failure-message` element exists.

- [ ] **Step 6: Bind dashboard SSE correctly**

In `templates/index.html`, add `data-job-id="{{ job.job_id }}"` to each `.job-card`. Confirm `static/app.js` receives updates for running jobs from `/job/<id>/stream`.

- [ ] **Step 7: Fix mojibake in active templates**

Replace corrupted visible strings such as `â†`, `ðŸ`, and `seÃ§Ã£o` in active `templates/` with plain ASCII labels or valid UTF-8.

---

### Task 6: Requirements And Verification

**Files:**
- Modify: `requirements.txt`
- Modify: `scripts/s08_validate.py`
- Modify: `scripts/test_pipeline.py`

- [ ] **Step 1: Add missing dependency**

Add `g2p_en` to `requirements.txt`, because `scripts/s04_align.py` imports it.

- [ ] **Step 2: Make validation command product-friendly**

Ensure `scripts/s08_validate.py` returns nonzero on contract failures and prints clear stage sections. Keep current behavior, but reuse common validation helpers where possible.

- [ ] **Step 3: Validate job metadata and status**

Extend `scripts/s08_validate.py`:

- `meta.json` valid: OK.
- only `metadata.json`: warning as legacy.
- both files with conflicting job identifiers: failure.
- `status.json` must include `stage`, `progress`, `error`, `updated_at`.

- [ ] **Step 4: Make pipeline test aware of forced mode**

Modify `scripts/test_pipeline.py` so Ollama is checked only when `lyrics.txt` is absent and Stage 05 will need the LLM path.

- [ ] **Step 5: Run focused unit tests**

Run:

```powershell
python -m unittest discover tests -v
```

Expected: all unit tests pass.

- [ ] **Step 6: Run existing robustness test**

Run:

```powershell
python scripts\test_lyrics_robustness.py
```

Expected: all tests pass after deciding whether contraction tests should expect normalized or original text. If product behavior preserves display text but normalizes alignment text, update tests to assert both contracts explicitly.

- [ ] **Step 7: Run sample validation**

Run:

```powershell
python scripts\s08_validate.py --job-dir jobs\test-struggle
```

Expected: no inverted timestamp failures after regenerating stale `aligned.json`.

---

## Self-Review

- Spec coverage: covers upload, lyrics, color-coded ASS, mixed audio, validation gate, and UI states.
- Completion scan: all sections are filled in and no unfinished implementation notes remain.
- Scope check: this is a single MVP slice. Hosting, accounts, and subtitle editing are out of scope.
- Type consistency: `JobMeta`, `JobStatus`, `PipelineRunner`, and validation helper names are consistent across tasks.
