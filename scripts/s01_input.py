"""
01_input.py — Validate and normalize input file.

Accepts audio (MP3, WAV, FLAC, OGG) or video (MP4, MKV, WEBM).
Extracts audio to WAV if needed. Writes metadata.json.
"""

import argparse
import json
import os
import subprocess
import shutil
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

FFPROBE_TIMEOUT_S = 30
FFMPEG_TIMEOUT_S = 300


SUPPORTED_AUDIO = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".wma"}
SUPPORTED_VIDEO = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
SUPPORTED = SUPPORTED_AUDIO | SUPPORTED_VIDEO


def probe_media(filepath: str) -> dict:
    """Use ffprobe to get media info."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        filepath
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=FFPROBE_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return json.loads(result.stdout)


def extract_audio(input_path: str, output_path: str) -> None:
    """Extract audio track to WAV using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vn",                    # no video
        "-acodec", "pcm_s16le",   # 16-bit PCM
        "-ar", "44100",           # 44.1kHz
        "-ac", "2",               # stereo
        output_path
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg extraction failed: {result.stderr}")


def run(input_file: str, job_dir: str) -> dict:
    """Main entry point."""
    input_path = Path(input_file)
    job_path = Path(job_dir)
    job_path.mkdir(parents=True, exist_ok=True)

    # Validate extension
    ext = input_path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(
            f"Unsupported format '{ext}'. Supported: {sorted(SUPPORTED)}"
        )

    # Probe media info
    probe = probe_media(str(input_path))
    duration = float(probe["format"].get("duration", 0))
    
    # Find audio stream info
    audio_stream = None
    has_video = False
    for stream in probe.get("streams", []):
        if stream["codec_type"] == "audio" and audio_stream is None:
            audio_stream = stream
        if stream["codec_type"] == "video":
            has_video = True

    if audio_stream is None:
        raise ValueError("No audio stream found in input file.")

    sample_rate = int(audio_stream.get("sample_rate", 44100))
    channels = int(audio_stream.get("channels", 2))

    # Copy original to job dir
    original_dest = job_path / f"original{ext}"
    shutil.copy2(str(input_path), str(original_dest))

    # Extract/convert to WAV
    wav_path = job_path / "input.wav"
    if ext == ".wav":
        # Even for WAV, normalize to 44.1kHz 16-bit stereo
        extract_audio(str(input_path), str(wav_path))
    else:
        extract_audio(str(input_path), str(wav_path))

    # Write metadata
    metadata = {
        "original_filename": input_path.name,
        "original_format": ext,
        "duration_seconds": duration,
        "sample_rate": sample_rate,
        "channels": channels,
        "has_video": has_video,
    }
    meta_path = job_path / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return metadata


def main():
    parser = argparse.ArgumentParser(description="Stage 01: Input validation")
    parser.add_argument("--input", required=True, help="Path to input audio/video file")
    parser.add_argument("--job-dir", required=True, help="Path to job directory")
    args = parser.parse_args()

    job_dir = Path(args.job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(job_dir / "pipeline.log", mode="a"),
        ],
    )
    
    logger.info("Stage 01 · Input")

    try:
        meta = run(args.input, args.job_dir)
        logger.info("Input OK — %s (%.1fs, %s)", 
                    meta['original_filename'], 
                    meta['duration_seconds'], 
                    meta['original_format'])
        logger.info("Stage 01 complete.")
    except Exception as e:
        logger.error("Input FAILED — %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
