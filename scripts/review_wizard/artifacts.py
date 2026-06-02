from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.review_wizard.contracts import AlignmentTake, Issue, QualityReport
from scripts.review_wizard.quality import quality_status


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def summarize_pipeline_artifacts(job_dir: Path) -> dict[str, Any]:
    transcript = _read_json(job_dir / "transcript.json")
    aligned = _read_json(job_dir / "aligned.json")
    analysis = _read_json(job_dir / "analysis.json")

    words = aligned.get("words") if isinstance(aligned.get("words"), list) else []
    lines = analysis.get("lines") if isinstance(analysis.get("lines"), list) else []
    segments = transcript.get("segments") if isinstance(transcript.get("segments"), list) else []

    return {
        "alignment_mode": transcript.get("alignment_mode", "unknown"),
        "word_count": len(words),
        "line_count": len(lines),
        "segment_count": len(segments),
        "has_transcript": bool(transcript),
        "has_aligned": bool(aligned),
        "has_analysis": bool(analysis),
        "line_ids": [f"line-{idx + 1}" for idx, _ in enumerate(lines)],
    }


def issues_from_artifact_summary(summary: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    if not summary["has_transcript"] or not summary["has_aligned"] or not summary["has_analysis"]:
        issues.append(
            Issue(
                id="issue-missing-pipeline-artifacts",
                type="pipeline_artifacts_missing",
                severity="high",
                perceptual_impact=0.85,
                confidence=1.0,
                priority_score=0.85,
                start_s=0.0,
                end_s=0.0,
                affected_ids=[],
                suggested_action="run_pipeline_before_quality_review",
            )
        )
    if summary["word_count"] == 0 and summary["has_aligned"]:
        issues.append(
            Issue(
                id="issue-aligned-words-empty",
                type="aligned_words_empty",
                severity="critical",
                perceptual_impact=1.0,
                confidence=1.0,
                priority_score=1.0,
                start_s=0.0,
                end_s=0.0,
                affected_ids=[],
                suggested_action="rerun_alignment",
            )
        )
    return issues


def take_and_report_from_summary(
    summary: dict[str, Any],
    issues: list[Issue],
) -> tuple[AlignmentTake, QualityReport]:
    critical = sum(1 for issue in issues if issue.severity in {"high", "critical"})
    score = 0.98 if not issues else max(0.0, 0.82 - critical * 0.12)
    status = quality_status(score=score, critical_open_issues=critical)
    take = AlignmentTake(
        id="take-pipeline-1",
        kind="pipeline_artifact",
        status=status,
        line_ids=summary.get("line_ids", []),
    )
    report = QualityReport(
        id="quality-pipeline-1",
        take_id=take.id,
        status=status,
        score=score,
        issue_ids=[issue.id for issue in issues],
    )
    return take, report
