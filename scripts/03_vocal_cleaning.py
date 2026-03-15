"""
03_vocal_cleaning.py — Step 03: Processamento e limpeza de vocais isolados.

Gera duas versões do vocal:
1. vocals_raw.wav (16k mono, highpass) - Para alinhamento MFA/CTC.
2. vocals_listen.wav (44k stereo, denoised, loudnorm) - Para o vídeo final.
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

    print(f"=== Step 03: Vocal Cleaning for {job_id} ===")
    _progress(0, "Iniciando limpeza de vocais...")

    sep_dir = kpaths.separation_dir(job_id)
    vocals_wav = sep_dir / "vocals.wav"
    
    if not vocals_wav.exists():
        print(f"ERRO: {vocals_wav} não encontrado. Execute Step 02 primeiro.")
        sys.exit(1)

    out_raw = kpaths.vocals_raw(job_id)
    out_listen = kpaths.vocals_listen(job_id)
    
    # ── vocals_raw.wav (Alinhamento) ──────────────────────────────────────────
    _progress(20, "Gerando vocals_raw.wav (16k, mono)...")
    cmd_raw = [
        "ffmpeg", "-y", "-i", str(vocals_wav),
        "-ar", "16000", "-ac", "1",
        "-af", "highpass=f=80",
        str(out_raw)
    ]
    subprocess.run(cmd_raw, check=True, capture_output=True)
    print(f"✓ vocals_raw.wav gerado: {out_raw.name}")

    # ── vocals_listen.wav (Áudio Final) ────────────────────────────────────────
    _progress(60, "Gerando vocals_listen.wav (44k, denoised)...")
    # Filtro: highpass, lowpass, denoiser leve, normalização EBU R128
    filters = (
        "highpass=f=120,"
        "lowpass=f=12000,"
        "afftdn=nf=-25:nr=6:nt=c,"
        "loudnorm=I=-16:TP=-1.5"
    )
    cmd_listen = [
        "ffmpeg", "-y", "-i", str(vocals_wav),
        "-ar", "44100", "-ac", "2",
        "-af", filters,
        str(out_listen)
    ]
    try:
        subprocess.run(cmd_listen, check=True, capture_output=True)
        print(f"✓ vocals_listen.wav gerado: {out_listen.name}")
    except subprocess.CalledProcessError as e:
         print(f"AVISO: Falha ao aplicar filtros avançados. Gerando versão básica. Erro: {e.stderr.decode()}")
         # Fallback to basic copy if filters fail (some ffmpeg versions lack afftdn)
         cmd_fallback = [
            "ffmpeg", "-y", "-i", str(vocals_wav),
            "-ar", "44100", "-ac", "2",
            str(out_listen)
         ]
         subprocess.run(cmd_fallback, check=True, capture_output=True)

    _progress(100, "Vocal Cleaning concluído.")

if __name__ == "__main__":
    main()
