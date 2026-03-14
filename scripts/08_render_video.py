"""
08_render_video.py — Step 09: Render karaoke preview video.

Inputs  (via --job-id):
  work/jobs/{job_id}/06_ass/karaoke.ass
  input/jobs/{job_id}/song.*
  work/jobs/{job_id}/08_mixed/guide.mp3     (preferido)
  work/jobs/{job_id}/08_mixed/instrumental.mp3

Outputs (via --job-id):
  work/jobs/{job_id}/07_video/karaoke_preview.mp4
"""
import sys
import io
import subprocess
import argparse
import tempfile
import shutil
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths

# Force UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def _progress(pct: int, msg: str = ""):
    if msg:
        print(f"PROGRESS: {pct} | {msg}", flush=True)
    else:
        print(f"PROGRESS: {pct}", flush=True)





def _find_audio(job_id: str) -> Path | None:
    input_root = kpaths.input_dir(job_id)

    # 1. Guia mixado (vocal guia + instrumental)
    guide = kpaths.final_mixed_audio(job_id) # Using a new accessor or kpaths.mixing_dir(job_id) / "guide.mp3"
    if guide.exists():
        print(f"  Audio: {guide.name} (mixado)")
        return guide

    # 2. Instrumental puro
    inst = kpaths.mixing_dir(job_id) / "instrumental.mp3"
    if inst.exists():
        print(f"  Audio: instrumental.mp3 (mixado)")
        return inst

    # 3. Original
    for ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a"]:
        p = input_root / f"song{ext}"
        if p.exists():
            print(f"  Audio: song{ext} (original)")
            return p

    return None


def _get_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _escape_ass_path(ass_path: Path) -> str:
    """
    Converte path para o formato que o filtro subtitles= do FFmpeg aceita.
    No Windows: barras invertidas → forward slashes, dois-pontos escapado.
    Espaços no path precisam de arquivo temporário sem espaços.
    """
    s = str(ass_path).replace("\\", "/")
    # Escapa dois-pontos (C:/ → C\:/)
    s = s[0] + "\\:" + s[2:] if len(s) > 1 and s[1] == ":" else s
    return s


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print("=== Fase I: Render Video Karaoke ===")
    _progress(0, "Iniciando render...")

    ass_path = kpaths.final_ass(job_id)
    out_dir  = kpaths.render_dir(job_id)
    out_video = kpaths.final_video(job_id)

    # ── Validações ────────────────────────────────────────────────────────────
    if not ass_path.exists():
        print(f"ERRO: karaoke.ass não encontrado: {ass_path}")
        sys.exit(1)

    audio_path = _find_audio(job_id)
    if audio_path is None:
        print("ERRO: Nenhum arquivo de áudio encontrado para o render.")
        sys.exit(1)

    _progress(5, "Detectando duração do áudio...")
    duration = _get_duration(audio_path)
    if duration <= 0:
        print(f"ERRO: Não foi possível detectar a duração de {audio_path}")
        sys.exit(1)

    print(f"  ASS:      {ass_path}")
    print(f"  Duração:  {duration:.1f}s")
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Copia ASS para path sem espaços se necessário ─────────────────────────
    # O filtro subtitles= do FFmpeg quebra com espaços no path mesmo escapado
    ass_to_use = ass_path
    tmp_dir = None

    if " " in str(ass_path):
        _progress(8, "Copiando ASS para path temporário (espaços no path)...")
        tmp_dir = tempfile.mkdtemp(prefix="kstudio_")
        ass_to_use = Path(tmp_dir) / "karaoke.ass"
        shutil.copy2(ass_path, ass_to_use)
        print(f"  ASS temp: {ass_to_use}")

    ass_escaped = _escape_ass_path(ass_to_use)

    # ── Monta comando FFmpeg ───────────────────────────────────────────────────
    # -t duration sem -shortest: evita conflito quando audio > video ou vice versa
    _progress(10, f"Iniciando encode ({duration:.0f}s de video)...")

    cmd = [
        "ffmpeg", "-y", "-hide_banner",
        # Background escuro gradient 1280x720
        "-f", "lavfi",
        "-i", f"color=c=#08090f:s=1280x720:d={duration},format=yuv420p",
        # Áudio
        "-i", str(audio_path),
        # Subtítulos ASS queimados no vídeo
        "-vf", f"subtitles='{ass_escaped}'",
        # Vídeo: H.264 rápido, qualidade boa
        "-c:v", "libx264",
        "-preset", "superfast",
        "-crf", "23",
        # Áudio: AAC 192k
        "-c:a", "aac",
        "-b:a", "192k",
        # Duração exata do áudio — sem -shortest para evitar conflito
        "-t", str(duration),
        # Progresso no stderr para parsear
        "-progress", "pipe:1",
        str(out_video),
    ]

    print(f"  CMD: {' '.join(cmd)}")

    # ── Executa com captura de progresso ──────────────────────────────────────
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stderr_lines = []
    last_pct = 10

    # FFmpeg com -progress pipe:1 escreve pares key=value no stdout
    for line in process.stdout:
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                ms = int(line.split("=")[1])
                elapsed_s = ms / 1_000_000
                pct = 10 + int(min(88, (elapsed_s / duration) * 88))
                if pct > last_pct:
                    last_pct = pct
                    mins = int(elapsed_s // 60)
                    secs = int(elapsed_s % 60)
                    _progress(pct, f"Codificando {mins}:{secs:02d} / {int(duration//60)}:{int(duration%60):02d}")
            except (ValueError, ZeroDivisionError):
                pass
        elif line.startswith("progress=end"):
            _progress(98, "Finalizando arquivo...")

    # Não lê stderr separadamente (já foi redirecionado para stdout)
    process.wait()

    # Limpa tmp
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if process.returncode != 0:
        print(f"\n  FFmpeg STDERR:\n{stderr_output[-2000:]}")
        print(f"\nERRO: FFmpeg retornou código {process.returncode}")
        sys.exit(1)

    if not out_video.exists():
        print(f"\nERRO: Vídeo não foi criado em {out_video}")
        sys.exit(1)

    size_mb = out_video.stat().st_size / (1024 * 1024)
    _progress(100, f"Video gerado — {size_mb:.1f} MB")
    print(f"✓ Vídeo salvo em: {out_video}")
    print(f"  Tamanho: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
