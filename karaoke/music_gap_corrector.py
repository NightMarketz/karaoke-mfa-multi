"""
music_gap_corrector.py — Logic for snapping word boundaries to voice activity.
Used by 05b_correct_alignment.py.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Set, Tuple
from .textgrid_parser import Interval
from .vad import VADSegment, voice_overlap_ratio


@dataclass
class CorrectorConfig:
    """Tunable parameters for alignment correction."""
    max_word_sec_voice:   float = 4.0      # Longest a word can be if it's in a vocal region
    max_word_sec_silence: float = 1.2      # Longest a word can be if it's in silence/music
    voice_overlap_threshold: float = 0.4   # Ratio of word duration that must be VAD-positive
    max_gap_sec:          float = 2.0      # Gap > this between words triggers a line break


@dataclass
class CorrectionReport:
    """Stats and metadata about the correction run."""
    words_clamped:     int = 0
    lines_split:       int = 0
    initial_sync_offset: float = 0.0
    max_duration_before: float = 0.0
    max_duration_after: float = 0.0
    huge_gaps_before:   int = 0
    unmapped_vocal_regions: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class CorrectedAlignment:
    """Result of gap correction."""
    words: List[Interval]
    line_breaks: Set[int] = field(default_factory=set)
    report: CorrectionReport = field(default_factory=CorrectionReport)


def _find_last_voice_boundary(
    word_start: float,
    word_end: float,
    vad_segments: List[VADSegment],
) -> float | None:
    """
    Find the end of voice activity WITHIN [word_start, word_end].
    Returns the clamped end of the last overlapping VAD segment,
    never exceeding word_end. Returns None if no overlap at all.

    Fix: previously returned seg.end unconditionally, which could be
    far beyond word_end for long VAD segments, defeating the clamp.
    """
    best = None
    for seg in vad_segments:
        overlap_start = max(word_start, seg.start)
        overlap_end   = min(word_end,   seg.end)
        if overlap_end > overlap_start:
            # Clamp to word boundary so we never exceed word_end
            clamped_end = min(seg.end, word_end)
            if best is None or clamped_end > best:
                best = clamped_end
    return best


def correct_alignment(
    words: List[Interval],
    vad_segments: List[VADSegment],
    config: CorrectorConfig | None = None,
) -> CorrectedAlignment:
    """
    Apply music-aware corrections to word-level alignment.

    Rules:
    1. Initial Sync: Anchor first word to first vocal segment if drift detected.
    2. Clamp words based on voice overlap ratio:
       - Mostly in voice → cap at MAX_WORD_SEC_VOICE
       - Mostly in silence → cap at MAX_WORD_SEC_SILENCE (or trim to voice boundary)
    3. Detect gaps > MAX_GAP_SEC between consecutive words → mark line breaks
    4. Ad-lib Detection: Identify vocal segments with no words.
    """
    if config is None:
        config = CorrectorConfig()

    report = CorrectionReport()
    corrected: List[Interval] = []
    line_breaks: Set[int] = set()

    if not words:
        # If no words but VAD exists, it's all ad-libs/instrumentals
        report.unmapped_vocal_regions = [(s.start, s.end) for s in vad_segments]
        return CorrectedAlignment([], set(), report)

    # Pre-compute stats
    report.max_duration_before = max(w.duration for w in words)
    report.huge_gaps_before = _count_huge_gaps(words, config.max_gap_sec)

    # 1. Initial Sync Check
    first_word = words[0]
    if vad_segments:
        first_voice = vad_segments[0]
        # If the first word starts way before the first voice (e.g. 5s gap)
        # OR if the first word spans the first voice but starts too early (drift)
        if first_word.start < first_voice.start - 1.0:
            shift = first_voice.start - first_word.start
            report.initial_sync_offset = shift
            # Note: We don't shift EVERYTHING (that's dangerous), but we clamp the first word's start
            # to be sane. MFA often drifts early in long intros.
            # However, usually the best fix is just to clamp its end later.
    
    # 2. Main correction loop
    mapped_voice_indices = set()

    for i, word in enumerate(words):
        # find overlaps
        overlapping_vad_indices = [
            idx for idx, s in enumerate(vad_segments)
            if max(word.start, s.start) < min(word.end, s.end)
        ]
        mapped_voice_indices.update(overlapping_vad_indices)

        ratio = voice_overlap_ratio(word.start, word.end, vad_segments)

        if ratio >= config.voice_overlap_threshold:
            max_dur = config.max_word_sec_voice
        else:
            max_dur = config.max_word_sec_silence

        new_start = word.start
        new_end = word.end

        # Handle drift start: if this is the first word and it starts way before any voice,
        # move its start forward to the first voice onset.
        # CRITICAL: also shift new_end by the same delta to preserve word duration
        # and avoid creating an Interval with end < start (negative duration).
        if i == 0 and vad_segments and word.start < vad_segments[0].start - 0.5:
            snapped_start = vad_segments[0].start - 0.1
            delta = snapped_start - word.start
            new_start = snapped_start
            new_end   = word.end + delta  # preserve original duration

        if (new_end - new_start) > max_dur:
            if ratio < config.voice_overlap_threshold:
                boundary = _find_last_voice_boundary(new_start, word.end, vad_segments)
                if boundary is not None and boundary > new_start:
                    new_end = min(boundary, new_start + max_dur)
                else:
                    new_end = new_start + max_dur
            else:
                new_end = new_start + max_dur

            report.words_clamped += 1

        corrected.append(Interval(start=new_start, end=new_end, text=word.text))

        # Check gap to NEXT word for line break
        if i < len(words) - 1:
            next_start = words[i + 1].start
            # We use the corrected end of the current word
            gap = next_start - new_end
            if gap > config.max_gap_sec:
                line_breaks.add(i)
                report.lines_split += 1

    # 3. Ad-lib Detection — vocal regions with no lyrics aligned to them.
    # These are exported via CorrectionReport.unmapped_vocal_regions so that
    # downstream steps (e.g. 03c_gemini_transcribe) can use them as adlib hints
    # instead of having Gemini discover them from scratch.
    for idx, seg in enumerate(vad_segments):
        if idx not in mapped_voice_indices:
            # This vocal region has no lyrics aligned to it!
            report.unmapped_vocal_regions.append((seg.start, seg.end))

    # Simétrico a max_duration_before (calculado antes do laço de correção):
    # mede a MESMA grandeza sobre a lista já corrigida, para que o relatório
    # deixe conferir o efeito do clamp em vez de só declarar a intenção dele.
    # `default` cobre o caso de `corrected` vazia — hoje impossível com `words`
    # não-vazia, mas 0.0 mantém a simetria com o retorno antecipado lá em cima.
    report.max_duration_after = max((w.duration for w in corrected), default=0.0)

    return CorrectedAlignment(corrected, line_breaks, report)


def _count_huge_gaps(words: List[Interval], threshold: float) -> int:
    count = 0
    for i in range(1, len(words)):
        gap = words[i].start - words[i - 1].end
        if gap > threshold:
            count += 1
    return count