"""
02_vocal_isolation.py — Step 02: Isolamento de vocais via Demucs.

Usa o modelo htdemucs para separar voz e instrumentos.
"""
import argparse
import subprocess
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import karaoke.paths as kpaths

def _progress(pct: int, msg: str = ""):
    print(f"PROGRESS: {pct} | {msg}", flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print(f"=== Step 02: Vocal Isolation for {job_id} ===")
    _progress(0, "Iniciando isolamento de vocais...")

    input_wav = kpaths.input_job_dir(job_id) / "song.wav"
    out_dir = kpaths.separation_dir(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not input_wav.exists():
        print(f"ERRO: {input_wav} não encontrado. Execute Step 01 primeiro.")
        sys.exit(1)

    _progress(10, "Executando Demucs (htdemucs)...")
    
    # We use conda run to ensure we use the correct environment
    # Note: htdemucs --two-stems vocals is fast and effective
    cmd = [
        "conda", "run", "-n", "demucs_env",
        "demucs", "-n", "htdemucs",
        "--two-stems", "vocals",
        "-o", str(out_dir),
        str(input_wav)
    ]
    
    try:
        # We don't use capture_output=True here to let the user see the Demucs progress
        subprocess.run(cmd, check=True)
        print("✓ Demucs concluído.")
    except Exception as e:
        print(f"ERRO ao executar Demucs: {e}")
        sys.exit(1)

    # Demucs saves in {out_dir}/htdemucs/{filename}/vocals.wav
    stem_name = input_wav.stem
    vocals_src = out_dir / "htdemucs" / stem_name / "vocals.wav"
    
    if not vocals_src.exists():
        print(f"ERRO: Vocal stem não encontrado em {vocals_src}")
        sys.exit(1)
        
    # Copy to a more predictable location for Step 03
    vocals_dest = out_dir / "vocals.wav"
    import shutil
    shutil.copy(vocals_src, vocals_dest)
    print(f"✓ Vocais isolados em: {vocals_dest}")

    _progress(100, "Vocal Isolation concluído.")

if __name__ == "__main__":
    main()
