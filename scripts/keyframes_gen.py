"""
keyframes_gen.py — Gera os N+1 keyframes de takes.json via ComfyUI.

Roda nesta maquina (a geracao de imagem e' barata aqui: ~15 s por keyframe
com os pesos quentes). Os MP4 dos takes sao gerados noutra maquina a partir
destes keyframes; ver scripts/takes_plan.py para o shot list.

Cada keyframe e' compartilhado por dois takes consecutivos (o kf_out de um
e' o kf_in do seguinte). Convencao: o keyframe usa o prompt do take que ele
INICIA; o ultimo keyframe reusa o prompt do ultimo take. Numa fronteira de
secao isso faz o take anterior terminar ja com o visual da secao nova, o que
e' o comportamento de transicao desejado.

Uso:
    python scripts/keyframes_gen.py --job-dir jobs/my-job
    python scripts/keyframes_gen.py --job-dir jobs/my-job --url http://127.0.0.1:8001

Le:
    jobs/{job_id}/takes.json
    data/workflows/anima_keyframe.json  (marcadores %prompt% e %seed%)
Escreve:
    jobs/{job_id}/keyframes/kf_000.png ...
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8000"
# O guia do ComfyUI deste ambiente registra porta dinamica entre sessoes.
PROBE_PORTS = (8000, 8001, 8188)
DEFAULT_WORKFLOW = Path("data/workflows/anima_keyframe.json")
_NONCE = itertools.count(int(time.time()))


def keyframe_jobs(takes: list[dict]) -> list[dict]:
    """takes.json -> um job por keyframe. N takes produzem N+1 jobs."""
    if not takes:
        return []
    jobs = [{
        "id": t["kf_in"],
        "prompt": t.get("keyframe_prompt", ""),
        "section": t.get("section", ""),
        "seed": 1000 + int(t.get("idx", i)),
    } for i, t in enumerate(takes)]
    last = takes[-1]
    jobs.append({
        "id": last["kf_out"],
        "prompt": last.get("keyframe_prompt", ""),
        "section": last.get("section", ""),
        "seed": 1000 + int(last.get("idx", len(takes) - 1)) + 1,
    })
    return jobs


def substitute(node: Any, mapping: dict[str, str]) -> Any:
    """Troca os marcadores DENTRO dos valores ja parseados.

    Substituir no JSON cru quebraria com aspas ou barra invertida no prompt,
    que vem de song.toml e e' texto livre do autor. Uma passada so: marcador
    que aparecer no texto substituido fica literal, nao e' re-substituido.
    """
    if not mapping:
        return node
    pattern = re.compile("|".join(re.escape(k) for k in mapping))
    def walk(n: Any) -> Any:
        if isinstance(n, str):
            return pattern.sub(lambda m: mapping[m.group(0)], n)
        if isinstance(n, list):
            return [walk(x) for x in n]
        if isinstance(n, dict):
            return {k: walk(v) for k, v in n.items()}
        return n
    return walk(node)


def build_graph(template: str, prompt: str, seed: int, prefix: str) -> dict:
    """Template com marcadores -> grafo API pronto para POST /prompt."""
    # %seed% e' numero cru, entao sai no texto (valor nosso, nao do autor).
    graph = json.loads(template.replace("%seed%", str(int(seed))))
    graph = substitute(graph, {"%prompt%": prompt})
    # Armadilha do ComfyUI: grafo identico reenviado devolve execution_cached
    # com outputs vazios. O nonce no prefixo garante saida nova.
    nonce = next(_NONCE)
    for node in graph.values():
        if node.get("class_type") == "SaveImage":
            node["inputs"]["filename_prefix"] = f"{prefix}_{nonce}"
    return graph


def probe_url(url: str | None) -> str:
    """Resolve a URL pelo dono (o servidor), nao por suposicao."""
    candidates = [url] if url else [f"http://127.0.0.1:{p}" for p in PROBE_PORTS]
    for base in candidates:
        try:
            urllib.request.urlopen(f"{base}/system_stats", timeout=3).read()
            return base
        except Exception:
            continue
    raise SystemExit(
        "ComfyUI nao respondeu em " + ", ".join(candidates) +
        ". Suba o servidor ou passe --url."
    )


def submit(base: str, graph: dict, client_id: str = "keyframes_gen") -> str:
    body = json.dumps({"prompt": graph, "client_id": client_id}).encode()
    req = urllib.request.Request(f"{base}/prompt", body,
                                 {"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))["prompt_id"]
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"ComfyUI recusou o grafo: {exc.read().decode()[:600]}")


def collect_outputs(entry: dict) -> list[dict]:
    """Arquivos declarados por QUALQUER chave de output.

    Workflow de imagem devolve "images"; o de video devolve "gifs" ou
    "videos" conforme o no de save. Assumir "images" perde o video inteiro.
    """
    return [f
            for out in entry.get("outputs", {}).values()
            for files in out.values() if isinstance(files, list)
            for f in files if isinstance(f, dict) and "filename" in f]


def wait_outputs(base: str, pid: str, timeout_s: int,
                 poll: float = 2.0) -> list[dict]:
    """Devolve os arquivos REALMENTE declarados. status nao e' evidencia."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(poll)
        try:
            hist = json.load(urllib.request.urlopen(f"{base}/history/{pid}", timeout=20))
        except Exception:
            continue
        if pid in hist:
            return collect_outputs(hist[pid])
    return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera os keyframes de takes.json via ComfyUI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--url", default=None,
                        help="URL do ComfyUI. Ausente = sonda 8000/8001/8188.")
    parser.add_argument("--output-dir", type=Path, default=Path("C:/ComfyUI/output"),
                        help="Onde o ComfyUI grava as imagens.")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    takes_path = args.job_dir / "takes.json"
    if not takes_path.exists():
        print(f"takes.json ausente em {args.job_dir}. Rode takes_plan.py antes.",
              file=sys.stderr)
        return 1
    takes = json.loads(takes_path.read_text(encoding="utf-8")).get("takes", [])
    jobs = keyframe_jobs(takes)
    if not jobs:
        print("takes.json nao produziu nenhum keyframe.", file=sys.stderr)
        return 1
    if not args.workflow.exists():
        print(f"workflow ausente: {args.workflow}", file=sys.stderr)
        return 1

    template = args.workflow.read_text(encoding="utf-8")
    base = probe_url(args.url)
    dest = args.job_dir / "keyframes"
    dest.mkdir(parents=True, exist_ok=True)
    print(f"ComfyUI: {base}  |  {len(jobs)} keyframes  ->  {dest}")

    ok = 0
    t0 = time.time()
    for i, job in enumerate(jobs, 1):
        graph = build_graph(template, job["prompt"], job["seed"], job["id"])
        pid = submit(base, graph)
        files = wait_outputs(base, pid, args.timeout)
        if not files:
            print(f"  [{i}/{len(jobs)}] {job['id']}: SEM SAIDA (status nao e' evidencia)")
            continue
        src = args.output_dir / files[0]["filename"]
        if not src.exists():
            print(f"  [{i}/{len(jobs)}] {job['id']}: declarado {files[0]['filename']} mas nao esta em disco")
            continue
        shutil.copyfile(src, dest / f"{job['id']}.png")
        ok += 1
        print(f"  [{i}/{len(jobs)}] {job['id']} ({job['section']}) ok  {time.time() - t0:.0f}s")

    print(f"\n{ok}/{len(jobs)} keyframes gerados em {time.time() - t0:.0f}s")
    return 0 if ok == len(jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
