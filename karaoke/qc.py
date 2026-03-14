"""
qc.py — Pure Quality-Control logic.
No subprocess, no file I/O.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class QCReport:
    total_words: int = 0
    too_short: int = 0       # dur < min_word_s
    too_long: int = 0        # dur > max_word_s
    huge_gaps: int = 0       # gap between consecutive words > max_gap_s
    max_gap_found: float = 0.0
    top_durations: List[Tuple[float, str]] = field(default_factory=list)
    p95_duration: float = 0.0
    duration_span: float = 0.0 # timestamp range between first and last word

    @property
    def pct_short(self) -> float:
        if self.total_words == 0:
            return 0.0
        return (self.too_short / self.total_words) * 100

    @property
    def pct_long(self) -> float:
        if self.total_words == 0:
            return 0.0
        return (self.too_long / self.total_words) * 100


def qc_words(
    words: list,          # List[Interval] from textgrid_parser
    max_word_s: float = 1.2,
    min_word_s: float = 0.03,
    max_gap_s: float = 0.5,
    top_n: int = 20,
) -> QCReport:
    """
    Compute quality metrics over a list of aligned Interval objects.
    Pure function — no I/O.
    """
    report = QCReport(total_words=len(words))
    durations: List[Tuple[float, str]] = []

    for i, w in enumerate(words):
        dur = w.duration
        durations.append((dur, w.text))

        if dur > max_word_s:
            report.too_long += 1
        if dur < min_word_s:
            report.too_short += 1

        if i > 0:
            gap = w.start - words[i - 1].end
            if gap > report.max_gap_found:
                report.max_gap_found = gap
            if gap > max_gap_s:
                report.huge_gaps += 1

    durations.sort(key=lambda x: x[0], reverse=True)
    report.top_durations = durations[:top_n]
    
    if report.total_words > 0:
        report.duration_span = words[-1].end - words[0].start
        
        # Calculate P95 Duration length
        # Durations are sorted strictly by reverse inside loop logic above:
        p95_index = max(0, int(len(durations) * 0.05))
        report.p95_duration = durations[p95_index][0]

    return report


def should_fail(
    report: QCReport,
    pct_thresh: float = 5.0,
    min_density_words_per_minute: int = 2,
    audio_duration_s: float | None = None
) -> Tuple[bool, str]:
    """
    Returns (failed, reason).
    ``failed`` is True when any metric exceeds the threshold.
    """
    if report.total_words == 0:
        return True, "Zero words in TextGrid — alignment produced nothing."

    reasons = []
    
    # Check Density (if total length is known, like we have from MFA or manually extracted)
    if audio_duration_s and audio_duration_s > 0:
        minutes = audio_duration_s / 60.0
        wpm = report.total_words / minutes
        if wpm < min_density_words_per_minute:
            reasons.append(f"Muitas palavras perdidas (Densidade baixíssima: {wpm:.1f} WPM, esperado: {min_density_words_per_minute}). MFA não alinhou a letra.")

    # High p95 duration is a proxy for bad general alignments (everything stretched out)
    if report.p95_duration > 1.8:
        reasons.append(f"P95 Word Duration ({report.p95_duration:.2f}s) além do tolerável (>1.8s). Provável desalinhamento geral ou letra incorreta.")

    if report.pct_long > pct_thresh:
        reasons.append(
            f"{report.pct_long:.1f}% of words > max duration "
            f"({report.too_long}/{report.total_words}). "
            "Possible causes: lyrics mismatch, vocal bleed, wrong tier."
        )
    if report.pct_short > pct_thresh:
        reasons.append(
            f"{report.pct_short:.1f}% of words < min duration "
            f"({report.too_short}/{report.total_words}). "
            "Possible cause: OOV / G2P dictionary missing."
        )

    if reasons:
        return True, " | ".join(reasons)
    return False, "OK"
