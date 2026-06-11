from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from math import isfinite
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReviewPoint:
    id: str
    stage_id: str
    level: str
    text: str
    start_s: float
    end_s: float
    parent_id: str | None = None
    source: str = "analysis"
    status: str = "open"
    priority: float = 0.0
    issue_ids: list[str] = field(default_factory=list)
    severity: str = "info"
    affected_ids: list[str] = field(default_factory=list)
    suggested_action: str = ""
    evidence_summary: str = ""
    tags: list[dict[str, str]] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return round(max(0.0, self.end_s - self.start_s), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage_id": self.stage_id,
            "level": self.level,
            "text": self.text,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "duration_s": self.duration_s,
            "parent_id": self.parent_id,
            "source": self.source,
            "status": self.status,
            "priority": self.priority,
            "issue_ids": list(self.issue_ids),
            "severity": self.severity,
            "affected_ids": list(self.affected_ids),
            "suggested_action": self.suggested_action,
            "evidence_summary": self.evidence_summary,
            "tags": [dict(tag) for tag in self.tags],
        }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _review_status(project: Any, point_id: str) -> str:
    for operation in reversed(getattr(project, "edit_operations", [])):
        if getattr(operation, "target_id", "") != point_id:
            continue
        operation_name = getattr(operation, "operation", "")
        if operation_name == "approve_review_point":
            return "approved"
        if operation_name == "apply_review_point_suggestion":
            return "suggestion_applied"
        if operation_name == "skip_review_point_with_risk":
            return "skipped_with_risk"
        if operation_name == "adjust_review_point_timing":
            return "edited"
    return "open"


def _timing_override(project: Any, point_id: str) -> dict[str, float] | None:
    for operation in reversed(getattr(project, "edit_operations", [])):
        if getattr(operation, "target_id", "") != point_id:
            continue
        if getattr(operation, "operation", "") != "adjust_review_point_timing":
            continue
        details = getattr(operation, "details", {})
        try:
            start_s = float(details["start_s"])
            end_s = float(details["end_s"])
        except (KeyError, TypeError, ValueError):
            return None
        return {"start_s": start_s, "end_s": end_s}
    return None


def _apply_timing_edits(points: list[ReviewPoint], project: Any) -> list[ReviewPoint]:
    edited: list[ReviewPoint] = []
    for point in points:
        override = _timing_override(project, point.id)
        if override is None:
            edited.append(point)
            continue
        edited.append(replace(point, start_s=override["start_s"], end_s=override["end_s"]))
    return edited


def _issue_overlaps_point(issue: Any, point: ReviewPoint) -> bool:
    affected_ids = getattr(issue, "affected_ids", [])
    if point.id in affected_ids:
        return True
    return float(getattr(issue, "start_s", 0.0)) <= point.end_s and float(getattr(issue, "end_s", 0.0)) >= point.start_s


def _decorate_with_issues(points: list[ReviewPoint], project: Any) -> list[ReviewPoint]:
    decorated: list[ReviewPoint] = []
    for point in points:
        matching = [
            issue
            for issue in getattr(project, "issues", [])
            if getattr(issue, "status", "open") == "open" and _issue_overlaps_point(issue, point)
        ]
        if not matching:
            decorated.append(point)
            continue

        matching.sort(key=lambda issue: float(getattr(issue, "priority_score", 0.0)), reverse=True)
        top_issue = matching[0]
        decorated.append(
            replace(
                point,
                priority=max(point.priority, float(getattr(top_issue, "priority_score", 0.0))),
                issue_ids=[str(getattr(issue, "id", "")) for issue in matching],
                severity=str(getattr(top_issue, "severity", "info")),
                affected_ids=list(getattr(top_issue, "affected_ids", [])),
                suggested_action=str(getattr(top_issue, "suggested_action", "")),
            )
        )
    return decorated


def _readable_issue_text(issue: Any) -> str:
    issue_type = str(getattr(issue, "type", "")).replace("_", " ").strip()
    suggested_action = str(getattr(issue, "suggested_action", "")).replace("_", " ").strip()
    if issue_type and suggested_action:
        return f"{issue_type}: {suggested_action}"
    return issue_type or suggested_action


def _has_valid_issue_timestamp(issue: Any) -> bool:
    try:
        start_s = float(getattr(issue, "start_s", 0.0))
        end_s = float(getattr(issue, "end_s", 0.0))
    except (TypeError, ValueError):
        return False
    return end_s > start_s


def _quality_issue_points(project: Any) -> list[ReviewPoint]:
    points: list[ReviewPoint] = []
    for issue in getattr(project, "issues", []):
        if getattr(issue, "status", "open") != "open" or not _has_valid_issue_timestamp(issue):
            continue
        issue_id = str(getattr(issue, "id", ""))
        point_id = f"issue:{issue_id}"
        points.append(
            ReviewPoint(
                id=point_id,
                stage_id="quality",
                level="issue",
                text=_readable_issue_text(issue),
                start_s=float(getattr(issue, "start_s")),
                end_s=float(getattr(issue, "end_s")),
                source="issue",
                status=_review_status(project, point_id),
                priority=float(getattr(issue, "priority_score", 0.0)),
                issue_ids=[issue_id],
                severity=str(getattr(issue, "severity", "info")),
                affected_ids=list(getattr(issue, "affected_ids", [])),
                suggested_action=str(getattr(issue, "suggested_action", "")),
            )
        )
    return points


def _audio_timing_text(diagnostic: dict[str, Any]) -> str:
    classification = str(
        diagnostic.get("tail_classification")
        or diagnostic.get("line_classification")
        or "audio_timing_review"
    ).replace("_", " ")
    suggestion = diagnostic.get("sound_suggestion") if isinstance(diagnostic.get("sound_suggestion"), dict) else {}
    caption = str(suggestion.get("suggested_caption") or "").strip()
    sound_type = str(suggestion.get("sound_type") or "").replace("_", " ").strip()
    review_flags = diagnostic.get("review_flags", [])
    if not isinstance(review_flags, list):
        review_flags = []
    flags = [str(flag).replace("_", " ") for flag in review_flags if str(flag).strip()]
    parts = [classification]
    if caption:
        parts.append(caption)
    if sound_type:
        parts.append(sound_type)
    parts.extend(flags)
    return ": ".join(parts)


def _audio_timing_bounds(diagnostic: dict[str, Any], line: dict[str, Any]) -> tuple[float, float]:
    evidence = diagnostic.get("audio_evidence") if isinstance(diagnostic.get("audio_evidence"), dict) else {}
    start_s = _finite_float(evidence.get("start_s"))
    end_s = _finite_float(evidence.get("end_s"))
    if start_s is None or end_s is None:
        start_s = _finite_float(line.get("start")) or 0.0
        end_s = _finite_float(line.get("end")) or start_s
    if end_s <= start_s:
        start_s = _finite_float(line.get("start")) or 0.0
        end_s = _finite_float(line.get("end")) or start_s
    return start_s, end_s


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _audio_timing_evidence_summary(diagnostic: dict[str, Any]) -> str:
    evidence = diagnostic.get("audio_evidence") if isinstance(diagnostic.get("audio_evidence"), dict) else {}
    start_s = _finite_float(evidence.get("start_s"))
    end_s = _finite_float(evidence.get("end_s"))
    voiced_ratio = _finite_float(evidence.get("voiced_ratio"))
    parts: list[str] = []
    if start_s is not None and end_s is not None and end_s > start_s:
        parts.append(f"audio {start_s:.2f}-{end_s:.2f}s")
    if voiced_ratio is not None:
        parts.append(f"voiced {voiced_ratio:.2f}")
    return " | ".join(parts)


REVIEW_ONLY_AUDIO_CLASSES = {
    "possible_lost_tail",
    "unwritten_interline_melisma",
}

FRIENDLY_TAG_LABELS = {
    "alignment_drift": "DFT",
    "early_next_line_entry_drift": "DFT",
    "final_word_after_alignment_hole": "A-HOLE",
    "false_long_tail": "F-TAIL",
    "inactive_or_false_tail": "F-TAIL",
    "line_low_vocal_evidence": "L-VOC",
    "long_structural_pause_audio_extension": "L-PAU",
    "possible_backing_or_alignment_issue": "B/ALG?",
    "possible_backing_vocal_not_in_lyrics": "BV?",
    "possible_lost_tail": "L-TAIL?",
    "possible_sustained_final_vowel": "P-SUS",
    "probable_unwritten_vowel_extension": "U-SUS",
    "review_only": "RO",
    "review_only_backing_or_drift": "B/DFT",
    "review_only_low_vocal_evidence": "L-VOC",
    "structural_pause_overridden_by_audio_tail": "P-OVR",
    "sustained_final_vowel": "SUS",
    "unwritten_interline_melisma": "U-MEL",
    "unwritten_vocal_melisma": "VOC",
    "written_melisma_extension": "W-MEL",
}

TAG_TITLES = {
    "alignment_drift": "Drift",
    "early_next_line_entry_drift": "Drift",
    "final_word_after_alignment_hole": "Alignment hole",
    "false_long_tail": "False tail",
    "inactive_or_false_tail": "False tail",
    "line_low_vocal_evidence": "Low vocal evidence",
    "long_structural_pause_audio_extension": "Long pause",
    "possible_backing_or_alignment_issue": "Backing/alignment?",
    "possible_backing_vocal_not_in_lyrics": "Backing vocal?",
    "possible_lost_tail": "Lost tail?",
    "possible_sustained_final_vowel": "Possible sustain",
    "probable_unwritten_vowel_extension": "Unwritten sustain",
    "review_only": "Review only",
    "review_only_backing_or_drift": "Backing/drift",
    "review_only_low_vocal_evidence": "Low vocal evidence",
    "structural_pause_overridden_by_audio_tail": "Pause override",
    "sustained_final_vowel": "Sustain",
    "unwritten_interline_melisma": "Unwritten melisma",
    "unwritten_vocal_melisma": "Vocalization",
    "written_melisma_extension": "Written melisma",
}


def _tag_key(value: str) -> str:
    return value.replace(" ", "_").strip().lower()


def _tag_label(value: str) -> str:
    normalized = _tag_key(value)
    return FRIENDLY_TAG_LABELS.get(normalized, value.replace("_", " ").strip().upper())


def _tag_title(value: str) -> str:
    normalized = _tag_key(value)
    fallback = value.replace("_", " ").strip()
    return TAG_TITLES.get(normalized, fallback.capitalize())


def _add_audio_timing_tag(
    tags: list[dict[str, str]],
    seen: set[str],
    value: Any,
    kind: str,
    css_class: str,
) -> None:
    raw = str(value or "").strip()
    if not raw:
        return
    key = raw.replace(" ", "_").lower()
    if key in seen:
        return
    seen.add(key)
    tags.append(
        {
            "label": _tag_label(raw),
            "title": _tag_title(raw),
            "kind": kind,
            "class": css_class,
            "value": raw,
        }
    )


def _audio_timing_classifications(diagnostic: dict[str, Any]) -> list[str]:
    classifications: list[str] = []
    for key in ("tail_classification", "line_classification"):
        value = str(diagnostic.get(key) or "").strip()
        if value:
            classifications.append(value)
    return classifications


def _audio_timing_tags(diagnostic: dict[str, Any]) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    seen: set[str] = set()
    classifications = _audio_timing_classifications(diagnostic)

    has_review_only_class = any(
        classification.startswith("review_only_") or classification in REVIEW_ONLY_AUDIO_CLASSES
        for classification in classifications
    )
    if has_review_only_class:
        _add_audio_timing_tag(tags, seen, "review_only", "review_state", "tag-warn")

    for classification in classifications:
        _add_audio_timing_tag(tags, seen, classification, "classification", "tag-cyan")

    diagnostic_tags = diagnostic.get("diagnostic_tags", [])
    if isinstance(diagnostic_tags, list):
        for tag in diagnostic_tags:
            _add_audio_timing_tag(tags, seen, tag, "diagnostic", "tag-purple")

    review_flags = diagnostic.get("review_flags", [])
    if isinstance(review_flags, list):
        for flag in review_flags:
            _add_audio_timing_tag(tags, seen, flag, "review_flag", "tag-warn")

    suggestion = diagnostic.get("sound_suggestion") if isinstance(diagnostic.get("sound_suggestion"), dict) else {}
    _add_audio_timing_tag(tags, seen, suggestion.get("sound_type"), "sound_type", "tag-purple")
    return tags


def _audio_timing_points(job_dir: Path, lines: list[dict[str, Any]], project: Any) -> list[ReviewPoint]:
    manifest = _load_json(job_dir / "output.ass.manifest.json")
    timing_audio_layers = manifest.get("timing_audio_layers") if isinstance(manifest.get("timing_audio_layers"), dict) else {}
    diagnostics = timing_audio_layers.get("diagnostics") if isinstance(timing_audio_layers.get("diagnostics"), list) else []
    points: list[ReviewPoint] = []
    for index, diagnostic in enumerate(diagnostics, start=1):
        if not isinstance(diagnostic, dict):
            continue
        try:
            line_index = int(diagnostic.get("line_index", -1))
        except (TypeError, ValueError):
            continue
        if not (0 <= line_index < len(lines)):
            continue
        line = lines[line_index]
        start_s, end_s = _audio_timing_bounds(diagnostic, line)
        if end_s <= start_s:
            continue
        suggestion = diagnostic.get("sound_suggestion") if isinstance(diagnostic.get("sound_suggestion"), dict) else {}
        suggested_action = str(suggestion.get("suggested_user_action") or diagnostic.get("recommended_fallback") or "review_audio_timing")
        classification = str(diagnostic.get("tail_classification") or diagnostic.get("line_classification") or "audio_timing")
        point_id = f"timing-audio:line-{line_index + 1}:{index}"
        points.append(
            ReviewPoint(
                id=point_id,
                stage_id="quality",
                level="issue",
                text=_audio_timing_text(diagnostic),
                start_s=start_s,
                end_s=end_s,
                source="timing_audio",
                status=_review_status(project, point_id),
                priority=0.65,
                severity="medium",
                affected_ids=[f"line-{line_index + 1}"],
                suggested_action=suggested_action,
                issue_ids=[classification],
                evidence_summary=_audio_timing_evidence_summary(diagnostic),
                tags=_audio_timing_tags(diagnostic),
            )
        )
    return points


def build_review_points(job_dir: Path, project: Any) -> list[ReviewPoint]:
    analysis = _load_json(job_dir / "analysis.json")
    aligned = _load_json(job_dir / "aligned.json")
    aligned_words = aligned.get("words", [])
    if not isinstance(aligned_words, list):
        aligned_words = []
    points: list[ReviewPoint] = []

    for line_index, line in enumerate(analysis.get("lines", []), start=1):
        if "start" not in line or "end" not in line:
            continue
        line_id = f"line-{line_index}"
        points.append(
            ReviewPoint(
                id=line_id,
                stage_id="alignment",
                level="line",
                text=str(line.get("text", "")),
                start_s=float(line["start"]),
                end_s=float(line["end"]),
                priority=0.2,
                status=_review_status(project, line_id),
            )
        )

        words = line.get("words", [])
        word_source = "analysis"
        if not words:
            words = [
                word
                for word in aligned_words
                if "start" in word
                and "end" in word
                and float(word["start"]) >= float(line["start"])
                and float(word["end"]) <= float(line["end"])
            ]
            word_source = "aligned"

        for word_index, word in enumerate(words, start=1):
            if "start" not in word or "end" not in word:
                continue
            word_id = f"{line_id}:word-{word_index}"
            points.append(
                ReviewPoint(
                    id=word_id,
                    stage_id="alignment",
                    level="word",
                    text=str(word.get("word", "")),
                    start_s=float(word["start"]),
                    end_s=float(word["end"]),
                    parent_id=line_id,
                    source=word_source,
                    priority=0.1,
                    status=_review_status(project, word_id),
                )
            )

    decorated_points = _decorate_with_issues(points, project)
    audio_timing_points = _audio_timing_points(job_dir, analysis.get("lines", []), project)
    return _apply_timing_edits(decorated_points + _quality_issue_points(project) + audio_timing_points, project)


def points_for_stage(points: list[ReviewPoint], stage_id: str) -> list[ReviewPoint]:
    return [point for point in points if point.stage_id == stage_id]


def filtered_review_points(
    points: list[ReviewPoint],
    stage_id: str,
    status_filter: str = "all",
    level_filter: str = "all",
) -> list[ReviewPoint]:
    status_filter = status_filter if status_filter in {"all", "open", "reviewed"} else "all"
    level_filter = level_filter if level_filter in {"all", "line", "word", "issue"} else "all"
    filtered = points_for_stage(points, stage_id)
    if status_filter == "open":
        filtered = [point for point in filtered if point.status == "open"]
    elif status_filter == "reviewed":
        filtered = [point for point in filtered if point.status != "open"]
    if level_filter != "all":
        filtered = [point for point in filtered if point.level == level_filter]
    return filtered


def next_open_point(points: list[ReviewPoint], stage_id: str) -> ReviewPoint | None:
    candidates = [point for point in points if point.stage_id == stage_id and point.status == "open"]
    if not candidates:
        return None
    return sorted(candidates, key=lambda point: (-point.priority, point.start_s, point.id))[0]


def next_open_point_after(points: list[ReviewPoint], active_point_id: str | None) -> ReviewPoint | None:
    if not points:
        return None
    active_index = -1
    if active_point_id:
        for index, point in enumerate(points):
            if point.id == active_point_id:
                active_index = index
                break
    ordered = points[active_index + 1 :] + points[: active_index + 1]
    return next((point for point in ordered if point.status == "open"), None)


def point_navigation(points: list[ReviewPoint], active_point_id: str | None) -> dict[str, Any]:
    if not points:
        return {
            "position": 0,
            "total": 0,
            "previous_id": None,
            "next_id": None,
            "next_open_id": None,
        }
    active_index = 0
    if active_point_id:
        for index, point in enumerate(points):
            if point.id == active_point_id:
                active_index = index
                break
    next_open = next_open_point_after(points, points[active_index].id)
    return {
        "position": active_index + 1,
        "total": len(points),
        "previous_id": points[active_index - 1].id if active_index > 0 else None,
        "next_id": points[active_index + 1].id if active_index + 1 < len(points) else None,
        "next_open_id": next_open.id if next_open else None,
    }


def review_point_window(
    points: list[ReviewPoint],
    active_point_id: str | None,
    window_size: int = 12,
) -> dict[str, Any]:
    if not points:
        return {
            "items": [],
            "start": 0,
            "end": 0,
            "total": 0,
            "has_previous": False,
            "has_next": False,
        }
    window_size = max(1, window_size)
    active_index = 0
    if active_point_id:
        for index, point in enumerate(points):
            if point.id == active_point_id:
                active_index = index
                break
    half_window = window_size // 2
    start_index = max(0, active_index - half_window)
    end_index = min(len(points), start_index + window_size)
    start_index = max(0, end_index - window_size)
    return {
        "items": points[start_index:end_index],
        "start": start_index + 1,
        "end": end_index,
        "total": len(points),
        "has_previous": start_index > 0,
        "has_next": end_index < len(points),
    }
