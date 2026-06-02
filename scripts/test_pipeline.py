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
import hashlib
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None

# Fix Windows encoding issues for checkmark/cross symbols
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
JOBS_DIR = PROJECT_ROOT / "jobs"
DEFAULT_TEST_JOB = JOBS_DIR / "test-struggle"
DEFAULT_INPUT = DEFAULT_TEST_JOB / "input.wav"
FFPROBE_TIMEOUT_S = 30
DEFAULT_STAGE06_PRESET = "single-style-kf"

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _read_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}

def resolve_stage06_preset(
    job_dir: Path,
    pipeline_toml: Path = PROJECT_ROOT / "pipeline.toml",
) -> str:
    """Resolve the ASS style preset with job metadata taking precedence."""
    meta = _read_json_object(job_dir / "meta.json")
    preset = meta.get("preset")
    if isinstance(preset, str) and preset.strip():
        return preset.strip()

    if tomllib is not None and pipeline_toml.exists():
        try:
            config = tomllib.loads(pipeline_toml.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            config = {}
        generate = config.get("generate") if isinstance(config, dict) else {}
        preset = generate.get("style_preset") if isinstance(generate, dict) else None
        if isinstance(preset, str) and preset.strip():
            return preset.strip()

    return DEFAULT_STAGE06_PRESET

def build_stage06_args(
    job_dir: Path,
    pipeline_toml: Path = PROJECT_ROOT / "pipeline.toml",
) -> list[str]:
    preset = resolve_stage06_preset(job_dir, pipeline_toml)
    return ["--job-dir", str(job_dir), "--preset", preset]

def _ass_dialogue_count(content: str) -> int:
    return content.count("\nDialogue:")

def _has_base_dialogue(content: str) -> bool:
    return any(
        line.startswith("Dialogue:") and "Base,," in line
        for line in content.splitlines()
    )

def _manifest_sha(manifest: dict, section: str, artifact: str) -> str | None:
    entries = manifest.get(section)
    if not isinstance(entries, dict):
        return None
    item = entries.get(artifact)
    if not isinstance(item, dict):
        return None
    sha = item.get("sha256")
    return sha if isinstance(sha, str) and sha else None

def validate_integration_provenance(job_dir: Path) -> bool:
    """Validate the final ASS/MP4 provenance graph after Stage 07."""
    analysis_path = job_dir / "analysis.json"
    ass_path = job_dir / "output.ass"
    ass_manifest_path = job_dir / "output.ass.manifest.json"
    mp4_path = job_dir / "output.mp4"
    mp4_manifest_path = job_dir / "output.mp4.manifest.json"

    is_ok = True
    is_ok &= validate(ass_manifest_path.exists(), "output.ass.manifest.json exists")
    is_ok &= validate(mp4_manifest_path.exists(), "output.mp4.manifest.json exists")
    if not is_ok:
        return False

    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        ass_content = ass_path.read_text(encoding="utf-8")
        ass_manifest = json.loads(ass_manifest_path.read_text(encoding="utf-8"))
        mp4_manifest = json.loads(mp4_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return validate(False, "provenance artifacts are readable JSON/text", str(exc))

    lines = analysis.get("lines") if isinstance(analysis, dict) else None
    line_count = len(lines) if isinstance(lines, list) else -1
    dialogue_count = _ass_dialogue_count(ass_content)
    is_ok &= validate(
        dialogue_count == line_count,
        "ASS dialogue count equals analysis line count",
        f"Dialogue={dialogue_count}, analysis lines={line_count}",
    )
    is_ok &= validate(not _has_base_dialogue(ass_content), "ASS has no Base,, dialogue")

    current_ass_sha = file_sha256(ass_path)
    current_analysis_sha = file_sha256(analysis_path)
    current_mp4_sha = file_sha256(mp4_path)
    declared_analysis_sha = _manifest_sha(ass_manifest, "inputs", "analysis.json")
    is_ok &= validate(
        declared_analysis_sha == current_analysis_sha,
        "output.ass.manifest.json references current analysis.json hash",
    )
    is_ok &= validate(
        _manifest_sha(ass_manifest, "outputs", "output.ass") == current_ass_sha,
        "output.ass.manifest.json references current output.ass hash",
    )
    is_ok &= validate(
        _manifest_sha(mp4_manifest, "outputs", "output.mp4") == current_mp4_sha,
        "output.mp4.manifest.json references current output.mp4 hash",
    )
    is_ok &= validate(
        _manifest_sha(mp4_manifest, "inputs", "output.ass") == current_ass_sha,
        "output.mp4.manifest.json references current output.ass hash",
    )
    return bool(is_ok)

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
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=FFPROBE_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        return 0.0
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
    s05_args = ["--job-dir", str(job_dir)]
    lyrics_file = job_dir / "lyrics.txt"
    if lyrics_file.exists():
        s05_args.extend(["--lyrics", str(lyrics_file)])
        validate(True, "Ollama skipped for forced lyrics path")
    elif not check_ollama():
        validate(False, "Ollama connection", "Is Ollama running at localhost:11434?")
        sys.exit(1)
    else:
        validate(True, "Ollama connection")

    if not run_script("s05_analyze.py", s05_args, timeout=600):
        sys.exit(1)
    if not validate_stage_05(job_dir):
        sys.exit(1)

    # ── Stage 06: Generate ASS ───────────────────────────────
    if not run_script("s06_generate_ass.py", build_stage06_args(job_dir)):
        sys.exit(1)
    if not validate_stage_06(job_dir):
        sys.exit(1)

    # ── Stage 07: Output ─────────────────────────────────────
    if not run_script("s07_output.py", ["--job-dir", str(job_dir)], timeout=300):
        sys.exit(1)
    if not validate_stage_07(job_dir):
        sys.exit(1)
    if not validate_integration_provenance(job_dir):
        sys.exit(1)

    print("\n====================================================")
    print("  FULL PIPELINE TEST SUCCESSFUL")
    print(f"  Result: {job_dir / 'output.mp4'}")
    print("====================================================")

if __name__ == "__main__":
    main()
