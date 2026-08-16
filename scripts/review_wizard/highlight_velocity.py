from __future__ import annotations

from typing import Any

VOWELS = set("aeiouAEIOUáéíóúâêîôûãõàèìòùÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙ")
SUSTAIN_SPLIT_THRESHOLD_S = 1.2
MIN_FRAGMENT_S = 0.08
MAX_ATTACK_S = 0.18
MAX_RELEASE_S = 0.18


def _field(value: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return default


def _time(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round_time(value: float) -> float:
    return round(value, 3)


def _segment_id(word: dict[str, Any], index: int) -> str:
    prefix = str(_field(word, "id", "word_id", default="word"))
    return f"{prefix}:hv-{index}"


def _plain_segment(
    word: dict[str, Any],
    text: str,
    start_s: float,
    end_s: float,
    role: str,
    source: str,
    index: int = 1,
) -> dict[str, Any]:
    return {
        "id": _segment_id(word, index),
        "text": text,
        "start": _round_time(start_s),
        "end": _round_time(end_s),
        "start_s": _round_time(start_s),
        "end_s": _round_time(end_s),
        "role": role,
        "source": source,
    }


def _melisma_end(segment: dict[str, Any], fallback: float) -> float:
    end_s = fallback
    for melisma in segment.get("melisma_segments", []) or []:
        end_s = max(end_s, _time(_field(melisma, "end_s", "end", default=end_s), end_s))
    return end_s


def _explicit_segments(word: dict[str, Any], word_start_s: float, word_end_s: float) -> list[dict[str, Any]]:
    segments = []
    for index, segment in enumerate(word.get("highlight_segments", []) or [], start=1):
        text = str(_field(segment, "text", "word", default="")).strip()
        if not text:
            continue
        start_s = _time(_field(segment, "start_s", "start", default=word_start_s), word_start_s)
        end_s = _time(_field(segment, "end_s", "end", default=word_end_s), word_end_s)
        end_s = _melisma_end(segment, end_s)
        if end_s <= start_s:
            end_s = start_s + MIN_FRAGMENT_S
        segments.append(
            {
                "id": str(_field(segment, "id", default=_segment_id(word, index))),
                "text": text,
                "start": _round_time(start_s),
                "end": _round_time(end_s),
                "start_s": _round_time(start_s),
                "end_s": _round_time(end_s),
                "role": str(_field(segment, "role", "kind", default="highlight")),
                "source": "explicit",
            }
        )
    return segments


def _syllable_segments(word: dict[str, Any], word_start_s: float, word_end_s: float) -> list[dict[str, Any]]:
    raw_syllables = [item for item in word.get("syllables", []) or [] if isinstance(item, dict)]
    if not raw_syllables:
        return []

    segments = []
    for index, syllable in enumerate(raw_syllables, start=1):
        text = str(_field(syllable, "text", "syllable", default="")).strip()
        if not text:
            continue
        start_value = _field(
            syllable,
            "karaoke_start",
            "start",
            "start_s",
            "vowel_start",
            "phonetic_start",
        )
        end_value = _field(syllable, "karaoke_end", "end", "end_s", "phonetic_end")
        if start_value is None or end_value is None:
            return []
        start_s = _time(start_value, word_start_s)
        end_s = _time(end_value, word_end_s)
        end_s = _melisma_end(syllable, end_s)
        if end_s <= start_s:
            end_s = start_s + MIN_FRAGMENT_S
        segments.append(
            {
                "id": str(_field(syllable, "id", "syllable_id", default=_segment_id(word, index))),
                "text": text,
                "start": _round_time(start_s),
                "end": _round_time(end_s),
                "start_s": _round_time(start_s),
                "end_s": _round_time(end_s),
                "role": "syllable",
                "source": "syllable",
            }
        )
    return segments


def _vowel_span(text: str) -> tuple[int, int] | None:
    first = None
    last = None
    for index, char in enumerate(text):
        if char in VOWELS:
            if first is None:
                first = index
            last = index
        elif first is not None:
            break
    if first is None or last is None:
        return None
    return first, last + 1


def _vowel_run_count(text: str) -> int:
    """Number of vowel runs (≈ orthographic syllables) in ``text``."""
    runs = 0
    in_run = False
    for char in text:
        if char in VOWELS:
            if not in_run:
                runs += 1
                in_run = True
        else:
            in_run = False
    return runs


def _fragment_text(text: str) -> tuple[str, str, str] | None:
    span = _vowel_span(text)
    if span is None:
        return None
    start, end = span
    attack = text[:start]
    nucleus = text[start:end]
    release = text[end:]
    if not nucleus:
        return None
    return attack, nucleus, release


def _edge_duration(total_s: float, max_s: float, ratio: float) -> float:
    return min(max_s, max(MIN_FRAGMENT_S, total_s * ratio))


def build_word_highlight_segments(word: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(_field(word, "word", "text", default="")).strip()
    start_s = _time(_field(word, "start", "start_s", default=0.0), 0.0)
    end_s = _time(_field(word, "end", "end_s", default=start_s), start_s)
    if end_s <= start_s:
        end_s = start_s + MIN_FRAGMENT_S

    explicit = _explicit_segments(word, start_s, end_s)
    if explicit:
        return explicit

    syllables = _syllable_segments(word, start_s, end_s)
    if syllables:
        return syllables

    duration_s = end_s - start_s
    fragments = _fragment_text(text)
    # The attack/vowel/release sustain split models ONE held vowel (a sustained
    # note like "br-eaa-k"). Applied to a multi-syllable word it dumps every
    # later syllable into the "release" ("Forfeður" -> F/o/rfeður), which lights
    # up at the wrong moment and reads as random. Only split words with a single
    # vowel run; a multi-syllable word with no measured syllable timing renders
    # whole-word (honest word-level highlight, not a faked sub-word split).
    if (
        duration_s < SUSTAIN_SPLIT_THRESHOLD_S
        or fragments is None
        or _vowel_run_count(text) > 1
    ):
        return [_plain_segment(word, text, start_s, end_s, "normal", "derived")]

    attack_text, vowel_text, release_text = fragments
    attack_s = _edge_duration(duration_s, MAX_ATTACK_S, 0.06) if attack_text else 0.0
    release_s = _edge_duration(duration_s, MAX_RELEASE_S, 0.05) if release_text else 0.0
    vowel_s = duration_s - attack_s - release_s
    if vowel_s < MIN_FRAGMENT_S:
        return [_plain_segment(word, text, start_s, end_s, "normal", "derived")]

    segments: list[dict[str, Any]] = []
    cursor = start_s
    index = 1
    if attack_text:
        next_cursor = cursor + attack_s
        segments.append(_plain_segment(word, attack_text, cursor, next_cursor, "consonant_attack", "derived", index))
        cursor = next_cursor
        index += 1

    next_cursor = end_s - release_s if release_text else end_s
    segments.append(_plain_segment(word, vowel_text, cursor, next_cursor, "sustained_vowel", "derived", index))
    cursor = next_cursor
    index += 1

    if release_text:
        segments.append(_plain_segment(word, release_text, cursor, end_s, "consonant_release", "derived", index))

    return segments


def build_line_highlight_segments(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for word_index, word in enumerate(words, start=1):
        word_with_id = {**word}
        word_with_id.setdefault("id", f"word-{word_index}")
        for segment in build_word_highlight_segments(word_with_id):
            segments.append({**segment, "word_index": word_index})
    return segments
