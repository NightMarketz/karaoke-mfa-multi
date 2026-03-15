import argparse
import sys
import io
from pathlib import Path
from scripts.compare_timing import compare_timings
import karaoke.paths as kpaths

# Force UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description="Compare MFA vs SOFA alignment results for a specific job.")
    parser.add_argument("--job-id", required=True, help="Job UUID to compare")
    parser.add_argument("--mfa-json", help="Path to MFA results (defaults to 05_alignment/word_timing_fixed.json)")
    parser.add_argument("--sofa-json", help="Path to SOFA results (defaults to 05_alignment/fused_alignment.json)")
    
    args = parser.parse_args()
    
    wav_path = kpaths.vocals_raw(args.job_id)
    
    # Logic for MFA JSON path
    if args.mfa_json:
        mfa_json = Path(args.mfa_json)
    else:
        # Try word_timing_fixed.json, fallback to word_timing.json
        align_dir = kpaths.alignment_dir(args.job_id)
        mfa_json = align_dir / "word_timing_fixed.json"
        if not mfa_json.exists():
            mfa_json = align_dir / "word_timing.json"
            
    # Logic for SOFA JSON path
    if args.sofa_json:
        sofa_json = Path(args.sofa_json)
    else:
        sofa_json = kpaths.fused_alignment_json(args.job_id)
        
    print(f"--- Aligner Comparison for Job: {args.job_id} ---")
    print(f"Audio: {wav_path}")
    print(f"Old (MFA): {mfa_json}")
    print(f"New (SOFA): {sofa_json}\n")
    
    if not wav_path.exists():
        print(f"ERROR: Audio not found at {wav_path}")
        sys.exit(1)
    if not mfa_json.exists():
        print(f"ERROR: MFA results not found at {mfa_json}")
        sys.exit(1)
    if not sofa_json.exists():
        print(f"ERROR: SOFA results not found at {sofa_json}")
        sys.exit(1)
        
    compare_timings(wav_path, mfa_json, sofa_json)

if __name__ == "__main__":
    main()
