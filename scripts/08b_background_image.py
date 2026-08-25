"""
08b_background_image.py — Gera a ilustracao de fundo a partir da letra.

Inputs  (via --job-id):
  work/jobs/{job_id}/input/lyrics.txt

Outputs (via --job-id):
  work/jobs/{job_id}/08_background/background.png

Falha NUNCA derruba o job: sem PNG, o Step 09 usa fundo chapado.
"""
import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths
from karaoke.background import build_brief, generate_image, image_prompt

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

WORKFLOW = Path(__file__).resolve().parent.parent / "config" / "comfy_workflow.json"


def _progress(pct: int, msg: str = ""):
    print(f"PROGRESS: {pct} | {msg}" if msg else f"PROGRESS: {pct}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Gera ilustracao de fundo (local)")
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    print("=== Step 08b: Background Illustration ===")
    out = kpaths.background_png(args.job_id)

    if out.exists():
        print(f"  Cache encontrado ({out.name}) — pulando geracao.")
        _progress(100, "Fundo em cache.")
        return

    try:
        _progress(10, "Lendo letra...")
        lyrics = kpaths.lyrics_path(args.job_id).read_text(encoding="utf-8")

        _progress(25, "Gerando brief visual (Ollama)...")
        brief = build_brief(lyrics)
        print(f"  Brief: {brief}")

        _progress(45, "Gerando ilustracao (ComfyUI)...")
        generate_image(image_prompt(brief), out, WORKFLOW)

        size_kb = out.stat().st_size / 1024
        _progress(100, f"Fundo gerado — {size_kb:.0f} KB")
        print(f"OK Fundo salvo em: {out}")
    except Exception as e:
        # Fundo e enfeite. Sem ele o Step 09 usa #08090f e o job segue.
        print(f"  AVISO: fundo nao gerado ({type(e).__name__}: {e})")
        print("  O video sera renderizado com fundo chapado.")
        _progress(100, "Sem fundo — seguindo com fundo chapado.")


if __name__ == "__main__":
    main()
