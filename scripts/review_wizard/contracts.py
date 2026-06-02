from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any


def _clean_dict(value: Any) -> Any:
    if isinstance(value, list):
        return [_clean_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean_dict(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class MelismaSegment:
    id: str
    start_s: float
    end_s: float
    kind: str = "note"
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class HighlightSegment:
    id: str
    text: str
    start_s: float
    end_s: float
    role: str = "highlight"
    source: str = "derived"
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class Syllable:
    id: str
    text: str
    start_s: float | None = None
    end_s: float | None = None
    confidence: float | None = None
    review_status: str = "generated"
    melisma_segments: list[MelismaSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class Word:
    id: str
    text: str
    syllables: list[Syllable] = field(default_factory=list)
    highlight_segments: list[HighlightSegment] = field(default_factory=list)
    start_s: float | None = None
    end_s: float | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class LyricLine:
    id: str
    text: str
    section: str
    words: list[Word] = field(default_factory=list)
    start_s: float | None = None
    end_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class TextSection:
    id: str
    label: str
    lines: list[LyricLine] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class PreparedText:
    language: str
    sections: list[TextSection] = field(default_factory=list)
    source: str = "generated"
    review_status: str = "needs_review"

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class MediaAsset:
    id: str
    kind: str
    path: str
    needs_stem_extraction: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class AlignmentTake:
    id: str
    kind: str
    status: str
    line_ids: list[str] = field(default_factory=list)
    parent_take_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class EditOperation:
    id: str
    operation: str
    target_id: str
    created_by: str
    details: dict[str, Any] = field(default_factory=dict)
    created_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class Issue:
    id: str
    type: str
    severity: str
    perceptual_impact: float
    confidence: float
    priority_score: float
    start_s: float
    end_s: float
    affected_ids: list[str]
    suggested_action: str
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


@dataclass(frozen=True)
class QualityReport:
    id: str
    take_id: str
    status: str
    score: float
    issue_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _clean_dict(asdict(self))


def _melisma_segment_from_dict(data: dict[str, Any]) -> MelismaSegment:
    return MelismaSegment(**data)


def _highlight_segment_from_dict(data: dict[str, Any]) -> HighlightSegment:
    return HighlightSegment(
        id=str(data["id"]),
        text=str(data["text"]),
        start_s=float(data["start_s"]),
        end_s=float(data["end_s"]),
        role=str(data.get("role", "highlight")),
        source=str(data.get("source", "derived")),
        confidence=data.get("confidence"),
    )


def _syllable_from_dict(data: dict[str, Any]) -> Syllable:
    return Syllable(
        id=str(data["id"]),
        text=str(data["text"]),
        start_s=data.get("start_s"),
        end_s=data.get("end_s"),
        confidence=data.get("confidence"),
        review_status=str(data.get("review_status", "generated")),
        melisma_segments=[
            _melisma_segment_from_dict(item) for item in data.get("melisma_segments", [])
        ],
    )


def _word_from_dict(data: dict[str, Any]) -> Word:
    return Word(
        id=str(data["id"]),
        text=str(data["text"]),
        syllables=[_syllable_from_dict(item) for item in data.get("syllables", [])],
        highlight_segments=[
            _highlight_segment_from_dict(item) for item in data.get("highlight_segments", [])
        ],
        start_s=data.get("start_s"),
        end_s=data.get("end_s"),
        confidence=data.get("confidence"),
    )


def _line_from_dict(data: dict[str, Any]) -> LyricLine:
    return LyricLine(
        id=str(data["id"]),
        text=str(data["text"]),
        section=str(data["section"]),
        words=[_word_from_dict(item) for item in data.get("words", [])],
        start_s=data.get("start_s"),
        end_s=data.get("end_s"),
    )


def _section_from_dict(data: dict[str, Any]) -> TextSection:
    return TextSection(
        id=str(data["id"]),
        label=str(data["label"]),
        lines=[_line_from_dict(item) for item in data.get("lines", [])],
    )


def _prepared_text_from_dict(data: dict[str, Any]) -> PreparedText | None:
    if not data:
        return None
    return PreparedText(
        language=str(data["language"]),
        sections=[_section_from_dict(item) for item in data.get("sections", [])],
        source=str(data.get("source", "generated")),
        review_status=str(data.get("review_status", "needs_review")),
    )


@dataclass(frozen=True)
class Project:
    project_id: str
    job_id: str
    schema_version: int = 1
    media_assets: list[MediaAsset] = field(default_factory=list)
    prepared_text: PreparedText | None = None
    evidence_bundle: dict[str, Any] = field(default_factory=dict)
    alignment_takes: list[AlignmentTake] = field(default_factory=list)
    edit_operations: list[EditOperation] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    quality_reports: list[QualityReport] = field(default_factory=list)
    preview_renders: list[dict[str, Any]] = field(default_factory=list)
    approved_take_id: str | None = None
    style_preset_id: str = "default"
    style_overrides: dict[str, Any] = field(default_factory=dict)
    exports: list[dict[str, Any]] = field(default_factory=list)
    wizard_steps: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def new(cls, project_id: str, job_id: str) -> "Project":
        return cls(project_id=project_id, job_id=job_id)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        return cls(
            project_id=str(data["project_id"]),
            job_id=str(data["job_id"]),
            schema_version=int(data.get("schema_version", 1)),
            media_assets=[MediaAsset(**item) for item in data.get("media_assets", [])],
            prepared_text=_prepared_text_from_dict(dict(data.get("prepared_text") or {})),
            evidence_bundle=dict(data.get("evidence_bundle", {})),
            alignment_takes=[AlignmentTake(**item) for item in data.get("alignment_takes", [])],
            edit_operations=[EditOperation(**item) for item in data.get("edit_operations", [])],
            issues=[Issue(**item) for item in data.get("issues", [])],
            quality_reports=[QualityReport(**item) for item in data.get("quality_reports", [])],
            preview_renders=list(data.get("preview_renders", [])),
            approved_take_id=data.get("approved_take_id"),
            style_preset_id=str(data.get("style_preset_id", "default")),
            style_overrides=dict(data.get("style_overrides", {})),
            exports=list(data.get("exports", [])),
            wizard_steps=dict(data.get("wizard_steps", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.prepared_text is None:
            payload["prepared_text"] = {}
        return _clean_dict(payload)

    def with_alignment_take(self, take: AlignmentTake) -> "Project":
        return replace(self, alignment_takes=[*self.alignment_takes, take])

    def with_edit_operation(self, operation: EditOperation) -> "Project":
        return replace(self, edit_operations=[*self.edit_operations, operation])

    def with_issue(self, issue: Issue) -> "Project":
        return replace(self, issues=[*self.issues, issue])

    def with_quality_report(self, report: QualityReport) -> "Project":
        return replace(self, quality_reports=[*self.quality_reports, report])
