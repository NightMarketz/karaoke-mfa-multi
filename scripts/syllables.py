"""syllables.py — pure phoneme→syllable grouping, timing and confidence.

Groups a word's timed phonemes into syllables (vowel nucleus + surrounding
onset/coda), derives each syllable's start/end from the phoneme intervals, and
scores a per-syllable ``confidence`` that is *aware of the s04 alignment source*:

  - ``hubertfa``            → real phoneme timing              → high base
  - ``ctc_forced``,
    ``ctc_forced+hubertfa`` → intra-word timing distributed by
                              proportion (s04) → APPROXIMATE     → low base
  - ``whisper_fallback``,
    ``interpolated``,
    ``needs_interpolation`` → no reliable phoneme               → lowest base

No phoneme timing at all ⇒ a single segment covering the whole word, low
confidence (the caller flags it). This module is deliberately free of I/O so it
can be unit-tested in isolation; ``s05_analyze`` imports from it.
"""

from __future__ import annotations

from typing import Any

# ── Tunables ────────────────────────────────────────────────────────────────
DEFAULT_MIN_SEGMENT_MS = 80

# ARPAbet vowel nuclei (the aligner emits ARPAbet-style phone labels).
PHONE_VOWELS = {
    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
    "IH", "IY", "OW", "OY", "UH", "UW", "AX",
}
TEXT_VOWELS = set("aeiouyáéíóúâêîôûãõàèìòùäëïöüAEIOUYÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÄËÏÖÜ")

# Source → base confidence.
#   hubertfa             : word span AND phonemes from HubertFA → highest.
#   ctc_forced+hubertfa  : CTC word span + HubertFA phonemes assigned by audio
#                          position (s04 _ctc_forced_with_phonemes) → real
#                          intra-word timing → reliable.
#   ctc_forced           : no phoneme timing at all (phonemes:[]) → the word
#                          renders as one segment; kept low.
#   whisper/interpolated : no reliable phoneme → lowest.
# The '+hubertfa' key is matched before the generic 'ctc_forced' substring.
SOURCE_BASE_CONFIDENCE = {
    "hubertfa": 0.92,
    "ctc_forced+hubertfa": 0.85,
    "ctc_forced": 0.55,
    "whisper_fallback": 0.35,
    "interpolated": 0.35,
    "needs_interpolation": 0.35,
}
# Absent/unknown source but real per-phone timing is present (e.g. a raw forced
# transcript that never went through s04's source tagging): treat as reliable.
DEFAULT_BASE_CONFIDENCE = 0.85

PHONE_PROJECTION_SOURCE = "phone_projection"
DURATION_FALLBACK_SOURCE = "duration_interpolation_fallback"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def phone_label(phone: dict[str, Any]) -> str:
    return str(phone.get("ph") or phone.get("phone") or phone.get("text") or "").upper()


def is_vowel_phone(phone: dict[str, Any]) -> bool:
    label = "".join(ch for ch in phone_label(phone) if ch.isalpha())
    return label in PHONE_VOWELS


def timed_phones(word: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the word's phonemes as ``{phone,start,end}`` with valid timing.

    Phonemes with missing/non-numeric or inverted/zero-length timing (error
    rule §8) are dropped, so the caller falls back to the word span.
    """
    phones: list[dict[str, Any]] = []
    last_end = None
    for raw in word.get("phonemes", []) or []:
        if not isinstance(raw, dict):
            continue
        label = phone_label(raw)
        if not label:
            continue
        try:
            start = float(raw.get("start", raw.get("start_s")))
            end = float(raw.get("end", raw.get("end_s")))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue  # §8: inverted/zero-length phone
        if last_end is not None and start < last_end - 1e-3:
            continue  # §8: overlapping/backwards phone (e.g. some aligners duplicate the run)
        phones.append({"phone": label, "start": round(start, 4), "end": round(end, 4)})
        last_end = end
    return phones


def phone_syllable_groups(phones: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group consecutive phones into syllables, one vowel nucleus per group.

    A consonant run before the first vowel is an onset; consonants after a vowel
    are held (``pending``) and attach as the onset of the next syllable when a
    new vowel appears, otherwise stay as the coda of the last one.
    """
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    has_vowel = False

    for phone in phones:
        if is_vowel_phone(phone):
            if has_vowel:
                groups.append(current)
                current = pending + [phone]
                pending = []
            else:
                current.extend(pending)
                pending = []
                current.append(phone)
                has_vowel = True
        elif has_vowel:
            pending.append(phone)
        else:
            current.append(phone)

    if current:
        current.extend(pending)
        groups.append(current)
    return groups or ([phones] if phones else [])


# Consonant sequences that act as a single onset and must not be split across a
# syllable boundary (digraphs + common English/PT-BR onset clusters). Used to
# place the boundary by the maximal-onset principle: give the following syllable
# the longest valid onset, leaving the rest as the previous syllable's coda.
_ONSET_UNITS = {
    # digraphs
    "th", "ch", "sh", "ph", "wh", "ck", "ng", "gh", "qu", "nh", "lh",
    "ll", "rr", "ss", "tt", "nn", "mm", "ff", "dd", "gg", "pp", "bb", "cc", "zz",
    # onset clusters
    "bl", "br", "cl", "cr", "dr", "fl", "fr", "gl", "gr", "pl", "pr",
    "sc", "sk", "sl", "sm", "sn", "sp", "st", "sw", "tr", "tw", "gn", "kn", "wr",
    "thr", "str", "spr", "spl", "scr", "shr",
}


def _vowel_runs(text: str) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] in TEXT_VOWELS:
            j = i
            while j < n and text[j] in TEXT_VOWELS:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def _onset_length(cluster: str) -> int:
    """How many trailing consonants of an intervocalic cluster start the next
    syllable (maximal onset). Single consonant → 1; a 2-3 char valid onset/
    digraph suffix → its length; otherwise just the last consonant."""
    if len(cluster) <= 1:
        return len(cluster)
    lowered = cluster.lower()
    if lowered in _ONSET_UNITS:
        return len(cluster)
    for size in (3, 2):
        if len(cluster) >= size and lowered[-size:] in _ONSET_UNITS:
            return size
    return 1


def basic_text_syllables(text: str) -> list[str]:
    """Orthographic split by the maximal-onset principle.

    Each vowel run is a nucleus; intervocalic consonants are split so the next
    syllable keeps the longest valid onset (digraph/cluster aware), e.g.
    ``breathing`` → ``brea``/``thing``, ``hungry`` → ``hun``/``gry``.
    """
    runs = _vowel_runs(text)
    if len(runs) <= 1:
        return [text]

    boundaries = [0]
    for (_, end_prev), (start_next, _) in zip(runs, runs[1:]):
        cluster = text[end_prev:start_next]
        onset = _onset_length(cluster)
        boundaries.append(start_next - onset)
    boundaries.append(len(text))

    chunks = [text[boundaries[i]:boundaries[i + 1]] for i in range(len(boundaries) - 1)]
    return [c for c in chunks if c] or [text]


def syllabification_is_plausible(
    text: str,
    group_count: int,
    word_span_s: float,
    min_segment_ms: int = DEFAULT_MIN_SEGMENT_MS,
) -> bool:
    """Whether a word should be split into ``group_count`` syllables at all.

    In fast passages (rap) a word is only tens of ms long and CTC word spans
    diverge from HubertFA phoneme positions, so a word's span captures phonemes
    that belong to its neighbours — a 1-syllable word like "Wolf" ends up with
    five vowel-nucleus groups. Splitting that is nonsense (and the render shows
    five fake highlights). Reject the split when either:

      - there are more phone groups than the spelling can justify (a word cannot
        have more syllables than its orthographic vowel runs), or
      - the word is too short to hold that many syllables at the min floor.

    The caller then renders the whole word as one highlight — correct for
    fast/compressed words, which cannot carry visible per-syllable timing.
    """
    if group_count <= 1:
        return True
    max_syllables = max(1, len(_vowel_runs(text)))
    if group_count > max_syllables:
        return False
    if word_span_s < group_count * (min_segment_ms / 1000.0):
        return False
    return True


def text_for_syllable_count(text: str, count: int) -> list[str]:
    """Split ``text`` into exactly ``count`` orthographic chunks."""
    chunks = basic_text_syllables(text)
    while len(chunks) > count and len(chunks) > 1:
        chunks[-2] += chunks[-1]
        chunks.pop()
    while len(chunks) < count:
        longest = max(range(len(chunks)), key=lambda index: len(chunks[index]))
        chunk = chunks[longest]
        split_at = max(1, len(chunk) // 2)
        chunks[longest:longest + 1] = [chunk[:split_at], chunk[split_at:]]
    return chunks[:count]


def source_base_confidence(source: str | None) -> float:
    """Base confidence for an s04 word ``source`` (see module docstring)."""
    key = (source or "").strip().lower()
    if key in SOURCE_BASE_CONFIDENCE:
        return SOURCE_BASE_CONFIDENCE[key]
    if "ctc_forced" in key:  # covers "ctc_forced+hubertfa"
        return SOURCE_BASE_CONFIDENCE["ctc_forced"]
    if not key:
        return DEFAULT_BASE_CONFIDENCE
    return DEFAULT_BASE_CONFIDENCE


def _duration_plausibility(duration_s: float) -> float:
    if duration_s <= 0.0:
        return 0.0
    if 0.06 <= duration_s <= 1.20:
        return 1.0
    if duration_s < 0.06:
        return _clamp01(duration_s / 0.06)
    return _clamp01(1.20 / duration_s)


def _has_measured_phone_timing(source: str | None) -> bool:
    """True when a syllable's phone timing was measured from audio by HubertFA.

    ``hubertfa`` and ``ctc_forced+hubertfa`` carry real per-phone timing; an
    absent source with phones present (a raw forced transcript) is treated the
    same. ``ctc_forced`` (phonemes:[]) and whisper/interpolated do NOT — their
    timing is guessed, so they keep the strict, heuristic-driven scoring.
    """
    key = (source or "").strip().lower()
    if not key:
        return True
    return "hubertfa" in key


def _word_boundary_fit(group: list[dict[str, Any]], word: dict[str, Any]) -> float:
    try:
        word_start = float(word.get("start", word.get("start_s")))
        word_end = float(word.get("end", word.get("end_s")))
    except (TypeError, ValueError):
        return 0.8
    if not group:
        return 0.0
    if word_start - 0.001 <= group[0]["start"] and group[-1]["end"] <= word_end + 0.001:
        return 1.0
    return 0.4


def syllable_confidence(
    group: list[dict[str, Any]],
    word: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    """Score a syllable's confidence, aware of ``word['source']``.

    ``confidence = source_base * quality``. When the phone timing was *measured*
    by HubertFA (see ``_has_measured_phone_timing``), the source base dominates
    and duration/boundary only lightly nudge it — a fast function word or a held
    note is real, not a timing error. When the timing is *guessed* (phone-less
    fallback, ``ctc_forced``, interpolated), ``quality`` blends phone coverage,
    duration plausibility and word-boundary fit, and a low transcription
    ``probability`` downgrades further, because those signals do carry
    information about how trustworthy the inferred span is. A ``low_confidence``
    transcription flag downgrades in both cases.
    """
    base = source_base_confidence(word.get("source"))
    duration_s = group[-1]["end"] - group[0]["start"] if group else 0.0
    breakdown = {
        "source_confidence": round(base, 4),
        "phone_coverage": 1.0 if group else 0.0,
        "duration_plausibility": round(_duration_plausibility(duration_s), 4),
        "word_boundary_fit": round(_word_boundary_fit(group, word), 4),
    }

    if group and _has_measured_phone_timing(word.get("source")):
        # HubertFA measured this syllable's timing directly from the audio, so the
        # heuristics that flag *guessed* timing don't apply here: a fast function
        # word (short phone span) or a held note (long span) is real, a few-ms
        # overshoot past the CTC word boundary is just CTC/HubertFA disagreement,
        # and the CTC transcription probability says nothing about the measured
        # timing. The source base (documented as reliable) is the primary signal
        # and at most a ~15% haircut comes off for an implausible duration or a
        # phones-outside-word span — never enough to force review on its own,
        # because a degenerate span here means CTC mis-sized the *word*, not that
        # the syllable is mis-split (which is all the reviewer can fix). Without
        # this, genuinely-fast function words flooded the syllable review queue.
        quality = (
            0.85
            + 0.10 * breakdown["duration_plausibility"]
            + 0.05 * breakdown["word_boundary_fit"]
        )
        confidence = base * quality
        if word.get("low_confidence"):
            confidence *= 0.65  # a flagged transcription still drops it into review
        return round(_clamp01(confidence), 4), breakdown

    # Guessed timing (phone-less fallback, ctc_forced, interpolated): the span is
    # inferred, so duration plausibility, boundary fit and transcription
    # probability all carry real signal about how trustworthy it is.
    quality = (
        0.55 * breakdown["phone_coverage"]
        + 0.28 * breakdown["duration_plausibility"]
        + 0.17 * breakdown["word_boundary_fit"]
    )
    confidence = base * quality
    if word.get("low_confidence"):
        confidence *= 0.6
    probability = word.get("probability")
    # Only a genuine 0..1 transcription probability downgrades. Some aligners
    # store a log-probability here (e.g. -20.6); those must not be treated as a
    # 0..1 value or they would wrongly zero the confidence.
    if isinstance(probability, (int, float)) and 0.0 <= probability < 0.5:
        confidence *= _clamp01(0.5 + float(probability))
    return round(_clamp01(confidence), 4), breakdown


def _word_span(word: dict[str, Any]) -> tuple[float, float]:
    start = float(word.get("start", word.get("start_s", 0.0)) or 0.0)
    end = float(word.get("end", word.get("end_s", start)) or start)
    if end <= start:
        end = start + DEFAULT_MIN_SEGMENT_MS / 1000.0
    return start, end


def split_word_syllables(
    word: dict[str, Any],
    *,
    min_segment_ms: int = DEFAULT_MIN_SEGMENT_MS,
) -> list[dict[str, Any]]:
    """Split one word into timed, scored syllables (pure, no I/O).

    Returns an ordered list of ``{text,start,end,confidence,source,phones}``.
    Timing comes from the phonemes; a floor of ``min_segment_ms`` is enforced
    per segment without exceeding the word end (error rule §8), and the last
    segment is clamped to the word end so the segments cover the word span.
    With no usable phonemes: a single whole-word segment, low confidence.
    """
    text = str(word.get("word") or word.get("text") or "")
    word_start, word_end = _word_span(word)
    floor_s = max(0.0, min_segment_ms / 1000.0)

    phones = timed_phones(word)
    if not phones:
        base = source_base_confidence(word.get("source"))
        return [{
            "text": text,
            "start": round(word_start, 4),
            "end": round(word_end, 4),
            "confidence": round(_clamp01(base * 0.5), 4),
            "source": DURATION_FALLBACK_SOURCE,
            "phones": [],
        }]

    groups = phone_syllable_groups(phones)
    if not syllabification_is_plausible(text, len(groups), word_end - word_start, min_segment_ms):
        # Fast/compressed word — phoneme bleed makes the split unreliable; render
        # the whole word as one highlight instead of faking N syllables.
        base = source_base_confidence(word.get("source"))
        return [{
            "text": text,
            "start": round(word_start, 4),
            "end": round(word_end, 4),
            "confidence": round(_clamp01(base), 4),
            "source": PHONE_PROJECTION_SOURCE,
            "phones": [p["phone"] for g in groups for p in g],
        }]
    texts = text_for_syllable_count(text, len(groups))
    segments: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        confidence, _ = syllable_confidence(group, word)
        segments.append({
            "text": texts[index],
            "start": round(group[0]["start"], 4),
            "end": round(group[-1]["end"], 4),
            "confidence": confidence,
            "source": PHONE_PROJECTION_SOURCE,
            "phones": [phone["phone"] for phone in group],
        })

    _apply_floor(segments, word_end, floor_s)
    segments[-1]["end"] = round(word_end, 4)
    return segments


def _apply_floor(segments: list[dict[str, Any]], word_end: float, floor_s: float) -> None:
    """Extend any sub-floor segment up to the floor without exceeding word_end."""
    for i, seg in enumerate(segments):
        if seg["end"] - seg["start"] >= floor_s:
            continue
        target = min(seg["start"] + floor_s, word_end)
        seg["end"] = round(target, 4)
        if i + 1 < len(segments) and segments[i + 1]["start"] < seg["end"]:
            segments[i + 1]["start"] = seg["end"]
