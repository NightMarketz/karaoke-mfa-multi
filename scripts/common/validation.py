from __future__ import annotations

from collections import Counter


def find_timestamp_errors(
    words: list[dict],
    min_duration: float = 0.001,
    overlap_tolerance_s: float = 0.0,
) -> list[str]:
    """
    Check word timing for invalid durations and overlaps.

    overlap_tolerance_s: how many seconds of backward overlap to allow before
    flagging as an error. CTC forced-alignment can produce small overlaps
    (~20–50 ms) at phrase boundaries that are imperceptible to viewers.
    Set to 0 (default) for strict validation; set to e.g. 0.03 to allow
    up to 30 ms of overlap without failing the job.
    """
    errors: list[str] = []
    prev_end: float | None = None
    for index, word in enumerate(words):
        label = str(word.get("word", f"#{index}"))
        start = float(word.get("start", 0.0))
        end = float(word.get("end", 0.0))
        if end - start < min_duration:
            errors.append(f"Word '{label}' invalid duration: {start:.4f} -> {end:.4f}")
        if prev_end is not None and start < prev_end - overlap_tolerance_s:
            errors.append(f"Word '{label}' overlaps previous: {start:.4f} < {prev_end:.4f}")
        prev_end = max(prev_end if prev_end is not None else end, end)
    return errors


def normalize_words(
    words: list[dict],
    segment_start: float,
    segment_end: float,
    min_duration: float = 0.05,
) -> list[dict]:
    if not words:
        return words

    count = len(words)
    window = max(segment_end - segment_start, min_duration * count)
    slot = window / count
    repaired: list[dict] = []
    prev_end = segment_start

    for index, word in enumerate(words):
        copy = dict(word)
        start = float(copy.get("start", segment_start + index * slot))
        end = float(copy.get("end", start + min_duration))
        slot_start = segment_start + index * slot
        slot_end = segment_end if index == count - 1 else min(segment_end, segment_start + (index + 1) * slot)

        if start < prev_end or end <= start:
            start = max(prev_end, slot_start)
            end = min(slot_end, start + max(min_duration, slot * 0.9))
        if end <= start:
            end = start + min_duration

        copy["start"] = round(start, 4)
        copy["end"] = round(end, 4)
        copy["source"] = copy.get("source", "repaired")
        repaired.append(copy)
        prev_end = copy["end"]

    return repaired


def word_sequence(words: list[dict]) -> list[str]:
    return [
        str(word.get("word", "")).casefold()
        for word in words
        if str(word.get("word", "")).strip()
    ]


def find_word_coverage_errors(aligned_words: list[dict], analysis_words: list[dict]) -> list[str]:
    aligned_counts = Counter(word_sequence(aligned_words))
    analysis_counts = Counter(word_sequence(analysis_words))
    errors: list[str] = []

    for token, expected in aligned_counts.items():
        actual = analysis_counts.get(token, 0)
        if actual < expected:
            errors.append(f"Word '{token}' appears {actual}/{expected} time(s) in analysis")

    return errors
