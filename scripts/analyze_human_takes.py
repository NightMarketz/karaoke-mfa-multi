"""
analyze_human_takes.py — Agrega os registros salvos por server_score_addendum.py
(save=1 no POST /api/score) em input/human_takes/*.json, agrupados por condicao.

Existe pra fechar o "Fica aberto" do spec 2026-09-10: ate agora todo numero do
scorer vem do stem do Demucs fazendo papel de take. Sem um corpo de takes
humanos reais (silencio, ruido de sala, fone vs. caixa...) nao da pra saber se
VOICE_FRAC/VOICE_PAD_MS/ONSET_THRESHOLD estao certos pra microfone de verdade.

  python scripts/analyze_human_takes.py                  # usa input/human_takes/
  python scripts/analyze_human_takes.py --dir outra/pasta
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from karaoke import paths as kpaths  # noqa: E402

SEM_CONDICAO = "(sem condicao)"
CAMPOS = ("total", "melody", "rhythm", "attacks")


def carrega_registros(diretorio: Path) -> list[dict]:
    """Um dict por .json em `diretorio` — nao entra em subpasta, nao valida schema
    (quem escreve e' sempre _salva_take_para_pesquisa, mesmo dono dos dois lados)."""
    if not diretorio.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(diretorio.glob("*.json"))]


def agrupa_por_condicao(registros: list[dict]) -> dict[str, list[dict]]:
    grupos: dict[str, list[dict]] = {}
    for r in registros:
        chave = r.get("condicao") or SEM_CONDICAO
        grupos.setdefault(chave, []).append(r)
    return grupos


def resume(grupo: list[dict]) -> dict:
    """Cardinalidade antes do veredito: grupo vazio devolve so {"n": 0}, nunca
    media/mediana de populacao vazia disfarcada de numero real."""
    n = len(grupo)
    if n == 0:
        return {"n": 0}
    resumo: dict = {"n": n}
    for campo in CAMPOS:
        vals = [r[campo] for r in grupo]
        resumo[campo] = {
            "media": round(statistics.mean(vals), 1),
            "mediana": round(statistics.median(vals), 1),
            "min": round(min(vals), 1),
            "max": round(max(vals), 1),
        }
    return resumo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=kpaths.repos_root() / "input" / "human_takes")
    args = ap.parse_args()

    registros = carrega_registros(args.dir)
    print(f"{len(registros)} registro(s) em {args.dir}")
    if not registros:
        print("nenhum take humano salvo ainda — grave em web/mimic.html com 'Salvar para pesquisa'.")
        return 1

    for condicao, grupo in sorted(agrupa_por_condicao(registros).items()):
        r = resume(grupo)
        print(f"\n{condicao} (n={r['n']})")
        for campo in CAMPOS:
            c = r[campo]
            print(f"  {campo:8} media {c['media']:5.1f}  mediana {c['mediana']:5.1f}  "
                  f"min {c['min']:5.1f}  max {c['max']:5.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
