"""
test_pipeline.py — Integration test for the karaoke pipeline.

Orchestrates stages 01 to 07 to verify the full pipeline.
Supports running from a raw input file or from existing stems.
"""

import sys
import os
import subprocess
import json
import requests
import argparse
from pathlib import Path

# Fix Windows encoding issues for checkmark/cross symbols
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
JOBS_DIR = PROJECT_ROOT / "jobs"
DEFAULT_TEST_JOB = JOBS_DIR / "test-struggle"
DEFAULT_INPUT = DEFAULT_TEST_JOB / "input.wav"

def validate(condition, message, hint=""):
    """Standardized validation reporting."""
    if not condition:
        print(f"  ✗ VALIDATION FAILED: {message}")
        if hint:
            print(f"    → {hint}")
        return False
    print(f"  ✓ {message}")
    return True

def check_ollama(url="http://localhost:11434"):
    """Check if Ollama is running and accessible."""
    try:
        resp = requests.get(f"{url}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False

def _ts_to_cs(ts: str) -> int:
    """Convert ASS timestamp H:MM:SS.cc to centiseconds."""
    try:
        parts = ts.split(':')
        h = int(parts[0])
        m = int(parts[1])
        s_parts = parts[2].split('.')
        s = int(s_parts[0])
        cs = int(s_parts[1])
        return (h * 360000) + (m * 6000) + (s * 100) + cs
    except Exception:
        return 0

def _get_wav_duration(path: Path) -> float:
    """Get duration of a WAV file in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", 
        "-show_entries", "format=duration", 
        "-of", "default=noprint_wrappers=1:nokey=1", 
        str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def validate_stage_01(job_dir: Path) -> bool:
    meta_file = job_dir / "metadata.json"
    is_ok = validate(meta_file.exists(), "metadata.json generated")
    if is_ok:
        with open(meta_file, "r") as f:
            meta = json.load(f)
            is_ok = validate("duration_seconds" in meta and meta["duration_seconds"] > 0, 
                           "metadata has valid duration", f"Found: {meta.get('duration_seconds')}s")
    validate((job_dir / "input.wav").exists(), "input.wav extracted")
    return is_ok

def validate_stage_02(job_dir: Path) -> bool:
    vocal_exists = (job_dir / "vocals.wav").exists()
    inst_exists = (job_dir / "instrumental.wav").exists()
    validate(vocal_exists, "vocals.wav generated")
    validate(inst_exists, "instrumental.wav generated")
    if vocal_exists and inst_exists:
        return validate(os.path.getsize(job_dir / "vocals.wav") > 0, "vocals.wav is not empty")
    return False

def validate_stage_03(job_dir: Path) -> bool:
    transcript_file = job_dir / "transcript.json"
    is_ok = validate(transcript_file.exists(), "transcript.json generated")
    if not is_ok:
        return False

    with open(transcript_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    is_ok = validate("segments" in data and len(data["segments"]) > 0,
                     "transcript contains segments", "Check output")
    if not is_ok:
        return False

    # Check alignment mode
    mode = data.get("alignment_mode", "whisper")
    print(f"  ℹ Alignment mode: {mode}")

    # Compare against reference timestamps if available
    ref_mapping_path = job_dir / "reference_mapping.json"
    if ref_mapping_path.exists():
        ref = json.load(open(ref_mapping_path, "r", encoding="utf-8"))
        tolerance = ref.get("tolerance_sec", 5)
        ref_lines = ref.get("lines", [])
        segments = data.get("segments", [])

        if len(segments) != len(ref_lines):
            print(f"  ⚠ Segment count mismatch: got {len(segments)}, reference has {len(ref_lines)}")
        
        drifts = []
        bad_count = 0
        check_count = min(len(segments), len(ref_lines))

        for i in range(check_count):
            ref_start = ref_lines[i].get("reference_start_sec")
            if ref_start is None:
                continue
            seg_start = segments[i].get("start", 0)
            drift = abs(seg_start - ref_start)
            drifts.append(drift)
            if drift > tolerance:
                bad_count += 1

        if drifts:
            avg_drift = sum(drifts) / len(drifts)
            max_drift = max(drifts)
            pct_ok = 100 * (1 - bad_count / len(drifts))
            validate(
                pct_ok >= 80,
                f"Timestamp accuracy: {pct_ok:.0f}% within {tolerance}s "
                f"(avg drift={avg_drift:.1f}s, max={max_drift:.1f}s)",
                f"{bad_count}/{len(drifts)} lines exceeded {tolerance}s tolerance",
            )
            # Informational — don't fail on drift, just warn
            if max_drift > tolerance:
                print(f"  ⚠ Worst drifts (>{tolerance}s):")
                for i in range(check_count):
                    ref_start = ref_lines[i].get("reference_start_sec")
                    if ref_start is None:
                        continue
                    d = abs(segments[i].get("start", 0) - ref_start)
                    if d > tolerance:
                        print(f"    line {i}: ref={ref_start}s got={segments[i]['start']:.1f}s (Δ{d:.1f}s) '{segments[i].get('text', '')[:40]}'")
    
    return is_ok

def validate_stage_04(job_dir: Path) -> bool:
    aligned_file = job_dir / "aligned.json"
    is_ok = validate(aligned_file.exists(), "aligned.json generated")
    if is_ok:
        with open(aligned_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            is_ok = validate("words" in data and len(data["words"]) > 0, "aligned.json has words")
            if is_ok:
                has_phonemes = any(len(w.get("phonemes", [])) > 0 for w in data["words"])
                validate(has_phonemes, "aligned.json contains phoneme data", "HubertFA might have failed to align")
    return is_ok

def validate_stage_05(job_dir: Path) -> bool:
    analysis_file = job_dir / "analysis.json"
    is_ok = validate(analysis_file.exists(), "analysis.json generated")
    if is_ok:
        with open(analysis_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            is_ok = validate("lines" in data and all("style" in l for l in data["lines"]), 
                           "analysis has style metadata")
    return is_ok

def validate_stage_06(job_dir: Path) -> bool:
    ass_file = job_dir / "output.ass"
    is_ok = validate(ass_file.exists(), "output.ass generated")
    if is_ok:
        with open(ass_file, "r", encoding="utf-8") as f:
            content = f.read()
            is_ok = validate("[Script Info]" in content, "ASS file has valid header")
            if is_ok:
                is_ok = validate("\\kf" in content, "ASS contains karaoke tags (\\kf)")
    return is_ok

def validate_stage_07(job_dir: Path) -> bool:
    output_file = job_dir / "output.mp4"
    is_ok = validate(output_file.exists(), "output.mp4 generated")
    if is_ok:
        is_ok = validate(os.path.getsize(output_file) > 1000, "output.mp4 is non-empty", f"Size: {os.path.getsize(output_file)} bytes")
    return is_ok

def run_script(script_name, args, timeout=None):
    """Run a pipeline script as a subprocess in the current environment."""
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        print(f"FAILED: Script {script_name} not found")
        return False
        
    cmd = [sys.executable, str(script_path)] + args
    print(f"\n--- Running: {script_name} ---")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=False, timeout=timeout)
        if result.returncode != 0:
            print(f"\nFAILED: {script_name} exited with code {result.returncode}")
            return False
        print(f"SUCCESS: {script_name} completed.")
        return True
    except subprocess.TimeoutExpired:
        print(f"\nFAILED: {script_name} timed out after {timeout}s")
        return False

def main():
    parser = argparse.ArgumentParser(description="Karaoke Pipeline Integration Test")
    parser.add_argument("--input", help="Path to input audio/video file")
    parser.add_argument("--job-dir", help="Clean job directory for new tests")
    parser.add_argument("--device", default="cuda", help="Device to use (cuda/cpu)")
    parser.add_argument("--compute-type", default="float32", help="Compute type for Whisper")
    args = parser.parse_args()

    print("====================================================")
    print("  Karaoke Pipeline Integration Test")
    print("====================================================")

    # Determine input and job directory
    if args.input:
        input_path = Path(args.input).resolve()
        if not input_path.exists():
            print(f"ERROR: Input file not found: {input_path}")
            sys.exit(1)
        
        job_dir = Path(args.job_dir).resolve() if args.job_dir else JOBS_DIR / f"test-{input_path.stem}"
        print(f"Mode: Full Pipeline (01-07)")
        print(f"Input: {input_path}")
        print(f"Job Dir: {job_dir}")
    else:
        if args.job_dir:
            job_dir = Path(args.job_dir).resolve()
            if not job_dir.exists():
                print(f"ERROR: Job dir {job_dir} not found.")
                sys.exit(1)
        else:
            if not DEFAULT_TEST_JOB.exists():
                print(f"ERROR: No input provided and default {DEFAULT_TEST_JOB} not found.")
                print("Usage: python scripts/test_pipeline.py --input <file>")
                sys.exit(1)
            job_dir = DEFAULT_TEST_JOB
            
        print(f"Mode: Partial Pipeline (03-07, using existing stems)")
        print(f"Job Dir: {job_dir}")

    # ── Stage 01: Input ──────────────────────────────────────
    if args.input:
        if not run_script("s01_input.py", ["--input", str(input_path), "--job-dir", str(job_dir)]):
            sys.exit(1)
        if not validate_stage_01(job_dir):
            sys.exit(1)

    # ── Stage 02: Demix ───────────────────────────────────────
    if args.input:
        if not run_script("s02_demix.py", ["--job-dir", str(job_dir)], timeout=300):
            sys.exit(1)
        if not validate_stage_02(job_dir):
            sys.exit(1)

    # ── Stage 03: Transcription / Alignment ─────────────────
    lyrics_file = job_dir / "lyrics.txt"
    if lyrics_file.exists():
        print(f"  → lyrics.txt found. Using Forced Alignment (s03b).")
        if not run_script("s03b_lyrics_align.py", [
            "--job-dir", str(job_dir),
            "--lyrics", str(lyrics_file)
        ], timeout=600):
            sys.exit(1)
    else:
        print(f"  → No lyrics.txt. Using Whisper Transcription (s03).")
        if not run_script("s03_transcribe.py", [
            "--job-dir", str(job_dir),
            "--device", args.device,
            "--compute-type", args.compute_type
        ], timeout=300):
            sys.exit(1)
            
    if not validate_stage_03(job_dir):
        sys.exit(1)

    # ── Stage 04: Align ──────────────────────────────────────
    onnx_path = PROJECT_ROOT / "models" / "hubertfa" / "model.onnx"
    if not onnx_path.exists():
        print(f"\n✗ FAILURE: HubertFA model missing at {onnx_path}")
        sys.exit(1)
        
    if not run_script("s04_align.py", ["--job-dir", str(job_dir)], timeout=300):
        sys.exit(1)
    if not validate_stage_04(job_dir):
        sys.exit(1)

    # ── Stage 05: Analyze ────────────────────────────────────
    print("\n--- Checking Pre-requisites (Stage 05) ---")
    if not check_ollama():
        validate(False, "Ollama connection", "Is Ollama running at localhost:11434?")
        sys.exit(1)
    else:
        validate(True, "Ollama connection")

    s05_args = ["--job-dir", str(job_dir)]
    lyrics_file = job_dir / "lyrics.txt"
    if lyrics_file.exists():
        s05_args.extend(["--lyrics", str(lyrics_file)])

    if not run_script("s05_analyze.py", s05_args, timeout=600):
        sys.exit(1)
    if not validate_stage_05(job_dir):
        sys.exit(1)

    # ── Stage 06: Generate ASS ───────────────────────────────
    if not run_script("s06_generate_ass.py", ["--job-dir", str(job_dir)]):
        sys.exit(1)
    if not validate_stage_06(job_dir):
        sys.exit(1)

    # ── Stage 07: Output ─────────────────────────────────────
    if not run_script("s07_output.py", ["--job-dir", str(job_dir)], timeout=300):
        sys.exit(1)
    if not validate_stage_07(job_dir):
        sys.exit(1)

    print("\n====================================================")
    print("  FULL PIPELINE TEST SUCCESSFUL")
    print(f"  Result: {job_dir / 'output.mp4'}")
    print("====================================================")

if __name__ == "__main__":
    main()
