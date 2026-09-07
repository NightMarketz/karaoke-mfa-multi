from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.common.config import load_app_config
from scripts.review_wizard.contracts import AlignmentTake, Issue, QualityReport
from scripts.review_wizard.quality import quality_status


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _uncertain_syllables(lines: list[Any], threshold: float) -> list[dict[str, Any]]:
    """Collect timed syllable segments whose confidence is below ``threshold``.

    Reads either the derived ``word['syllables']`` or a manual
    ``word['highlight_segments']`` override — both carry a ``confidence`` and an
    id — so a low-confidence segment always surfaces as a review issue and is
    never silently rendered.
    """
    flagged: list[dict[str, Any]] = []
    for line_index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            continue
        for word in line.get("words", []) or []:
            if not isinstance(word, dict):
                continue
            segments = word.get("highlight_segments") or word.get("syllables") or []
            for seg in segments:
                if not isinstance(seg, dict) or "confidence" not in seg:
                    continue
                try:
                    confidence = float(seg["confidence"])
                except (TypeError, ValueError):
                    continue
                if confidence >= threshold:
                    continue
                seg_id = str(
                    seg.get("id")
                    or seg.get("syllable_id")
                    or f"line-{line_index}-{seg.get('text', '')}"
                )
                flagged.append({
                    "id": seg_id,
                    "confidence": round(confidence, 4),
                    "text": str(seg.get("text", "")),
                    "start_s": float(seg.get("start", seg.get("start_s", 0.0)) or 0.0),
                    "end_s": float(seg.get("end", seg.get("end_s", 0.0)) or 0.0),
                })
    return flagged


def summarize_pipeline_artifacts(job_dir: Path) -> dict[str, Any]:
    transcript = _read_json(job_dir / "transcript.json")
    aligned = _read_json(job_dir / "aligned.json")
    analysis = _read_json(job_dir / "analysis.json")

    words = aligned.get("words") if isinstance(aligned.get("words"), list) else []
    lines = analysis.get("lines") if isinstance(analysis.get("lines"), list) else []
    segments = transcript.get("segments") if isinstance(transcript.get("segments"), list) else []

    threshold = load_app_config().syllable_uncertain_threshold
    return {
        "alignment_mode": transcript.get("alignment_mode", "unknown"),
        "word_count": len(words),
        "line_count": len(lines),
        "segment_count": len(segments),
        "has_transcript": bool(transcript),
        "has_aligned": bool(aligned),
        "has_analysis": bool(analysis),
        "line_ids": [f"line-{idx + 1}" for idx, _ in enumerate(lines)],
        "uncertain_syllables": _uncertain_syllables(lines, threshold),
        "syllable_uncertain_threshold": threshold,
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
    for flagged in summary.get("uncertain_syllables", []):
        uncertainty = round(1.0 - flagged["confidence"], 4)
        issues.append(
            Issue(
                id=f"issue-syllable-uncertain-{flagged['id']}",
                type="syllable_uncertain",
                severity="medium",
                perceptual_impact=0.5,
                confidence=uncertainty,
                priority_score=round(0.5 * uncertainty, 4),
                start_s=flagged["start_s"],
                end_s=flagged["end_s"],
                affected_ids=[flagged["id"]],
                suggested_action="review_syllable_boundaries",
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
