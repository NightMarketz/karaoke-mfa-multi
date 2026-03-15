"""
04_mfa_alignment.py — Step 04: Alinhamento Primário via Montreal Forced Aligner (MFA).

Consolida a preparação de corpus e a execução do alinhamento CTC.
"""
import argparse
import subprocess
import sys
import shutil
import json
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

    print(f"=== Step 04: MFA Alignment for {job_id} ===")
    _progress(0, "Iniciando alinhamento MFA...")

    # 1. Preparar Corpus
    corpus_dir = kpaths.mfa_corpus_dir(job_id)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    
    vocals_raw = kpaths.vocals_raw(job_id)
    lyrics_txt = kpaths.lyrics_path(job_id)
    
    if not vocals_raw.exists():
        print(f"ERRO: {vocals_raw} não encontrado. Execute Step 03 primeiro.")
        sys.exit(1)
        
    # Copy vocals to corpus
    shutil.copy(vocals_raw, corpus_dir / "vocals.wav")
    
    # Simple lyrics pre-processing for MFA (remove punctuation, uppercase)
    # MFA works best with uppercase in many cases, but here we just clean it.
    with open(lyrics_txt, 'r', encoding='utf-8') as f:
        text = f.read().replace('\n', ' ').strip()
        # Basic cleanup: remove special chars
        import re
        text = re.sub(r'[^\w\s]', '', text).upper()
        
    with open(corpus_dir / "vocals.txt", 'w', encoding='utf-8') as f:
        f.write(text)
        
    _progress(30, "Corpus preparado. Iniciando alinhamento...")

    # 2. Executar MFA
    out_tg = kpaths.mfa_textgrid(job_id)
    out_tg.parent.mkdir(parents=True, exist_ok=True)
    
    # Command structure using conda run
    # MFA 'align' with CTC model is faster and more robust for karaoke
    # We use a Portuguese dictionary if available
    dict_path = "input/dicts/pt_mfa.dict"
    model_name = "portuguese_mfa" # Or "portuguese_mfa"
    
    cmd = [
        "conda", "run", "-n", "mfa_env",
        "mfa", "align",
        str(corpus_dir),
        dict_path,
        model_name,
        str(out_tg.parent),
        "--clean", "--overwrite"
    ]
    
    print(f"CMD: {' '.join(cmd)}")
    
    try:
        # MFA can be noisy, but we want to see if it fails
        subprocess.run(cmd, check=True)
        print("✓ MFA concluído.")
    except Exception as e:
        print(f"ERRO ao executar MFA: {e}")
        # Note: In a real pipeline, we might fall back to WhisperX if MFA fails here
        sys.exit(1)

    # Validate output
    # MFA usually outputs as {job_id}/vocals.TextGrid in the output folder
    mfa_result = out_tg.parent / "vocals.TextGrid"
    if mfa_result.exists() and mfa_result != out_tg:
        shutil.move(mfa_result, out_tg)

    if not out_tg.exists():
        print(f"ERRO: Alinhamento falhou, TextGrid não encontrado em {out_tg}")
        sys.exit(1)

    _progress(100, "MFA Alignment concluído.")

if __name__ == "__main__":
    main()
