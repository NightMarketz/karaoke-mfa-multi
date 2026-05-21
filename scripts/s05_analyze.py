"""
s05_analyze.py — Lyric analysis and line-level metadata.

Two modes of operation:

  1. FORCED ALIGNMENT (s03b path — alignment_mode == "forced"):
     When transcript.json comes from s03b_lyrics_align.py, every segment
     already maps 1:1 to a lyric line and carries a section label.
     Stage 05 builds analysis.json deterministically — no LLM needed.
     Style is derived from the section label, color/effect from a lookup
     table. This guarantees N segments → N display lines with zero
     hallucination risk.

  2. WHISPER PATH (alignment_mode != "forced"):
     Falls back to the LLM (Ollama) to group words into display lines,
     assign style/color/effect. Retries on malformed JSON, then falls
     back to a rule-based grouper if the LLM fails completely.

Output schema (analysis.json):
    {
        "lines": [
            {
                "text":   "never gonna give you up",
                "start":  1.24,
                "end":    4.80,
                "style":  "verse",        // verse|chorus|bridge|intro|outro|ad_lib
                "color":  "default",      // default|warm|cool|intense|soft
                "effect": "highlight",    // highlight|fade_in|bounce|none
                "words":  [
                    {"word": "never", "start": 1.24, "end": 1.58},
                    ...
                ]
            }
        ]
    }

Usage (auto):
    python scripts/s05_analyze.py --job-dir jobs/my-job

Usage (debug — print prompt and raw LLM response):
    python scripts/s05_analyze.py --job-dir jobs/my-job --log-level DEBUG

Reads:
    jobs/{job_id}/transcript.json
    jobs/{job_id}/aligned.json

Writes:
    jobs/{job_id}/analysis.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from hw_detect import detect, HardwareProfile

logger = logging.getLogger(__name__)

OLLAMA_DEFAULT_URL   = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "gemma4:27b"

# Maximum words per display line — LLM is instructed to respect this,
# but we also enforce it in post-processing as a hard cap.
MAX_WORDS_PER_LINE = 8

# If LLM returns malformed JSON after this many retries, we fall back
# to the rule-based grouper.
MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# Ollama connectivity
# ---------------------------------------------------------------------------

def _check_ollama(base_url: str, model: str, timeout: int = 10) -> str | None:
    """
    Verify Ollama is reachable and the model is available.
    Returns None if OK, or an error string if not.
    """
    try:
        req = urllib.request.Request(f"{base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        available = [m["name"] for m in data.get("models", [])]
        if not any(model in name for name in available):
            return (
                f"Model '{model}' not found in Ollama. "
                f"Available: {available}. "
                f"Run: ollama pull {model}"
            )
        return None
    except urllib.error.URLError as e:
        return f"Ollama not reachable at {base_url}: {e}"
    except Exception as e:
        return f"Ollama check failed: {e}"


# ---------------------------------------------------------------------------
# Low-confidence word correction
# ---------------------------------------------------------------------------

def _extract_lyrics_tokens(lyrics_path: Path) -> list[str]:
    """
    Extract clean word tokens from a lyrics.txt file.

    Strips section markers ([Chorus], [Verse], etc.), stage directions
    (lines entirely in brackets), punctuation, and normalises whitespace.
    Returns a flat list of lowercase word tokens in lyric order.
    """
    import re
    tokens: list[str] = []
    section_re  = re.compile(r"^\s*\[.*?\]\s*$")
    word_re     = re.compile(r"[a-zA-Z']+")

    for line in lyrics_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or section_re.match(line):
            continue
        for match in word_re.finditer(line):
            tokens.append(match.group().lower())

    return tokens


def _correct_low_confidence(
    words:       list[dict],
    transcript:  dict,
    lyrics_path: Path,
) -> list[dict]:
    """
    Replace low_confidence words with tokens from lyrics.txt.
    """
    lc_words = [w for w in words if w.get("low_confidence")]
    if not lc_words:
        return words

    lyrics_tokens = _extract_lyrics_tokens(lyrics_path)
    if not lyrics_tokens:
        logger.warning("lyrics.txt is empty or has no singable content — skipping correction")
        return words

    total_words  = len(words)
    total_tokens = len(lyrics_tokens)
    corrected    = 0

    transcript_words_flat = [
        w for seg in transcript.get("segments", [])
        for w in seg.get("words", [])
    ]
    lc_set = {
        w["word"].strip().lower()
        for w in transcript_words_flat
        if w.get("low_confidence")
    }

    result = []
    for i, word in enumerate(words):
        w_lower = word["word"].strip().lower().rstrip(".,!?;:'")
        if word.get("low_confidence") or w_lower in lc_set:
            ratio       = i / max(total_words - 1, 1)
            token_idx   = min(round(ratio * (total_tokens - 1)), total_tokens - 1)
            replacement = lyrics_tokens[token_idx]

            if replacement != w_lower:
                word = dict(word)
                word["word"]             = replacement
                word["corrected_from"]   = words[i]["word"]
                corrected += 1

        result.append(word)

    return result


# ---------------------------------------------------------------------------
# Section-to-style mapping (deterministic, for forced alignment path)
# ---------------------------------------------------------------------------

SECTION_TO_STYLE: dict[str, str] = {
    "intro":         "intro",
    "verse":         "verse",
    "pre-chorus":    "verse",
    "pre-chorus 2":  "verse",
    "chorus":        "chorus",
    "chorus 2":      "chorus",
    "interlude":     "bridge",
    "bridge":        "bridge",
    "outro chorus":  "outro",
    "outro hook":    "outro",
    "outro":         "outro",
    "guitar solo":   "bridge",
}

STYLE_DEFAULTS: dict[str, dict[str, str]] = {
    "intro":   {"color": "soft",    "effect": "fade_in"},
    "verse":   {"color": "default", "effect": "highlight"},
    "chorus":  {"color": "intense", "effect": "highlight"},
    "bridge":  {"color": "cool",    "effect": "highlight"},
    "outro":   {"color": "warm",    "effect": "fade_in"},
    "ad_lib":  {"color": "soft",    "effect": "none"},
}


# ---------------------------------------------------------------------------
# Deterministic segment-aware grouper (forced alignment path)
# ---------------------------------------------------------------------------

def _segment_aware_grouper(
    segments: list[dict],
    words:    list[dict],
) -> list[dict]:
    """
    Build analysis lines 1:1 from transcript segments (forced alignment).
    """
    lines: list[dict] = []
    word_idx = 0

    for seg in segments:
        seg_word_count = len(seg.get("words", []))
        seg_words = words[word_idx : word_idx + seg_word_count]
        word_idx += seg_word_count

        if not seg_words:
            continue

        section  = seg.get("section", "verse").lower()
        style    = SECTION_TO_STYLE.get(section, "verse")
        defaults = STYLE_DEFAULTS.get(style, STYLE_DEFAULTS["verse"])

        lines.append({
            "text":   seg.get("text", " ".join(w["word"] for w in seg_words)),
            "start":  seg_words[0]["start"],
            "end":    seg_words[-1]["end"],
            "style":  style,
            "color":  defaults["color"],
            "effect": defaults["effect"],
            "words":  [
                {"word": w["word"], "start": w["start"], "end": w["end"]}
                for w in seg_words
            ],
        })

    if word_idx < len(words):
        leftover = words[word_idx:]
        lines.append({
            "text":   " ".join(w["word"] for w in leftover),
            "start":  leftover[0]["start"],
            "end":    leftover[-1]["end"],
            "style":  "ad_lib",
            "color":  "soft",
            "effect": "none",
            "words":  [
                {"word": w["word"], "start": w["start"], "end": w["end"]}
                for w in leftover
            ],
        })

    return lines


# ---------------------------------------------------------------------------
# Prompt builder (LLM path — used only when alignment_mode != "forced")
# ---------------------------------------------------------------------------

def _build_prompt(
    words:       list[dict],
    language:    str,
    lyrics_path: "Path | None" = None,
) -> str:
    word_list = "\n".join(
        f'{i}: "{w["word"]}"'
        for i, w in enumerate(words)
    )

    structure_block = ""
    if lyrics_path and lyrics_path.exists():
        structure = lyrics_path.read_text(encoding="utf-8").strip()
        structure_block = f"""Song structure (use section labels to assign styles):
{structure}

IMPORTANT: Map section labels to styles exactly:
[Chorus] or [Chorus 2] -> "chorus"
[Verse] -> "verse"
[Bridge] -> "bridge"
[Pre-Chorus] or [Pre-Chorus 2] -> "verse"
[Intro] -> "intro"
[Outro Chorus] or [Outro Hook] -> "outro"
[Interlude] -> "bridge"

"""

    return f"""You are a karaoke subtitle designer. You will be given a numbered list of lyrics words (language: {language}).

{structure_block}Your task:
1. Group the words into display lines suitable for karaoke subtitles.
   - Each line should be 3-8 words (natural phrase breaks, not arbitrary cuts).
   - Aim for lines that feel like natural lyric lines a singer would breathe between.
2. For each line, assign:
   - "style": one of ["verse", "chorus", "bridge", "intro", "outro", "ad_lib"]
   - "color": one of ["default", "warm", "cool", "intense", "soft"]
   - "effect": one of ["highlight", "fade_in", "bounce", "none"]
3. Choruses are usually the repeated hook section. Bridges are contrasting sections.

CRITICAL RULES:
- Output ONLY valid JSON. No markdown, no explanation, no ```json fences.
- Do NOT invent or modify word order. Use words exactly as given.
- Each word index must appear exactly once across all lines.
- The "word_indices" array must be a flat list of consecutive integers from the numbered list.

Output format (JSON only):
{{
  "lines": [
    {{
      "style": "verse",
      "color": "default",
      "effect": "highlight",
      "word_indices": [0, 1, 2, 3, 4]
    }}
  ]
}}

Words:
{word_list}"""


# ---------------------------------------------------------------------------
# LLM streaming call
# ---------------------------------------------------------------------------

def _call_ollama_stream(
    base_url:    str,
    model:       str,
    prompt:      str,
    temperature: float,
    num_ctx:     int,
    timeout:     int,
) -> str:
    payload = json.dumps({
        "model":  model,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_ctx":     num_ctx,
            "num_predict": 4096,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data    = payload,
        headers = {"Content-Type": "application/json"},
        method  = "POST",
    )

    chunks: list[str] = []
    t0 = time.time()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunk = obj.get("response", "")
                if chunk:
                    chunks.append(chunk)
                if obj.get("done", False):
                    break
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama stream error: {e}") from e

    elapsed = time.time() - t0
    full_text = "".join(chunks)
    logger.info("LLM response: %.0f chars in %.1fs", len(full_text), elapsed)
    return full_text


# ---------------------------------------------------------------------------
# Response parsing and post-processing
# ---------------------------------------------------------------------------

def _parse_gemma_response(raw: str, words: list[dict]) -> list[dict] | None:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = "\n".join(
            line for line in clean.splitlines()
            if not line.strip().startswith("```")
        )

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as e:
        logger.debug("JSON parse failed: %s\nRaw (first 500): %s", e, raw[:500])
        return None

    if "lines" not in data or not isinstance(data["lines"], list):
        logger.debug("LLM response missing 'lines' key")
        return None

    lines: list[dict] = []
    seen_indices: set[int] = set()

    for line_data in data["lines"]:
        indices = line_data.get("word_indices", [])
        if not indices:
            continue

        valid_indices = [
            i for i in indices
            if isinstance(i, int) and 0 <= i < len(words) and i not in seen_indices
        ]
        if not valid_indices:
            continue
        seen_indices.update(valid_indices)

        line_words = [words[i] for i in valid_indices]
        line_text  = " ".join(w["word"] for w in line_words)

        lines.append({
            "text":   line_text,
            "start":  line_words[0]["start"],
            "end":    line_words[-1]["end"],
            "style":  line_data.get("style",  "verse"),
            "color":  line_data.get("color",  "default"),
            "effect": line_data.get("effect", "highlight"),
            "words":  [
                {"word": w["word"], "start": w["start"], "end": w["end"]}
                for w in line_words
            ],
        })

    if not lines:
        return None

    missed = [w for i, w in enumerate(words) if i not in seen_indices]
    if missed:
        if lines:
            lines[-1]["words"].extend(
                {"word": w["word"], "start": w["start"], "end": w["end"]}
                for w in missed
            )
            lines[-1]["end"]  = missed[-1]["end"]
            lines[-1]["text"] = lines[-1]["text"] + " " + " ".join(w["word"] for w in missed)

    return lines


# ---------------------------------------------------------------------------
# Rule-based fallback grouper
# ---------------------------------------------------------------------------

def _rule_based_grouper(words: list[dict]) -> list[dict]:
    logger.warning("Using rule-based fallback grouper (LLM output unusable)")
    lines = []
    for i in range(0, len(words), MAX_WORDS_PER_LINE):
        chunk = words[i : i + MAX_WORDS_PER_LINE]
        lines.append({
            "text":   " ".join(w["word"] for w in chunk),
            "start":  chunk[0]["start"],
            "end":    chunk[-1]["end"],
            "style":  "verse",
            "color":  "default",
            "effect": "highlight",
            "words":  [
                {"word": w["word"], "start": w["start"], "end": w["end"]}
                for w in chunk
            ],
        })
    return lines


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_analysis(data: dict) -> list[str]:
    errors = []
    if "lines" not in data or not data["lines"]:
        return ["'lines' is missing or empty"]

    first = data["lines"][0]
    for key in ("text", "start", "end", "style", "words"):
        if key not in first:
            errors.append(f"First line missing key: '{key}'")

    valid_styles = {"verse", "chorus", "bridge", "intro", "outro", "ad_lib"}
    bad_styles = [
        l["style"] for l in data["lines"]
        if l.get("style") not in valid_styles
    ]
    if bad_styles:
        errors.append(f"Unknown style values: {set(bad_styles)}")

    return errors


def _update_status(job_dir: Path, stage: str, progress: int, error: str = "") -> None:
    status_path = job_dir / "status.json"
    existing: dict[str, Any] = {}
    if status_path.exists():
        try:
            existing = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            pass
    existing.update({
        "stage": stage, "progress": progress,
        "error": error, "updated_at": time.time(),
    })
    status_path.write_text(json.dumps(existing, indent=2))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    hw: HardwareProfile = detect()

    parser = argparse.ArgumentParser(
        description="Stage 05 — Lyric analysis (deterministic or LLM).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--job-dir",     required=True, type=Path)
    parser.add_argument("--ollama-url",  default=OLLAMA_DEFAULT_URL)
    parser.add_argument("--model",       default=hw.ollama_model,
                        help="Ollama model. hw_detect default: %(default)s.")
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--num-ctx",     type=int, default=hw.ollama_num_ctx,
                        help="Context window. hw_detect default: %(default)s.")
    parser.add_argument("--timeout",     type=int, default=600,
                        help="Per-request timeout in seconds.")
    parser.add_argument("--language",    default="en",
                        help="Language hint passed to the LLM in the prompt.")
    parser.add_argument("--lyrics",      type=Path, default=None,
                        metavar="PATH",
                        help=(
                            "Path to lyrics.txt with [Section] markers. "
                            "If provided: (1) injected into prompt for accurate style "
                            "classification, (2) used to correct low_confidence words "
                            "from transcript.json before sending to the LLM."
                        ))
    parser.add_argument("--log-level",   default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    job_dir: Path = args.job_dir.resolve()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(job_dir / "pipeline.log", mode="a"),
        ],
    )

    if not job_dir.exists():
        logger.error("Job directory does not exist: %s", job_dir)
        return 1

    # ── Validate inputs ────────────────────────────────────────────────────
    for fname in ("transcript.json", "aligned.json"):
        p = job_dir / fname
        if not p.exists() or p.stat().st_size == 0:
            logger.error("%s missing or empty. Run earlier stages first.", fname)
            return 1

    # ── Load data ──────────────────────────────────────────────────────────
    transcript = json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
    aligned    = json.loads((job_dir / "aligned.json").read_text(encoding="utf-8"))

    words = aligned.get("words", [])
    if not words:
        logger.error("aligned.json has no words.")
        return 1

    language       = transcript.get("language", args.language)
    alignment_mode = transcript.get("alignment_mode", "whisper")
    segments       = transcript.get("segments", [])

    logger.info(
        "Stage 05 · Analyze  alignment_mode=%s  words=%d  segments=%d  language=%s",
        alignment_mode, len(words), len(segments), language,
    )

    # ── Low-confidence word correction via lyrics.txt ─────────────────────
    lyrics_path: Path | None = args.lyrics
    if lyrics_path is None:
        auto = job_dir / "lyrics.txt"
        if auto.exists():
            lyrics_path = auto
            logger.info("Auto-discovered lyrics: %s", lyrics_path)

    if lyrics_path and lyrics_path.exists():
        logger.info("Loaded reference lyrics from %s", lyrics_path)
        words = _correct_low_confidence(words, transcript, lyrics_path)
    else:
        lc = [w for w in words if w.get("low_confidence")]
        if lc:
            logger.warning(
                "%d low-confidence words in aligned output (no lyrics for correction): %s",
                len(lc), [w["word"] for w in lc],
            )

    _update_status(job_dir, "analyzing", 0)

    # ══════════════════════════════════════════════════════════════════════
    # PATH A: Forced alignment — deterministic, no LLM
    # ══════════════════════════════════════════════════════════════════════
    if alignment_mode == "forced" and segments:
        logger.info(
            "Forced alignment detected — using deterministic segment grouper "
            "(%d segments, LLM skipped)",
            len(segments),
        )
        _update_status(job_dir, "analyzing", 50)
        lines = _segment_aware_grouper(segments, words)

    # ══════════════════════════════════════════════════════════════════════
    # PATH B: Whisper — LLM-based grouping with retry + fallback
    # ══════════════════════════════════════════════════════════════════════
    else:
        logger.info("Whisper path — using LLM for line grouping (model=%s)", args.model)

        # Check Ollama connectivity (only needed for LLM path)
        logger.info("Checking Ollama at %s...", args.ollama_url)
        err = _check_ollama(args.ollama_url, args.model)
        if err:
            logger.error("Ollama check failed: %s", err)
            return 1
        logger.info("Ollama OK — model %s is available", args.model)

        prompt = _build_prompt(words, language, lyrics_path)
        logger.debug("Prompt (%d chars):\n%s", len(prompt), prompt)

        lines = None

        for attempt in range(1, MAX_RETRIES + 1):
            logger.info("LLM call attempt %d/%d...", attempt, MAX_RETRIES)
            _update_status(job_dir, "analyzing", 10 + attempt * 20)

            try:
                raw = _call_ollama_stream(
                    base_url    = args.ollama_url,
                    model       = args.model,
                    prompt      = prompt,
                    temperature = args.temperature,
                    num_ctx     = args.num_ctx,
                    timeout     = args.timeout,
                )
            except RuntimeError as e:
                logger.error("Ollama stream failed: %s", e)
                _update_status(job_dir, "failed", 0, str(e))
                return 1

            logger.debug("Raw LLM response:\n%s", raw[:1000])
            lines = _parse_gemma_response(raw, words)

            if lines is not None:
                logger.info("LLM response parsed OK on attempt %d (%d lines)", attempt, len(lines))
                break
            else:
                logger.warning("Attempt %d: LLM returned unparseable JSON — retrying", attempt)

        # Fallback if all retries failed
        if lines is None:
            lines = _rule_based_grouper(words)

    # ── Build and validate output ─────────────────────────────────────────
    analysis = {"lines": lines}
    errors   = _validate_analysis(analysis)
    if errors:
        for e in errors:
            logger.warning("Analysis validation: %s", e)

    # Log style distribution for quick verification
    style_dist: dict[str, int] = {}
    for line in lines:
        s = line.get("style", "unknown")
        style_dist[s] = style_dist.get(s, 0) + 1
    logger.info("Analysis complete: %d lines, style distribution: %s", len(lines), style_dist)

    _update_status(job_dir, "analyzing", 90)

    output_path = job_dir / "analysis.json"
    output_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
    logger.info(
        "Written: %s (%d lines, %.1f KB)",
        output_path.name, len(lines), output_path.stat().st_size / 1e3,
    )

    _update_status(job_dir, "analyzing", 100)
    logger.info("Stage 05 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

