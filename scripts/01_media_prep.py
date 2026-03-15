"""
01_media_prep.py — Step 01: Extração de áudio e validação de mídia.

Busca por video_original.mp4 ou similar e extrai o áudio para vocals_mix.wav.
Também garante que lyrics.txt existe.
"""
import argparse
import subprocess
import sys
import shutil
from pathlib import Path

# Force UTF-8 for Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import karaoke.paths as kpaths

def _progress(pct: int, msg: str = ""):
    print(f"PROGRESS: {pct} | {msg}", flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print(f"=== Step 01: Media Prep for {job_id} ===")
    _progress(0, "Iniciando preparação de mídia...")

    input_dir = kpaths.input_job_dir(job_id)
    lyrics_txt = kpaths.lyrics_path(job_id)
    
    # Check lyrics
    if not lyrics_txt.exists():
        print(f"ERRO: {lyrics_txt} não encontrado.")
        sys.exit(1)
    
    _progress(10, "Verificando arquivos de vídeo/áudio...")
    
    # Look for video or audio source
    sources = list(input_dir.glob("video_original.*")) + list(input_dir.glob("song.*"))
    if not sources:
        print(f"ERRO: Nenhuma fonte de mídia (video_original.* ou song.*) encontrada em {input_dir}")
        sys.exit(1)
    
    source_file = sources[0]
    out_audio = kpaths.input_job_dir(job_id) / "song.wav"
    
    if source_file.suffix.lower() in ['.mp4', '.mkv', '.avi', '.mov']:
        _progress(30, f"Extraindo áudio de {source_file.name}...")
        cmd = [
            "ffmpeg", "-y", "-i", str(source_file),
            "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            str(out_audio)
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"✓ Áudio extraído para {out_audio.name}")
        except subprocess.CalledProcessError as e:
            print(f"ERRO FFmpeg: {e.stderr.decode()}")
            sys.exit(1)
    else:
        _progress(30, f"Convertendo/Copiando áudio de {source_file.name}...")
        # Even if it's already audio, we convert to standard wav for predictability
        cmd = [
            "ffmpeg", "-y", "-i", str(source_file),
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            str(out_audio)
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✓ Áudio padronizado para {out_audio.name}")

    _progress(100, "Media Prep concluído.")

if __name__ == "__main__":
    main()
