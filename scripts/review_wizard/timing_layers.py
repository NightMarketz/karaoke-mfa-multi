from __future__ import annotations

from typing import Any
import re
from pathlib import Path
import copy

from scripts.review_wizard.vocal_activity import VocalActivityProbe

BAD_GAP_THRESHOLD_S = 1.20
INSTRUMENTAL_PAUSE_THRESHOLD_S = 3.00
BREATH_GAP_THRESHOLD_S = 0.45
TAIL_SUSTAIN_THRESHOLD_S = 1.20
LOST_TAIL_MAX_WORD_S = 0.45
AUDIO_EXTENSION_MAX_FINAL_WORD_S = 0.60
WRITTEN_MELISMA_MIN_ATTACHED_TAIL_S = 0.20
MUSICAL_PAUSE_STYLES = {"outro", "intro", "ad_lib"}
SAFE_EXTENSION_CLASSES = {
    "probable_unwritten_vowel_extension",
    "written_melisma_extension",
}


def is_review_only_audio_timing(timing: dict[str, Any]) -> bool:
    return str(timing.get("line_classification") or "").startswith("review_only")


def _time(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _line_style(line: dict[str, Any]) -> str:
    return str(line.get("style") or line.get("section") or "").strip().lower()


def _word_text(word: dict[str, Any]) -> str:
    return str(word.get("word") or word.get("text") or "").strip()


def _normalized_line_text(line: dict[str, Any]) -> str:
    text = str(line.get("text") or " ".join(_word_text(word) for word in line.get("words") or []))
    return " ".join(re.findall(r"[a-z0-9']+", text.lower()))


def _sustain_type(text: str) -> str:
    clean = "".join(re.findall(r"[a-z]+", text.lower()))
    if re.search(r"([aeiou])\1{2,}", clean) or re.search(r"([hmw])\1{3,}", clean):
        return "melisma"
    return "vowel_extension"


def _is_textual_melisma(text: str) -> bool:
    return _sustain_type(text) == "melisma"


def _sound_suggestion(
    *,
    sound_type: str,
    suggested_caption: str,
    suggested_user_action: str,
) -> dict[str, str]:
    return {
        "sound_type": sound_type,
        "suggested_caption": suggested_caption,
        "suggested_user_action": suggested_user_action,
    }


def _word_extension_caption(word: str) -> str:
    clean = word.strip()
    return f"{clean}..." if clean else "[vocalizacao]"


def _has_final_word_after_alignment_hole(timing: dict[str, Any], words: list[dict[str, Any]]) -> bool:
    for gap in timing.get("inter_word_gaps", []):
        if gap.get("classification") != "bad_gap":
            continue
        before_word_index = int(gap.get("before_word_index", -1))
        if before_word_index != len(words) - 1:
            continue
        before_word = words[before_word_index]
        before_start_s = _time(before_word.get("start", before_word.get("start_s")), 0.0)
        before_end_s = _time(before_word.get("end", before_word.get("end_s")), before_start_s)
        if max(0.0, before_end_s - before_start_s) <= LOST_TAIL_MAX_WORD_S:
            return True
    return False


def _has_short_first_word_entry_drift(timing: dict[str, Any], words: list[dict[str, Any]]) -> bool:
    if len(words) < 2:
        return False
    first_word = words[0]
    first_start_s = _time(first_word.get("start", first_word.get("start_s")), 0.0)
    first_end_s = _time(first_word.get("end", first_word.get("end_s")), first_start_s)
    if max(0.0, first_end_s - first_start_s) > LOST_TAIL_MAX_WORD_S:
        return False
    return any(
        gap.get("classification") == "bad_gap" and int(gap.get("after_word_index", -1)) == 0
        for gap in timing.get("inter_word_gaps", [])
    )


def _has_large_internal_alignment_hole(timing: dict[str, Any]) -> bool:
    return any(
        gap.get("classification") == "bad_gap"
        and float(gap.get("gap_s", 0.0)) >= INSTRUMENTAL_PAUSE_THRESHOLD_S
        for gap in timing.get("inter_word_gaps", [])
    )


def _classify_inter_word_gap(gap_s: float, *, style: str) -> str:
    if gap_s >= BAD_GAP_THRESHOLD_S:
        if style in MUSICAL_PAUSE_STYLES:
            if gap_s >= INSTRUMENTAL_PAUSE_THRESHOLD_S:
                return "instrumental_pause"
            return "musical_pause"
        return "bad_gap"
    if gap_s >= BREATH_GAP_THRESHOLD_S:
        return "breath_gap"
    return "small_gap"


def classify_line_timing(
    line: dict[str, Any],
    next_line: dict[str, Any] | None = None,
    known_tail_melisma_lines: set[str] | None = None,
) -> dict[str, Any]:
    words = list(line.get("words") or [])
    style = _line_style(line)
    inter_word_gaps: list[dict[str, Any]] = []
    vocal_periods: list[dict[str, Any]] = []

    for index in range(1, len(words)):
        previous = words[index - 1]
        current = words[index]
        previous_end = _time(previous.get("end", previous.get("end_s")), 0.0)
        current_start = _time(current.get("start", current.get("start_s")), previous_end)
        gap_s = max(0.0, current_start - previous_end)
        inter_word_gaps.append(
            {
                "after_word_index": index - 1,
                "before_word_index": index,
                "after_word": _word_text(previous),
                "before_word": _word_text(current),
                "gap_s": round(gap_s, 3),
                "classification": _classify_inter_word_gap(gap_s, style=style),
            }
        )

    for index, word in enumerate(words):
        start_s = _time(word.get("start", word.get("start_s")), 0.0)
        end_s = _time(word.get("end", word.get("end_s")), start_s)
        duration_s = max(0.0, end_s - start_s)
        if duration_s >= TAIL_SUSTAIN_THRESHOLD_S or _is_textual_melisma(_word_text(word)):
            vocal_periods.append(
                {
                    "word_index": index,
                    "word": _word_text(word),
                    "start_s": round(start_s, 3),
                    "end_s": round(end_s, 3),
                    "duration_s": round(duration_s, 3),
                    "classification": _sustain_type(_word_text(word)),
                }
            )

    tail: dict[str, Any] = {"classification": "none"}
    if words:
        last_word = words[-1]
        last_start = _time(last_word.get("start", last_word.get("start_s")), 0.0)
        last_end = _time(last_word.get("end", last_word.get("end_s")), last_start)
        duration_s = max(0.0, last_end - last_start)
        next_gap_s = 0.0
        if next_line is not None:
            next_gap_s = max(0.0, _time(next_line.get("start"), last_end) - last_end)
        sustain_type = _sustain_type(_word_text(last_word))
        if duration_s >= TAIL_SUSTAIN_THRESHOLD_S or sustain_type == "melisma":
            classification = f"tail_{sustain_type}"
        elif (
            next_gap_s >= BAD_GAP_THRESHOLD_S
            and duration_s <= LOST_TAIL_MAX_WORD_S
            and _normalized_line_text(line) in (known_tail_melisma_lines or set())
        ):
            classification = "possible_lost_tail"
        elif next_gap_s >= INSTRUMENTAL_PAUSE_THRESHOLD_S:
            classification = "instrumental_pause"
        elif next_gap_s >= BAD_GAP_THRESHOLD_S:
            classification = "musical_pause"
        else:
            classification = "none"
        tail = {
            "word_index": len(words) - 1,
            "word": _word_text(last_word),
            "duration_s": round(duration_s, 3),
            "next_gap_s": round(next_gap_s, 3),
            "classification": classification,
            "sustain_type": sustain_type,
        }

    return {
        "style": style,
        "inter_word_gaps": inter_word_gaps,
        "vocal_periods": vocal_periods,
        "tail": tail,
    }


def build_audio_backed_timing(
    lines: list[dict[str, Any]],
    *,
    audio_activity: dict[Any, dict[str, Any]],
) -> list[dict[str, Any]]:
    timings: list[dict[str, Any]] = []
    for line_index, line in enumerate(lines):
        next_line = lines[line_index + 1] if line_index + 1 < len(lines) else None
        timing = classify_line_timing(line, next_line=next_line, known_tail_melisma_lines=set())
        words = list(line.get("words") or [])

        audio_vocal_periods = []
        for word_index, word in enumerate(words):
            stats = audio_activity.get((line_index, word_index), {})
            text = _word_text(word)
            start_s = _time(word.get("start", word.get("start_s")), 0.0)
            end_s = _time(word.get("end", word.get("end_s")), start_s)
            duration_s = max(0.0, end_s - start_s)
            if stats.get("active") and (duration_s >= TAIL_SUSTAIN_THRESHOLD_S or _is_textual_melisma(text)):
                audio_vocal_periods.append(
                    {
                        "word_index": word_index,
                        "word": text,
                        "start_s": round(start_s, 3),
                        "end_s": round(end_s, 3),
                        "duration_s": round(duration_s, 3),
                        "classification": _sustain_type(text),
                        "audio_evidence": stats,
                    }
                )
        timing["vocal_periods"] = audio_vocal_periods

        if words:
            tail = dict(timing["tail"])
            tail_key = ("tail", line_index)
            tail_stats = audio_activity.get(tail_key, {})
            tail_regions = audio_activity.get(("tail_regions", line_index), [])
            last_word_index = len(words) - 1
            last_word = words[last_word_index]
            last_word_text = _word_text(last_word)
            is_textual_tail_melisma = _is_textual_melisma(last_word_text)
            if isinstance(tail_regions, list) and tail_regions:
                tail_start_s = _time(tail_stats.get("start_s"), 0.0)
                attach_window_s = 0.75 if is_textual_tail_melisma else 0.35
                attached_regions = [
                    region
                    for region in tail_regions
                    if _time(region.get("start_s"), tail_start_s) <= tail_start_s + attach_window_s
                ]
                if attached_regions:
                    tail_stats = dict(attached_regions[0])
            last_word_stats = audio_activity.get((line_index, last_word_index), {})
            is_written_melisma_tail = (
                tail.get("classification") == "tail_melisma"
                and is_textual_tail_melisma
            )
            can_extend_written_melisma = (
                is_written_melisma_tail
                and tail_stats.get("active")
                and float(tail_stats.get("voiced_ratio", 0.0)) >= 0.55
                and float(tail_stats.get("duration_s", 0.0)) >= WRITTEN_MELISMA_MIN_ATTACHED_TAIL_S
            )
            can_promote_audio_tail = (
                tail_stats.get("active")
                and float(tail_stats.get("voiced_ratio", 0.0)) >= 0.75
                and float(tail.get("duration_s", 0.0)) <= AUDIO_EXTENSION_MAX_FINAL_WORD_S
                and float(tail.get("next_gap_s", 0.0)) >= BAD_GAP_THRESHOLD_S
            )
            can_flag_possible_lost_tail = (
                tail_stats.get("active")
                and float(tail_stats.get("voiced_ratio", 0.0)) >= 0.55
                and float(tail_stats.get("duration_s", 0.0)) >= 0.75
                and float(tail.get("duration_s", 0.0)) <= AUDIO_EXTENSION_MAX_FINAL_WORD_S
                and float(tail.get("next_gap_s", 0.0)) >= BAD_GAP_THRESHOLD_S
            )
            can_flag_interline_melisma = (
                tail_stats.get("active")
                and float(tail_stats.get("voiced_ratio", 0.0)) >= 0.60
                and float(tail_stats.get("duration_s", 0.0)) >= 0.75
                and float(tail.get("duration_s", 0.0)) >= TAIL_SUSTAIN_THRESHOLD_S
            )
            has_structural_drift_gap = any(gap.get("classification") == "bad_gap" for gap in timing.get("inter_word_gaps", []))
            has_long_final_word = float(tail.get("duration_s", 0.0)) >= 2.0
            has_strong_tail_vocal_period = any(
                period.get("word_index") == last_word_index
                and period.get("classification") in {"melisma", "vowel_extension"}
                and (period.get("audio_evidence") or {}).get("active")
                for period in audio_vocal_periods
            )
            can_trim_false_long_tail = (
                tail.get("classification") == "tail_vowel_extension"
                and has_long_final_word
                and (has_structural_drift_gap or not has_strong_tail_vocal_period)
                and bool(last_word_stats)
                and not last_word_stats.get("active")
                and float(last_word_stats.get("voiced_ratio", 0.0)) <= 0.25
            )
            if can_extend_written_melisma:
                tail["classification"] = "written_melisma_extension"
                tail["confidence"] = "high" if float(tail_stats.get("voiced_ratio", 0.0)) >= 0.75 else "medium"
                tail["audio_evidence"] = tail_stats
                tail["sound_suggestion"] = _sound_suggestion(
                    sound_type="written_melisma",
                    suggested_caption=last_word_text,
                    suggested_user_action="extend_existing_word",
                )
            elif can_promote_audio_tail:
                tail["classification"] = "probable_unwritten_vowel_extension"
                tail["confidence"] = "high" if float(tail_stats.get("voiced_ratio", 0.0)) >= 0.75 else "medium"
                tail["audio_evidence"] = tail_stats
                tail["sound_suggestion"] = _sound_suggestion(
                    sound_type="sustained_final_vowel",
                    suggested_caption=_word_extension_caption(last_word_text),
                    suggested_user_action="extend_final_vowel",
                )
            elif can_flag_possible_lost_tail:
                tail["classification"] = "possible_lost_tail"
                tail["confidence"] = "medium"
                tail["recommended_fallback"] = "manual_review_or_local_realign"
                tail["audio_evidence"] = tail_stats
                tail["sound_suggestion"] = _sound_suggestion(
                    sound_type="possible_sustained_final_vowel",
                    suggested_caption=_word_extension_caption(last_word_text),
                    suggested_user_action="review_before_extending_final_vowel",
                )
            elif can_flag_interline_melisma:
                tail["classification"] = "unwritten_interline_melisma"
                tail["confidence"] = "medium"
                tail["recommended_fallback"] = "flag_review_or_create_extension_bar"
                tail["audio_evidence"] = tail_stats
                tail["sound_suggestion"] = _sound_suggestion(
                    sound_type="unwritten_vocal_melisma",
                    suggested_caption="[vocalizacao]",
                    suggested_user_action="review_or_add_non_lyric_vocal_caption",
                )
            elif can_trim_false_long_tail:
                tail["classification"] = "false_long_tail"
                tail["confidence"] = "high"
                tail["recommended_fallback"] = "trim_to_last_active_vocal"
                tail["audio_evidence"] = last_word_stats
                tail["sound_suggestion"] = _sound_suggestion(
                    sound_type="inactive_or_false_tail",
                    suggested_caption="",
                    suggested_user_action="trim_or_realign",
                )
            elif tail.get("classification") == "tail_melisma" and not last_word_stats.get("active"):
                tail["classification"] = "none"
                tail["audio_evidence"] = last_word_stats
            elif tail.get("classification") in {"tail_melisma", "tail_vowel_extension"}:
                tail["audio_evidence"] = last_word_stats
            timing["tail"] = tail

        has_bad_gap = any(gap.get("classification") == "bad_gap" for gap in timing.get("inter_word_gaps", []))
        has_audio_supported_word = any(
            (audio_activity.get((line_index, word_index), {}) or {}).get("active")
            for word_index in range(len(words))
        )
        if has_bad_gap and has_audio_supported_word:
            timing["line_classification"] = "review_only_backing_or_drift"
            timing["confidence"] = "high"
            if (
                line_index > 0
                and _time(lines[line_index - 1].get("end"), 0.0) > _time(line.get("start"), 0.0)
            ) or _has_short_first_word_entry_drift(timing, words):
                timing["recommended_fallback"] = "move_line_start_later_or_review_previous_tail"
                timing["diagnostic_tags"] = ["early_next_line_entry_drift"]
                timing["sound_suggestion"] = _sound_suggestion(
                    sound_type="alignment_drift",
                    suggested_caption="",
                    suggested_user_action="move_line_start_later_or_review_previous_tail",
                )
            elif _has_final_word_after_alignment_hole(timing, words):
                timing["recommended_fallback"] = "review_local_realignment"
                timing["diagnostic_tags"] = ["final_word_after_alignment_hole"]
                timing["sound_suggestion"] = _sound_suggestion(
                    sound_type="alignment_hole",
                    suggested_caption="",
                    suggested_user_action="review_local_realign",
                )
            else:
                timing["recommended_fallback"] = "manual_review_or_local_realign"
                timing["diagnostic_tags"] = ["possible_backing_vocal_not_in_lyrics"]
                if _has_large_internal_alignment_hole(timing):
                    timing["sound_suggestion"] = _sound_suggestion(
                        sound_type="possible_backing_or_alignment_issue",
                        suggested_caption="[revisar vocal/alinhamento]",
                        suggested_user_action="review_backing_vocal_or_local_realign",
                    )
                else:
                    timing["sound_suggestion"] = _sound_suggestion(
                        sound_type="possible_backing_vocal_not_in_lyrics",
                        suggested_caption="[vocal de apoio]",
                        suggested_user_action="review_backing_vocal_or_local_realign",
                    )

        timings.append(timing)
    return timings


def build_audio_activity_map(
    lines: list[dict[str, Any]],
    vocals_path: Path,
) -> dict[Any, dict[str, Any]]:
    probe = VocalActivityProbe.from_wav(vocals_path)
    activity: dict[Any, dict[str, Any]] = {}
    for line_index, line in enumerate(lines):
        words = list(line.get("words") or [])
        for word_index, word in enumerate(words):
            start_s = _time(word.get("start", word.get("start_s")), 0.0)
            end_s = _time(word.get("end", word.get("end_s")), start_s)
            activity[(line_index, word_index)] = probe.interval_stats(start_s, end_s)

        if words and line_index + 1 < len(lines):
            last_word = words[-1]
            tail_start_s = _time(last_word.get("end", last_word.get("end_s")), 0.0)
            next_start_s = _time(lines[line_index + 1].get("start"), tail_start_s)
            if next_start_s > tail_start_s:
                activity[("tail", line_index)] = probe.interval_stats(tail_start_s, next_start_s)
                activity[("tail_regions", line_index)] = probe.voiced_regions(tail_start_s, next_start_s)
    return activity


def apply_audio_backed_tail_extensions(
    lines: list[dict[str, Any]],
    timings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    extended_lines = copy.deepcopy(lines)
    for line_index, timing in enumerate(timings):
        if line_index >= len(extended_lines):
            continue
        if is_review_only_audio_timing(timing):
            continue
        tail = timing.get("tail", {})
        word_index = int(tail.get("word_index", -1))
        words = extended_lines[line_index].get("words") or []
        if not (0 <= word_index < len(words)):
            continue
        if tail.get("classification") == "false_long_tail":
            current_start_s = _time(words[word_index].get("start", words[word_index].get("start_s")), 0.0)
            current_end_s = _time(words[word_index].get("end", words[word_index].get("end_s")), current_start_s)
            trimmed_end_s = min(current_end_s, current_start_s + 0.60)
            if trimmed_end_s > current_start_s:
                words[word_index]["end"] = round(trimmed_end_s, 3)
                words[word_index]["audio_trim"] = {
                    "source": "vocals.wav",
                    "end_s": round(trimmed_end_s, 3),
                    "classification": tail.get("classification"),
                }
                extended_lines[line_index]["end"] = max(
                    _time(extended_lines[line_index].get("start"), current_start_s),
                    round(trimmed_end_s, 3),
                )
            continue

        if tail.get("classification") not in SAFE_EXTENSION_CLASSES:
            continue
        audio_evidence = tail.get("audio_evidence") or {}
        extension_end_s = _time(audio_evidence.get("end_s"), 0.0)
        current_end_s = _time(words[word_index].get("end", words[word_index].get("end_s")), 0.0)
        if extension_end_s <= current_end_s:
            continue

        words[word_index]["end"] = round(extension_end_s, 3)
        words[word_index]["audio_extension"] = {
            "source": "vocals.wav",
            "end_s": round(extension_end_s, 3),
            "voiced_ratio": audio_evidence.get("voiced_ratio"),
            "classification": tail.get("classification"),
        }
        extended_lines[line_index]["end"] = max(_time(extended_lines[line_index].get("end"), current_end_s), round(extension_end_s, 3))
    return extended_lines


def gap_should_be_absorbed(gap: dict[str, Any]) -> bool:
    return gap.get("classification") == "small_gap"


def summarize_timing_layers(lines: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    gap_counts: dict[str, int] = {}
    tail_counts: dict[str, int] = {}
    vocal_period_counts: dict[str, int] = {}
    known_tail_melisma_lines = {
        _normalized_line_text(line)
        for line in lines
        if classify_line_timing(line)["tail"].get("classification") in {"tail_melisma", "tail_vowel_extension"}
    }

    for index, line in enumerate(lines):
        next_line = lines[index + 1] if index + 1 < len(lines) else None
        timing = classify_line_timing(
            line,
            next_line=next_line,
            known_tail_melisma_lines=known_tail_melisma_lines,
        )
        for gap in timing["inter_word_gaps"]:
            classification = str(gap.get("classification", "unknown"))
            gap_counts[classification] = gap_counts.get(classification, 0) + 1
        for period in timing["vocal_periods"]:
            classification = str(period.get("classification", "unknown"))
            vocal_period_counts[classification] = vocal_period_counts.get(classification, 0) + 1
        tail_classification = str(timing["tail"].get("classification", "none"))
        tail_counts[tail_classification] = tail_counts.get(tail_classification, 0) + 1

    return {
        "inter_word_gaps": gap_counts,
        "vocal_periods": vocal_period_counts,
        "tails": tail_counts,
    }


def summarize_audio_backed_timing(timings: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    gap_counts: dict[str, int] = {}
    tail_counts: dict[str, int] = {}
    vocal_period_counts: dict[str, int] = {}

    for timing in timings:
        for gap in timing.get("inter_word_gaps", []):
            classification = str(gap.get("classification", "unknown"))
            gap_counts[classification] = gap_counts.get(classification, 0) + 1
        for period in timing.get("vocal_periods", []):
            classification = str(period.get("classification", "unknown"))
            vocal_period_counts[classification] = vocal_period_counts.get(classification, 0) + 1
        tail = timing.get("tail", {})
        classification = str(tail.get("classification", "none"))
        tail_counts[classification] = tail_counts.get(classification, 0) + 1

    return {
        "inter_word_gaps": gap_counts,
        "vocal_periods": vocal_period_counts,
        "tails": tail_counts,
    }


def _diagnostic_event(
    *,
    line_index: int,
    text: str,
    classification: str,
    confidence: str,
    evidence: list[str],
    recommended_fallback: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "line_index": line_index,
        "text": text,
        "classification": classification,
        "confidence": confidence,
        "evidence": evidence,
        "recommended_fallback": recommended_fallback,
        "details": details,
    }


def _known_tail_lines(lines: list[dict[str, Any]]) -> set[str]:
    return {
        _normalized_line_text(line)
        for line in lines
        if classify_line_timing(line)["tail"].get("classification") in {"tail_melisma", "tail_vowel_extension"}
    }


def build_timing_diagnostics(lines: list[dict[str, Any]]) -> dict[str, Any]:
    known_tail_melisma_lines = _known_tail_lines(lines)
    events: list[dict[str, Any]] = []

    for index, line in enumerate(lines):
        next_line = lines[index + 1] if index + 1 < len(lines) else None
        timing = classify_line_timing(
            line,
            next_line=next_line,
            known_tail_melisma_lines=known_tail_melisma_lines,
        )
        text = str(line.get("text") or "")

        has_bad_gap = any(gap.get("classification") == "bad_gap" for gap in timing["inter_word_gaps"])
        if has_bad_gap and timing["vocal_periods"]:
            events.append(
                _diagnostic_event(
                    line_index=index,
                    text=text,
                    classification="suspect_vocal_drift",
                    confidence="high",
                    evidence=["bad_gap_in_line", "long_vocal_period_in_same_line"],
                    recommended_fallback="local_realignment_review",
                    details={
                        "gaps": [gap for gap in timing["inter_word_gaps"] if gap.get("classification") == "bad_gap"],
                        "vocal_periods": timing["vocal_periods"],
                    },
                )
            )

        if index + 1 < len(lines):
            next_line = lines[index + 1]
            current_end_s = _time(line.get("end"), 0.0)
            next_start_s = _time(next_line.get("start"), current_end_s)
            if current_end_s > 0.0 and next_start_s < current_end_s:
                overlap_s = round(current_end_s - next_start_s, 3)
                events.append(
                    _diagnostic_event(
                        line_index=index,
                        text=text,
                        classification="previous_tail_likely_stolen_by_next_line",
                        confidence="high",
                        evidence=["next_line_starts_before_previous_line_end", "overlapping_phrase_boundary"],
                        recommended_fallback="extend_previous_tail_or_move_next_line_start_later",
                        details={
                            "next_line_index": index + 1,
                            "next_line_text": str(next_line.get("text") or ""),
                            "overlap_s": overlap_s,
                        },
                    )
                )
                next_words = list(next_line.get("words") or [])
                early_word = _word_text(next_words[0]) if next_words else ""
                events.append(
                    _diagnostic_event(
                        line_index=index + 1,
                        text=str(next_line.get("text") or ""),
                        classification="early_next_line_entry_drift",
                        confidence="high",
                        evidence=["line_start_overlaps_previous_tail"],
                        recommended_fallback="move_line_start_later_or_review_previous_tail",
                        details={
                            "previous_line_index": index,
                            "previous_line_text": text,
                            "overlap_s": overlap_s,
                            "early_word": early_word,
                        },
                    )
                )

        for gap in timing["inter_word_gaps"]:
            classification = str(gap.get("classification"))
            if classification == "instrumental_pause":
                events.append(
                    _diagnostic_event(
                        line_index=index,
                        text=text,
                        classification="instrumental_pause",
                        confidence="high",
                        evidence=["long_gap", "pause_style_section", "no_assigned_vocal_in_gap"],
                        recommended_fallback="preserve_silence_gap",
                        details=gap,
                    )
                )
            elif classification == "bad_gap":
                if int(gap.get("before_word_index", -1)) == len(line.get("words") or []) - 1:
                    before_word = (line.get("words") or [])[int(gap.get("before_word_index", 0))]
                    before_start_s = _time(before_word.get("start", before_word.get("start_s")), 0.0)
                    before_end_s = _time(before_word.get("end", before_word.get("end_s")), before_start_s)
                    before_duration_s = max(0.0, before_end_s - before_start_s)
                    if before_duration_s <= LOST_TAIL_MAX_WORD_S:
                        events.append(
                            _diagnostic_event(
                                line_index=index,
                                text=text,
                                classification="final_word_after_alignment_hole",
                                confidence="high",
                                evidence=["large_gap_before_final_word", "short_final_word", "non_pause_section"],
                                recommended_fallback="review_local_realignment",
                                details={
                                    **gap,
                                    "final_word_duration_s": round(before_duration_s, 3),
                                },
                            )
                        )
                events.append(
                    _diagnostic_event(
                        line_index=index,
                        text=text,
                        classification="alignment_hole",
                        confidence="high",
                        evidence=["large_internal_gap", "non_pause_section"],
                        recommended_fallback="preserve_gap_and_flag_review",
                        details=gap,
                    )
                )

        tail = timing["tail"]
        tail_classification = str(tail.get("classification"))
        if tail_classification == "possible_lost_tail":
            events.append(
                _diagnostic_event(
                    line_index=index,
                    text=text,
                    classification="possible_lost_tail",
                    confidence="medium",
                    evidence=["short_final_word", "long_next_gap", "same_line_has_confirmed_tail"],
                    recommended_fallback="extend_final_vowel_candidate",
                    details=tail,
                )
            )
        elif tail_classification == "instrumental_pause":
            events.append(
                _diagnostic_event(
                    line_index=index,
                    text=text,
                    classification="instrumental_pause",
                    confidence="high",
                    evidence=["long_gap_to_next_line", "no_tail_sustain"],
                    recommended_fallback="preserve_silence_gap",
                    details=tail,
                )
            )

    summary: dict[str, int] = {}
    for event in events:
        classification = str(event["classification"])
        summary[classification] = summary.get(classification, 0) + 1

    return {
        "events": events,
        "summary": summary,
    }
