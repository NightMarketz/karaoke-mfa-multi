"""
s02_demix.py — Source separation via Demucs htdemucs.

Runs Demucs in a subprocess using the demucs_env Python executable
(isolated conda env). Hardware config is resolved via hw_detect and
exposed as argparse defaults, so CLI args always win for manual runs.

Usage (auto hardware):
    python scripts/s02_demix.py --job-dir jobs/my-job

Usage (manual override for debug):
    python scripts/s02_demix.py --job-dir jobs/my-job --device cpu --segment 8

Outputs written to jobs/{job_id}/:
    vocals.wav          — separated vocal stem (44.1kHz WAV)
    instrumental.wav    — separated instrumental stem (44.1kHz WAV)
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

# hw_detect lives in the same scripts/ directory
sys.path.insert(0, str(Path(__file__).parent))
from hw_detect import detect, HardwareProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Demucs runs in its own conda env — this Python is NOT the current one.
DEMUCS_PYTHON_DEFAULT = (
    "C:/Users/Katz/miniforge3/envs/demucs_env/python.exe"
)
DEMUCS_TIMEOUT_S = 1800

# Accepted input extensions that Demucs can handle directly.
# Stage 01 should have already normalised video → WAV, but we handle both.
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_input(job_dir: Path) -> Path:
    """Find the input file written by Stage 01."""
    for ext in [*AUDIO_EXTENSIONS, *VIDEO_EXTENSIONS]:
        candidate = job_dir / f"input{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"No input.* file found in {job_dir}. "
        "Run Stage 01 (s01_input.py) first."
    )


def _update_status(job_dir: Path, stage: str, progress: int, error: str = "") -> None:
    status_path = job_dir / "status.json"
    existing = {}
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


def _run_demucs(
    demucs_python: str,
    model: str,
    device: str,
    segment: int,
    jobs: int,
    input_path: Path,
    output_dir: Path,
    timeout: int,
) -> None:
    """
    Invoke Demucs as a subprocess in the demucs_env.

    Demucs outputs to: {output_dir}/{model}/{track_name}/{stem}.wav
    We rename those to vocals.wav and instrumental.wav in job_dir.
    """
    cmd = [
        demucs_python, "-m", "demucs",
        "-n", model,
        "--two-stems", "vocals",
        "--device", device,
        "--segment", str(segment),
        "--jobs", str(jobs),
        str(input_path),
        "-o", str(output_dir),
    ]

    logger.info("Running Demucs: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Demucs timed out after {timeout}s") from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"Demucs exited with code {result.returncode}. "
            "Check logs above for details."
        )


def _collect_stems(model: str, input_path: Path, output_dir: Path, job_dir: Path) -> None:
    """
    Move Demucs output stems to the flat job_dir structure.

    Demucs creates: {output_dir}/{model}/{track_stem}/{vocals|no_vocals}.wav
    We want:        {job_dir}/vocals.wav  and  {job_dir}/instrumental.wav
    """
    track_name = input_path.stem
    demucs_out = output_dir / model / track_name

    vocals_src = demucs_out / "vocals.wav"
    instr_src  = demucs_out / "no_vocals.wav"

    if not vocals_src.exists():
        raise FileNotFoundError(
            f"Demucs did not produce vocals.wav at {vocals_src}. "
            "Check that --two-stems vocals was accepted."
        )
    if not instr_src.exists():
        raise FileNotFoundError(
            f"Demucs did not produce no_vocals.wav at {instr_src}."
        )

    shutil.move(str(vocals_src), str(job_dir / "vocals.wav"))
    shutil.move(str(instr_src),  str(job_dir / "instrumental.wav"))

    # Clean up the Demucs output tree
    demucs_root = output_dir / model
    if demucs_root.exists():
        shutil.rmtree(demucs_root)
        logger.debug("Cleaned up Demucs intermediate dir: %s", demucs_root)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # ── Hardware detection (sets argparse defaults) ────────────────────────
    hw: HardwareProfile = detect()

    # ── CLI ────────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Stage 02 — Source separation via Demucs htdemucs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--job-dir", required=True, type=Path,
        help="Path to the job directory (e.g. jobs/my-job).",
    )
    parser.add_argument(
        "--model", default="htdemucs",
        help="Demucs model name.",
    )
    parser.add_argument(
        "--device", default=hw.demix_device,
        help="Compute device. hw_detect default: %(default)s.",
    )
    parser.add_argument(
        "--segment", type=int, default=hw.demix_segment,
        help="Chunk size in seconds. Smaller = less VRAM. hw_detect default: %(default)s.",
    )
    parser.add_argument(
        "--jobs", type=int, default=hw.demix_jobs,
        help="Parallel Demucs workers. hw_detect default: %(default)s.",
    )
    parser.add_argument(
        "--demucs-python", default=DEMUCS_PYTHON_DEFAULT,
        help="Python executable inside demucs_env.",
    )
    parser.add_argument(
        "--demucs-timeout", type=int, default=DEMUCS_TIMEOUT_S,
        help="Maximum seconds to wait for Demucs before failing the stage.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    # ── Logging ────────────────────────────────────────────────────────────
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(args.job_dir / "pipeline.log", mode="a"),
        ],
    )

    job_dir: Path = args.job_dir.resolve()
    if not job_dir.exists():
        logger.error("Job directory does not exist: %s", job_dir)
        return 1

    logger.info(
        "Stage 02 · Demix  device=%s  segment=%ds  jobs=%d",
        args.device, args.segment, args.jobs,
    )

    # ── Validate demucs_env Python ─────────────────────────────────────────
    demucs_python = Path(args.demucs_python)
    if not demucs_python.exists():
        logger.error(
            "demucs_env Python not found at %s. "
            "Run setup_env.ps1 first.",
            demucs_python,
        )
        return 1

    # ── Find input ─────────────────────────────────────────────────────────
    try:
        input_path = _find_input(job_dir)
    except FileNotFoundError as e:
        logger.error("%s", e)
        return 1

    logger.info("Input: %s", input_path.name)
    _update_status(job_dir, "demixing", 0)

    # ── Run Demucs ─────────────────────────────────────────────────────────
    # Demucs writes its output tree inside job_dir/demucs_tmp/
    demucs_tmp = job_dir / "demucs_tmp"
    demucs_tmp.mkdir(exist_ok=True)

    try:
        _run_demucs(
            demucs_python = str(demucs_python),
            model         = args.model,
            device        = args.device,
            segment       = args.segment,
            jobs          = args.jobs,
            input_path    = input_path,
            output_dir    = demucs_tmp,
            timeout       = args.demucs_timeout,
        )
        _update_status(job_dir, "demixing", 80)

        _collect_stems(args.model, input_path, demucs_tmp, job_dir)

    except (RuntimeError, FileNotFoundError) as e:
        logger.error("Demix failed: %s", e)
        _update_status(job_dir, "failed", 0, str(e))
        return 1
    finally:
        # Always clean up temp dir
        if demucs_tmp.exists():
            shutil.rmtree(demucs_tmp, ignore_errors=True)

    # ── Validate output ────────────────────────────────────────────────────
    for stem_name in ("vocals.wav", "instrumental.wav"):
        stem_path = job_dir / stem_name
        if not stem_path.exists() or stem_path.stat().st_size == 0:
            logger.error("Output missing or empty: %s", stem_name)
            _update_status(job_dir, "failed", 0, f"Missing output: {stem_name}")
            return 1
        logger.info("Output OK: %s (%.1f MB)", stem_name, stem_path.stat().st_size / 1e6)

    _update_status(job_dir, "demixing", 100)
    logger.info("Stage 02 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
