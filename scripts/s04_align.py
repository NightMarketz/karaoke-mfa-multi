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
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from hw_detect import detect, HardwareProfile

# Fix Windows encoding issues for checkmark/cross symbols
if sys.platform == "win32":
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except (AttributeError, io.UnsupportedOperation):
        pass

logger = logging.getLogger(__name__)

# Silence phoneme labels emitted by HubertFA
_SILENCE_LABELS = {"SIL", "SP", "AP", "sil", "sp", "ap", "<SIL>", "<SP>"}
_STRESS_RE = re.compile(r"\d+$")


def _parse_textgrid(path: Path) -> list[dict[str, Any]]:
    """Parse a Praat TextGrid file (inline). Handles long/short formats."""
    text = path.read_text(encoding="utf-8", errors="replace")
    intervals: list[dict[str, Any]] = []
    current_tier: str = "phones"
    tier_name_re = re.compile(r'name\s*=\s*"([^"]+)"')
    interval_re  = re.compile(
        r'xmin\s*=\s*([\d.]+)\s*\n\s*xmax\s*=\s*([\d.]+)\s*\n\s*text\s*=\s*"([^"]*)"',
        re.MULTILINE,
    )
    tier_match = tier_name_re.search(text)
    if tier_match:
        current_tier = tier_match.group(1)

    for m in interval_re.finditer(text):
        intervals.append({
            "tier": current_tier,
            "xmin": float(m.group(1)),
            "xmax": float(m.group(2)),
            "text": m.group(3).strip(),
        })
    if not intervals:
        raise ValueError(f"No intervals parsed from TextGrid at {path}")
    return intervals


def _phonemise_text(text: str, g2p) -> list[str]:
    """Convert text to ARPAbet (stress stripped)."""
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
    """Preserve CTC word timestamps without phoneme data (forced mode fallback)."""
    result = []
    for w in words:
        entry = dict(w)
        entry.update({"source": "ctc_forced", "phonemes": []})
        result.append(entry)
    return result


def _ctc_forced_with_phonemes(
    words: list[dict], ph_ivs: list[dict], offset: float
) -> list[dict]:
    """
    Keep CTC word timestamps, attach HubertFA phonemes as metadata only.

    For forced alignment mode: word start/end come from the CTC aligner
    (s03b) and are NOT overwritten unless they are invalid (zero duration).
    Phonemes from HubertFA are distributed by count ratio and attached as 
    enrichment data.
    """
    result, ph_idx, total_ph = [], 0, len(ph_ivs)
    min_dur = 0.050  # 50ms

    for w_i, word in enumerate(words):
        rem_w = len(words) - w_i
        rem_ph = total_ph - ph_idx
        n_ph = max(1, round(rem_ph / rem_w)) if w_i < len(words) - 1 else rem_ph
        ivs = ph_ivs[ph_idx : ph_idx + n_ph]
        ph_idx += n_ph

        w_start = word["start"]
        w_end   = word["end"]

        # Enforce minimum duration for words that arrived broken from s03b
        if w_end <= w_start:
            w_end = w_start + min_dur
            logger.info("Fixed zero-duration word '%s' in forced mode: %.4f -> %.4f", 
                        word["word"], w_start, w_end)

        # Prevent overlap with PREVIOUS word in result list
        if result:
            prev_end = result[-1]["end"]
            if w_start < prev_end:
                # If they overlap, push start forward but maintain min duration
                w_start = prev_end
                if w_end < w_start + min_dur:
                    w_end = w_start + min_dur

        entry = {
            "word":     word["word"],
            "start":    round(w_start, 4),
            "end":      round(w_end, 4),
            "source":   "ctc_forced" if not ivs else "ctc_forced+hubertfa",
            "phonemes": [
                {"ph": v["text"], "start": round(v["xmin"] + offset, 4),
                 "end": round(v["xmax"] + offset, 4)}
                for v in ivs
            ],
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




def _map_phonemes_to_words(words: list[dict], ph_ivs: list[dict], offset: float) -> list[dict]:
    """Distribute phonemes across words by count ratio."""
    result, ph_idx, total_ph = [], 0, len(ph_ivs)
    for w_i, word in enumerate(words):
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
    status_path.write_text(json.dumps(data, indent=2))


def main() -> int:
    hw = detect()
    parser = argparse.ArgumentParser(description="Stage 04 — Phoneme Alignment (Batch ONNX)")
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--hubertfa-dir", default="vendor/HubertFA", type=Path)
    parser.add_argument("--checkpoint", default="models/hubertfa/model.onnx", type=Path)
    parser.add_argument("--language", default="en")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    args = parser.parse_args()

    job_dir = args.job_dir.resolve()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(job_dir / "pipeline.log", mode="a"),
        ],
    )
    
    vocals_path, transcript_path = job_dir / "vocals.wav", job_dir / "transcript.json"
    if not vocals_path.exists() or not transcript_path.exists():
        logger.error("Inputs missing in %s", job_dir); return 1

    model_dir = args.checkpoint.parent
    for sidecar in ("config.json", "vocab.json", "VERSION"):
        if not (model_dir / sidecar).exists():
            logger.error("Missing HubertFA sidecar file: %s", sidecar); return 1

    try:
        from g2p_en import G2p
        g2p = G2p()
    except ImportError:
        logger.error("pip install g2p_en required"); return 1

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    segments = transcript.get("segments", [])
    if not segments: logger.error("No segments found"); return 1

    alignment_mode = transcript.get("alignment_mode", "whisper")
    is_forced = alignment_mode == "forced"

    logger.info(
        "Stage 04 · Align  alignment_mode=%s  segments=%d",
        alignment_mode, len(segments),
    )
    if is_forced:
        logger.info(
            "Forced alignment detected — CTC timestamps will be preserved. "
            "HubertFA phonemes attached as metadata only."
        )

    _update_status(job_dir, "aligning", 0)
    all_aligned_words = []

    # Determine the correct fallback function based on alignment mode
    _fallback = _ctc_forced_fallback if is_forced else _whisper_fallback

    with tempfile.TemporaryDirectory(prefix="hfa_batch_") as tmp_str:
        tmp_dir = Path(tmp_str)
        logger.info("Batch Prep: Slicing %d segments into %s", len(segments), tmp_dir)
        
        for i, seg in enumerate(segments):
            stem = f"seg_{i:04d}"
            try:
                _slice_wav(vocals_path, tmp_dir / f"{stem}.wav", seg["start"], seg["end"])
                phs = [p.lower() for p in _phonemise_text(seg["text"], g2p)]
                (tmp_dir / f"{stem}.lab").write_text(" ".join(phs), encoding="utf-8")
            except Exception as e:
                logger.warning("Prep failed for segment %d: %s", i, e)

        # ── Run HubertFA ONCE for all segments ──
        logger.info("Batch Inference: Running HubertFA onnx_infer.py (Model: %s)", args.checkpoint.name)
        cmd = [
            sys.executable, str(args.hubertfa_dir / "onnx_infer.py"),
            "--onnx_path", str(args.checkpoint),
            "--wav_folder", str(tmp_dir),
            "--out_path", str(tmp_dir),
            "--g2p", "phoneme",
            "--language", args.language
        ]
        
        start_time = time.time()
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error("HubertFA Batch failed:\n%s", res.stderr)
            # Global fallback if batch inference crashes
            for seg in segments:
                all_aligned_words.extend(_fallback(seg.get("words", [])))
        else:
            elapsed = time.time() - start_time
            logger.info("Batch Inference OK (%.2fs for %d segments)", elapsed, len(segments))

            # ── Parse and map results ──
            tg_dir = tmp_dir / "TextGrid"
            for i, seg in enumerate(segments):
                stem = f"seg_{i:04d}"
                tg_path = tg_dir / f"{stem}.TextGrid"
                
                if tg_path.exists():
                    try:
                        ivs = [v for v in _parse_textgrid(tg_path) if v["text"] not in _SILENCE_LABELS and v["text"]]
                        if is_forced:
                            # Forced mode: keep CTC timestamps, attach phonemes as metadata
                            words = _ctc_forced_with_phonemes(seg.get("words", []), ivs, seg["start"])
                        else:
                            # Whisper mode: derive timestamps from HubertFA phonemes
                            words = _map_phonemes_to_words(seg.get("words", []), ivs, seg["start"])
                        
                        # Apply linear interpolation for missing/inverted words
                        words = _linear_interpolate_words(words, seg["start"], seg["end"])
                        
                        all_aligned_words.extend(words)
                        continue
                    except Exception as e:
                        logger.warning("Parse failed for %s: %s", stem, e)
                
                # Fallback for individual missing/failed segments
                all_aligned_words.extend(_fallback(seg.get("words", [])))

    # Save output
    aligned = {"words": all_aligned_words}
    output_path = job_dir / "aligned.json"
    output_path.write_text(json.dumps(aligned, indent=2, ensure_ascii=False))
    
    # Count sources for logging
    source_counts: dict[str, int] = {}
    for w in all_aligned_words:
        s = w.get("source", "unknown")
        source_counts[s] = source_counts.get(s, 0) + 1
    logger.info("Stage 04 OK: %d words, sources: %s", len(all_aligned_words), source_counts)
    _update_status(job_dir, "aligning", 100)
    return 0

if __name__ == "__main__":
    sys.exit(main())
