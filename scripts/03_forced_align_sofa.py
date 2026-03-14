import argparse
import sys
import subprocess
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))
from karaoke import paths

def run_sofa_align(job_id: str):
    """
    Executes SOFA (Segment-Oriented Forced Alignment) using the 'sofa' conda environment.
    """
    input_wav = paths.vocals_raw(job_id)
    output_dir = paths.sofa_dir(job_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_tg = paths.sofa_textgrid(job_id)
    
    print(f"[SOFA] Aligning {input_wav}...")
    
    # This will be refined with the exact SOFA call logic (model, dictionary)
    # The user mentioned: "modelo de inglês + dicionário adaptado para português"
    cmd = [
        "conda", "run", "-n", "sofa",
        "python", "-m", "sofa_cli", # Placeholder for actual SOFA command
        "--input", str(input_wav),
        "--output", str(output_tg)
    ]
    
    print(f"[SOFA] Running: {' '.join(cmd)}")
    # subprocess.run(cmd, check=True)
    
    print(f"[SOFA] Done. Output: {output_tg}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SOFA Forced Alignment Stage")
    parser.add_argument("--job-id", required=True, help="Job UUID")
    args = parser.parse_args()
    
    run_sofa_align(args.job_id)
