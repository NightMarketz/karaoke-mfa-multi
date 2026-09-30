"""
08c_scene_background.py — fundo da cena reativa para um job.

    python scripts/08c_scene_background.py --job-id <id> --scene guts_camp

Le input/scenes/<cena>/ e o no_vocals.wav do job; escreve, em
08_background/, background_scene.mp4 + .json (cena) + _relatorio.json
(estados e brilho da faixa do topo por quadro, para o portao real).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths
from karaoke import onset, scene_compose, scene_score
from karaoke.bounce import read_mono_wav

RAIZ = Path(__file__).resolve().parent.parent
CENAS = RAIZ / "input" / "scenes"


def _duracao(wav: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", str(wav)],
                         capture_output=True, text=True, check=True, timeout=30)
    return float(out.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--scene", required=True)
    args = ap.parse_args()

    print("=== Step 08c: Cena reativa ===")
    wav = kpaths.demucs_out_dir(args.job_id) / "no_vocals.wav"
    saida = kpaths.background_scene_mp4(args.job_id)
    try:
        if not wav.exists():
            raise FileNotFoundError(f"instrumental nao encontrado: {wav}")
        loops, masc, fps, _ = scene_compose.carregar_pacote(CENAS / args.scene)
        audio, sr = read_mono_wav(wav)
        rms, fd = onset.compute_rms(audio, sr)
        est, w, g = scene_score.score(rms, fd, onset.detect_onsets(rms, fd), fps, _duracao(wav))
        saida.parent.mkdir(parents=True, exist_ok=True)
        for velho in (saida, saida.with_suffix(".json"),
                      saida.with_name("background_scene_relatorio.json")):
            velho.unlink(missing_ok=True)
        faixa = scene_compose.compor(loops, masc, w, g, fps, saida)
    except Exception as e:
        print(f"ERRO: cena '{args.scene}' nao gerada ({type(e).__name__}: {e})")
        sys.exit(1)

    saida.with_suffix(".json").write_text(json.dumps({"scene": args.scene}), encoding="utf-8")
    trocas = [[round(i / fps, 2), int(s)] for i, s in enumerate(est) if i == 0 or s != est[i - 1]]
    saida.with_name("background_scene_relatorio.json").write_text(
        json.dumps({"fps": fps, "estados": trocas, "faixa_topo_luma": [round(x, 1) for x in faixa]}),
        encoding="utf-8")
    print(f"OK {saida.name}: {len(est)} quadros, {len(trocas)} trechos de estado")


if __name__ == "__main__":
    main()
