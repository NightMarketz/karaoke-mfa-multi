"""
07_audio_mixing.py — Step 07: Mix Stems & Mastering.

Creates professional karaoke mixes from separated stems:
1. Instrumental Mix: drums + bass + other.
2. Guide Vocal Mix: instrumental + vocals (low volume).
3. Mastered original: original audio normalized.

Outputs:
  work/07_mixed/instrumental.mp3
  work/07_mixed/guide.mp3
"""
import os
import sys
import io
import subprocess
import argparse
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths

# Force UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')



def run_ffmpeg(args):
    """Run FFmpeg and handle errors."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args
    print(f"  CMD: ffmpeg {' '.join(args[:10])}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERRO FFmpeg: {result.stderr}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print("=== Fase H: Mixagem e Masterização de Stems ===")

    stems_dir = kpaths.stems_dir(job_id)
    out_dir = kpaths.mixing_dir(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Vocal stem is always required
    vocals = stems_dir / "vocals.wav"

    if not vocals.exists():
        print(f"ERRO: Stem não encontrado: {vocals}")
        print("Certifique-se que o upload de stems incluiu o vocal ou o Step 02 (Demucs) rodou com sucesso.")
        sys.exit(1)

    # All other wav files are considered instrumental stems (including 'no_vocals.wav' from two-stems demucs)
    instrumental_stems = [f for f in stems_dir.glob("*.wav") if f.name != "vocals.wav"]
    
    if not instrumental_stems:
        print("AVISO: Nenhum stem instrumental encontrado além do vocal.")
    
    # 1. PRE-MIX INSTRUMENTAL (Mastering Chain: loudnorm + limiter)
    inst_mp3 = out_dir / "instrumental.mp3"
    print(f"  Gerando Mix Instrumental (Karaoke) com {len(instrumental_stems)} stems...")
    
    if len(instrumental_stems) > 0:
        inputs = []
        for s in instrumental_stems:
            inputs.extend(["-i", str(s)])
        
        filter_inputs = "".join([f"[{i}]" for i in range(len(instrumental_stems))])
        
        run_ffmpeg([
            *inputs,
            "-filter_complex", f"{filter_inputs}amix=inputs={len(instrumental_stems)}:dropout_transition=0,loudnorm=I=-14:TP=-1.5:LRA=11",
            "-b:a", "192k", str(inst_mp3)
        ])
    else:
        # Fallback if no instrumental stems exist (e.g. only vocals provided)
        # Just create an empty/silent instrumental or copy vocals?
        # A completely silent 1s file for instrumental to avoid breaking the pipeline
        run_ffmpeg([
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "1", "-b:a", "192k", str(inst_mp3)
        ])

    # 2. GENERATE GUIDE VOCAL WITH SIDECHAIN COMPRESSION
    guide_mp3 = out_dir / "guide.mp3"
    print(f"  Gerando Mix com Guia Vocal (-12dB com ducking)...")
    
    if len(instrumental_stems) > 0:
        inputs = []
        for s in instrumental_stems:
            inputs.extend(["-i", str(s)])
        # Append vocals as the LAST input
        inputs.extend(["-i", str(vocals)])
        voc_idx = len(instrumental_stems)
        
        filter_inputs = "".join([f"[{i}]" for i in range(len(instrumental_stems))])
        
        run_ffmpeg([
            *inputs,
            "-filter_complex", 
            f"{filter_inputs}amix=inputs={len(instrumental_stems)}:dropout_transition=0[inst];" +
            f"[{voc_idx}]volume=0.12[voc_quiet];" +
            "[inst][voc_quiet]sidechaincompress=threshold=0.02:ratio=4:attack=5:release=200[inst_ducked];" +
            "[inst_ducked][voc_quiet]amix=inputs=2:dropout_transition=0,loudnorm=I=-14:TP=-1.5:LRA=11[out]",
            "-map", "[out]", "-b:a", "320k", str(guide_mp3)
        ])
    else:
        # If no instrumental stems, guide is just the vocals
        run_ffmpeg([
            "-i", str(vocals),
            "-filter_complex", "volume=0.12,loudnorm=I=-14:TP=-1.5:LRA=11",
            "-b:a", "320k", str(guide_mp3)
        ])

    print("\n✅ Mixagem concluída!")
    print(f"  - Karaoke: {inst_mp3.name}")
    print(f"  - Com Guia: {guide_mp3.name}")

if __name__ == "__main__":
    main()
