"""
s03b_lyrics_align.py — Forced lyric alignment via CTC + MMS Wav2Vec2.

Bypasses Whisper entirely when lyrics.txt is available. Instead of
transcribing (asking "what is being sung?"), this script aligns (asking
"when is each known word being sung?") — the same paradigm used by
MyKaraoke Video, Youka, and Capify.

Why this beats Whisper for karaoke when lyrics exist:
    - Whisper was trained on speech, not singing. VAD removes sustained
      notes. Greedy beam=1 hallucinates on sparse/extended vocals.
    - Forced alignment takes the known lyrics as ground truth and finds
      the precise timestamp for each word. Zero hallucination possible.
    - For "Struggle"-type songs (long instrumental intro, sparse vocals,
      scream sections), forced alignment is the only reliable approach.

Model: MahmoudAshraf/mms-300m-1130-forced-aligner (~1.2 GB)
    - Downloaded automatically on first run to ~/.cache/huggingface/
    - Supports 1130+ languages via Meta's Massively Multilingual Speech
    - Runs on CPU (no DirectML/CUDA required — same constraint as Whisper)

Hardware note (Z13 AMD iGPU):
    ctc-forced-aligner uses PyTorch CPU path. The model runs efficiently
    on the Z13's CPU for songs up to ~10 minutes. DirectML is not needed
    here — HubertFA in Stage 04 handles the GPU-accelerated work.

Output schema: identical to s03_transcribe.py transcript.json so Stage 04
(HubertFA) and Stage 05 (Ollama) work without any modification.

Additional fields in transcript.json (not present in Whisper output):
    alignment_mode: "forced"           — signals downstream that lyrics
                                         are ground truth
    segments[*].section: "chorus"      — section label from lyrics.txt
                                         used by s05 to skip LLM style
                                         inference

Usage (auto — called by test_pipeline.py when lyrics.txt exists):
    python scripts/s03b_lyrics_align.py
        --job-dir jobs/my-job
        --lyrics  jobs/my-job/lyrics.txt

Usage (explicit language):
    python scripts/s03b_lyrics_align.py
        --job-dir jobs/my-job
        --lyrics  jobs/my-job/lyrics.txt
        --language jpn

Pitch-guided boundary correction (pYIN):
    After CTC alignment, pYIN (via librosa) detects note onsets in the
    vocals.wav. Each CTC word boundary is snapped to the nearest note
    onset within a ±1.5s window. This is the same technique used by
    Spotify Research to improve alignment accuracy on sustained notes
    and melismatic transitions — the main failure mode of generic CTC
    aligners on singing voice.

    The correction is conservative: if a snap would invert a word
    boundary relative to its neighbor, it is discarded. The original
    CTC timestamp is kept as fallback.

Reads:
    jobs/{job_id}/vocals.wav
    <lyrics_path>               (lyrics.txt with [Section] markers)

Writes:
    jobs/{job_id}/transcript.json
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root
sys.path.insert(0, str(Path(__file__).parent))                    # scripts/ dir
from hw_detect import detect
try:
    from scripts.common.observability import write_event
except ModuleNotFoundError:
    from common.observability import write_event
try:
    from scripts.common.config import load_app_config as _load_cfg
except ModuleNotFoundError:
    from common.config import load_app_config as _load_cfg
_cfg = _load_cfg()

# Fix Windows encoding issues for checkmark/cross symbols
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, io.UnsupportedOperation):
        pass

logger = logging.getLogger(__name__)

# ISO-639-3 language codes for the MMS model.
# Different from Whisper's ISO-639-1 codes (en → eng, ja → jpn, pt → por).
LANGUAGE_MAP = {
    "en": "eng", "ja": "jpn", "pt": "por", "zh": "zho",
    "es": "spa", "fr": "fra", "de": "deu", "ko": "kor",
    "ar": "ara", "ru": "rus", "it": "ita", "nl": "nld",
}

# Section label → style name (used by s05 to bypass LLM style inference)
# Canonical section label → ASS style name.
# Keys are lowercase, stripped. Add new genres / DAWs here as discovered.
SECTION_TO_STYLE: dict[str, str] = {
    # ── Intro / Outro ───────────────────────────────────────────────────
    "intro":            "intro",
    "introduction":     "intro",
    "opening":          "intro",
    "outro":            "outro",
    "outro chorus":     "outro",
    "outro hook":       "outro",
    "ending":           "outro",
    "fade out":         "outro",
    "fade-out":         "outro",
    "coda":             "outro",
    # ── Verse ───────────────────────────────────────────────────────────
    "verse":            "verse",
    "verse 1":          "verse",
    "verse 2":          "verse",
    "verse 3":          "verse",
    "estrofe":          "verse",   # Portuguese
    "estrofa":          "verse",   # Spanish
    "rap":              "rap",     # bare [Rap], common in Suno / pt-BR lyrics
    "rap verse":        "verse",
    "spoken":           "verse",
    "spoken word":      "verse",
    # ── Chorus / Hook ───────────────────────────────────────────────────
    "chorus":           "chorus",
    "chorus 2":         "chorus",
    "chorus 3":         "chorus",
    "refrao":           "chorus",  # Portuguese (no accent)
    "refrão":           "chorus",  # Portuguese (with accent)
    "refrán":           "chorus",  # Spanish
    "hook":             "chorus",
    "hook 2":           "chorus",
    "drop":             "chorus",  # EDM
    "drop 1":           "chorus",
    "drop 2":           "chorus",
    "big chorus":       "chorus",
    "final chorus":     "chorus",
    "climax":           "chorus",
    # ── Pre-Chorus ──────────────────────────────────────────────────────
    "pre-chorus":       "verse",
    "pre-chorus 2":     "verse",
    "pre chorus":       "verse",
    "pre-hook":         "verse",
    "lift":             "verse",   # some EDM / pop labels
    "build":            "verse",
    "build-up":         "verse",
    "buildup":          "verse",
    # ── Bridge / Breakdown ──────────────────────────────────────────────
    "bridge":           "bridge",
    "ponte":            "bridge",  # Portuguese/Spanish
    "breakdown":        "bridge",
    "break":            "bridge",
    "interlude":        "bridge",
    "guitar solo":      "bridge",
    "solo":             "bridge",
    "instrumental":     "bridge",
    "instrumental break":"bridge",
    "spoken bridge":    "bridge",
    "dialogue":         "bridge",
    "transition":       "bridge",
    "middle 8":         "bridge",
    "middle eight":     "bridge",
}

# Prefix-based fallback mapping (tried when exact label not found).
# If a label STARTS WITH a prefix, it maps to that style.
_SECTION_PREFIX_FALLBACK: dict[str, str] = {
    "verse":    "verse",
    "chorus":   "chorus",
    "refra":    "chorus",   # refrão / refrán
    "hook":     "chorus",
    "drop":     "chorus",
    "bridge":   "bridge",
    "pont":     "bridge",   # ponte
    "break":    "bridge",
    "pre":      "verse",    # pre-chorus / pre-hook
    "intro":    "intro",
    "outro":    "outro",
    "solo":     "bridge",
    "interl":   "bridge",
    "instru":   "bridge",
    "build":    "verse",
    "spoken":   "verse",
    "coda":     "outro",
}


# ---------------------------------------------------------------------------
# Lyrics parser
# ---------------------------------------------------------------------------

def _resolve_section(label: str) -> tuple[str, str]:
    """
    Map a raw section label to a canonical section key and ASS style.

    Resolution order:
    1. Exact match in SECTION_TO_STYLE
    2. Numbered suffix strip: "chorus 3" → "chorus"
    3. Prefix match in _SECTION_PREFIX_FALLBACK
    4. Default "verse" (logged as unknown)

    Returns (canonical_label, style_name).
    """
    # 1. Exact match
    if label in SECTION_TO_STYLE:
        return label, SECTION_TO_STYLE[label]

    # 2. Strip trailing number/parenthetical and retry
    # "chorus 3" → "chorus", "verse (2)" → "verse"
    stripped = re.sub(r"[\s\d\(\)]+$", "", label).strip()
    if stripped and stripped in SECTION_TO_STYLE:
        return stripped, SECTION_TO_STYLE[stripped]

    # 3. Prefix fallback
    for prefix, style in _SECTION_PREFIX_FALLBACK.items():
        if label.startswith(prefix):
            # Return a normalized label so downstream grouping works
            return label, style

    # 4. Unknown — return as-is with verse style; caller logs the marker
    return label, "verse"


def _is_stage_direction(label: str) -> bool:
    """
    Heuristic: is this [Label] a stage direction rather than a section marker?

    Stage directions tend to be verbose descriptive phrases:
    "Heavy Wall of Sound", "Drums kick in", "Raw Scream", etc.
    Section markers are short: "Chorus", "Verse", "Bridge".

    Rules (in order):
    1. If label is already a known section → NOT a stage direction.
    2. If label has more than 4 words → IS a stage direction.
    3. If label contains a stage-direction-specific keyword → IS a stage direction.
       Keywords are deliberately narrow to avoid false-positives on labels
       like "guitar solo" or "spoken word" that are valid section names.
    """
    # Rule 1: known sections are never stage directions
    if label in SECTION_TO_STYLE:
        return False
    stripped = re.sub(r"[\s\d\(\)]+$", "", label).strip()
    if stripped and stripped in SECTION_TO_STYLE:
        return False

    # Rule 2: word count threshold
    words = label.split()
    if len(words) > 4:
        return True

    # Rule 3: stage-specific keywords — deliberately narrow.
    # Excludes "guitar", "spoken", "bass", "solo" which are valid section names.
    direction_keywords = {
        # Percussion / instruments
        "drums", "kick", "snare", "hi-hat", "bass", "guitar",
        # Texture / dynamics
        "wall of", "riff", "melody", "tempo", "groove", "volume",
        "heavy", "loud", "soft", "slow", "fast", "staccato",
        # Vocal technique
        "scream", "whisper", "adlib", "ad lib", "backing", "vocal",
        "acapella", "a cappella", "monotone", "strain",
        # Production terms
        "instrumental only", "music only", "instrumental break",
        "ambient", "noise", "drone", "pad",
        "distortion", "feedback", "reverb", "echo",
        # Emotional/intensity descriptors (when NOT a section label)
        "tension", "energy", "build up", "climactic", "emotional",
        "chaotic", "explosion", "heavy groove",
        "cracks with", "maximum",
        "long instrumental", "long intro", "long outro",
        "short instrumental", "extended",
        "half time", "double time", "time signature",
    }
    return any(kw in label for kw in direction_keywords)


def _parse_lyrics(lyrics_path: Path) -> list[dict[str, str]]:
    """
    Parse lyrics.txt into a list of section-aware lyric line dicts.

    Returns:
        [{"text": "Cause I'm still here", "section": "chorus"}, ...]

    Resolution:
        - Pure [Label] lines: resolved via _resolve_section() with fallback chain
        - Verbose stage direction lines: skipped (do not update section)
        - Unknown markers: assigned "verse" style, original label preserved for
          s08_validate to report ("unknown section markers detected")
        - Inline directions like (Screams) or [Scream]: stripped from text
    """
    section_only_re = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    # Match: (complete), [complete], or (unclosed at end of line
    inline_dir_re   = re.compile(r"\([^)]*\)|\[[^\]]*\]|\([^)]*$")
    word_re         = re.compile(r"[a-zA-Z''\u00C0-\u024F]+")

    current_section  = "verse"
    unknown_markers: list[str] = []
    lines: list[dict[str, str]] = []

    for raw_line in lyrics_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        # Pure section marker line
        m = section_only_re.match(stripped)
        if m:
            raw_label = m.group(1).strip()
            label     = raw_label.lower()

            # Skip verbose stage directions (they don't change section)
            if _is_stage_direction(label):
                logger.debug("Stage direction skipped: [%s]", raw_label)
                continue

            canonical, style = _resolve_section(label)

            if style == "verse" and canonical not in SECTION_TO_STYLE:
                # Genuinely unknown — track for s08 reporting
                unknown_markers.append(raw_label)
                logger.warning(
                    "Unknown section marker [%s] — defaulting to 'verse'. "
                    "Add to SECTION_TO_STYLE if this is a real section.",
                    raw_label,
                )
            else:
                logger.debug("Section: [%s] → %s (%s)", raw_label, canonical, style)

            current_section = canonical
            continue

        # Strip inline stage directions from text lines
        clean = inline_dir_re.sub("", stripped).strip()
        # Must have at least one alphabetic word to be singable
        if not word_re.search(clean):
            continue

        lines.append({
            "text":             clean,
            "section":          current_section,
            "unknown_markers":  unknown_markers.copy() if unknown_markers else [],
        })

    if unknown_markers:
        logger.warning(
            "Encountered %d unknown section marker(s): %s. "
            "These were defaulted to 'verse'. "
            "s08_validate will report them.",
            len(set(unknown_markers)),
            sorted(set(unknown_markers)),
        )

    return lines


def _lyrics_observability_details(
    lyrics_path: Path,
    lyric_lines: list[dict[str, str]],
) -> dict[str, Any]:
    section_only_re = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    stage_direction_count = 0
    for raw_line in lyrics_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        match = section_only_re.match(stripped)
        if match and _is_stage_direction(match.group(1).strip().lower()):
            stage_direction_count += 1

    unknown_markers = sorted(set(
        marker
        for line in lyric_lines
        for marker in line.get("unknown_markers", [])
    ))
    sections = sorted({line.get("section", "verse") for line in lyric_lines})
    return {
        "line_count": len(lyric_lines),
        "section_count": len(sections),
        "sections": sections,
        "unknown_marker_count": len(unknown_markers),
        "unknown_markers": unknown_markers,
        "stage_direction_stripped_count": stage_direction_count,
    }


def _expand_contractions(text: str) -> str:
    """
    Normalize common singing contractions to improve model alignment confidence.
    This preserves word count to avoid desyncing the alignment results.
    """
    # Simply remove apostrophes from common contractions and normalize
    # This avoids the "I'm" -> "I am" (1 word -> 2 words) desync issue.
    contractions = {
        r"\b'cause\b": "cause",
        r"\bcause\b":  "cause",
        r"\b'til\b":   "til",
        r"\btil\b":    "til",
        r"\b'em\b":    "em",
        r"\b'bout\b":  "bout",
        r"\bgonna\b":  "gonna",
        r"\bwanna\b":  "wanna",
        r"\bgotta\b":  "gotta",
        r"\bi'm\b":    "im",
        r"\bi've\b":   "ive",
        r"\bi'll\b":   "ill",
        r"\bi'd\b":    "id",
        r"\bit's\b":   "its",
        r"\bcan't\b":  "cant",
        r"\bwon't\b":  "wont",
        r"\bdon't\b":  "dont",
        r"\bdidn't\b": "didnt",
        r"\bcouldn't\b":"couldnt",
        r"\bshouldn't\b":"shouldnt",
        r"\bwouldn't\b":"wouldnt",
        r"\bain't\b":  "aint",
    }
    
    expanded = text.lower()
    for pattern, replacement in contractions.items():
        expanded = re.sub(pattern, replacement, expanded)
    
    # Also strip any remaining apostrophes that might confuse tokenization
    expanded = expanded.replace("'", "")
    
    return expanded


def _build_full_text(lyric_lines: list[dict], expand: bool = False) -> str:
    """Flatten all lyric lines into a single space-separated string."""
    if expand:
        return " ".join(_expand_contractions(line["text"]) for line in lyric_lines)
    return " ".join(line["text"] for line in lyric_lines)


def _split_words_by_lines(
    lyric_lines: list[dict],
    word_results: list[dict],
) -> list[dict[str, Any]]:
    """
    Re-group flat word results back into lyric-line segments.

    The CTC aligner returns a flat list of word timestamps. We re-assign
    each word to its original lyric line by consuming words in order and
    matching against each line's expected word count.

    Returns a list of segment dicts matching the transcript.json schema,
    with an extra 'section' field for s05 to consume.
    """
    word_re = re.compile(r"[a-zA-Z''\u00C0-\u024F]+")
    segments: list[dict[str, Any]] = []
    word_idx = 0
    total_words = len(word_results)

    for lyric_line in lyric_lines:
        # Count words expected in this lyric line
        lyric_line_words = word_re.findall(lyric_line["text"])
        n = len(lyric_line_words)

        if word_idx >= total_words:
            # Ran out of aligned words — create a dummy segment
            logger.warning(
                "Ran out of aligned words at lyric line: '%s'",
                lyric_line["text"][:60],
            )
            break

        # Take the next n words from the flat result list
        chunk = word_results[word_idx : word_idx + n]
        word_idx += n

        if not chunk:
            continue

        # Enforce minimum word duration and non-overlap
        min_dur = 0.050  # 50ms
        for i in range(len(chunk)):
            w = chunk[i]
            if w["end"] <= w["start"]:
                w["end"] = w["start"] + min_dur
            
            # Prevent overlap with next word in chunk
            if i < len(chunk) - 1:
                next_w = chunk[i+1]
                if w["end"] > next_w["start"]:
                    # Split the gap or push back?
                    # Push back is safer for CTC
                    mid = (w["start"] + next_w["end"]) / 2
                    w["end"] = mid
                    next_w["start"] = mid
            
            # Final sanity check for duration
            if w["end"] - w["start"] < min_dur:
                w["end"] = w["start"] + min_dur

        seg_start = chunk[0]["start"]
        seg_end   = chunk[-1]["end"]

        segments.append({
            "text":    lyric_line["text"],
            "section": lyric_line["section"],
            "start":   round(seg_start, 4),
            "end":     round(seg_end,   4),
            "words": [
                {
                    "word":        lyric_line_words[i],  # Preserve original text
                    "start":       round(chunk[i]["start"], 4),
                    "end":         round(chunk[i]["end"],   4),
                    "probability": round(chunk[i].get("score", 1.0), 4),
                }
                for i in range(len(chunk))
            ],
        })

    if word_idx < total_words:
        logger.warning(
            "%d aligned words were not assigned to any lyric line "
            "(lyric line count may differ from lyrics.txt word count)",
            total_words - word_idx,
        )

    return segments



# ---------------------------------------------------------------------------
# Pitch-guided boundary correction
# ---------------------------------------------------------------------------

def _extract_note_onsets_crepe(
    vocals_path: Path,
    sr_target: int = 16000,
) -> tuple[list[float], Any, Any]:
    """
    Extract note onsets and voiced frames using torchcrepe.

    Returns:
        (onsets, times, voiced)
    """
    import torchcrepe
    import torch
    import numpy as np

    logger.info("Loading audio for CREPE pitch detection...")
    # torchcrepe expects float32 tensor at 16kHz
    import soundfile as sf
    import resampy
    audio_raw, sr = sf.read(str(vocals_path), always_2d=False)
    if audio_raw.ndim > 1:
        audio_raw = audio_raw.mean(axis=1)  # stereo → mono
    if sr != sr_target:
        audio_raw = resampy.resample(audio_raw, sr, sr_target)
        sr = sr_target

    audio_tensor = torch.tensor(audio_raw, dtype=torch.float32).unsqueeze(0)
    hop_length = 160  # 10ms at 16kHz — CREPE default

    # Predict pitch with Viterbi decoding (smoother, fewer octave errors)
    frequency, periodicity = torchcrepe.predict(
        audio_tensor,
        sr,
        hop_length=hop_length,
        fmin=50.0,
        fmax=2006.0,
        model="full",
        decoder=torchcrepe.decode.viterbi,
        return_periodicity=True,
        device="cpu",
        batch_size=_cfg.crepe_batch_size,
    )

    frequency   = frequency.squeeze().numpy()
    periodicity = periodicity.squeeze().numpy()
    times = np.arange(len(frequency)) * (hop_length / sr)

    # Voiced = periodicity > 0.21 (torchcrepe recommended threshold)
    voiced = periodicity > 0.21

    onsets: list[float] = []

    # Onset type 1: unvoiced → voiced transitions
    for i in range(1, len(voiced)):
        if not voiced[i - 1] and voiced[i]:
            onsets.append(float(times[i]))

    # Onset type 2: large pitch jumps (>2 semitones) within voiced regions
    prev_f0 = None
    for i in range(len(voiced)):
        if voiced[i] and frequency[i] > 0:
            if prev_f0 is not None and prev_f0 > 0:
                semitones = abs(12 * np.log2(frequency[i] / prev_f0))
                if semitones > 2.0:
                    onsets.append(float(times[i]))
            prev_f0 = float(frequency[i])
        else:
            prev_f0 = None

    onsets_sorted = sorted(set(round(t, 3) for t in onsets))
    logger.info(
        "CREPE detected %d note onsets in %.1fs of audio",
        len(onsets_sorted), len(audio_raw) / sr,
    )
    return onsets_sorted, times, voiced


def _extract_note_onsets_pyin(
    vocals_path: Path,
    sr_target: int = 22050,
) -> tuple[list[float], Any, Any]:
    """
    Extract note onsets using pYIN (librosa). 

    Returns:
        (onsets, times, voiced)
    """
    import librosa
    import numpy as np

    logger.info("Loading audio for pYIN pitch detection (fallback)...")
    y, sr = librosa.load(str(vocals_path), sr=sr_target, mono=True)

    hop_length = 512  # ~23ms at 22050Hz
    f0, voiced_flag, _ = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C6"),
        sr=sr,
        hop_length=hop_length,
        fill_na=None,
    )
    times = librosa.frames_to_time(range(len(voiced_flag)), sr=sr, hop_length=hop_length)

    onsets: list[float] = []

    for i in range(1, len(voiced_flag)):
        if not voiced_flag[i - 1] and voiced_flag[i]:
            onsets.append(float(times[i]))

    prev_f0 = None
    for t, v, f in zip(times, voiced_flag, f0):
        if v and f is not None and not np.isnan(f):
            if prev_f0 is not None and prev_f0 > 0:
                semitones = abs(12 * np.log2(f / prev_f0))
                if semitones > 2.0:
                    onsets.append(float(t))
            prev_f0 = f
        else:
            prev_f0 = None

    onsets_sorted = sorted(set(round(t, 3) for t in onsets))
    logger.info(
        "pYIN detected %d note onsets in %.1fs of audio",
        len(onsets_sorted), len(y) / sr,
    )
    return onsets_sorted, np.array(times), np.array(voiced_flag, dtype=bool)


def _extract_note_onsets(
    vocals_path: Path,
    sr_target: int = 16000,
    onset_window: float = 1.5,
) -> tuple[list[float], str, Any, Any]:
    """
    Extract note onset times with automatic engine selection.

    Priority chain:
        1. torchcrepe  — neural, Viterbi decoded, ~50MB model download
        2. pYIN        — DSP-based, in librosa (already installed), no download
        3. []          — empty list (pitch correction skipped gracefully)

    Returns:
        (onsets, engine_name, frames_times, voiced_frames_bool)
    """
    import numpy as np
    
    # Try torchcrepe first
    try:
        import torchcrepe  # noqa: F401
        logger.info("Pitch engine: torchcrepe (primary)")
        onsets, times, voiced = _extract_note_onsets_crepe(vocals_path, sr_target)
        return onsets, "torchcrepe", times, voiced
    except ImportError:
        logger.info(
            "torchcrepe not installed — falling back to pYIN. "
            "For better accuracy: pip install torchcrepe"
        )
    except Exception as e:
        logger.warning("torchcrepe failed (%s) — falling back to pYIN", e)

    # Fall back to pYIN
    try:
        import librosa  # noqa: F401
        logger.info("Pitch engine: pYIN/librosa (fallback)")
        onsets, times, voiced = _extract_note_onsets_pyin(vocals_path, sr_target=22050)
        return onsets, "pYIN", times, voiced
    except ImportError:
        logger.warning("librosa not installed — pitch correction disabled")
    except Exception as e:
        logger.warning("pYIN failed (%s) — pitch correction disabled", e)

    return [], "none", np.array([]), np.array([], dtype=bool)


def _snap_to_onsets(
    segments:       list[dict],
    onsets:         list[float],
    snap_window:    float = 1.5,
    min_word_dur:   float = 0.05,
) -> tuple[list[dict], int]:
    """
    Snap CTC word boundaries to the nearest pitch-detected note onset.
    Applied primarily to word STARTS. 
    """
    if not onsets:
        return segments, 0

    import bisect

    corrections = 0

    for seg in segments:
        words = seg.get("words", [])
        for w_i, word in enumerate(words):
            original_start = word["start"]
            original_end   = word["end"]
            prev_end = words[w_i - 1]["end"] if w_i > 0 else 0.0

            # Find nearest onset within window
            idx = bisect.bisect_left(onsets, original_start)
            candidates = []
            for oi in [idx - 1, idx, idx + 1]:
                if 0 <= oi < len(onsets):
                    delta = abs(onsets[oi] - original_start)
                    if delta <= snap_window:
                        candidates.append((delta, onsets[oi]))

            if not candidates:
                continue

            _, best_onset = min(candidates)

            # Safety checks before applying snap
            if best_onset >= original_end:
                continue   # would collapse or invert the word
            if best_onset < prev_end + min_word_dur:
                continue   # would overlap with previous word

            delta = best_onset - original_start
            if abs(delta) < 0.01:
                continue   # negligible correction, skip

            word["start"] = round(best_onset, 4)
            corrections += 1

            logger.debug(
                "Snap '%s': %.4f → %.4f (Δ%.3fs, onset=%.4f)",
                word["word"], original_start, best_onset, delta, best_onset,
            )

        # Update segment start/end from words after snapping
        if words:
            seg["start"] = words[0]["start"]
            seg["end"]   = words[-1]["end"]

    return segments, corrections


# ---------------------------------------------------------------------------
# Melisma / phrase-end extension
# ---------------------------------------------------------------------------

def _find_voiced_end(
    times:             Any,         # np.ndarray of frame times (seconds)
    voiced:            Any,         # np.ndarray of bool, same length as times
    search_start:      float,
    search_end:        float,
    silence_tolerance: float = 0.20,
) -> float | None:
    """
    Find the last time in [search_start, search_end] where the voice is active,
    allowing brief unvoiced gaps up to silence_tolerance seconds.
    """
    import bisect

    if len(times) == 0 or search_end <= search_start:
        return None

    i0 = bisect.bisect_left(times, search_start)
    i1 = min(bisect.bisect_right(times, search_end), len(times))

    if i0 >= i1:
        return None

    last_voiced_t: float | None = None
    gap_start: float | None = None   # when unvoiced region began

    for i in range(i0, i1):
        t = float(times[i])
        if voiced[i]:
            last_voiced_t = t
            gap_start = None   # reset gap clock
        else:
            if gap_start is None:
                gap_start = t
            elif (t - gap_start) > silence_tolerance:
                # Silence exceeded tolerance — voice is genuinely off
                break

    return last_voiced_t


def _extend_phrase_ends_voiced(
    segments:          list[dict],
    times:             Any,        # np.ndarray from pitch detection
    voiced:            Any,        # np.ndarray[bool]
    min_tail_gap:      float = 0.40,  # only extend when gap to next seg > this
    silence_tolerance: float = 0.20,  # tolerance for brief gaps inside a hold
    min_extension:     float = 0.10,  # skip if extension would be trivially small
    max_extension:     float = 8.0,   # cap — no single word hold should be >8s
    end_margin:        float = 0.05,  # stop this far before next segment start
) -> tuple[list[dict], int]:
    """
    Extend the last word of each phrase to cover melismatic holds.
    """
    if len(times) == 0:
        return segments, 0

    n = len(segments)
    extensions = 0

    for i, seg in enumerate(segments):
        words = seg.get("words", [])
        if not words:
            continue

        last_w = words[-1]
        word_end = last_w["end"]

        # Cap: don't extend past start of next segment (with margin)
        if i + 1 < n:
            cap = segments[i + 1]["start"] - end_margin
        else:
            cap = word_end + max_extension

        # Only consider extending when there's a meaningful gap
        tail_gap = cap - word_end
        if tail_gap < min_tail_gap:
            continue

        # Query voiced array for last active frame in the gap
        voiced_end = _find_voiced_end(
            times, voiced,
            search_start=word_end,
            search_end=min(cap, word_end + max_extension),
            silence_tolerance=silence_tolerance,
        )

        if voiced_end is None:
            continue

        extension_amount = voiced_end - word_end
        if extension_amount < min_extension:
            continue

        # Apply extension
        old_end = round(word_end, 4)
        new_end = round(voiced_end, 4)
        last_w["end"] = new_end
        seg["end"]    = new_end
        extensions   += 1

        logger.debug(
            "Phrase end extended: '%s' … '%s' %.4f → %.4f (+%.2fs, gap was %.2fs)",
            seg["text"][:30], last_w["word"],
            old_end, new_end, extension_amount, tail_gap,
        )

    return segments, extensions


def _vocal_gate_boundaries(
    segments:          list[dict],
    times:             Any,        # np.ndarray from pitch detection
    voiced:            Any,        # np.ndarray[bool]
    max_seek:          float = 2.0,  # how far to look for voice activity
) -> tuple[list[dict], int]:
    """
    Ensure word boundaries don't start/end in silence by snapping them 
    to the nearest voiced frame. Prevents stretching over instrumentals.
    """
    if len(times) == 0:
        return segments, 0

    import bisect
    import numpy as np
    
    corrections = 0
    
    for seg in segments:
        words = seg.get("words", [])
        for word in words:
            # ── Trim Start ──
            # If CTC says word starts in silence, look forward for voice
            idx_start = bisect.bisect_left(times, word["start"])
            if idx_start < len(voiced) and not voiced[idx_start]:
                # Search forward for first voiced frame
                search_limit = bisect.bisect_right(times, word["start"] + max_seek)
                voiced_indices = np.where(voiced[idx_start:search_limit])[0]
                if len(voiced_indices) > 0:
                    new_start = float(times[idx_start + voiced_indices[0]])
                    if new_start < word["end"]:
                        word["start"] = round(new_start, 4)
                        corrections += 1

            # ── Trim End ──
            # If word ends in silence, look backward for last voice
            idx_end = min(bisect.bisect_right(times, word["end"]), len(voiced) - 1)
            if idx_end >= 0 and not voiced[idx_end]:
                # Search backward for last voiced frame
                search_limit = max(0, bisect.bisect_left(times, word["end"] - max_seek))
                voiced_indices = np.where(voiced[search_limit:idx_end])[0]
                if len(voiced_indices) > 0:
                    new_end = float(times[search_limit + voiced_indices[-1]])
                    if new_end > word["start"]:
                        word["end"] = round(new_end, 4)
                        corrections += 1
        
        # Sync segment boundaries
        if words:
            seg["start"] = words[0]["start"]
            seg["end"]   = words[-1]["end"]

    return segments, corrections


# ---------------------------------------------------------------------------
# Status helper
# ---------------------------------------------------------------------------

def _update_status(job_dir: Path, stage: str, progress: int, error: str = "") -> None:
    status_path = job_dir / "status.json"
    existing: dict[str, Any] = {}
    if status_path.exists():
        try:
            existing = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            pass
    existing.update({
        "stage":      stage,
        "progress":   progress,
        "error":      error,
        "updated_at": time.time(),
    })
    status_path.write_text(json.dumps(existing, indent=2))


def _write_event(
    job_dir: Path,
    event: str,
    level: str = "info",
    message: str = "",
    details: dict[str, Any] | None = None,
    artifact: str | None = None,
) -> None:
    try:
        write_event(
            job_dir,
            event,
            "stage03b",
            level=level,
            message=message,
            details=details,
            artifact=artifact,
        )
    except Exception:
        logger.debug("Failed to write observability event %s", event, exc_info=True)


def _write_missing_job_event(job_dir: Path, message: str) -> None:
    parent = job_dir.parent if job_dir.parent != job_dir else Path.cwd()
    write_event(
        parent / "_stage03b",
        "stage03b.failed",
        "stage03b",
        level="error",
        message=message,
        details={"reason": "job_dir_missing", "missing_job_dir": str(job_dir)},
    )


def _fail(job_dir: Path, event: str, message: str, details: dict[str, Any] | None = None) -> int:
    _write_event(job_dir, event, level="error", message=message, details=details)
    if event != "stage03b.failed":
        _write_event(job_dir, "stage03b.failed", level="error", message=message, details=details)
    return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    hw = detect()

    parser = argparse.ArgumentParser(
        description=(
            "Stage 03b — Forced lyric alignment via CTC + MMS Wav2Vec2. "
            "Requires lyrics.txt. Bypasses Whisper transcription entirely."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--job-dir",  required=True, type=Path,
                        help="Path to the job directory.")
    parser.add_argument("--lyrics",   required=True, type=Path,
                        help="Path to lyrics.txt with [Section] markers.")
    parser.add_argument("--language", default="eng",
                        metavar="ISO639-3",
                        help=(
                            "ISO-639-3 language code for the MMS model. "
                            "eng=English, jpn=Japanese, por=Portuguese. "
                            "Auto-converts ISO-639-1 codes (en→eng, etc.)."
                        ))
    parser.add_argument("--batch-size", type=int, default=8,
                        help="Batch size for emission generation. Reduce if OOM.")
    parser.add_argument("--snap-window", type=float, default=0.75,
                        metavar="SECONDS",
                        help=(
                            "Maximum distance (seconds) to snap a CTC word boundary "
                            "to a pitch-detected note onset. Default: 1.5."
                        ))
    parser.add_argument("--no-pitch", action="store_true",
                        help="Disable pitch correction entirely (use raw CTC timestamps).")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    job_dir: Path = args.job_dir.resolve()
    lyrics_path: Path = args.lyrics.resolve()

    log_handlers: list[logging.Handler] = [logging.StreamHandler()]
    if job_dir.exists():
        log_handlers.append(logging.FileHandler(job_dir / "pipeline.log", mode="a"))
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
        handlers=log_handlers,
    )

    # Auto-convert ISO-639-1 → ISO-639-3 if needed
    language = args.language
    if len(language) == 2 and language in LANGUAGE_MAP:
        language = LANGUAGE_MAP[language]
        logger.info("Language code converted: %s → %s", args.language, language)

    if not job_dir.exists():
        logger.error("Job directory does not exist: %s", job_dir)
        _write_missing_job_event(job_dir, f"Job directory does not exist: {job_dir}")
        return 1

    logger.info(
        "Stage 03b · Forced Align  language=%s  batch=%d",
        language, args.batch_size,
    )
    _write_event(
        job_dir,
        "stage03b.started",
        message="Stage 03b forced lyric alignment started",
        details={
            "language": language,
            "batch_size": args.batch_size,
            "snap_window": args.snap_window,
            "pitch_enabled": not args.no_pitch,
        },
    )

    # ── Validate inputs ────────────────────────────────────────────────────
    vocals_path = job_dir / "vocals.wav"
    if not vocals_path.exists() or vocals_path.stat().st_size == 0:
        message = "vocals.wav missing or empty. Run Stage 02 first."
        logger.error(message)
        return _fail(
            job_dir,
            "stage03b.input_missing",
            message,
            {"artifact": "vocals.wav", "path": str(vocals_path)},
        )

    if not lyrics_path.exists():
        message = f"lyrics.txt not found at {lyrics_path}"
        logger.error(message)
        return _fail(
            job_dir,
            "stage03b.input_missing",
            message,
            {"artifact": "lyrics.txt", "path": str(lyrics_path)},
        )

    logger.info("Audio:  %s (%.1f MB)", vocals_path.name, vocals_path.stat().st_size / 1e6)
    logger.info("Lyrics: %s", lyrics_path)

    # ── Parse lyrics ───────────────────────────────────────────────────────
    lyric_lines = _parse_lyrics(lyrics_path)
    if not lyric_lines:
        message = "No singable lines found in lyrics.txt"
        logger.error(message)
        return _fail(job_dir, "stage03b.input_missing", message, {"artifact": "lyrics.txt"})

    full_text = _build_full_text(lyric_lines, expand=True)
    total_lyric_words = sum(
        len(re.findall(r"[a-zA-Z''\u00C0-\u024F]+", line["text"]))
        for line in lyric_lines
    )

    logger.info(
        "Parsed %d lyric lines, %d words across %d sections",
        len(lyric_lines),
        total_lyric_words,
        len({l["section"] for l in lyric_lines}),
    )
    lyrics_details = _lyrics_observability_details(lyrics_path, lyric_lines)
    _write_event(
        job_dir,
        "stage03b.lyrics_reference_loaded",
        message="Lyrics reference loaded",
        details={**lyrics_details, "word_count": total_lyric_words},
        artifact=lyrics_path.name,
    )
    _write_event(
        job_dir,
        "stage03b.forced_alignment_text_built",
        message="Forced alignment text built",
        details={"word_count": total_lyric_words, "character_count": len(full_text)},
    )
    _write_event(
        job_dir,
        "stage03b.alignment_path_selected",
        message="CTC forced alignment path selected",
        details={"aligner": "ctc-forced-aligner/mms-300m-1130", "language": language},
    )

    _update_status(job_dir, "aligning_lyrics", 0)

    # ── Import ctc-forced-aligner ─────────────────────────────────────────
    try:
        import torch
        from ctc_forced_aligner import (
            load_audio,
            load_alignment_model,
            generate_emissions,
            preprocess_text,
            get_alignments,
            get_spans,
            postprocess_results,
        )
    except ImportError:
        message = (
            "ctc-forced-aligner is not installed.\n"
            "Run: pip install git+https://github.com/MahmoudAshraf97/ctc-forced-aligner.git"
        )
        logger.error(message)
        return _fail(job_dir, "stage03b.failed", message)

    # ── Load model ─────────────────────────────────────────────────────────
    logger.info("Loading MMS alignment model...")
    _update_status(job_dir, "aligning_lyrics", 10)

    try:
        alignment_model, alignment_tokenizer = load_alignment_model(
            device="cpu",
            dtype=torch.float32,
        )
    except Exception as e:
        logger.error("Failed to load alignment model: %s", e)
        _update_status(job_dir, "failed", 0, str(e))
        return _fail(job_dir, "stage03b.failed", f"Failed to load alignment model: {e}")

    logger.info("Model loaded.")
    _update_status(job_dir, "aligning_lyrics", 20)

    # ── Load audio ─────────────────────────────────────────────────────────
    try:
        audio_waveform = load_audio(
            str(vocals_path),
            alignment_model.dtype,
            alignment_model.device,
        )
    except Exception as e:
        logger.error("Failed to load audio: %s", e)
        _update_status(job_dir, "failed", 0, str(e))
        return _fail(job_dir, "stage03b.failed", f"Failed to load audio: {e}")

    # ── Generate emissions ────────────────────────────────────────────────
    logger.info("Generating acoustic emissions...")
    _update_status(job_dir, "aligning_lyrics", 35)

    try:
        emissions, stride = generate_emissions(
            alignment_model,
            audio_waveform,
            batch_size=args.batch_size,
        )
    except Exception as e:
        logger.error("Emission generation failed: %s", e)
        _update_status(job_dir, "failed", 0, str(e))
        return _fail(job_dir, "stage03b.failed", f"Emission generation failed: {e}")

    # ── Preprocess text and align ─────────────────────────────────────────
    logger.info("Aligning %d words against audio...", total_lyric_words)
    _update_status(job_dir, "aligning_lyrics", 55)
    _write_event(
        job_dir,
        "stage03b.ctc_alignment_started",
        message="CTC forced alignment started",
        details={"word_count": total_lyric_words, "language": language},
    )

    try:
        tokens_starred, text_starred = preprocess_text(
            full_text,
            romanize=True,
            language=language,
        )
        segments_raw, scores, blank_token = get_alignments(
            emissions,
            tokens_starred,
            alignment_tokenizer,
        )
        spans = get_spans(tokens_starred, segments_raw, blank_token)
        word_results = postprocess_results(text_starred, spans, stride, scores)
    except Exception as e:
        logger.error("Alignment failed: %s", e)
        _update_status(job_dir, "failed", 0, str(e))
        return _fail(job_dir, "stage03b.failed", f"Alignment failed: {e}")

    logger.info("Raw alignment returned %d word entries", len(word_results))
    _write_event(
        job_dir,
        "stage03b.ctc_alignment_finished",
        message="CTC forced alignment finished",
        details={"word_count": len(word_results), "language": language},
    )
    _update_status(job_dir, "aligning_lyrics", 75)

    # ── Re-group into lyric-line segments ─────────────────────────────────
    segments = _split_words_by_lines(lyric_lines, word_results)

    if not segments:
        logger.error("No segments produced after grouping.")
        _update_status(job_dir, "failed", 0, "No segments after grouping")
        return _fail(job_dir, "stage03b.failed", "No segments after grouping")

    # ── Pitch-guided boundary correction ───────────────────────────────────
    # Step 1 — Snap CTC word STARTS to note onsets (existing).
    # Step 2 — Extend last word ENDS to voiced audio end (new: melisma fix).
    pitch_engine = "none"
    n_snapped = 0
    n_extended = 0
    if not args.no_pitch and args.snap_window > 0:
        logger.info(
            "Running pitch detection (snap_window=%.1fs)...",
            args.snap_window,
        )
        _update_status(job_dir, "aligning_lyrics", 80)

        onsets, pitch_engine, pitch_times, pitch_voiced = _extract_note_onsets(
            vocals_path, onset_window=args.snap_window,
        )

        if onsets:
            segments, n_snapped = _snap_to_onsets(
                segments,
                onsets,
                snap_window=args.snap_window,
            )
            logger.info("Step 1 — onset snap: %d word starts corrected", n_snapped)
        else:
            logger.info("No note onsets detected — onset snap skipped")

        if len(pitch_times) > 0:
            segments, n_extended = _extend_phrase_ends_voiced(
                segments,
                pitch_times,
                pitch_voiced,
            )
            logger.info("Step 2 — phrase end extension: %d phrase ends extended", n_extended)

        # Step 3 — Vocal Gating: Trim words that start/end in non-voiced regions
        if len(pitch_times) > 0:
            segments, n_gated = _vocal_gate_boundaries(
                segments,
                pitch_times,
                pitch_voiced,
            )
            logger.info("Step 3 — vocal gating: %d boundaries trimmed to voice activity", n_gated)
    else:
        logger.info("Pitch correction disabled")
    _write_event(
        job_dir,
        "stage03b.correction_path_selected",
        message="Pitch/onset correction path selected",
        details={
            "pitch_engine": pitch_engine,
            "pitch_enabled": not args.no_pitch and args.snap_window > 0,
            "snap_window": args.snap_window,
            "onset_snaps": n_snapped,
            "phrase_extensions": n_extended,
        },
    )

    # ── Validate timestamps ────────────────────────────────────────────────
    inverted = 0
    for seg in segments:
        for w in seg.get("words", []):
            if w["start"] >= w["end"]:
                inverted += 1
                logger.warning(
                    "Inverted word timestamp: '%s' start=%.4f end=%.4f",
                    w["word"], w["start"], w["end"],
                )

    if inverted:
        logger.warning(
            "%d word timestamps are inverted after alignment. "
            "HubertFA (Stage 04) will apply min/max correction.",
            inverted,
        )

    # ── Build transcript.json ──────────────────────────────────────────────
    total_words_aligned = sum(len(s["words"]) for s in segments)
    section_distribution = {}
    for seg in segments:
        sec = seg.get("section", "verse")
        section_distribution[sec] = section_distribution.get(sec, 0) + 1

    # Collect unknown section markers logged by _parse_lyrics
    all_unknown = sorted(set(
        m for line in lyric_lines
        for m in line.get("unknown_markers", [])
    ))

    transcript: dict[str, Any] = {
        "language":                "en",
        "language_probability":    1.0,
        "alignment_mode":          "forced",
        "aligner":                 "ctc-forced-aligner/mms-300m-1130",
        "forced_language":         language,
        "pitch_engine":            pitch_engine,
        "onset_snaps":             n_snapped,
        "phrase_extensions":       n_extended,
        "segment_count":           len(segments),
        "word_count":              total_words_aligned,
        "section_distribution":    section_distribution,
        "unknown_section_markers": all_unknown,
        "segments":                segments,
    }

    logger.info(
        "Alignment complete: %d/%d words in %d segments",
        total_words_aligned, total_lyric_words, len(segments),
    )

    # ── Write output ───────────────────────────────────────────────────────
    output_path = job_dir / "transcript.json"
    output_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))
    logger.info(
        "Written: %s (%.1f KB, alignment_mode=forced)",
        output_path.name, output_path.stat().st_size / 1e3,
    )
    _write_event(
        job_dir,
        "stage03b.transcript_written",
        message="Forced alignment transcript written",
        artifact=output_path.name,
        details={
            "segment_count": len(segments),
            "word_count": total_words_aligned,
            "section_count": len(section_distribution),
            "unknown_marker_count": len(all_unknown),
            "unknown_markers": all_unknown,
            "pitch_engine": pitch_engine,
            "alignment_mode": "forced",
            "size_bytes": output_path.stat().st_size,
        },
    )

    _update_status(job_dir, "aligning_lyrics", 100)
    logger.info("Stage 03b complete.")
    _write_event(
        job_dir,
        "stage03b.completed",
        message="Stage 03b forced lyric alignment completed",
        details={
            "segment_count": len(segments),
            "word_count": total_words_aligned,
            "section_count": len(section_distribution),
            "unknown_marker_count": len(all_unknown),
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
