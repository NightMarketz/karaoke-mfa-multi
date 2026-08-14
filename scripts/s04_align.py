"""
s04_align.py — Singing-aware phoneme alignment via HubertFA.

Converts word-level Whisper timestamps into phoneme-level timing
using HubertFA (ONNX, singing-optimised), with g2p_en for EN phonemisation.

Architecture:
    1. Prepare segments: slice vocals.wav → wav/lab pairs in tmp_dir
    2. Batch Inference: Run HubertFA onnx_infer.py ONCE on tmp_dir
    3. Parse results: Find each .TextGrid, map phonemes back to words
    4. Fallback: Linear interpolation from Whisper timestamps if a segment fails

Phoneme pipeline (EN-only, Phase 1):
    g2p_en  →  ARPAbet with stress (AH0, N, EH1, ...)
            →  strip stress digits  →  (AH, N, EH, ...)
            →  write to .lab file one token per line

HubertFA CLI:
    python onnx_infer.py --onnx_path <m> --wav_folder <wf> --out_path <o> --g2p phoneme
    Output structure: <out_path>/TextGrid/segment_name.TextGrid
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from hw_detect import detect, HardwareProfile
from scripts.common.config import load_app_config
from scripts.common.observability import record_artifact, write_event
from scripts.common.validation import normalize_words

# Fix Windows encoding issues for checkmark/cross symbols
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, io.UnsupportedOperation):
        pass

logger = logging.getLogger(__name__)

# Silence phoneme labels emitted by HubertFA
_SILENCE_LABELS = {"SIL", "SP", "AP", "sil", "sp", "ap", "<SIL>", "<SP>"}
_PHONE_TIERS = {"phones", "phonemes", "phone"}


def _phone_intervals(intervals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only real phoneme intervals from a parsed TextGrid.

    HubertFA emits a ``words`` tier and a ``phones`` tier; only the phones tier
    is phonemic. Falls back to all non-silence intervals if no tier is named
    like a phone tier (defensive against future tier renames).
    """
    phones = [v for v in intervals if v.get("tier") in _PHONE_TIERS]
    source = phones if phones else intervals
    return [v for v in source if v["text"] and v["text"] not in _SILENCE_LABELS]
_STRESS_RE = re.compile(r"\d+$")

# Default word-duration floor (ms). Overridable via [align] min_word_ms / env.
DEFAULT_MIN_WORD_MS = 120


def _apply_word_duration_floor(
    spans: list[tuple[float, float]], min_word_dur: float
) -> tuple[list[tuple[float, float]], int]:
    """Grow degenerate word spans to ``min_word_dur`` without breaking line-sync.

    CTC compresses short function words to ~0 and parks them as tiny islands with
    silence on either side. Each sub-floor word is widened symmetrically around
    its own midpoint to reach the floor, clamped to its neighbours' boundaries
    (``[prev.end, next.start]``) so words never overlap. The first word's start
    and the last word's end are never moved, so the line envelope (line-sync) is
    preserved. If the free space between neighbours is itself below the floor the
    word takes all of it (still an improvement). ``phonemes:[]`` words widen too
    — a wider span lets s04 bucket the phonemes that actually belong to them.

    ponytail: only expands into free gaps; it does not steal from an abutting
    over-long neighbour. Add that if wedged sub-floor words (no gap either side)
    ever show up — the measured corpus has none.

    Returns the adjusted spans and the count of words that were below the floor.
    """
    if not spans or min_word_dur <= 0:
        return spans, 0

    result = list(spans)
    n = len(result)
    half = min_word_dur / 2.0
    n_below = 0
    for i, (start, end) in enumerate(result):
        if (end - start) >= min_word_dur - 1e-9:
            continue
        n_below += 1
        left_bound = result[i - 1][1] if i > 0 else start   # don't cross prev word / line start
        right_bound = result[i + 1][0] if i + 1 < n else end  # don't cross next word / line end
        if right_bound - left_bound <= end - start + 1e-9:
            continue  # no free space around this word — leave it as-is
        mid = (start + end) / 2.0
        new_start, new_end = mid - half, mid + half
        if new_start < left_bound:      # shove right to stay off the previous word
            new_end += left_bound - new_start
            new_start = left_bound
        if new_end > right_bound:       # shove left to stay off the next word
            new_start -= new_end - right_bound
            new_end = right_bound
        new_start = max(new_start, left_bound)
        new_end = min(new_end, right_bound)
        result[i] = (round(new_start, 4), round(new_end, 4))
    return result, n_below


def demo() -> None:
    """Self-check: floor grows a degenerate word into its gap, envelope intact."""
    # Tiny interior word (18ms) with silence on both sides — the real case.
    spans = [(0.0, 0.4), (0.52, 0.54), (0.66, 1.0)]
    out, n = _apply_word_duration_floor(spans, 0.12)
    assert n == 1, n
    assert out[0] == (0.0, 0.4) and out[2] == (0.66, 1.0), out          # neighbours untouched
    assert out[1][1] - out[1][0] >= 0.12 - 1e-6, out                    # floor reached
    assert out[1][0] >= 0.4 and out[1][1] <= 0.66, out                  # no overlap
    # First/last words pin the line envelope; a healthy word is untouched.
    healthy = [(0.0, 1.0), (5.0, 6.0)]
    out2, n2 = _apply_word_duration_floor(healthy, 0.12)
    assert out2 == healthy and n2 == 0, (out2, n2)
    print("s04 word-duration floor demo OK")

    # Sequence-mode assignment: two words, real g2p counts [1, 2]. A mis-sized CTC
    # span (word A oversized) would time-bucket B's first phone into A; sequence
    # mode slices by count instead, so each word gets exactly its own phones.
    words = [{"word": "a", "start": 0.0, "end": 0.95}, {"word": "cat", "start": 0.95, "end": 1.2}]
    ph_ivs = [
        {"text": "AH", "xmin": 0.0, "xmax": 0.3},
        {"text": "K",  "xmin": 0.85, "xmax": 1.0},   # midpoint 0.925 → falls in A's oversized span
        {"text": "AE", "xmin": 1.0, "xmax": 1.2},
    ]
    seq = _ctc_forced_with_phonemes(words, ph_ivs, 0.0, phone_counts=[1, 2], assign="sequence")
    assert [p["ph"] for p in seq[0]["phonemes"]] == ["AH"], seq[0]
    assert [p["ph"] for p in seq[1]["phonemes"]] == ["K", "AE"], seq[1]
    # Legacy timebucket would misassign "K" to word A (its midpoint is inside A).
    tb = _ctc_forced_with_phonemes(words, ph_ivs, 0.0, phone_counts=[1, 2], assign="timebucket")
    assert [p["ph"] for p in tb[0]["phonemes"]] == ["AH", "K"], tb[0]
    # Guard: broken count invariant (sum=5 ≠ 3 phones) falls back to timebucket.
    guarded = _ctc_forced_with_phonemes(words, ph_ivs, 0.0, phone_counts=[2, 3], assign="sequence")
    assert [p["ph"] for p in guarded[0]["phonemes"]] == ["AH", "K"], guarded[0]
    print("s04 sequence-assignment demo OK")

    # Whisper mode (timing derived from phonemes): real counts [1,2] keep K with
    # "cat"; the uniform ratio split would round word A up to 2 and steal K.
    wmap = _map_phonemes_to_words(words, ph_ivs, 0.0, phone_counts=[1, 2])
    assert [p["ph"] for p in wmap[0]["phonemes"]] == ["AH"], wmap[0]
    assert [p["ph"] for p in wmap[1]["phonemes"]] == ["K", "AE"], wmap[1]
    uni = _map_phonemes_to_words(words, ph_ivs, 0.0)  # no counts → uniform ratio
    assert [p["ph"] for p in uni[0]["phonemes"]] == ["AH", "K"], uni[0]
    print("s04 whisper-mode map demo OK")

    # Icelandic lexicon: a listed word bypasses g2p (key ignores case/punct/accents kept).
    lex = {_word_key("Dýrið"): ["D", "IY", "R", "IH", "DH"]}
    assert _phonemise_text("Dýrið,", None, lex) == ["D", "IY", "R", "IH", "DH"]  # g2p unused
    assert _word_key("Höfuðið!") == "höfuðið"
    print("s04 icelandic-lexicon demo OK")


@contextmanager
def _hfa_batch_dir(job_dir: Path):
    tmp_dir = job_dir / f".hfa_batch_{uuid4().hex[:8]}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=False)
    write_event(
        job_dir,
        "stage04.temp_dir_created",
        "aligning",
        details={"path": str(tmp_dir), "name": tmp_dir.name},
    )
    try:
        yield tmp_dir
    finally:
        cleanup_error = ""
        try:
            shutil.rmtree(tmp_dir)
        except Exception as exc:
            cleanup_error = str(exc)
            shutil.rmtree(tmp_dir, ignore_errors=True)
        removed = not tmp_dir.exists()
        write_event(
            job_dir,
            "stage04.temp_dir_cleanup",
            "aligning",
            level="info" if removed else "warning",
            message=cleanup_error,
            details={"path": str(tmp_dir), "name": tmp_dir.name, "removed": removed},
        )


def _parse_textgrid(path: Path) -> list[dict[str, Any]]:
    """Parse a Praat TextGrid file (inline). Handles long/short formats.

    HubertFA writes two tiers — ``words`` then ``phones`` — so each interval is
    tagged with the tier it actually belongs to (tracked by file position),
    otherwise phoneme and word intervals get mixed and duplicated.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    intervals: list[dict[str, Any]] = []
    tier_name_re = re.compile(r'name\s*=\s*"([^"]+)"')
    interval_re  = re.compile(
        r'xmin\s*=\s*([\d.]+)\s*\n\s*xmax\s*=\s*([\d.]+)\s*\n\s*text\s*=\s*"([^"]*)"',
        re.MULTILINE,
    )
    # Merge tier-name markers and intervals into one position-ordered stream so
    # each interval inherits the most recent tier name before it.
    events: list[tuple[int, str, Any]] = []
    for m in tier_name_re.finditer(text):
        events.append((m.start(), "tier", m.group(1)))
    for m in interval_re.finditer(text):
        events.append((m.start(), "iv", (float(m.group(1)), float(m.group(2)), m.group(3).strip())))
    events.sort(key=lambda e: e[0])

    current_tier = "phones"
    for _, kind, value in events:
        if kind == "tier":
            current_tier = value
        else:
            xmin, xmax, txt = value
            intervals.append({"tier": current_tier, "xmin": xmin, "xmax": xmax, "text": txt})
    if not intervals:
        raise ValueError(f"No intervals parsed from TextGrid at {path}")
    return intervals


# Icelandic-only letters — used to flag words that g2p_en would mis-phonemise.
_IS_CHARS = set("þðæöáéíóúýÞÐÆÖÁÉÍÓÚÝ")


def _word_key(text: str) -> str:
    """Lexicon lookup key: letters only, lowercased (keeps þðæö and accents)."""
    return "".join(ch for ch in text.lower() if ch.isalpha())


def _load_is_lexicon(path: Path) -> dict[str, list[str]]:
    """Load an Icelandic word→ARPAbet lexicon (``word\\tPH PH PH`` per line).

    The HubertFA model has no native Icelandic phone set (only en/ja/zh), so
    these are the nearest en/ ARPAbet phones — good enough to get the vowel /
    syllable count right, which is what g2p_en gets wrong on Icelandic spelling.
    Optional: returns {} if the file is absent.
    """
    lex: dict[str, list[str]] = {}
    if not path.exists():
        return lex
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        word, _, phones = line.partition("\t")
        phones = phones or ""
        key = _word_key(word)
        if key and phones.split():
            lex[key] = phones.upper().split()
    return lex


def _phonemise_text(text: str, g2p, is_lexicon: dict[str, list[str]] | None = None) -> list[str]:
    """Convert text to ARPAbet (stress stripped).

    A single word present in ``is_lexicon`` is taken from there verbatim (correct
    Icelandic pronunciation); everything else goes through g2p_en.
    """
    if is_lexicon:
        hit = is_lexicon.get(_word_key(text))
        if hit is not None:
            return list(hit)
    raw = g2p(text)
    phonemes = []
    for token in raw:
        if token and token[0].isupper() and token.isalpha() or _STRESS_RE.search(token):
            clean = _STRESS_RE.sub("", token).upper()
            if clean:
                phonemes.append(clean)
    return phonemes


def _slice_wav(source: Path, out: Path, start_s: float, end_s: float) -> None:
    """Slice WAV range using stdlib wave."""
    import wave
    with wave.open(str(source), "rb") as src:
        params, rate = src.getparams(), src.getframerate()
        start_f, end_f = int(start_s * rate), int(end_s * rate)
        src.setpos(start_f)
        frames = src.readframes(end_f - start_f)
    with wave.open(str(out), "wb") as dst:
        dst.setparams(params)
        dst.writeframes(frames)


def _whisper_fallback(words: list[dict]) -> list[dict]:
    """Build word list from Whisper timestamps when alignment fails."""
    result = []
    for w in words:
        entry = dict(w)  # preserve all existing flags (low_confidence, probability)
        entry.update({"source": "whisper_fallback", "phonemes": []})
        result.append(entry)
    return result


def _ctc_forced_fallback(words: list[dict]) -> list[dict]:
    """Preserve provider word timestamps without phoneme data."""
    result = []
    for w in words:
        entry = dict(w)
        entry.update({"source": w.get("source", "ctc_forced"), "phonemes": []})
        result.append(entry)
    return result


def _ctc_forced_with_phonemes(
    words: list[dict], ph_ivs: list[dict], offset: float,
    min_word_dur: float = DEFAULT_MIN_WORD_MS / 1000.0,
    phone_counts: list[int] | None = None,
    assign: str = "sequence",
) -> list[dict]:
    """
    Keep CTC word timestamps; attach each HubertFA phoneme to a word. Word
    start/end always come from the CTC aligner (s03b) and are NOT overwritten
    unless invalid — only the phoneme→word assignment differs by ``assign``:

    * ``sequence`` (default): slice the ordered phone stream by the real g2p
      phoneme count per word (``phone_counts``). Forced alignment aligns exactly
      the phoneme sequence we fed it, in order, so the filtered ``phones`` tier
      maps 1:1 to the concatenated per-word g2p phones. This is how MFA / SOFA
      group phones into words (by lexicon count), not by time. Falls back to
      ``timebucket`` for a segment iff the count invariant does not hold.
    * ``timebucket``: assign each phoneme to the word whose [start, end] span its
      midpoint falls into (nearest word if it lands in a gap). Legacy path;
      drifts when CTC word spans are mis-sized in sustained singing.

    A word that captures no phoneme stays plain ``ctc_forced`` with
    ``phonemes: []`` (renders as a single highlight downstream).
    """
    min_dur = 0.050  # 50ms

    # Normalise word spans first (fix zero-duration and overlaps), keeping order.
    spans: list[tuple[float, float]] = []
    for word in words:
        w_start = word["start"]
        w_end = word["end"]
        if w_end <= w_start:
            w_end = w_start + min_dur
            logger.info("Fixed zero-duration word '%s' in forced mode: %.4f -> %.4f",
                        word["word"], w_start, w_end)
        if spans:
            prev_end = spans[-1][1]
            if w_start < prev_end:
                w_start = prev_end
                if w_end < w_start + min_dur:
                    w_end = w_start + min_dur
        spans.append((round(w_start, 4), round(w_end, 4)))

    # Lift degenerate (near-zero) word spans to a plausible floor before phonemes
    # are bucketed, so CTC-compressed function words get real timing and their
    # phonemes land inside their own span. Line envelope stays fixed (line-sync).
    spans, _ = _apply_word_duration_floor(spans, min_word_dur)

    # Absolute-time phonemes, in TextGrid order.
    phones = [
        {"ph": v["text"], "start": round(v["xmin"] + offset, 4),
         "end": round(v["xmax"] + offset, 4)}
        for v in ph_ivs
    ]

    # Choose assignment. Sequence mode needs the count invariant to hold for this
    # segment; otherwise it would shift every following word, so fall back to time.
    use_sequence = (
        assign == "sequence"
        and phone_counts is not None
        and len(phone_counts) == len(words)
        and sum(phone_counts) == len(phones)
    )
    if assign == "sequence" and phone_counts is not None and not use_sequence:
        logger.warning(
            "phone-assign=sequence: count invariant broke (words=%d, counts=%d/sum=%d, "
            "phones=%d) — using timebucket for this segment",
            len(words), len(phone_counts), sum(phone_counts), len(phones),
        )

    buckets: list[list[dict]] = [[] for _ in words]
    if use_sequence:
        idx = 0
        for i, n in enumerate(phone_counts):
            buckets[i] = phones[idx : idx + n]
            idx += n
    elif spans:
        for ph in phones:
            mid = (ph["start"] + ph["end"]) / 2.0
            idx = next(
                (i for i, (ws, we) in enumerate(spans) if ws - 1e-6 <= mid <= we + 1e-6),
                None,
            )
            if idx is None:  # fell in a gap — attach to the nearest word boundary
                idx = min(
                    range(len(spans)),
                    key=lambda i: min(abs(mid - spans[i][0]), abs(mid - spans[i][1])),
                )
            buckets[idx].append(ph)

    result = []
    for i, word in enumerate(words):
        w_start, w_end = spans[i]
        ivs = buckets[i]
        base_source = word.get("source", "ctc_forced")
        entry = {
            "word":     word["word"],
            "start":    w_start,
            "end":      w_end,
            "source":   base_source if not ivs else f"{base_source}+hubertfa",
            "phonemes": ivs,
        }
        if word.get("low_confidence"):
            entry["low_confidence"] = True
        if "probability" in word:
            entry["probability"] = word["probability"]
        result.append(entry)
    return result
def _linear_interpolate_words(words: list[dict], seg_start: float, seg_end: float) -> list[dict]:
    """
    Fill in missing or inverted timestamps by interpolating between known good points.
    Used when HubertFA fails but surrounding words in the same segment are valid.
    """
    n = len(words)
    if n == 0: return words
    
    # Identify good anchors (words with valid HubertFA phoneme data)
    anchors = [] # list of (index, start, end)
    for i, w in enumerate(words):
        if w.get("source") in ("hubertfa", "ctc_forced+hubertfa"):
            anchors.append((i, w["start"], w["end"]))
            
    if not anchors:
        # No good anchors in this segment, keep original fallback (Whisper/CTC)
        return words
        
    # Interpolate before first anchor
    first_idx, first_start, _ = anchors[0]
    if first_idx > 0:
        slice_dur = (first_start - seg_start) / (first_idx + 1)
        for i in range(first_idx):
            words[i]["start"] = round(seg_start + i * slice_dur, 4)
            words[i]["end"]   = round(seg_start + (i + 1) * slice_dur, 4)
            words[i]["source"] = "interpolated"

    # Interpolate between anchors
    for a in range(len(anchors) - 1):
        idx1, _, end1 = anchors[a]
        idx2, start2, _ = anchors[a+1]
        gap = idx2 - idx1
        if gap > 1:
            slice_dur = (start2 - end1) / gap
            for i in range(1, gap):
                words[idx1 + i]["start"] = round(end1 + (i-1) * slice_dur, 4)
                words[idx1 + i]["end"]   = round(end1 + i * slice_dur, 4)
                words[idx1 + i]["source"] = "interpolated"
                
    # Interpolate after last anchor
    last_idx, _, last_end = anchors[-1]
    if last_idx < n - 1:
        gap = n - last_idx
        slice_dur = (seg_end - last_end) / gap
        for i in range(1, gap):
            words[last_idx + i]["start"] = round(last_end + (i-1) * slice_dur, 4)
            words[last_idx + i]["end"]   = round(last_end + i * slice_dur, 4)
            words[last_idx + i]["source"] = "interpolated"
            
    return words




def _map_phonemes_to_words(
    words: list[dict], ph_ivs: list[dict], offset: float,
    phone_counts: list[int] | None = None,
) -> list[dict]:
    """Assign phonemes to words and derive word timing from them (whisper mode).

    Slices the ordered phone stream by the real g2p phoneme count per word
    (``phone_counts``) — the same lexicon-count grouping as forced mode — when the
    count invariant holds. Falls back to a uniform count-ratio split when counts
    are absent or don't match the aligned phone stream.
    """
    result, ph_idx, total_ph = [], 0, len(ph_ivs)
    use_sequence = (
        phone_counts is not None
        and len(phone_counts) == len(words)
        and sum(phone_counts) == total_ph
    )
    if phone_counts is not None and not use_sequence:
        logger.warning(
            "map_phonemes: count invariant broke (words=%d, counts=%d/sum=%d, "
            "phones=%d) — using uniform ratio split",
            len(words), len(phone_counts), sum(phone_counts), total_ph,
        )
    for w_i, word in enumerate(words):
        if use_sequence:
            n_ph = phone_counts[w_i]
        else:
            rem_w = len(words) - w_i
            rem_ph = total_ph - ph_idx
            n_ph = max(1, round(rem_ph / rem_w)) if w_i < len(words) - 1 else rem_ph
        ivs = ph_ivs[ph_idx : ph_idx + n_ph]
        ph_idx += n_ph
        if not ivs:
            result.append({
                "word": word["word"], "start": word["start"], "end": word["end"],
                "source": "needs_interpolation", "phonemes": []
            })
            continue

        # Use min/max across all phoneme intervals for this word.
        word_start = round(min(iv["xmin"] for iv in ivs) + offset, 4)
        word_end   = round(max(iv["xmax"] for iv in ivs) + offset, 4)

        if word_start >= word_end:
            logger.warning("Word '%s': inverted timestamps (%.4f >= %.4f) - marking for interpolation", 
                           word["word"], word_start, word_end)
            result.append({
                "word": word["word"], "start": word["start"], "end": word["end"],
                "source": "needs_interpolation", "phonemes": []
            })
            continue

        entry = {
            "word":     word["word"],
            "start":    word_start,
            "end":      word_end,
            "source":   "hubertfa",
            "phonemes": [{"ph": v["text"], "start": round(v["xmin"] + offset, 4), "end": round(v["xmax"] + offset, 4)} for v in ivs]
        }
        if word.get("low_confidence"): entry["low_confidence"] = True
        if "probability" in word: entry["probability"] = word["probability"]
        result.append(entry)
    return result


def _update_status(job_dir: Path, stage: str, progress: int, error: str = "") -> None:
    status_path = job_dir / "status.json"
    data = json.loads(status_path.read_text()) if status_path.exists() else {}
    data.update({"stage": stage, "progress": progress, "error": error, "updated_at": time.time()})
    status_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _stage04_event(
    job_dir: Path,
    event: str,
    level: str = "info",
    message: str = "",
    **details: Any,
) -> None:
    write_event(
        job_dir,
        event,
        "aligning",
        level=level,
        message=message,
        details=details,
    )


def _stage04_fail(job_dir: Path, event: str, message: str, **details: Any) -> int:
    _stage04_event(job_dir, event, level="error", message=message, **details)
    _stage04_event(job_dir, "stage04.failed", level="error", message=message, **details)
    return 1


def _write_missing_job_event(job_dir: Path, message: str) -> None:
    parent = job_dir.parent if job_dir.parent != job_dir else Path.cwd()
    write_event(
        parent / "_stage04",
        "stage04.failed",
        "aligning",
        level="error",
        message=message,
        details={"reason": "job_dir_missing", "missing_job_dir": str(job_dir)},
    )


def _source_distribution(words: list[dict]) -> dict[str, int]:
    source_counts: dict[str, int] = {}
    for w in words:
        s = w.get("source", "unknown")
        source_counts[s] = source_counts.get(s, 0) + 1
    return source_counts


def _available_onnx_providers() -> list[str]:
    try:
        import onnxruntime as ort
    except Exception:
        return []
    return list(ort.get_available_providers())


def _fallback_all_segments(segments: list[dict], fallback) -> tuple[list[dict], int]:
    all_words: list[dict] = []
    word_count = 0
    for seg in segments:
        words = fallback(seg.get("words", []))
        words = normalize_words(words, seg["start"], seg["end"])
        all_words.extend(words)
        word_count += len(words)
    return all_words, word_count


def main() -> int:
    hw = detect()
    app_config = load_app_config()
    parser = argparse.ArgumentParser(description="Stage 04 — Phoneme Alignment (Batch ONNX)")
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--hubertfa-dir", default=app_config.align_hubertfa_dir, type=Path)
    parser.add_argument("--checkpoint", default=app_config.align_checkpoint, type=Path)
    parser.add_argument("--language", default=app_config.align_language)
    parser.add_argument("--hubertfa-timeout", default=app_config.align_hubertfa_timeout_s, type=int)
    parser.add_argument(
        "--allow-cpu-hubertfa",
        action="store_true",
        help="Allow HubertFA ONNX inference when only CPUExecutionProvider is available.",
    )
    parser.add_argument("--log-level", default=app_config.log_level, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument(
        "--phone-assign",
        default="sequence",
        choices=["sequence", "timebucket"],
        help="Forced-mode phoneme→word assignment: 'sequence' slices the phone "
             "stream by real g2p count per word (default); 'timebucket' is the "
             "legacy midpoint-in-CTC-span assignment.",
    )
    args = parser.parse_args()

    job_dir = args.job_dir.resolve()
    log_handlers: list[logging.Handler] = [logging.StreamHandler()]
    if job_dir.exists():
        log_handlers.append(logging.FileHandler(job_dir / "pipeline.log", mode="a"))
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
        handlers=log_handlers,
    )

    if not job_dir.exists():
        message = f"Job directory does not exist: {job_dir}"
        logger.error(message)
        _write_missing_job_event(job_dir, message)
        return 1

    _stage04_event(
        job_dir,
        "stage04.started",
        alignment_mode="unknown",
        language=args.language,
        hubertfa_timeout=args.hubertfa_timeout,
    )
    
    vocals_path, transcript_path = job_dir / "vocals.wav", job_dir / "transcript.json"
    if not vocals_path.exists() or not transcript_path.exists():
        record_artifact(job_dir, "aligning", vocals_path)
        record_artifact(job_dir, "aligning", transcript_path)
        message = f"Inputs missing in {job_dir}"
        logger.error(message)
        return _stage04_fail(
            job_dir,
            "stage04.input_missing",
            message,
            vocals_exists=vocals_path.exists(),
            transcript_exists=transcript_path.exists(),
        )
    record_artifact(job_dir, "aligning", vocals_path)
    record_artifact(job_dir, "aligning", transcript_path)

    model_dir = args.checkpoint.parent
    for sidecar in ("config.json", "vocab.json", "VERSION"):
        if not (model_dir / sidecar).exists():
            message = f"Missing HubertFA sidecar file: {sidecar}"
            logger.error(message)
            return _stage04_fail(
                job_dir,
                "stage04.sidecar_missing",
                message,
                sidecar=sidecar,
                path=str(model_dir / sidecar),
            )

    try:
        from g2p_en import G2p
        g2p = G2p()
    except ImportError as exc:
        message = "pip install g2p_en required"
        logger.error(message)
        return _stage04_fail(
            job_dir,
            "stage04.import_failed",
            message,
            module="g2p_en",
            error=str(exc),
        )

    # Optional pronunciation lexicons (word→ARPAbet), next to the model: any
    # <lang>_pron_dict.txt. Words listed there bypass g2p_en, which mangles
    # non-English spelling (is_ = Icelandic, pt_ = Brazilian Portuguese).
    is_lexicon: dict[str, list[str]] = {}
    for lex_path in sorted(model_dir.glob("*_pron_dict.txt")):
        loaded = _load_is_lexicon(lex_path)
        is_lexicon.update(loaded)
        if loaded:
            logger.info("Loaded lexicon: %d words (%s)", len(loaded), lex_path.name)

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    segments = transcript.get("segments", [])
    if not segments:
        message = "No segments found"
        logger.error(message)
        return _stage04_fail(job_dir, "stage04.no_segments", message)

    alignment_mode = transcript.get("alignment_mode", "whisper")
    preserves_provider_timing = alignment_mode == "forced"
    _stage04_event(
        job_dir,
        "stage04.transcript_loaded",
        alignment_mode=alignment_mode,
        segment_count=len(segments),
        language=args.language,
        hubertfa_timeout=args.hubertfa_timeout,
    )

    logger.info(
        "Stage 04 · Align  alignment_mode=%s  segments=%d",
        alignment_mode, len(segments),
    )
    if preserves_provider_timing:
        logger.info(
            "Provider alignment detected — word timestamps will be preserved. "
            "HubertFA phonemes attached as metadata only."
        )

    _update_status(job_dir, "aligning", 0)
    all_aligned_words = []

    # Word-duration floor: lift CTC-compressed function words to a plausible
    # duration during phoneme attachment (forced mode). See _apply_word_duration_floor.
    min_word_dur = app_config.align_min_word_ms / 1000.0
    words_below_floor_before = sum(
        1
        for seg in segments
        for w in seg.get("words", [])
        if float(w.get("end", 0.0)) - float(w.get("start", 0.0)) < min_word_dur - 1e-9
    )

    # Determine the correct fallback function based on alignment mode
    _fallback = _ctc_forced_fallback if preserves_provider_timing else _whisper_fallback

    with _hfa_batch_dir(job_dir) as tmp_dir:
        logger.info("Batch Prep: Slicing %d segments into %s", len(segments), tmp_dir)
        prepared_count = 0
        skipped_count = 0
        
        for i, seg in enumerate(segments):
            stem = f"seg_{i:04d}"
            try:
                _slice_wav(vocals_path, tmp_dir / f"{stem}.wav", seg["start"], seg["end"])
                # Phonemise per word so the .lab we align and the per-word counts
                # come from the SAME g2p pass — this makes the count invariant that
                # sequence-mode phoneme→word assignment relies on exact. Falls back
                # to whole-segment text when a segment carries no word list.
                seg_words = seg.get("words", [])
                if seg_words:
                    per_word = [_phonemise_text(w["word"], g2p, is_lexicon) for w in seg_words]
                    phs_seq = [p for wp in per_word for p in wp]
                    seg["_ph_counts"] = [len(wp) for wp in per_word]
                    # Flag Icelandic-spelled words missing from the lexicon so it
                    # can grow — these still fall back to g2p_en (mangled).
                    for w in seg_words:
                        if any(ch in _IS_CHARS for ch in w["word"]) and _word_key(w["word"]) not in is_lexicon:
                            logger.warning("Icelandic word not in lexicon (g2p_en fallback): %r", w["word"])
                else:
                    phs_seq = _phonemise_text(seg["text"], g2p, is_lexicon)
                    seg["_ph_counts"] = None
                phs = [p.lower() for p in phs_seq]
                (tmp_dir / f"{stem}.lab").write_text(" ".join(phs), encoding="utf-8")
                prepared_count += 1
            except Exception as e:
                skipped_count += 1
                logger.warning("Prep failed for segment %d: %s", i, e)
        _stage04_event(
            job_dir,
            "stage04.batch_prepared",
            prepared=prepared_count,
            skipped=skipped_count,
            segment_count=len(segments),
        )

        # ── Run HubertFA ONCE for all segments ──
        res = None
        start_time = time.time()
        providers = _available_onnx_providers()
        accelerated = {"CUDAExecutionProvider", "DmlExecutionProvider"}
        if not args.allow_cpu_hubertfa and not accelerated.intersection(providers):
            reason = (
                "cpu_only_onnx_provider"
                if "CPUExecutionProvider" in providers
                else "onnx_provider_unavailable"
            )
            logger.warning(
                "Skipping HubertFA: ONNX providers=%s. Use --allow-cpu-hubertfa to force CPU inference.",
                providers,
            )
            _stage04_event(
                job_dir,
                "stage04.hubertfa_skipped",
                level="warning",
                reason=reason,
                providers=providers,
            )
            fallback_words, fallback_word_count = _fallback_all_segments(segments, _fallback)
            all_aligned_words.extend(fallback_words)
            _stage04_event(
                job_dir,
                "stage04.fallback_used",
                level="warning",
                reason=reason,
                word_count=fallback_word_count,
            )
        else:
            logger.info("Batch Inference: Running HubertFA onnx_infer.py (Model: %s)", args.checkpoint.name)
            cmd = [
                sys.executable, str(args.hubertfa_dir / "onnx_infer.py"),
                "--onnx_path", str(args.checkpoint),
                "--wav_folder", str(tmp_dir),
                "--out_path", str(tmp_dir),
                "--g2p", "phoneme",
                "--language", args.language
            ]
            
            _stage04_event(
                job_dir,
                "stage04.hubertfa_started",
                timeout=args.hubertfa_timeout,
                prepared=prepared_count,
                skipped=skipped_count,
                providers=providers,
            )
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=args.hubertfa_timeout,
                )
            except subprocess.TimeoutExpired:
                logger.error("HubertFA Batch timed out after %ss; using fallback timings", args.hubertfa_timeout)
                _stage04_event(
                    job_dir,
                    "stage04.hubertfa_timeout",
                    level="error",
                    message=f"HubertFA timed out after {args.hubertfa_timeout}s",
                    timeout=args.hubertfa_timeout,
                )
                fallback_words, fallback_word_count = _fallback_all_segments(segments, _fallback)
                all_aligned_words.extend(fallback_words)
                _stage04_event(
                    job_dir,
                    "stage04.fallback_used",
                    level="warning",
                    reason="hubertfa_timeout",
                    word_count=fallback_word_count,
                )

        if res is not None and res.returncode != 0:
            logger.error("HubertFA Batch failed:\n%s", res.stderr)
            _stage04_event(
                job_dir,
                "stage04.hubertfa_finished",
                level="error",
                message=f"return code {res.returncode}",
                returncode=res.returncode,
            )
            # Global fallback if batch inference crashes
            fallback_words, fallback_word_count = _fallback_all_segments(segments, _fallback)
            all_aligned_words.extend(fallback_words)
            _stage04_event(
                job_dir,
                "stage04.fallback_used",
                level="warning",
                reason="hubertfa_nonzero",
                word_count=fallback_word_count,
            )
        elif res is not None:
            elapsed = time.time() - start_time
            logger.info("Batch Inference OK (%.2fs for %d segments)", elapsed, len(segments))
            _stage04_event(
                job_dir,
                "stage04.hubertfa_finished",
                returncode=res.returncode,
                duration_ms=int(elapsed * 1000),
            )

            # ── Parse and map results ──
            tg_dir = tmp_dir / "TextGrid"
            for i, seg in enumerate(segments):
                stem = f"seg_{i:04d}"
                tg_path = tg_dir / f"{stem}.TextGrid"
                
                if tg_path.exists():
                    try:
                        ivs = _phone_intervals(_parse_textgrid(tg_path))
                        if preserves_provider_timing:
                            # Provider timing mode: keep word timestamps, attach phonemes as metadata
                            words = _ctc_forced_with_phonemes(
                                seg.get("words", []), ivs, seg["start"],
                                min_word_dur=min_word_dur,
                                phone_counts=seg.get("_ph_counts"),
                                assign=args.phone_assign,
                            )
                        else:
                            # Whisper mode: derive timestamps from HubertFA phonemes
                            words = _map_phonemes_to_words(
                                seg.get("words", []), ivs, seg["start"],
                                phone_counts=seg.get("_ph_counts"),
                            )
                        
                        # Apply linear interpolation for missing/inverted words
                        words = _linear_interpolate_words(words, seg["start"], seg["end"])
                        words = normalize_words(words, seg["start"], seg["end"])
                         
                        all_aligned_words.extend(words)
                        continue
                    except Exception as e:
                        logger.warning("Parse failed for %s: %s", stem, e)
                        _stage04_event(
                            job_dir,
                            "stage04.parse_failed",
                            level="warning",
                            message=str(e),
                            stem=stem,
                            segment_index=i,
                        )
                
                # Fallback for individual missing/failed segments
                words = _fallback(seg.get("words", []))
                words = normalize_words(words, seg["start"], seg["end"])
                all_aligned_words.extend(words)
                _stage04_event(
                    job_dir,
                    "stage04.fallback_used",
                    level="warning",
                    reason="segment_textgrid_missing_or_failed",
                    word_count=len(words),
                    stem=stem,
                    segment_index=i,
                )

    # Save output
    aligned = {"alignment_mode": alignment_mode, "words": all_aligned_words}
    output_path = job_dir / "aligned.json"
    source_counts = _source_distribution(all_aligned_words)

    # Record the word-duration-floor decision and its measured effect.
    durations_ms = sorted(
        round((float(w.get("end", 0.0)) - float(w.get("start", 0.0))) * 1000.0, 1)
        for w in all_aligned_words
    )
    median_word_ms = durations_ms[len(durations_ms) // 2] if durations_ms else 0.0
    words_below_floor_after = sum(1 for d in durations_ms if d < min_word_dur * 1000.0 - 1e-6)
    _stage04_event(
        job_dir,
        "stage04.word_floor_applied",
        min_word_ms=app_config.align_min_word_ms,
        words_below_floor_before=words_below_floor_before,
        words_below_floor_after=words_below_floor_after,
        median_word_ms=median_word_ms,
        word_count=len(all_aligned_words),
    )
    _stage04_event(
        job_dir,
        "stage04.source_distribution",
        word_count=len(all_aligned_words),
        source_distribution=source_counts,
    )
    output_path.write_text(json.dumps(aligned, indent=2, ensure_ascii=False), encoding="utf-8")
    record_artifact(job_dir, "aligning", output_path)
    _stage04_event(
        job_dir,
        "stage04.aligned_written",
        word_count=len(all_aligned_words),
        source_distribution=source_counts,
        path=str(output_path),
        size_bytes=output_path.stat().st_size,
    )
    logger.info("Stage 04 OK: %d words, sources: %s", len(all_aligned_words), source_counts)
    _update_status(job_dir, "aligning", 100)
    _stage04_event(
        job_dir,
        "stage04.completed",
        word_count=len(all_aligned_words),
        source_distribution=source_counts,
    )
    return 0

if __name__ == "__main__":
    sys.exit(main())
