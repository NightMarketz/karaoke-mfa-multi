from __future__ import annotations

import re

from scripts.review_wizard.contracts import (
    Issue,
    LyricLine,
    PreparedText,
    Syllable,
    TextSection,
    Word,
)


VOWELS = "aeiou\u00e1\u00e9\u00ed\u00f3\u00fa\u00e2\u00ea\u00f4\u00e3\u00f5\u00e0\u00fcAEIOU\u00c1\u00c9\u00cd\u00d3\u00da\u00c2\u00ca\u00d4\u00c3\u00d5\u00c0\u00dc"


def _slug(prefix: str, index: int) -> str:
    return f"{prefix}-{index + 1}"


def _basic_syllables(word: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for char in word:
        current += char
        if char in VOWELS:
            chunks.append(current)
            current = ""
    if current:
        if chunks:
            chunks[-1] += current
        else:
            chunks.append(current)
    return chunks or [word]


def _split_sections(raw_lyrics: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_label = "Verse"
    current_lines: list[str] = []
    for raw in raw_lyrics.splitlines():
        line = raw.strip()
        if not line:
            continue
        marker = re.fullmatch(r"\[([^\]]+)\]", line)
        if marker:
            if current_lines:
                sections.append((current_label, current_lines))
                current_lines = []
            current_label = marker.group(1).strip() or "Verse"
            continue
        current_lines.append(line)
    if current_lines:
        sections.append((current_label, current_lines))
    return sections or [("Verse", [])]


def prepare_text_for_review(raw_lyrics: str, language: str) -> tuple[PreparedText, list[Issue]]:
    issues: list[Issue] = []
    sections: list[TextSection] = []
    line_index = 0
    word_index = 0
    syllable_index = 0

    for section_index, (label, lines) in enumerate(_split_sections(raw_lyrics)):
        lyric_lines: list[LyricLine] = []
        for text in lines:
            words: list[Word] = []
            tokens = re.findall(r"[\w']+", text)
            line_id = _slug("line", line_index)

            if len(tokens) > 14:
                issues.append(
                    Issue(
                        id=f"issue-long-line-{line_index + 1}",
                        type="text_line_too_long",
                        severity="medium",
                        perceptual_impact=0.65,
                        confidence=1.0,
                        priority_score=0.65,
                        start_s=0.0,
                        end_s=0.0,
                        affected_ids=[line_id],
                        suggested_action="split_line",
                    )
                )

            if language == "pt" and re.search(r"\bpara\s+amor\b", text, flags=re.IGNORECASE):
                issues.append(
                    Issue(
                        id=f"issue-contraction-{line_index + 1}",
                        type="possible_contraction",
                        severity="low",
                        perceptual_impact=0.4,
                        confidence=0.7,
                        priority_score=0.4,
                        start_s=0.0,
                        end_s=0.0,
                        affected_ids=[line_id],
                        suggested_action="review_sung_variant",
                    )
                )

            for token in tokens:
                syllables = [
                    Syllable(id=_slug("syllable", syllable_index + offset), text=part)
                    for offset, part in enumerate(_basic_syllables(token))
                ]
                syllable_index += len(syllables)
                words.append(Word(id=_slug("word", word_index), text=token, syllables=syllables))
                word_index += 1

            lyric_lines.append(
                LyricLine(id=line_id, text=text, section=label.lower(), words=words)
            )
            line_index += 1

        sections.append(TextSection(id=_slug("section", section_index), label=label, lines=lyric_lines))

    return PreparedText(language=language, sections=sections), issues
