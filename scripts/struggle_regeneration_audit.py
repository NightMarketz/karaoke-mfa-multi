from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.provenance import ProvenanceError, file_sha256, load_manifest

JOBS_ROOT = PROJECT_ROOT / "jobs"
DEFAULT_REPORT = PROJECT_ROOT / ".Codex" / "tasks" / "struggle-regeneration-report.md"
DEFAULT_PRESET = "single-style-kf"

DERIVED_ARTIFACTS = (
    "analysis.json",
    "output.ass",
    "output.ass.manifest.json",
    "output.mp4",
    "output.mp4.manifest.json",
    "preview_full.mp4",
    "preview_full.manifest.json",
)


@dataclass
class StageCommand:
    stage: str
    args: list[str]


@dataclass
class CommandResult:
    command: StageCommand
    returncode: int | None
    skipped: bool = False
    error: str = ""


@dataclass
class AuditResult:
    job_dir: Path
    ok: bool = True
    issues: list[str] = field(default_factory=list)
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    cleaned_artifacts: list[str] = field(default_factory=list)
    commands: list[CommandResult] = field(default_factory=list)

    def fail(self, issue: str) -> None:
        self.ok = False
        self.issues.append(issue)


def discover_struggle_jobs(jobs_root: Path = JOBS_ROOT) -> list[Path]:
    if not jobs_root.exists():
        return []
    return sorted(
        [
            path
            for path in jobs_root.iterdir()
            if path.is_dir() and "struggle" in path.name.lower()
        ],
        key=lambda path: path.name.lower(),
    )


def clean_derived_artifacts(job_dir: Path, *, clean: bool) -> list[str]:
    if clean:
        _ensure_job_dir_under_jobs_root(job_dir)
    found: list[str] = []
    for name in DERIVED_ARTIFACTS:
        path = job_dir / name
        if not path.exists():
            continue
        found.append(name)
        if clean and path.is_file():
            path.unlink()
    return found


def build_stage_commands(job_dir: Path, *, preset: str = DEFAULT_PRESET) -> list[StageCommand]:
    stage05_args = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "s05_analyze.py"),
        "--job-dir",
        str(job_dir),
    ]
    lyrics_path = job_dir / "lyrics.txt"
    if lyrics_path.exists():
        stage05_args.extend(["--lyrics", str(lyrics_path)])
    return [
        StageCommand("stage05", stage05_args),
        StageCommand("stage06", [sys.executable, str(PROJECT_ROOT / "scripts" / "s06_generate_ass.py"), "--job-dir", str(job_dir), "--preset", preset]),
        StageCommand("stage07", [sys.executable, str(PROJECT_ROOT / "scripts" / "s07_output.py"), "--job-dir", str(job_dir)]),
    ]


def run_stage_commands(commands: list[StageCommand], *, run: bool) -> list[CommandResult]:
    results: list[CommandResult] = []
    for command in commands:
        if not run:
            results.append(CommandResult(command=command, returncode=None, skipped=True, error="not run; pass --run to execute"))
            continue
        try:
            completed = subprocess.run(command.args, cwd=PROJECT_ROOT)
        except OSError as exc:
            results.append(CommandResult(command=command, returncode=1, error=str(exc)))
            break
        results.append(CommandResult(command=command, returncode=completed.returncode))
        if completed.returncode != 0:
            break
    return results


def audit_job(job_dir: Path) -> AuditResult:
    result = AuditResult(job_dir=job_dir)
    if not job_dir.exists():
        result.fail("job directory does not exist")
        return result

    _audit_provenance(result)
    _audit_about_to_snap(result)
    return result


def apply_command_failures(result: AuditResult) -> None:
    for item in result.commands:
        if item.skipped:
            continue
        if item.returncode != 0:
            result.fail(f"{item.command.stage} failed with exit {item.returncode}")
            if item.error:
                result.fail(f"{item.command.stage} error: {item.error}")


def _audit_provenance(result: AuditResult) -> None:
    job_dir = result.job_dir
    check: dict[str, Any] = {"ok": True}
    result.checks["provenance"] = check

    analysis_path = job_dir / "analysis.json"
    ass_path = job_dir / "output.ass"
    mp4_path = job_dir / "output.mp4"
    ass_manifest_path = job_dir / "output.ass.manifest.json"
    mp4_manifest_path = job_dir / "output.mp4.manifest.json"

    for path in (analysis_path, ass_path, mp4_path, ass_manifest_path, mp4_manifest_path):
        if not path.exists():
            _fail_check(result, check, f"{path.name} missing")
    if not check["ok"]:
        return

    try:
        analysis = _read_json(analysis_path)
        ass_manifest = load_manifest(ass_manifest_path)
        mp4_manifest = load_manifest(mp4_manifest_path)
        ass_content = ass_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError, ProvenanceError) as exc:
        _fail_check(result, check, f"provenance artifacts unreadable: {exc}")
        return

    analysis_lines = analysis.get("lines") if isinstance(analysis, dict) else None
    line_count = len(analysis_lines) if isinstance(analysis_lines, list) else -1
    dialogue_count = _ass_dialogue_count(ass_content)
    check["dialogue_count"] = dialogue_count
    check["analysis_line_count"] = line_count

    if ass_manifest.get("renderer_mode") != "single_layer_kf":
        _fail_check(result, check, "renderer_mode is not single_layer_kf")
    if _has_base_dialogue(ass_content):
        _fail_check(result, check, "ASS contains legacy Base,, dialogue")
    if dialogue_count != line_count:
        _fail_check(result, check, f"dialogue count mismatch: ASS={dialogue_count}, analysis={line_count}")

    expected_analysis_sha = _manifest_sha(ass_manifest, "inputs", "analysis.json")
    expected_ass_sha = _manifest_sha(ass_manifest, "outputs", "output.ass")
    expected_mp4_sha = _manifest_sha(mp4_manifest, "outputs", "output.mp4")
    expected_mp4_ass_sha = _manifest_sha(mp4_manifest, "inputs", "output.ass")
    current_analysis_sha = file_sha256(analysis_path)
    current_ass_sha = file_sha256(ass_path)
    current_mp4_sha = file_sha256(mp4_path)

    if expected_analysis_sha != current_analysis_sha:
        _fail_check(result, check, "analysis.json hash does not match output.ass.manifest.json")
    if expected_ass_sha != current_ass_sha:
        _fail_check(result, check, "output.ass hash does not match output.ass.manifest.json")
    if expected_mp4_sha != current_mp4_sha:
        _fail_check(result, check, "output.mp4 hash does not match output.mp4.manifest.json")
    if expected_mp4_ass_sha != current_ass_sha:
        _fail_check(result, check, "output.mp4.manifest.json does not reference current output.ass hash")


def _audit_about_to_snap(result: AuditResult) -> None:
    check: dict[str, Any] = {"ok": True}
    result.checks["about_to_snap"] = check
    analysis_path = result.job_dir / "analysis.json"
    ass_path = result.job_dir / "output.ass"
    if not analysis_path.exists():
        _fail_check(result, check, "analysis.json missing for About to snap audit")
        return

    try:
        analysis = _read_json(analysis_path)
    except (OSError, json.JSONDecodeError) as exc:
        _fail_check(result, check, f"analysis.json unreadable: {exc}")
        return

    lines = analysis.get("lines") if isinstance(analysis, dict) else []
    about_lines = [
        line for line in lines
        if isinstance(line, dict) and _normalize_text(str(line.get("text", ""))) == "about to snap"
    ]
    if not about_lines:
        _fail_check(result, check, "last About to snap line not found")
        return

    line = about_lines[-1]
    words = line.get("words") if isinstance(line.get("words"), list) else []
    snap = next((word for word in words if _normalize_text(str(word.get("word", ""))) == "snap"), None)
    if not isinstance(snap, dict):
        _fail_check(result, check, "snap word not found in last About to snap line")
        return

    from scripts.review_wizard.highlight_velocity import build_word_highlight_segments

    segments = build_word_highlight_segments(snap)
    sustained = next((segment for segment in segments if segment.get("role") == "sustained_vowel"), None)
    if not sustained:
        _fail_check(result, check, "snap sustained vowel segment not found")
        return

    sustained_start = float(sustained.get("start_s", sustained["start"]))
    sustained_end = float(sustained.get("end_s", sustained["end"]))
    duration_s = sustained_end - sustained_start
    duration_cs = max(1, int(round(duration_s * 100)))
    expected_vowel_kf = f"\\kf{duration_cs}}}{sustained.get('text')}"
    check["sustained_vowel_duration_s"] = round(duration_s, 3)
    check["expected_vowel_kf"] = expected_vowel_kf

    if duration_s <= 6.0:
        _fail_check(result, check, "snap sustained vowel is not longer than 6s")
    if ass_path.exists():
        ass_content = ass_path.read_text(encoding="utf-8")
        if expected_vowel_kf not in ass_content:
            _fail_check(result, check, f"ASS does not contain expected sustained vowel tag {expected_vowel_kf}")


def write_markdown_report(path: Path, results: list[AuditResult]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Struggle Regeneration Audit", ""]
    for result in results:
        lines.extend(_render_result(result))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _render_result(result: AuditResult) -> list[str]:
    lines = [
        f"## {result.job_dir.name}",
        "",
        f"- Status: {'PASS' if result.ok else 'FAIL'}",
        f"- Job dir: `{result.job_dir}`",
    ]
    if result.cleaned_artifacts:
        lines.append(f"- Cleaned artifacts: {', '.join(f'`{name}`' for name in result.cleaned_artifacts)}")
    else:
        lines.append("- Cleaned artifacts: none")

    if result.commands:
        lines.append("- Commands:")
        for item in result.commands:
            status = "not run" if item.skipped else f"exit {item.returncode}"
            lines.append(f"  - `{item.command.stage}`: {status}")
            if item.error:
                lines.append(f"    - {item.error}")
    else:
        lines.append("- Commands: not run")

    if result.checks:
        lines.append("- Checks:")
        for name, check in result.checks.items():
            status = "PASS" if check.get("ok") else "FAIL"
            lines.append(f"  - `{name}`: {status}")
            for key, value in check.items():
                if key == "ok":
                    continue
                lines.append(f"    - {key}: `{value}`")
    if result.issues:
        lines.append("- Issues:")
        for issue in result.issues:
            lines.append(f"  - {issue}")
    lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Controlled Struggle regeneration and provenance audit")
    parser.add_argument("--job-dir", action="append", default=[], help="Struggle job directory to audit/regenerate")
    parser.add_argument("--preset", default=DEFAULT_PRESET)
    parser.add_argument("--clean", action="store_true", help="Delete derived artifacts before optional regeneration")
    parser.add_argument("--run", action="store_true", help="Run Stage 05, 06, and 07 commands")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--fail-on-issues", action="store_true")
    args = parser.parse_args(argv)

    job_dirs = [Path(item).resolve() for item in args.job_dir]
    if not job_dirs:
        job_dirs = discover_struggle_jobs()

    results: list[AuditResult] = []
    for job_dir in job_dirs:
        try:
            cleaned = clean_derived_artifacts(job_dir, clean=args.clean)
            commands = build_stage_commands(job_dir, preset=args.preset)
            command_results = run_stage_commands(commands, run=args.run)
            result = audit_job(job_dir)
            result.cleaned_artifacts = cleaned if args.clean else []
            result.commands = command_results
            apply_command_failures(result)
        except ValueError as exc:
            result = AuditResult(job_dir=job_dir)
            result.fail(str(exc))
        results.append(result)

    try:
        report_path = write_markdown_report(Path(args.report), results)
    except PermissionError as exc:
        report_path = PROJECT_ROOT / Path(args.report).name
        print(f"WARNING: could not write report to {args.report}: {exc}", file=sys.stderr)
        print(f"WARNING: writing fallback report to {report_path}", file=sys.stderr)
        write_markdown_report(report_path, results)
    print(f"Report written: {report_path}")
    has_issues = any(not result.ok for result in results)
    return 1 if args.fail_on_issues and has_issues else 0


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _ensure_job_dir_under_jobs_root(job_dir: Path) -> None:
    resolved_job = job_dir.resolve()
    resolved_root = JOBS_ROOT.resolve()
    try:
        resolved_job.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"job directory is outside jobs root: {resolved_job}") from exc


def _manifest_sha(manifest: dict[str, Any], section: str, artifact: str) -> str | None:
    entries = manifest.get(section)
    if not isinstance(entries, dict):
        return None
    item = entries.get(artifact)
    if not isinstance(item, dict):
        return None
    sha = item.get("sha256")
    return sha if isinstance(sha, str) and sha else None


def _ass_dialogue_count(content: str) -> int:
    return sum(1 for line in content.splitlines() if line.startswith("Dialogue:"))


def _has_base_dialogue(content: str) -> bool:
    return any(line.startswith("Dialogue:") and "Base,," in line for line in content.splitlines())


def _normalize_text(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(normalized.split())


def _fail_check(result: AuditResult, check: dict[str, Any], issue: str) -> None:
    check["ok"] = False
    result.fail(issue)


if __name__ == "__main__":
    raise SystemExit(main())
