"""
s03_transcribe.py — Speech-to-text with word-level timestamps via faster-whisper.

HARDWARE NOTE (Z13 AMD iGPU):
    CTranslate2 (the backend for faster-whisper) has NO DirectML support.
    Passing device="directml" or device="cuda" on an AMD-only system raises
    a RuntimeError at model load. hw_detect always returns device="cpu" for
    this stage. This is enforced here as a hard guard regardless of CLI args.

Usage (auto hardware):
    python scripts/s03_transcribe.py --job-dir jobs/my-job

Usage (manual override — device is ignored, compute_type can be changed):
    python scripts/s03_transcribe.py --job-dir jobs/my-job --compute-type int8_float16

Reads:
    jobs/{job_id}/vocals.wav

Writes:
    jobs/{job_id}/transcript.json
    {
        "language": "en",
        "language_probability": 0.98,
        "segments": [
            {
                "text": "never gonna give you up",
                "start": 1.24,
                "end": 3.80,
                "words": [
                    {"word": "never", "start": 1.24, "end": 1.58, "probability": 0.97},
                    ...
                ]
            }
        ]
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from hw_detect import detect, HardwareProfile
from scripts.common.config import load_app_config
try:
    from scripts.common.observability import write_event
except ModuleNotFoundError:
    from common.observability import write_event

logger = logging.getLogger(__name__)

# CTranslate2 valid device values. DirectML is NOT in this list.
_VALID_CT2_DEVICES = {"cpu", "cuda", "auto"}

# Compute types valid on CPU (CTranslate2 docs).
_VALID_CPU_COMPUTE_TYPES = {"int8", "int8_float32", "int8_float16", "float32"}


# ---------------------------------------------------------------------------
# Helpers
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
        "stage": stage,
        "progress": progress,
        "error": error,
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
            "stage03",
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
        parent / "_stage03",
        "stage03.failed",
        "stage03",
        level="error",
        message=message,
        details={"reason": "job_dir_missing", "missing_job_dir": str(job_dir)},
    )


def _fail(job_dir: Path, event: str, message: str, details: dict[str, Any] | None = None) -> int:
    _write_event(job_dir, event, level="error", message=message, details=details)
    _write_event(job_dir, "stage03.failed", level="error", message=message, details=details)
    return 1


def _validate_device(requested: str) -> str:
    """
    Enforce CTranslate2 device constraints.

    If the caller passes an unsupported device (e.g. "directml"),
    log a warning and fall back to "cpu" instead of crashing at model load.
    This is a safety net — hw_detect should never return "directml" for
    the transcribe stage, but CLI overrides or config errors can slip through.
    """
    if requested not in _VALID_CT2_DEVICES:
        logger.warning(
            "Device '%s' is not supported by CTranslate2. "
            "Falling back to 'cpu'. "
            "(CTranslate2 supports: %s)",
            requested,
            ", ".join(sorted(_VALID_CT2_DEVICES)),
        )
        return "cpu"
    return requested


def _build_transcript(
    segments,
    info,
    low_confidence_threshold: float = 0.25,
) -> dict[str, Any]:
    """Convert faster-whisper segment iterator to our JSON schema.

    Words with probability below low_confidence_threshold are flagged with
    "low_confidence": true. These can be corrected downstream in s05 using
    a reference lyrics file (--lyrics). Flagging never removes words —
    the original Whisper output is always preserved for timing.
    """
    result: dict[str, Any] = {
        "language": info.language,
        "language_probability": round(info.language_probability, 4),
        "segments": [],
    }

    for seg in segments:
        words = []
        if seg.words:
            for w in seg.words:
                entry: dict[str, Any] = {
                    "word": w.word.strip(),
                    "start": round(w.start, 4),
                    "end": round(w.end, 4),
                    "probability": round(w.probability, 4),
                }
                if w.probability < low_confidence_threshold:
                    entry["low_confidence"] = True
                words.append(entry)

        result["segments"].append({
            "text": seg.text.strip(),
            "start": round(seg.start, 4),
            "end": round(seg.end, 4),
            "words": words,
        })

    return result


def _validate_transcript(data: dict[str, Any]) -> list[str]:
    """
    Validate the transcript schema. Returns a list of error strings.
    Empty list = valid.
    """
    errors = []
    if "language" not in data:
        errors.append("Missing key: 'language'")
    if "segments" not in data:
        errors.append("Missing key: 'segments'")
        return errors
    if not isinstance(data["segments"], list):
        errors.append("'segments' must be a list")
        return errors
    if len(data["segments"]) == 0:
        errors.append("'segments' is empty — no speech detected")
        return errors
    first = data["segments"][0]
    for key in ("text", "start", "end", "words"):
        if key not in first:
            errors.append(f"First segment missing key: '{key}'")
    if "words" in first and len(first["words"]) == 0:
        errors.append(
            "First segment has no word-level timestamps. "
            "Ensure word_timestamps=True was passed."
        )
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # ── Hardware detection ─────────────────────────────────────────────────
    hw: HardwareProfile = detect()
    app_config = load_app_config()

    # ── CLI ────────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Stage 03 — Speech-to-text via faster-whisper.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--job-dir", required=True, type=Path,
        help="Path to the job directory.",
    )
    parser.add_argument(
        "--model-size", default=app_config.transcribe_model_size,
        help="Whisper model variant.",
    )
    parser.add_argument(
        "--language", default=app_config.transcribe_language,
        help="Language code ('auto' for detection, 'en', 'ja', 'pt', etc.).",
    )
    # Device: hw_detect always returns "cpu" for this stage.
    # Exposed as a CLI arg so the constraint is visible and overridable
    # (override will be validated and may be silently corrected to "cpu").
    parser.add_argument(
        "--device", default=hw.transcribe_device,
        help=(
            "CTranslate2 device. NOTE: DirectML is NOT supported — any "
            "unsupported value is corrected to 'cpu'. hw_detect default: %(default)s."
        ),
    )
    parser.add_argument(
        "--compute-type", default=hw.transcribe_compute,
        choices=sorted(_VALID_CPU_COMPUTE_TYPES),
        help="CTranslate2 quantization. 'int8' is fastest on CPU. hw_detect default: %(default)s.",
    )
    parser.add_argument(
        "--beam-size", type=int, default=hw.transcribe_beam_size,
        help="Beam search width. 1 = greedy (fastest). hw_detect default: %(default)s.",
    )
    parser.add_argument(
        "--no-vad", action="store_true",
        help="Disable VAD filter. Default: %(default)s.",
    )
    parser.add_argument(
        "--vad", action="store_true", default=hw.transcribe_vad,
        help="Enable VAD filter (silence skipping). Default: %(default)s.",
    )
    parser.add_argument(
        "--low-confidence-threshold", type=float, default=app_config.transcribe_low_confidence_threshold,
        metavar="THRESHOLD",
        help=(
            "Words with probability below this value are flagged "
            "'low_confidence': true in transcript.json. "
            "These can be corrected in s05 via --lyrics. Default: %(default)s."
        ),
    )
    parser.add_argument(
        "--log-level", default=app_config.log_level,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    # ── Logging ────────────────────────────────────────────────────────────
    job_dir: Path = args.job_dir.resolve()
    log_file = job_dir / "pipeline.log"
    log_handlers: list[logging.Handler] = [logging.StreamHandler()]
    if job_dir.exists():
        log_handlers.append(logging.FileHandler(log_file, mode="a"))
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
        handlers=log_handlers,
    )

    if not job_dir.exists():
        logger.error("Job directory does not exist: %s", job_dir)
        _write_missing_job_event(job_dir, f"Job directory does not exist: {job_dir}")
        return 1

    # ── Enforce device constraint ──────────────────────────────────────────
    device = _validate_device(args.device)
    
    # VAD logic: prioritize explicit --vad, then --no-vad, then hw default
    vad_filter = args.vad
    if args.no_vad:
        vad_filter = False

    logger.info(
        "Stage 03 · Transcribe  model=%s  device=%s  compute=%s  beam=%d  vad=%s",
        args.model_size, device, args.compute_type, args.beam_size, vad_filter,
    )
    _write_event(
        job_dir,
        "stage03.started",
        message="Stage 03 transcription started",
        details={
            "model": args.model_size,
            "device": device,
            "compute_type": args.compute_type,
            "beam_size": args.beam_size,
            "vad_filter": vad_filter,
        },
    )

    # ── Validate input ─────────────────────────────────────────────────────
    vocals_path = job_dir / "vocals.wav"
    if not vocals_path.exists():
        message = f"vocals.wav not found in {job_dir}. Run Stage 02 (s02_demix.py) first."
        logger.error(message)
        return _fail(
            job_dir,
            "stage03.input_missing",
            message,
            {"artifact": "vocals.wav", "path": str(vocals_path)},
        )
    if vocals_path.stat().st_size == 0:
        message = "vocals.wav is empty (0 bytes)."
        logger.error(message)
        return _fail(
            job_dir,
            "stage03.input_missing",
            message,
            {"artifact": "vocals.wav", "path": str(vocals_path), "size_bytes": 0},
        )

    logger.info("Input: %s (%.1f MB)", vocals_path.name, vocals_path.stat().st_size / 1e6)
    _update_status(job_dir, "transcribing", 0)

    # ── Load model ─────────────────────────────────────────────────────────
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        message = (
            "faster-whisper is not installed. "
            "Run: pip install faster-whisper  (inside karaoke_env)"
        )
        logger.error(message)
        return _fail(job_dir, "stage03.whisper_import_failed", message)

    logger.info("Loading Whisper model '%s' on %s/%s...", args.model_size, device, args.compute_type)
    try:
        model = WhisperModel(
            args.model_size,
            device=device,
            compute_type=args.compute_type,
        )
    except Exception as e:
        logger.error("Failed to load Whisper model: %s", e)
        _update_status(job_dir, "failed", 0, str(e))
        return _fail(
            job_dir,
            "stage03.whisper_import_failed",
            f"Failed to load Whisper model: {e}",
            {
                "model": args.model_size,
                "device": device,
                "compute_type": args.compute_type,
            },
        )
    _write_event(
        job_dir,
        "stage03.whisper_model_loaded",
        message="Whisper model loaded",
        details={
            "model": args.model_size,
            "device": device,
            "compute_type": args.compute_type,
        },
    )

    _update_status(job_dir, "transcribing", 20)

    # ── Transcribe ─────────────────────────────────────────────────────────
    language_arg = None if args.language == "auto" else args.language

    logger.info("Transcribing%s...", f" (lang={language_arg})" if language_arg else " (auto-detect)")
    try:
        segments_iter, info = model.transcribe(
            str(vocals_path),
            language=language_arg,
            word_timestamps=True,
            beam_size=args.beam_size,
            vad_filter=vad_filter,
        )
        # Materialise the lazy iterator before closing the model
        transcript = _build_transcript(
            segments_iter, info,
            low_confidence_threshold=args.low_confidence_threshold,
        )
    except Exception as e:
        logger.error("Transcription failed: %s", e)
        _update_status(job_dir, "failed", 0, str(e))
        return _fail(
            job_dir,
            "stage03.transcribe_failed",
            f"Transcription failed: {e}",
            {
                "model": args.model_size,
                "device": device,
                "compute_type": args.compute_type,
            },
        )

    _update_status(job_dir, "transcribing", 85)
    logger.info(
        "Detected language: %s (%.1f%% confidence)",
        transcript["language"],
        transcript["language_probability"] * 100,
    )
    logger.info("Segments: %d", len(transcript["segments"]))

    # ── Validate output schema ─────────────────────────────────────────────
    errors = _validate_transcript(transcript)
    if errors:
        for err in errors:
            logger.error("Transcript validation: %s", err)
        _update_status(job_dir, "failed", 0, f"Invalid transcript: {errors[0]}")
        return _fail(
            job_dir,
            "stage03.transcribe_failed",
            f"Invalid transcript: {errors[0]}",
            {"errors": errors},
        )

    total_words = sum(len(s["words"]) for s in transcript["segments"])
    logger.info("Total words with timestamps: %d", total_words)

    # ── Low-confidence report ──────────────────────────────────────────────
    all_words = [w for s in transcript["segments"] for w in s["words"]]
    lc_words  = [w for w in all_words if w.get("low_confidence")]
    if lc_words:
        lc_pct = 100 * len(lc_words) / len(all_words) if all_words else 0
        logger.warning(
            "Low-confidence words: %d/%d (%.0f%%) — threshold=%.2f",
            len(lc_words), len(all_words), lc_pct,
            args.low_confidence_threshold,
        )
        for w in lc_words:
            logger.warning(
                "  low_conf: '%s' (prob=%.4f) at %.2fs–%.2fs",
                w["word"], w["probability"], w["start"], w["end"],
            )
        if lc_pct > app_config.transcribe_lc_warning_pct:
            logger.warning(
                "%.0f%% of words are low-confidence. "
                "Consider using --lyrics to correct via s05.",
                lc_pct,
            )
    else:
        logger.info("Low-confidence words: none (all >= %.2f)", args.low_confidence_threshold)

    # ── Write output ───────────────────────────────────────────────────────
    output_path = job_dir / "transcript.json"
    output_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False))
    logger.info("Written: %s (%.1f KB)", output_path.name, output_path.stat().st_size / 1e3)
    _write_event(
        job_dir,
        "stage03.transcript_written",
        message="Transcript written",
        artifact=output_path.name,
        details={
            "segment_count": len(transcript["segments"]),
            "word_count": total_words,
            "language": transcript.get("language"),
            "language_probability": transcript.get("language_probability"),
            "alignment_mode": transcript.get("alignment_mode", "whisper"),
            "size_bytes": output_path.stat().st_size,
        },
    )

    _update_status(job_dir, "transcribing", 100)
    logger.info("Stage 03 complete.")
    _write_event(
        job_dir,
        "stage03.completed",
        message="Stage 03 transcription completed",
        details={
            "segment_count": len(transcript["segments"]),
            "word_count": total_words,
            "language": transcript.get("language"),
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
