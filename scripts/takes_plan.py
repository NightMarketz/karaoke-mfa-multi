"""
takes_plan.py — Planeja os takes de video generativo a partir de analysis.json.

Nao e' um estagio do pipeline: e' a ferramenta de handoff para a maquina que
gera video. Le analysis.json (+ um song.toml autoral opcional) e escreve
takes.json, o shot list que a outra maquina consome.

Aritmetica load-bearing (medida, nao suposta):

  * O modelo gera sempre a janela nativa de 81 frames @16fps = 5.06 s.
  * A emenda entre dois takes precisa de um crossfade de 4 frames (250 ms).
    Medido: corte seco da um salto de luma de 4.89 contra 3.31 do maior salto
    interno; com 4 frames cai para 1.68. 8 ou 12 frames nao compram nada.
  * Logo cada take OCUPA 81-4 = 77 frames (4.8125 s) na linha do tempo e os
    4 restantes pagam a emenda. Sem isso, 35 emendas acumulam ~8.75 s de
    deriva e o video desalinha da letra no fim da musica.
  * Takes consecutivos COMPARTILHAM o keyframe de fronteira: N takes -> N+1
    imagens. Corta 49% da geracao de imagem e e' o que torna a emenda
    coerente (medido: 26.0 dB na juntura contra 12.5 dB de controle).

Uso:
    python scripts/takes_plan.py --job-dir jobs/my-job
    python scripts/takes_plan.py --job-dir jobs/my-job --song song.toml

Le:
    jobs/{job_id}/analysis.json
    song.toml (opcional)
Escreve:
    jobs/{job_id}/takes.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Janela nativa do Wan 2.2 I2V (template oficial video_wan2_2_14B_flf2v).
DEFAULT_TAKE_FRAMES = 81
DEFAULT_FPS = 16
# Medido: 4 frames levam o salto na emenda de 4.89 para 1.68, abaixo do
# maior salto interno do proprio take. 8 e 12 nao melhoram o suficiente
# para justificar o dobro/triplo de frames consumidos.
DEFAULT_OVERLAP_FRAMES = 4


def _sections(lines: list[dict]) -> list[dict]:
    """Agrupa linhas consecutivas de mesmo style numa secao."""
    out: list[dict] = []
    for line in lines:
        style = line.get("style", "verse")
        start = float(line.get("start", 0.0))
        end = float(line.get("end", start))
        if out and out[-1]["style"] == style:
            out[-1]["end"] = max(out[-1]["end"], end)
        else:
            out.append({"style": style, "start": start, "end": end})
    return out


def plan_takes(
    lines: list[dict],
    *,
    fps: int = DEFAULT_FPS,
    take_frames: int = DEFAULT_TAKE_FRAMES,
    overlap_frames: int = DEFAULT_OVERLAP_FRAMES,
) -> list[dict]:
    """analysis["lines"] -> shot list. Um take nunca cruza fronteira de secao."""
    if not lines:
        return []
    slot_s = (take_frames - overlap_frames) / fps
    takes: list[dict] = []
    for sec in _sections(lines):
        dur = sec["end"] - sec["start"]
        if dur <= 0:
            continue
        n = max(1, -(-dur // slot_s))  # ceil, sem importar math
        n = int(n)
        for i in range(n):
            start = sec["start"] + i * slot_s
            end = min(sec["end"], start + slot_s)
            idx = len(takes)
            takes.append({
                "idx": idx,
                "section": sec["style"],
                "start": round(start, 6),
                "end": round(end, 6),
                "generate_frames": take_frames,
                "overlap_frames": overlap_frames,
                "fps": fps,
                # fronteira compartilhada: o kf_out de um e' o kf_in do proximo
                "kf_in": f"kf_{idx:03d}",
                "kf_out": f"kf_{idx + 1:03d}",
                "trimmed": (end - start) < slot_s - 1e-9,
            })
    return takes


def keyframe_ids(takes: list[dict]) -> list[str]:
    """Os N+1 keyframes que os takes exigem, em ordem, sem repeticao."""
    if not takes:
        return []
    ids = [t["kf_in"] for t in takes]
    ids.append(takes[-1]["kf_out"])
    return ids


def _load_song(path: Path | None) -> dict[str, Any]:
    """song.toml autoral: estilo global + cena por secao. Ausente = vazio."""
    if path is None or not path.exists():
        return {}
    try:
        import tomllib
    except ModuleNotFoundError:  # py<3.11
        import tomli as tomllib  # type: ignore
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _prompts(takes: list[dict], song: dict[str, Any]) -> None:
    """Preenche prompt de keyframe e de movimento a partir do song.toml."""
    style = song.get("style", {})
    base = str(style.get("base", "")).strip()
    suffix = str(style.get("keyframe_suffix", "")).strip()
    negative = str(style.get("negative", "")).strip()
    scenes = song.get("sections", {})
    for t in takes:
        scene = str(scenes.get(t["section"], "")).strip()
        t["keyframe_prompt"] = ", ".join(p for p in (base, scene, suffix) if p)
        t["motion_prompt"] = ", ".join(p for p in (base, scene) if p)
        t["negative_prompt"] = negative


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Planeja os takes de video a partir de analysis.json.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--song", type=Path, default=None,
                        help="song.toml autoral (estilo + cena por secao).")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--take-frames", type=int, default=DEFAULT_TAKE_FRAMES)
    parser.add_argument("--overlap-frames", type=int, default=DEFAULT_OVERLAP_FRAMES)
    args = parser.parse_args()

    analysis_path = args.job_dir / "analysis.json"
    if not analysis_path.exists():
        print(f"analysis.json ausente em {args.job_dir}. Rode o s05 antes.",
              file=sys.stderr)
        return 1
    try:
        lines = json.loads(analysis_path.read_text(encoding="utf-8")).get("lines", [])
    except json.JSONDecodeError as exc:
        print(f"analysis.json invalido: {exc}", file=sys.stderr)
        return 1

    takes = plan_takes(lines, fps=args.fps, take_frames=args.take_frames,
                       overlap_frames=args.overlap_frames)
    if not takes:
        print("analysis.json nao produziu nenhum take.", file=sys.stderr)
        return 1
    _prompts(takes, _load_song(args.song))
    kfs = keyframe_ids(takes)

    out = args.job_dir / "takes.json"
    out.write_text(json.dumps({
        "fps": args.fps,
        "take_frames": args.take_frames,
        "overlap_frames": args.overlap_frames,
        "slot_seconds": (args.take_frames - args.overlap_frames) / args.fps,
        "keyframes": kfs,
        "takes": takes,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    covered = sum(t["end"] - t["start"] for t in takes)
    print(f"takes.json: {len(takes)} takes, {len(kfs)} keyframes, "
          f"{covered:.2f}s cobertos ({covered / 60:.2f} min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
