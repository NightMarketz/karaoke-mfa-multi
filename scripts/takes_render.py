"""
takes_render.py — Gera os MP4 dos takes via ComfyUI FLF2V numa maquina remota.

Segunda metade do handoff aberto por takes_plan.py. Roda NESTA maquina e fala
com o ComfyUI da maquina de video pela LAN: sobe os keyframes, submete um
grafo por take, baixa o MP4. A outra maquina precisa ter subido o ComfyUI com
--listen, senao so escuta 127.0.0.1 e nao ha o que alcancar.

Cada keyframe e' compartilhado por dois takes (o kf_out de um e' o kf_in do
seguinte), entao N takes custam N+1 uploads, nao 2N.

Evidencia: o disco e' da outra maquina, entao contar arquivo local nao serve.
A prova e' o ffprobe do MP4 baixado — a contagem de frames tem que bater com
generate_frames. Take curto envenena, em silencio, todas as emendas seguintes.

Uso:
    python scripts/takes_render.py --job-dir jobs/my-job --url http://192.168.0.42:8188
    python scripts/takes_render.py --job-dir jobs/my-job --url ... --concat

Le:
    jobs/{job_id}/takes.json
    jobs/{job_id}/keyframes/kf_000.png ...
    data/workflows/wan_flf2v.json  (marcadores %first% %last% %prompt%
                                    %negative% %seed% %frames%)
Escreve:
    jobs/{job_id}/takes/take_000.mp4 ...
    jobs/{job_id}/backdrop.mp4  (com --concat)
"""

from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.keyframes_gen import probe_url, submit, substitute, wait_outputs

DEFAULT_WORKFLOW = "data/workflows/wan_flf2v.json"
# Marcadores que o grafo exportado da outra maquina tem que carregar.
REQUIRED_MARKERS = ("%first%", "%last%", "%prompt%", "%negative%",
                    "%seed%", "%frames%")
# Marcadores numericos: saem no texto cru, antes do parse, porque o valor e'
# nosso (nao do autor) e precisa chegar ao grafo como numero, nao string.
_NUMERIC_MARKERS = ("%seed%", "%frames%")
_NONCE = itertools.count(int(time.time()))


def render_jobs(takes: list[dict]) -> list[dict]:
    """takes.json -> um job de video por take."""
    return [{
        "id": f"take_{int(t.get('idx', i)):03d}",
        "idx": int(t.get("idx", i)),
        "section": t.get("section", ""),
        "first": t["kf_in"],
        "last": t["kf_out"],
        "prompt": t.get("motion_prompt", ""),
        "negative": t.get("negative_prompt", ""),
        "frames": int(t.get("generate_frames", 81)),
        "fps": int(t.get("fps", 16)),
        "seed": 2000 + int(t.get("idx", i)),
    } for i, t in enumerate(takes)]


def build_graph(template: str, job: dict) -> dict:
    """Template com marcadores -> grafo API pronto para POST /prompt."""
    missing = [m for m in REQUIRED_MARKERS if m not in template]
    if missing:
        raise ValueError(
            "workflow sem os marcadores " + ", ".join(missing) +
            ". Exporte o grafo em API format e insira os marcadores."
        )
    raw = template
    for marker, value in (("%seed%", job["seed"]), ("%frames%", job["frames"])):
        raw = raw.replace(marker, str(int(value)))
    graph = json.loads(raw)
    graph = substitute(graph, {
        "%first%": job["first"],
        "%last%": job["last"],
        "%prompt%": job["prompt"],
        "%negative%": job["negative"],
    })
    # Armadilha do ComfyUI: grafo identico reenviado devolve execution_cached
    # com outputs vazios. O nonce no prefixo garante saida nova.
    nonce = next(_NONCE)
    for node in graph.values():
        inputs = node.get("inputs", {})
        if "filename_prefix" in inputs:
            inputs["filename_prefix"] = f"{job['id']}_{nonce}"
    return graph


def _fmt(seconds: float) -> str:
    """6 casas e' a precisao com que takes_plan.py ja gravou os tempos."""
    return f"{seconds:.6f}".rstrip("0").rstrip(".") or "0"


def splice_offsets(takes: list[dict]) -> list[float]:
    """Onde cada emenda comeca, em segundos desde o inicio do primeiro take.

    Sai do start ABSOLUTO de takes.json, nao de k x slot: o ultimo take de uma
    secao e' trimmed (ocupa menos que o slot) e o slot uniforme empurraria
    todos os takes seguintes pra frente, desalinhando da letra.
    """
    if len(takes) < 2:
        return []
    t0 = float(takes[0]["start"])
    return [round(float(t["start"]) - t0, 6) for t in takes[1:]]


def find_gaps(takes: list[dict]) -> list[dict]:
    """Emendas que o material gerado nao alcanca (intervalo instrumental).

    Um take rende take_frames; a emenda consome overlap_frames. Se o proximo
    take comeca depois de (take_frames - overlap_frames)/fps, faltam frames e
    montar em silencio encurtaria o video contra a letra.
    """
    gaps: list[dict] = []
    for prev, cur in zip(takes, takes[1:]):
        fps = int(cur.get("fps", 16))
        slot = (int(cur.get("generate_frames", 81))
                - int(cur.get("overlap_frames", 4))) / fps
        spacing = float(cur["start"]) - float(prev["start"])
        if spacing - slot > 1e-6:
            gaps.append({"after_idx": int(prev.get("idx", 0)),
                         "seconds": round(spacing - slot, 6)})
    return gaps


def concat_filter(offsets: list[float], duration: float) -> str:
    """filter_complex: um xfade por emenda, encadeado cabeca-com-cauda."""
    if not offsets:
        return ""
    parts, prev = [], "[0:v]"
    for i, offset in enumerate(offsets, start=1):
        label = f"[v{i}]"
        parts.append(f"{prev}[{i}:v]xfade=transition=fade:"
                     f"duration={_fmt(duration)}:offset={_fmt(offset)}{label}")
        prev = label
    return ";".join(parts)


def _ffprobe(path: Path, entries: str) -> str:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
             "-show_entries", entries, "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def probe_frames(path: Path) -> int:
    """Conta os frames DECODIFICANDO. -1 se o ffprobe nao conseguiu ler.

    nb_frames do container mente ou vem N/A conforme o muxer; -count_frames
    custa alguns ms num clipe de 81 frames e nao mente.
    """
    value = _ffprobe(path, "stream=nb_read_frames").split(",")[0].strip()
    return int(value) if value.isdigit() else -1


def probe_fps(path: Path) -> float:
    """fps real do stream. -1.0 se nao deu para ler."""
    value = _ffprobe(path, "stream=r_frame_rate").split(",")[0].strip()
    try:
        num, _, den = value.partition("/")
        return int(num) / int(den or 1)
    except (ValueError, ZeroDivisionError):
        return -1.0


def verify_take(path: Path, expected_frames: int,
                expected_fps: int | None = None) -> str | None:
    """None se o take serve. Senao, a razao — com os dois numeros.

    O disco e' da outra maquina, entao o status do ComfyUI nao e' evidencia:
    a prova e' o arquivo baixado, decodificado aqui.
    """
    path = Path(path)
    if not path.exists():
        return f"{path.name}: nao chegou em disco"
    if path.stat().st_size == 0:
        return f"{path.name}: 0 bytes"
    got = probe_frames(path)
    if got < 0:
        return f"{path.name}: ffprobe nao leu video nenhum"
    if got != expected_frames:
        return f"{path.name}: {got} frames, esperado {expected_frames}"
    if expected_fps is not None:
        fps = probe_fps(path)
        # O fps mora em takes.json E no no CreateVideo do workflow. Discordando,
        # a contagem de frames ainda bate e so a montagem sai desalinhada.
        if abs(fps - expected_fps) > 1e-6:
            return (f"{path.name}: {fps:g} fps, esperado {expected_fps} "
                    "(o no CreateVideo do workflow discorda de takes.json)")
    return None


def check_models(graph: dict, object_info: dict) -> list[str]:
    """Confere os nomes de arquivo do grafo contra o que a maquina remota tem.

    Os nomes vieram do template oficial, nao da maquina que vai rodar: melhor
    cobrar antes do que descobrir no primeiro take, depois da fila inteira.
    """
    problemas = []
    for nid, node in graph.items():
        cls = node.get("class_type", "")
        info = object_info.get(cls)
        if info is None:
            problemas.append(f"no {nid}: a maquina remota nao conhece {cls}")
            continue
        required = info.get("input", {}).get("required", {})
        for name, value in node.get("inputs", {}).items():
            spec = required.get(name)
            # Enum chega como [[opcao, ...], {...}]; texto livre, como ["STRING", ...].
            if not (isinstance(spec, list) and spec and isinstance(spec[0], list)):
                continue
            opcoes = spec[0]
            if isinstance(value, str) and value not in opcoes:
                amostra = ", ".join(map(str, opcoes[:8])) or "nenhuma"
                problemas.append(
                    f"no {nid} ({cls}.{name}): {value} nao existe la. "
                    f"{len(opcoes)} disponivel(is): {amostra}")
    return problemas


def upload_image(base: str, path: Path) -> str:
    """Sobe um keyframe e devolve o nome que o ComfyUI reportou.

    O nome vem do servidor, nao do nosso palpite: ele desambigua colisao
    acrescentando sufixo, e usar o nome local carregaria a imagem errada.
    """
    boundary = "----takesrender"
    head = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
            "Content-Type: image/png\r\n\r\n").encode()
    tail = (f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'
            f"--{boundary}--\r\n").encode()
    req = urllib.request.Request(
        f"{base}/upload/image", head + path.read_bytes() + tail,
        {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        info = json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"upload de {path.name} recusado: {exc.read().decode()[:400]}")
    sub = info.get("subfolder", "")
    return f"{sub}/{info['name']}" if sub else info["name"]


def download(base: str, ref: dict, dest: Path) -> None:
    """Baixa um arquivo declarado pelo /history via /view."""
    query = urllib.parse.urlencode({
        "filename": ref["filename"],
        "subfolder": ref.get("subfolder", ""),
        "type": ref.get("type", "output"),
    })
    with urllib.request.urlopen(f"{base}/view?{query}", timeout=600) as resp:
        dest.write_bytes(resp.read())


def fetch_object_info(base: str) -> dict:
    """O que a maquina remota realmente tem instalado."""
    try:
        return json.load(urllib.request.urlopen(f"{base}/object_info", timeout=120))
    except Exception as exc:
        raise SystemExit(f"/object_info nao respondeu em {base}: {exc}")


def render_all(base: str, jobs: list[dict], *, template: str, kf_dir: Path,
               dest: Path, timeout: int = 1800, poll: float = 2.0,
               log=print) -> tuple[int, list[str]]:
    """Gera cada take na maquina remota. Devolve (ok, motivos de falha)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    uploaded: dict[str, str] = {}
    ok, failures = 0, []
    t0 = time.time()
    for i, job in enumerate(jobs, 1):
        tag = f"[{i}/{len(jobs)}] {job['id']}"
        done = next((p for p in sorted(dest.glob(f"{job['id']}.*"))
                     if p.suffix != ".part"
                     and verify_take(p, job["frames"],
                                     expected_fps=job.get("fps")) is None), None)
        if done is not None:
            ok += 1
            log(f"  {tag}: ja estava pronto, pulado")
            continue
        for slot in ("first", "last"):
            kf = job[slot]
            if kf not in uploaded:
                src = Path(kf_dir) / f"{kf}.png"
                if not src.exists():
                    failures.append(f"{job['id']}: keyframe ausente {src}")
                    break
                uploaded[kf] = upload_image(base, src)
        else:
            graph = build_graph(template, {**job,
                                           "first": uploaded[job["first"]],
                                           "last": uploaded[job["last"]]})
            pid = submit(base, graph, client_id="takes_render")
            files = wait_outputs(base, pid, timeout, poll=poll)
            if not files:
                failures.append(f"{job['id']}: sem saida (status nao e' evidencia)")
                log(f"  {tag}: SEM SAIDA")
                continue
            part = dest / f"{job['id']}.part"
            download(base, files[0], part)
            reason = verify_take(part, job["frames"], expected_fps=job.get("fps"))
            if reason:
                # Nao deixa o reprovado em disco: na proxima rodada ele
                # pareceria pronto e envenenaria a montagem em silencio.
                part.unlink(missing_ok=True)
                failures.append(reason)
                log(f"  {tag}: RECUSADO — {reason}")
                continue
            final = dest / f"{job['id']}{Path(files[0]['filename']).suffix or '.mp4'}"
            part.replace(final)
            ok += 1
            log(f"  {tag} ({job['section']}) ok  {time.time() - t0:.0f}s")
            continue
        log(f"  {tag}: {failures[-1]}")
    return ok, failures


def montage(clips: list[Path], takes: list[dict], out: Path) -> str | None:
    """Emenda os takes com xfade. None se montou; senao, a razao.

    Recusa buraco: se o proximo take comeca depois do material que o anterior
    rende, emendar em silencio encurta o video contra a letra — que e' a
    deriva que a aritmetica de takes_plan.py existe para evitar.
    """
    out = Path(out)
    clips = [Path(c) for c in clips]
    if len(clips) != len(takes):
        return f"{len(clips)} clipes para {len(takes)} takes"
    faltando = [c.name for c in clips if not c.exists()]
    if faltando:
        return "clipe ausente: " + ", ".join(faltando)
    gaps = find_gaps(takes)
    if gaps:
        detalhe = ", ".join(f"depois do take {g['after_idx']}: {g['seconds']:.3f}s"
                            for g in gaps)
        return (f"{len(gaps)} buraco(s) sem take gerado ({detalhe}). "
                "Emendar assim desalinharia o video da letra.")
    fps = int(takes[0].get("fps", 16))
    overlap = int(takes[0].get("overlap_frames", 4))
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for clip in clips:
        cmd += ["-i", str(clip)]
    graph = concat_filter(splice_offsets(takes), overlap / fps)
    if graph:
        cmd += ["-filter_complex", graph, "-map", f"[v{len(clips) - 1}]"]
    cmd += ["-r", str(fps), "-pix_fmt", "yuv420p", str(out)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"ffmpeg falhou: {exc}"
    if proc.returncode != 0:
        out.unlink(missing_ok=True)
        return f"ffmpeg saiu {proc.returncode}: {proc.stderr.strip()[:400]}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera os MP4 dos takes via ComfyUI FLF2V remoto.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--workflow", type=Path, default=Path(DEFAULT_WORKFLOW))
    parser.add_argument("--url", default=None,
                        help="URL do ComfyUI da maquina de video "
                             "(ex.: http://192.168.0.42:8188). Ausente = sonda "
                             "esta maquina, que quase nunca e' o que voce quer.")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="Por take. Video demora muito mais que imagem.")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Nao conferir os nomes de modelo contra a maquina.")
    parser.add_argument("--concat", action="store_true",
                        help="Depois de gerar, emenda tudo em backdrop.mp4.")
    args = parser.parse_args()

    takes_path = args.job_dir / "takes.json"
    if not takes_path.exists():
        print(f"takes.json ausente em {args.job_dir}. Rode takes_plan.py antes.",
              file=sys.stderr)
        return 1
    takes = json.loads(takes_path.read_text(encoding="utf-8")).get("takes", [])
    jobs = render_jobs(takes)
    if not jobs:
        print("takes.json nao produziu nenhum take.", file=sys.stderr)
        return 1
    if not args.workflow.exists():
        print(f"workflow ausente: {args.workflow}\n"
              "Exporte o grafo FLF2V em API format na maquina de video e "
              "insira os marcadores " + " ".join(REQUIRED_MARKERS),
              file=sys.stderr)
        return 1

    template = args.workflow.read_text(encoding="utf-8")
    kf_dir = args.job_dir / "keyframes"
    dest = args.job_dir / "takes"
    base = probe_url(args.url)
    print(f"ComfyUI: {base}  |  {len(jobs)} takes  ->  {dest}")

    # Os nomes de modelo do grafo vieram do template oficial, nao desta
    # maquina. Cobrar agora custa uma chamada; descobrir depois custa a fila.
    if not args.skip_preflight:
        problemas = check_models(build_graph(template, jobs[0]),
                                 fetch_object_info(base))
        if problemas:
            print(f"preflight reprovou {len(problemas)} no(s):", file=sys.stderr)
            for linha in problemas:
                print(f"  {linha}", file=sys.stderr)
            print("Ajuste os nomes em " + str(args.workflow) +
                  " ou passe --skip-preflight.", file=sys.stderr)
            return 1

    ok, failures = render_all(base, jobs, template=template, kf_dir=kf_dir,
                              dest=dest, timeout=args.timeout)
    print(f"\n{ok}/{len(jobs)} takes prontos")
    for reason in failures:
        print(f"  falhou: {reason}")
    if ok != len(jobs):
        return 1
    if not args.concat:
        return 0

    clips = [next(iter(sorted(dest.glob(f"{j['id']}.*"))), dest / f"{j['id']}.mp4")
             for j in jobs]
    out = args.job_dir / "backdrop.mp4"
    reason = montage(clips, takes, out)
    if reason:
        print(f"montagem recusada: {reason}", file=sys.stderr)
        return 1
    # Re-derivacao por outro caminho: o que o arquivo tem contra o que a
    # aritmetica dos takes previa. Se nao fecha, o numero acima e' opiniao.
    fps = int(takes[0].get("fps", 16))
    offsets = splice_offsets(takes)
    esperado = round((offsets[-1] if offsets else 0.0) * fps) + int(
        takes[0].get("generate_frames", 81))
    medido = probe_frames(out)
    print(f"{out}: {medido} frames medidos, {esperado} previstos "
          f"({medido / fps:.2f}s)")
    if medido != esperado:
        print("montagem nao fecha com a aritmetica dos takes.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
