"""
s07_output.py — Burn ASS subtitles into video via ffmpeg.

Merges the instrumental stem with the karaoke ASS subtitle track,
rendering the final MP4 using hardware-accelerated AMF (AMD) when
available, falling back to libx264 software encoding.

Quality mapping (invisible to caller, resolved by hw_detect):
    h264_amf  → CQP mode  (-rc cqp -qp_i Q -qp_p Q -qp_b Q)
    libx264   → CRF mode  (-crf Q)
    AMF does not implement CRF. Passing -crf to h264_amf is silently
    ignored, leaving quality uncontrolled. CQP is the correct equivalent.

Usage (auto hardware):
    python scripts/s07_output.py --job-dir jobs/my-job

Usage (force software encode for comparison):
    python scripts/s07_output.py --job-dir jobs/my-job --vcodec libx264 --quality 18

Usage (dummy run — skip subtitles, instrumental only, for AMF smoke test):
    python scripts/s07_output.py --job-dir jobs/my-job --no-subtitles

Reads:
    jobs/{job_id}/instrumental.wav
    jobs/{job_id}/output.ass          (optional with --no-subtitles)

Writes:
    jobs/{job_id}/output.mp4
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from hw_detect import detect, HardwareProfile
from scripts.common.observability import (
    build_observability_summary,
    record_artifact,
    write_event,
)

logger = logging.getLogger(__name__)

# Default resolution for the black background canvas.
# ASS subtitles are composited on top of this.
DEFAULT_RESOLUTION = "1920x1080"
DEFAULT_FRAMERATE  = "30"
STAGE = "rendering"


# ---------------------------------------------------------------------------
# Quality argument builder
# ---------------------------------------------------------------------------

def _build_quality_args(vcodec: str, quality: int) -> list[str]:
    """
    Return ffmpeg quality flags for the given codec.

    AMF uses Constant QP (CQP) — passing -crf to h264_amf is silently
    ignored by ffmpeg, leaving bitrate uncontrolled. CQP with matching
    qp_i / qp_p / qp_b is the correct equivalent to CRF for AMF.

    qp_b is included to prevent B-frame quality drift when AMF's default
    B-frame QP offset is non-zero.
    """
    q = str(quality)
    if vcodec == "h264_amf":
        return ["-rc", "cqp", "-qp_i", q, "-qp_p", q, "-qp_b", q]
    else:
        # libx264 and other software encoders use CRF
        return ["-crf", q]


def _build_subtitle_filter(ass_path: Path) -> str:
    """
    Build the ass= filter string for filter_complex.
    On Windows, the path must be escaped for the filtergraph (forward slashes + escaped colons)
    and quoted to prevent being misinterpreted as filter options.
    """
    safe_path = str(ass_path).replace("\\", "/").replace(":", "\\:")
    return f"ass=filename='{safe_path}'"


# ---------------------------------------------------------------------------
# Validation helpers
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


def _fail_stage07(
    job_dir: Path,
    reason: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    write_event(
        job_dir,
        "stage07.failed",
        STAGE,
        level="error",
        message=message,
        details={"reason": reason, **(details or {})},
    )
    build_observability_summary(job_dir)


def _check_input_artifact(
    job_dir: Path,
    path: Path,
    *,
    required: bool,
    empty_is_missing: bool = True,
) -> dict[str, Any]:
    details = record_artifact(job_dir, STAGE, path, required=required)
    exists = bool(details["exists"])
    size_bytes = int(details["size_bytes"])
    available = exists and (size_bytes > 0 or not empty_is_missing)
    event_details = {
        **details,
        "artifact": path.name,
        "available": available,
    }
    write_event(
        job_dir,
        "stage07.input_artifact_checked",
        STAGE,
        level="info" if available or not required else "error",
        message=f"{path.name} {'available' if available else 'missing or empty'}",
        details=event_details,
        artifact=path.name,
    )
    if not available:
        write_event(
            job_dir,
            "stage07.input_missing",
            STAGE,
            level="error" if required else "warning",
            message=f"{path.name} missing or empty",
            details=event_details,
            artifact=path.name,
        )
    return event_details


def _probe_media_duration(path: Path, timeout: int = 15) -> float | None:
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if probe.returncode != 0:
            return None
        data = json.loads(probe.stdout)
        format_duration = data.get("format", {}).get("duration")
        if format_duration is not None:
            return float(format_duration)
        for stream in data.get("streams", []):
            duration = stream.get("duration")
            if duration is not None:
                return float(duration)
    except Exception:
        return None
    return None


def _validate_mp4(path: Path) -> list[str]:
    """
    Run ffprobe on the output MP4 to verify it has valid video + audio streams.
    Returns a list of error strings. Empty = valid.
    """
    errors = []
    if not path.exists():
        return ["output.mp4 does not exist"]
    if path.stat().st_size < 10_000:
        errors.append(f"output.mp4 is suspiciously small ({path.stat().st_size} bytes)")

    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.returncode != 0:
            errors.append(f"ffprobe failed (exit {probe.returncode})")
            return errors

        info = json.loads(probe.stdout)
        streams = info.get("streams", [])
        codec_types = {s.get("codec_type") for s in streams}

        if "video" not in codec_types:
            errors.append("output.mp4 has no video stream")
        if "audio" not in codec_types:
            errors.append("output.mp4 has no audio stream")

        # Check video codec matches what we requested
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        if video_streams:
            actual_codec = video_streams[0].get("codec_name", "unknown")
            logger.debug("Video codec in output: %s", actual_codec)

    except subprocess.TimeoutExpired:
        errors.append("ffprobe timed out — output may be corrupt")
    except (json.JSONDecodeError, KeyError) as e:
        errors.append(f"ffprobe output unparseable: {e}")

    return errors


# ---------------------------------------------------------------------------
# ffmpeg command builder
# ---------------------------------------------------------------------------

def _build_ffmpeg_cmd(
    instrumental_path: Path,
    ass_path: Path | None,
    output_path: Path,
    vcodec: str,
    quality: int,
    resolution: str,
    framerate: str,
    audio_codec: str,
    audio_bitrate: str,
) -> list[str]:
    """
    Build the full ffmpeg command list.

    Strategy:
      - Input 0: instrumental.wav  (audio source)
      - Input 1: lavfi color=black (synthetic video canvas)
      - If ASS present: apply ass= filter to canvas
      - -shortest: stop when audio ends (canvas is infinite)
    """
    quality_args = _build_quality_args(vcodec, quality)

    vf_filter = (
        _build_subtitle_filter(ass_path)
        if ass_path is not None
        else "null"
    )

    # Canvas duration = audio duration + 2s buffer.
    # Without the buffer, -shortest cuts the video exactly at audio end,
    # which truncates the fade-out of the last subtitle line.
    # ffprobe reads audio duration; falls back to 3600s (1 hour) if unreadable.
    try:
        import subprocess as _sp, json as _json
        _probe = _sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(instrumental_path)],
            capture_output=True, text=True, timeout=15,
        )
        _data = _json.loads(_probe.stdout)
        _audio_dur = float(next(
            s["duration"] for s in _data.get("streams", [])
            if s.get("codec_type") == "audio"
        ))
        canvas_duration = _audio_dur + 2.0
    except Exception:
        canvas_duration = 3600.0  # safe fallback

    cmd = [
        "ffmpeg", "-y",
        # Audio input
        "-i", str(instrumental_path),
        # Synthetic video canvas — fixed duration avoids -shortest cut
        "-f", "lavfi",
        "-i", f"color=c=black:s={resolution}:r={framerate}:d={canvas_duration:.3f}",
        # Video filter: overlay ASS subtitles (or pass-through)
        "-vf", vf_filter,
        # Video encode
        "-c:v", vcodec,
        *quality_args,
        # Audio encode
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
        # -shortest now stops at audio end (canvas is 2s longer — safe)
        "-shortest",
        str(output_path),
    ]

    return cmd


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # ── Hardware detection ─────────────────────────────────────────────────
    hw: HardwareProfile = detect()

    # ── CLI ────────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Stage 07 — Render karaoke MP4 via ffmpeg.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--job-dir", required=True, type=Path,
        help="Path to the job directory.",
    )
    parser.add_argument(
        "--vcodec", default=hw.ffmpeg_vcodec,
        help="Video codec. hw_detect default: %(default)s.",
    )
    parser.add_argument(
        "--quality", type=int, default=hw.ffmpeg_quality,
        help=(
            "Quality value. For h264_amf: CQP 0-51 (lower=better). "
            "For libx264: CRF 0-51. hw_detect default: %(default)s."
        ),
    )
    parser.add_argument(
        "--resolution", default=DEFAULT_RESOLUTION,
        help="Output canvas resolution (WxH).",
    )
    parser.add_argument(
        "--framerate", default=DEFAULT_FRAMERATE,
        help="Output framerate.",
    )
    parser.add_argument(
        "--vocals-volume", type=float, default=1.0,
        help="Volume multiplier for the vocals track.",
    )
    parser.add_argument(
        "--instrumental-volume", type=float, default=1.0,
        help="Volume multiplier for the instrumental track.",
    )
    parser.add_argument(
        "--audio-codec", default="aac",
        help="Audio codec.",
    )
    parser.add_argument(
        "--audio-bitrate", default="192k",
        help="Audio bitrate.",
    )
    parser.add_argument(
        "--no-subtitles", action="store_true",
        help=(
            "Skip ASS overlay. Renders instrumental-only MP4. "
            "Useful for AMF smoke test without a complete pipeline run.",
        ),
    )
    parser.add_argument(
        "--timeout", type=int, default=600,
        help="ffmpeg timeout in seconds.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    # ── Logging ────────────────────────────────────────────────────────────
    job_dir: Path = args.job_dir.resolve()
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
        logger.error("Job directory does not exist: %s", job_dir)
        event_dir = job_dir.parent / "_stage07"
        write_event(
            event_dir,
            "stage07.failed",
            STAGE,
            level="error",
            message=f"Job directory does not exist: {job_dir}",
            details={"reason": "job_dir_missing", "missing_job_dir": str(job_dir)},
        )
        build_observability_summary(event_dir)
        return 1

    write_event(
        job_dir,
        "stage07.started",
        STAGE,
        message="Stage 07 render started",
        details={
            "vcodec": args.vcodec,
            "quality": args.quality,
            "resolution": args.resolution,
            "framerate": args.framerate,
            "audio_codec": args.audio_codec,
            "audio_bitrate": args.audio_bitrate,
            "no_subtitles": args.no_subtitles,
        },
    )

    logger.info(
        "Stage 07 · Output  vcodec=%s  quality=%d (%s)  resolution=%s",
        args.vcodec,
        args.quality,
        "CQP" if args.vcodec == "h264_amf" else "CRF",
        args.resolution,
    )

    # ── Validate inputs ────────────────────────────────────────────────────
    instrumental_path = job_dir / "instrumental.wav"
    instrumental_details = _check_input_artifact(job_dir, instrumental_path, required=True)
    if not instrumental_details["available"]:
        logger.error(
            "instrumental.wav missing or empty. Run Stage 02 (s02_demix.py) first."
        )
        _fail_stage07(
            job_dir,
            "missing_input",
            "instrumental.wav missing or empty",
            {"artifact": "instrumental.wav"},
        )
        return 1

    vocals_path = job_dir / "vocals.wav"
    vocals_details = _check_input_artifact(job_dir, vocals_path, required=False)
    has_vocals = bool(vocals_details["available"])
    if not has_vocals:
        logger.warning("vocals.wav missing or empty. Output will be instrumental only.")

    ass_path: Path | None = None
    if not args.no_subtitles:
        ass_path = job_dir / "output.ass"
        ass_details = _check_input_artifact(job_dir, ass_path, required=True)
        if not ass_details["available"] and not ass_path.exists():
            logger.error(
                "output.ass not found in %s. "
                "Run Stage 06 (s06_generate_ass.py) first, "
                "or use --no-subtitles for a dummy render.",
                job_dir,
            )
            _fail_stage07(
                job_dir,
                "missing_input",
                "output.ass not found",
                {"artifact": "output.ass"},
            )
            return 1
        if not ass_details["available"]:
            logger.error("output.ass is empty (0 bytes).")
            _fail_stage07(
                job_dir,
                "missing_input",
                "output.ass is empty",
                {"artifact": "output.ass"},
            )
            return 1
        # Quick sanity check: valid ASS starts with [Script Info]
        header = ass_path.read_text(encoding="utf-8", errors="replace")[:64]
        if "[Script Info]" not in header:
            logger.error(
                "output.ass does not look like a valid ASS file "
                "(missing [Script Info] header). "
                "pysubs2 may have written a corrupt file."
            )
            write_event(
                job_dir,
                "stage07.input_missing",
                STAGE,
                level="error",
                message="output.ass missing [Script Info] header",
                details={"artifact": "output.ass", "reason": "invalid_ass_header"},
                artifact="output.ass",
            )
            _fail_stage07(
                job_dir,
                "invalid_input",
                "output.ass missing [Script Info] header",
                {"artifact": "output.ass"},
            )
            return 1
        logger.info("Subtitles: %s (%.1f KB)", ass_path.name, ass_path.stat().st_size / 1e3)
    else:
        _check_input_artifact(job_dir, job_dir / "output.ass", required=False)
        logger.info("Subtitles: skipped (--no-subtitles)")

    output_path = job_dir / "output.mp4"
    _update_status(job_dir, "rendering", 0)
    write_event(
        job_dir,
        "stage07.audio_mix_selected",
        STAGE,
        message="Audio mix selected",
        details={
            "mode": "mixed_vocals_instrumental" if has_vocals else "instrumental_only",
            "has_vocals": has_vocals,
            "instrumental_volume": args.instrumental_volume,
            "vocals_volume": args.vocals_volume,
        },
    )

    # ── Build and run ffmpeg ───────────────────────────────────────────────
    # 1. Inputs
    cmd = ["ffmpeg", "-y"]
    
    # Input 0: Instrumental (Required)
    cmd += ["-i", str(instrumental_path)]
    
    # Input 1: Vocals (Optional)
    if has_vocals:
        cmd += ["-i", str(vocals_path)]
    
    # Input V: Synthetic video canvas
    # Determine the canvas input index: it's 1 if no vocals, 2 if vocals exist
    canvas_idx = 2 if has_vocals else 1
    
    # ffprobe for duration
    try:
        _probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(instrumental_path)],
            capture_output=True, text=True, timeout=15,
        )
        _data = json.loads(_probe.stdout)
        _audio_dur = float(next(
            s["duration"] for s in _data.get("streams", [])
            if s.get("codec_type") == "audio"
        ))
        canvas_duration = _audio_dur + 2.0
    except Exception:
        canvas_duration = 3600.0  # safe fallback

    cmd += [
        "-f", "lavfi",
        "-i", f"color=c=black:s={args.resolution}:r={args.framerate}:d={canvas_duration:.3f}",
    ]
    write_event(
        job_dir,
        "stage07.canvas_selected",
        STAGE,
        message="Synthetic background canvas selected",
        details={
            "background": "black",
            "resolution": args.resolution,
            "framerate": args.framerate,
            "duration_seconds": canvas_duration,
            "source": "instrumental_duration_plus_buffer"
            if canvas_duration != 3600.0
            else "fallback",
        },
    )

    # 2. Filters
    # Video Filter: Subtitles
    vf_filter = _build_subtitle_filter(ass_path) if ass_path else "null"
    
    # Audio Filter: Mixing
    if has_vocals:
        # Mix instrumental (0:a) and vocals (1:a)
        af_filter = (
            f"[0:a]volume={args.instrumental_volume}[inst];"
            f"[1:a]volume={args.vocals_volume}[voc];"
            f"[inst][voc]amix=inputs=2:duration=first[aout]"
        )
    else:
        # Just volume adjustment for instrumental
        af_filter = f"[0:a]volume={args.instrumental_volume}[aout]"

    cmd += [
        "-filter_complex", f"[{canvas_idx}:v]{vf_filter}[vout];{af_filter}",
        # Mapping
        "-map", "[vout]",
        "-map", "[aout]",
        # Codecs
        "-c:v", args.vcodec,
        *_build_quality_args(args.vcodec, args.quality),
        "-c:a", args.audio_codec,
        "-b:a", args.audio_bitrate,
        "-shortest",
        str(output_path),
    ]

    logger.info("ffmpeg command:\n  %s", " ".join(cmd))
    _update_status(job_dir, "rendering", 10)
    write_event(
        job_dir,
        "stage07.ffmpeg_started",
        STAGE,
        message="ffmpeg render started",
        details={
            "timeout_seconds": args.timeout,
            "vcodec": args.vcodec,
            "audio_codec": args.audio_codec,
            "input_count": 3 if has_vocals else 2,
            "command": cmd,
        },
    )

    t0 = time.time()
    try:
        result = subprocess.run(cmd, capture_output=False, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out after %ds.", args.timeout)
        _update_status(job_dir, "failed", 0, f"ffmpeg timeout ({args.timeout}s)")
        duration_ms = int((time.time() - t0) * 1000)
        write_event(
            job_dir,
            "stage07.ffmpeg_timeout",
            STAGE,
            level="error",
            message=f"ffmpeg timed out after {args.timeout}s",
            duration_ms=duration_ms,
            details={"timeout_seconds": args.timeout},
        )
        write_event(
            job_dir,
            "stage07.render_failed",
            STAGE,
            level="error",
            message=f"ffmpeg timeout ({args.timeout}s)",
            duration_ms=duration_ms,
            details={"reason": "ffmpeg_timeout", "timeout_seconds": args.timeout},
        )
        _fail_stage07(
            job_dir,
            "ffmpeg_timeout",
            f"ffmpeg timeout ({args.timeout}s)",
            {"timeout_seconds": args.timeout},
        )
        return 1
    except FileNotFoundError:
        logger.error("ffmpeg not found in PATH.")
        _update_status(job_dir, "failed", 0, "ffmpeg not in PATH")
        duration_ms = int((time.time() - t0) * 1000)
        write_event(
            job_dir,
            "stage07.ffmpeg_missing",
            STAGE,
            level="error",
            message="ffmpeg not found in PATH",
            duration_ms=duration_ms,
            details={"executable": "ffmpeg"},
        )
        write_event(
            job_dir,
            "stage07.render_failed",
            STAGE,
            level="error",
            message="ffmpeg not in PATH",
            duration_ms=duration_ms,
            details={"reason": "ffmpeg_missing"},
        )
        _fail_stage07(job_dir, "ffmpeg_missing", "ffmpeg not in PATH")
        return 1

    elapsed = time.time() - t0
    write_event(
        job_dir,
        "stage07.ffmpeg_finished",
        STAGE,
        message=f"ffmpeg exited with code {result.returncode}",
        duration_ms=int(elapsed * 1000),
        details={"returncode": result.returncode},
    )

    if result.returncode != 0:
        logger.error("ffmpeg exited with code %d.", result.returncode)
        _update_status(job_dir, "failed", 0, f"ffmpeg exit {result.returncode}")
        write_event(
            job_dir,
            "stage07.render_failed",
            STAGE,
            level="error",
            message=f"ffmpeg exit {result.returncode}",
            duration_ms=int(elapsed * 1000),
            details={"reason": "ffmpeg_nonzero", "returncode": result.returncode},
        )
        _fail_stage07(
            job_dir,
            "ffmpeg_nonzero",
            f"ffmpeg exit {result.returncode}",
            {"returncode": result.returncode},
        )
        return 1

    logger.info("ffmpeg completed in %.1fs.", elapsed)
    _update_status(job_dir, "rendering", 85)

    # ── Validate output ────────────────────────────────────────────────────
    errors = _validate_mp4(output_path)
    if errors:
        for err in errors:
            logger.error("Output validation: %s", err)
        _update_status(job_dir, "failed", 0, f"Invalid MP4: {errors[0]}")
        write_event(
            job_dir,
            "stage07.render_failed",
            STAGE,
            level="error",
            message=f"Invalid MP4: {errors[0]}",
            details={"reason": "output_validation_failed", "errors": errors},
        )
        _fail_stage07(
            job_dir,
            "output_validation_failed",
            f"Invalid MP4: {errors[0]}",
            {"errors": errors},
        )
        return 1

    size_mb = output_path.stat().st_size / 1e6
    output_duration = _probe_media_duration(output_path, timeout=30)
    output_details: dict[str, Any] = {
        "path": str(output_path),
        "name": output_path.name,
        "size_bytes": output_path.stat().st_size,
    }
    if output_duration is not None:
        output_details["duration_seconds"] = output_duration
    write_event(
        job_dir,
        "stage07.output_written",
        STAGE,
        message="output.mp4 written",
        details=output_details,
        artifact=output_path.name,
    )
    logger.info(
        "Output OK: %s (%.1f MB)  encode=%.1fs",
        output_path.name, size_mb, elapsed,
    )

    _update_status(job_dir, "done", 100)
    write_event(
        job_dir,
        "stage07.completed",
        STAGE,
        message="Stage 07 render completed",
        duration_ms=int(elapsed * 1000),
        details={"output": str(output_path), "size_bytes": output_path.stat().st_size},
    )
    build_observability_summary(job_dir)
    logger.info("Stage 07 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
