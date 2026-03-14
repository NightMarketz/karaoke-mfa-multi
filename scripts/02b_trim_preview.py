import sys
import io
import json
import subprocess
import argparse
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





def trim_wav(src: Path, dst: Path, start: float, duration: float, sample_rate: int, channels: int):
    """Corta um WAV usando ffmpeg. dst pode ser igual a src."""
    tmp = dst.with_suffix(".tmp.wav")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-ss", str(start),
        "-t",  str(duration),
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-c:a", "pcm_s16le",
        str(tmp),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERRO ffmpeg: {result.stderr}")
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dst)
    return True


def get_duration(path: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print("=== Step 02b: Preview Trim ===")
    _progress(0, "Lendo configuração de preview...")

    job_root = kpaths.job_dir(job_id)
    config_path = job_root / "preview_config.json"

    if not config_path.exists():
        print("  preview_config.json não encontrado — nada a fazer.")
        _progress(100, "Sem preview config — pulando")
        return

    config = json.loads(config_path.read_text(encoding="utf-8"))
    duration = float(config.get("duration", 60))
    start    = float(config.get("start", 0))
    trimmed  = config.get("trimmed", False)

    if trimmed:
        print(f"  Job já foi cortado anteriormente para {duration}s. Pulando.")
        _progress(100, "Já cortado — pulando")
        return

    print(f"  Corte: {start}s → {start + duration}s ({duration}s de preview)")

    vocals_dir = kpaths.vocals_dir(job_id)
    stems_dir  = kpaths.htdemucs_dir(job_id) / "song"

    # Lista de arquivos para cortar: (path, sample_rate, channels)
    targets = []

    raw = vocals_dir / "vocals_raw.wav"
    if raw.exists():
        targets.append((raw, 16000, 1))

    listen = vocals_dir / "vocals_listen.wav"
    if listen.exists():
        targets.append((listen, 44100, 2))

    for stem_name in ["vocals", "drums", "bass", "other", "no_vocals"]:
        p = stems_dir / f"{stem_name}.wav"
        if p.exists():
            targets.append((p, 44100, 2))

    if not targets:
        print("  ERRO: Nenhum arquivo WAV encontrado para cortar.")
        sys.exit(1)

    total = len(targets)
    for i, (path, sr, ch) in enumerate(targets):
        pct = 5 + int((i / total) * 88)
        _progress(pct, f"Cortando {path.name}...")

        # Preserva original como *_full.wav
        full_backup = path.with_name(path.stem + "_full.wav")
        if not full_backup.exists():
            path.rename(full_backup)
            src = full_backup
        else:
            src = full_backup  # já foi renomeado numa tentativa anterior

        # Valida duração
        orig_dur = get_duration(src)
        if orig_dur < start:
            print(f"  Aviso: {path.name} tem {orig_dur:.1f}s — menor que o start {start}s. Pulando.")
            # Restaura
            import shutil
            shutil.copy2(str(src), str(path))
            continue

        actual_dur = min(duration, orig_dur - start)
        ok = trim_wav(src, path, start, actual_dur, sr, ch)
        if ok:
            print(f"  ✓ {path.name}: {orig_dur:.1f}s → {actual_dur:.1f}s")
        else:
            print(f"  ✗ Falha ao cortar {path.name}")
            sys.exit(1)

    # Marca como cortado no config
    config["trimmed"] = True
    config["actual_duration"] = min(duration, get_duration(kpaths.vocals_dir(job_id) / "vocals_raw.wav"))
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    _progress(100, f"Preview pronto — {duration:.0f}s cortados de {total} arquivos")
    print(f"✅ {total} arquivos cortados para {duration:.0f}s de preview")
    print(f"   Originais preservados como *_full.wav")


if __name__ == "__main__":
    main()
