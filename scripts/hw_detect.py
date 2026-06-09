"""
hw_detect.py — ROG Flow Z13 hardware profile detector.

Runs once at pipeline startup. Detects DirectML and AMF availability,
then returns a HardwareProfile with per-stage device configs.

Usage (standalone smoke test):
    python scripts/hw_detect.py

Usage (imported):
    from hw_detect import detect
    hw = detect()
    print(hw.transcribe_device)  # always "cpu" on AMD iGPU
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Ensure project root is in sys.path so 'scripts.common' resolves whether
# this module is imported directly (server) or via a subprocess that added
# only the scripts/ directory to sys.path.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.common.config import load_hardware_config


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class HardwareProfile:
    """Per-stage hardware config resolved at runtime."""

    # ── Stage 02 · Demucs (PyTorch — DirectML supported) ──────────────────
    demix_device: str          # "directml" | "cpu"
    demix_compute: str         # "float16"  | "float32"
    demix_segment: int         # chunk size in seconds (smaller = less VRAM)
    demix_jobs: int            # parallel workers (1 avoids shared-mem thrash)

    # ── Stage 03 · faster-whisper (CTranslate2 — NO DirectML) ─────────────
    # CTranslate2 only supports CUDA + CPU. DirectML crashes at model load.
    transcribe_device: str     # always "cpu" on AMD iGPU
    transcribe_compute: str    # "int8" (~4x faster than float32 on CPU)
    transcribe_beam_size: int  # 1 = fastest, 5 = most accurate
    transcribe_vad: bool       # skip silence segments (~20% runtime savings)

    # ── Stage 04 · HubertFA (PyTorch — DirectML supported) ────────────────
    align_device: str          # "directml" | "cpu"
    align_batch_size: int      # reduce if OOM on shared memory

    # ── Stage 05 · Ollama (self-managed, do not override) ─────────────────
    ollama_model: str
    ollama_num_ctx: int        # prompt context window
    ollama_num_thread: int     # CPU threads; leave cores for Ollama GPU path

    # ── Stage 07 · ffmpeg (AMF = AMD hardware encoder) ───────────────────
    ffmpeg_vcodec: str         # "h264_amf" | "libx264"
    ffmpeg_quality: int        # AMF quality scale 0-51 (lower = better)

    # ── Resolved capabilities (read-only diagnostic) ──────────────────────
    directml_available: bool = field(default=False, repr=True)
    amf_available: bool = field(default=False, repr=True)

    def summary(self) -> str:
        lines = [
            "── Z13 Hardware Profile ──────────────────────",
            f"  DirectML      : {'yes' if self.directml_available else 'NO — CPU fallback'}",
            f"  AMF encoder   : {'yes' if self.amf_available else 'NO — libx264 fallback'}",
            "",
            f"  02 Demix      : device={self.demix_device}  compute={self.demix_compute}  segment={self.demix_segment}s  jobs={self.demix_jobs}",
            f"  03 Transcribe : device={self.transcribe_device}  compute={self.transcribe_compute}  beam={self.transcribe_beam_size}  vad={self.transcribe_vad}",
            f"  04 Align      : device={self.align_device}  batch={self.align_batch_size}",
            f"  05 Analyze    : model={self.ollama_model}  ctx={self.ollama_num_ctx}  threads={self.ollama_num_thread}",
            f"  07 Output     : vcodec={self.ffmpeg_vcodec}  quality={self.ffmpeg_quality}",
            "──────────────────────────────────────────────",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _check_directml() -> bool:
    """
    Verify torch-directml is installed AND a device is accessible.
    Does a minimal tensor op to confirm the driver is functional.
    """
    try:
        import torch_directml  # type: ignore
        import torch

        device = torch_directml.device()
        # Minimal smoke test — allocate and immediately free
        t = torch.zeros(4, device=device)
        del t
        return True
    except ImportError:
        # torch-directml not installed
        return False
    except Exception:
        # Driver present but device init failed (e.g., no compatible GPU)
        return False


def _check_amf() -> bool:
    """
    Check if the ffmpeg binary in PATH was built with h264_amf support.
    AMF is AMD's hardware H.264 encoder — much faster than libx264 on Z13.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "h264_amf" in result.stdout
    except FileNotFoundError:
        # ffmpeg not in PATH — will be caught by Stage 07 validation anyway
        return False
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect(verbose: bool = False, config_path: Path | str = "pipeline.toml") -> HardwareProfile:
    """
    Detect hardware capabilities and return an optimised HardwareProfile.

    Call once at server startup or at the top of each script.
    Detection is fast (<500ms) because DirectML smoke-test uses a tiny tensor.

    Args:
        verbose: Print detection results to stdout.

    Returns:
        HardwareProfile with per-stage device assignments.
    """
    if verbose:
        if sys.platform == "win32":
            sys.stdout.reconfigure(encoding="utf-8")
        print("hw_detect: probing hardware...", flush=True)

    dml = _check_directml()
    amf = _check_amf()
    hardware_config = load_hardware_config(config_path)
    forced_cpu = hardware_config.profile == "cpu_only"
    forced_z13 = hardware_config.profile == "z13"
    gpu_defaults = hardware_config.z13
    cpu_defaults = hardware_config.cpu_only
    base_defaults = cpu_defaults if forced_cpu else gpu_defaults
    dml_enabled = False if forced_cpu else (True if forced_z13 else dml)
    amf_enabled = False if forced_cpu else (True if forced_z13 else amf)

    if verbose:
        print(f"  DirectML : {'OK' if dml else 'not available'}")
        print(f"  AMF      : {'OK' if amf else 'not available'}")

    profile = HardwareProfile(
        # ── Stage 02 · Demix ──────────────────────────────────────────────
        demix_device   = gpu_defaults.demix_device if dml_enabled else cpu_defaults.demix_device,
        demix_compute  = gpu_defaults.demix_compute if dml_enabled else cpu_defaults.demix_compute,
        # 4s segments keep peak VRAM at ~1.2GB on shared-memory Z13 iGPU.
        # Default htdemucs segment (7.8s) peaks at ~2.4GB and competes with
        # Ollama's allocation during Stage 05.
        demix_segment  = gpu_defaults.demix_segment if dml_enabled else cpu_defaults.demix_segment,
        # Single worker avoids shared-memory contention between Demucs and OS.
        demix_jobs     = gpu_defaults.demix_jobs if dml_enabled else cpu_defaults.demix_jobs,

        # ── Stage 03 · Transcribe ─────────────────────────────────────────
        # CRITICAL: CTranslate2 has no DirectML backend. Setting device to
        # anything other than "cpu" or "cuda" raises a RuntimeError on load.
        # int8 quantization gives ~4x speedup over float32 on CPU with
        # negligible accuracy loss for speech recognition.
        transcribe_device    = base_defaults.transcribe_device,
        transcribe_compute   = base_defaults.transcribe_compute,
        # beam_size=1 (greedy) is fastest. For karaoke word-timing accuracy,
        # greedy is sufficient — we're not optimising for WER on noisy speech.
        transcribe_beam_size = base_defaults.transcribe_beam_size,
        # VAD filter disabled to prevent syllable loss in singing voice.
        transcribe_vad = base_defaults.transcribe_vad,

        # ── Stage 04 · Align ──────────────────────────────────────────────
        align_device     = gpu_defaults.align_device if dml_enabled else cpu_defaults.align_device,
        # batch_size=16 on DirectML; halve it on CPU to avoid RAM pressure
        # when vocals.wav is long (>5 min).
        align_batch_size = gpu_defaults.align_batch_size if dml_enabled else cpu_defaults.align_batch_size,

        # ── Stage 05 · Ollama ─────────────────────────────────────────────
        ollama_model      = base_defaults.ollama_model,
        ollama_num_ctx    = base_defaults.ollama_num_ctx,
        # Leave cores for OS + Ollama's internal GPU offload scheduler.
        ollama_num_thread = base_defaults.ollama_num_thread,

        # ── Stage 07 · Output ─────────────────────────────────────────────
        ffmpeg_vcodec  = gpu_defaults.ffmpeg_vcodec if amf_enabled else cpu_defaults.ffmpeg_vcodec,
        # AMF quality=23 ≈ libx264 crf=23: visually transparent, ~3x faster.
        ffmpeg_quality = gpu_defaults.ffmpeg_quality if amf_enabled else cpu_defaults.ffmpeg_quality,

        # Diagnostic flags
        directml_available = dml_enabled,
        amf_available      = amf_enabled,
    )

    if verbose:
        print(profile.summary())

    return profile


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    profile = detect(verbose=True)
    # Exit 1 if no hardware acceleration at all (useful in CI)
    if not profile.directml_available and not profile.amf_available:
        print("\nWARNING: no GPU acceleration detected — pipeline will run on CPU only.")
        sys.exit(0)  # not a hard failure, just advisory
    sys.exit(0)
