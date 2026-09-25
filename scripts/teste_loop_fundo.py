"""
teste_loop_fundo.py — bancada: imagem de fundo -> loop MiniMax-H3 -> GIF, com medicao.

Responde, com numero e tira de contato, se um fundo animado em loop serve para
o karaoke: o loop fecha? a faixa da legenda "respira"? quanto custa?

    # 1) gera a imagem (SD1.5 + LoRA) e anima
    python scripts/teste_loop_fundo.py --ckpt <checkpoint_sd15.safetensors> \
        --lora fengjing.safetensors --prompt "anime landscape, night city, rain"

    # 1b) qualquer template de imagem so com %prompt%/%seed% (formato do 08b)
    python scripts/teste_loop_fundo.py --workflow config/comfy_workflow_one_obsession.json \
        --prompt "scenery, no humans, night, lake, starry sky, moon, reflection"

    # 2) so anima uma imagem que ja existe
    python scripts/teste_loop_fundo.py --image work/algum_fundo.png

Saida em work/teste_loop/<carimbo>/: base.png, frames/, loop.mp4, loop.gif,
contato.png e relatorio.json.

Roda no ComfyUI de C:/rk (ROCm): o Desktop nao tem os nos locais do H3 e
fixa 28 blocos no Anima, o que quebra o One Obsession (36 blocos). Suba com
os modelos de C:/ComfyUI/models:

    C:
kenv-rocm\Scripts\python.exe C:
k\ComfyUI\main.py <flags do C:
k
un_comfy.ps1>         --extra-model-paths-config config/comfy_extra_model_paths_rk.yaml

O loop fecha por CONSTRUCAO: a imagem base e ancorada (MiniMaxH3AddGuide) no
primeiro e no ultimo quadro, e tambem em 31/62/93 — so as pontas deixavam a
camera fazer panoramica e a faixa da legenda respirar 26/255 (medido).

Os numeros sao triagem. Quem decide e a tira de contato, a olho (guia §2.7).
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

from karaoke.background import (_bust_cache, _diagnostico, _post_json,
                                resolve_comfy_host)

RAIZ = Path(__file__).resolve().parent.parent
WF_IMAGEM = RAIZ / "config" / "comfy_workflow_sd15_lora.json"
WF_LOOP = RAIZ / "config" / "comfy_workflow_h3_loop_ref2va.json"
# Pasta do ComfyUI que roda o H3 (input/ e output/ saem dela).
COMFY_DIR = Path(os.environ.get("COMFYUI_DIR", "C:/rk/ComfyUI"))
SAIDA = RAIZ / "work" / "teste_loop"

# Movimento LOCAL: a tentativa anterior pediu "ambiente" e saiu rampa global
# de brilho (pico 63/255), que faz a legenda respirar.
PROMPT_MOVIMENTO = ("<Picture 1> static camera, locked-off shot. Gentle ripples, "
                    "drifting clouds, softly flickering distant lights, constant "
                    "lighting. Calm night, no people, no text.")

FPS = 24            # fps nativo do H3
FAIXA_LEGENDA = (0.62, 0.92)   # fracao da altura onde a legenda do ASS mora
RAZAO_EMENDA_MAX = 1.5         # mesmo limite do make_loop_gif --forward


def preencher(template: str, valores: dict) -> dict:
    """Troca %chave% no TEXTO do template e devolve o grafo parseado.

    Strings entram escapadas (sem aspas proprias, o template ja as tem);
    numeros entram crus. Marcador que sobrar e erro: um valor esquecido
    viraria um grafo quebrado que o ComfyUI rejeita longe daqui.
    """
    texto = template
    for k, v in valores.items():
        marca = f"%{k}%"
        if marca not in texto:
            raise ValueError(f"template sem o marcador {marca}")
        texto = texto.replace(marca, json.dumps(v)[1:-1] if isinstance(v, str) else str(v))
    if "%" in texto:
        import re
        sobra = sorted(set(re.findall(r"%[a-z_]+%", texto)))
        if sobra:
            raise ValueError(f"marcadores sem valor: {sobra}")
    return json.loads(texto)


def rodar(host: str, grafo: dict, limite_s: int) -> tuple:
    """Enfileira, espera e devolve (imagens de saida, segundos)."""
    _bust_cache(grafo)
    t0 = time.monotonic()
    pid = _post_json(f"{host}/prompt", {"prompt": grafo}, timeout=60)["prompt_id"]
    import urllib.request
    while time.monotonic() - t0 < limite_s:
        with urllib.request.urlopen(f"{host}/history/{pid}", timeout=30) as r:
            hist = json.loads(r.read())
        if pid in hist:
            entrada = hist[pid] or {}
            imgs = [i for no in (entrada.get("outputs") or {}).values()
                    for i in (no or {}).get("images", [])]
            if not imgs:
                raise RuntimeError("ComfyUI terminou sem saida — " + _diagnostico(entrada))
            return imgs, time.monotonic() - t0
        time.sleep(3)
    raise TimeoutError(f"nao terminou em {limite_s}s")


def grade_h3(n: int) -> bool:
    """17k+5 (grade do H3) e > 93, a ultima ancora fixa do grafo: 107, 124, 141..."""
    return n > 93 and n % 17 == 5


def _src(img: dict) -> Path:
    return COMFY_DIR / img.get("type", "output") / img.get("subfolder", "") / img["filename"]


def medir(frames) -> dict:
    """frames: array (n, h, w, 3) float. Emenda e brilho da faixa da legenda.

    emenda/vizinhos e o predicado do make_loop_gif --forward, ja visto
    vermelho em material quebrado (3,87 e 1,56 reprovados). A faixa da
    legenda mede a "respiracao": variacao do brilho medio ao longo do loop.
    """
    import numpy as np
    viz = float(np.abs(np.diff(frames, axis=0)).mean())
    emenda = float(np.abs(frames[-1] - frames[0]).mean())
    h = frames.shape[1]
    a, b = int(h * FAIXA_LEGENDA[0]), int(h * FAIXA_LEGENDA[1])
    luma = frames[:, a:b].mean(axis=(1, 2, 3))
    return {
        "vizinhos": round(viz, 3),
        "emenda": round(emenda, 3),
        "razao_emenda": round(emenda / viz, 2) if viz else None,
        "fecha": bool(viz and emenda / viz <= RAZAO_EMENDA_MAX),
        "faixa_legenda_luma_min": round(float(luma.min()), 1),
        "faixa_legenda_luma_max": round(float(luma.max()), 1),
        "faixa_legenda_respiracao": round(float(luma.max() - luma.min()), 1),
    }


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--image", help="pula a geracao e anima esta imagem")
    ap.add_argument("--ckpt", help="checkpoint SD1.5 (nome em models/checkpoints)")
    ap.add_argument("--workflow", help="template de imagem com so %%prompt%%/%%seed%% "
                    "(ex.: config/comfy_workflow_one_obsession.json)")
    ap.add_argument("--lora", default="fengjing.safetensors")
    ap.add_argument("--lora-w", type=float, default=0.8)
    ap.add_argument("--prompt", default="anime landscape, scenery, wide shot, "
                    "night sky, lake reflection, soft light, no humans, masterpiece")
    ap.add_argument("--movimento", default=PROMPT_MOVIMENTO)
    ap.add_argument("--frames", type=int, default=124, help="17k+5: 107, 124, 141")
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=576)
    ap.add_argument("--gif-width", type=int, default=640)
    a = ap.parse_args()

    if not grade_h3(a.frames):
        sys.exit("--frames tem de ser 17k+5 (107, 124, 141): grade do H3")
    if not (a.image or a.ckpt or a.workflow):
        sys.exit("passe --image <png>, --ckpt <checkpoint SD1.5> ou --workflow <template>")

    pasta = SAIDA / datetime.now().strftime("%Y%m%d_%H%M%S")
    (pasta / "frames").mkdir(parents=True)
    host = resolve_comfy_host()
    rel = {"host": host, "args": vars(a)}
    print(f"  host: {host} -> {pasta}")

    base = pasta / "base.png"
    if a.image:
        shutil.copy2(a.image, base)
    else:
        if a.workflow:
            grafo = preencher(Path(a.workflow).read_text(encoding="utf-8"), {
                "seed": uuid.uuid4().int % 2 ** 32, "prompt": a.prompt})
        else:
            grafo = preencher(WF_IMAGEM.read_text(encoding="utf-8"), {
                "seed": uuid.uuid4().int % 2 ** 32, "ckpt": a.ckpt, "lora": a.lora,
                "lora_w": a.lora_w, "prompt": a.prompt})
        imgs, dt = rodar(host, grafo, limite_s=600)
        shutil.copy2(_src(imgs[0]), base)
        rel["imagem_s"] = round(dt, 1)
        print(f"  imagem: {dt:.0f}s")

    nome_input = f"teste_loop_{uuid.uuid4().hex[:8]}.png"
    shutil.copy2(base, COMFY_DIR / "input" / nome_input)
    grafo = preencher(WF_LOOP.read_text(encoding="utf-8"), {
        "seed": uuid.uuid4().int % 2 ** 32,
        "prompt": a.movimento, "image": nome_input,
        "width": a.width, "height": a.height, "length": a.frames})
    print(f"  loop H3: {a.width}x{a.height}, {a.frames} quadros")
    imgs, dt = rodar(host, grafo, limite_s=3600)
    for i, img in enumerate(imgs):
        shutil.copy2(_src(img), pasta / "frames" / f"f_{i:04d}.png")
    rel.update(loop_s=round(dt, 1), quadros=len(imgs),
               s_por_quadro=round(dt / max(len(imgs), 1), 2))
    print(f"  MEDIDO: {len(imgs)} quadros em {dt:.0f}s ({rel['s_por_quadro']}s/quadro)")

    # A ancora em -1 faz o ultimo quadro == primeiro. No loop ele
    # apareceria duas vezes seguidas (um "soluco"): corta o ultimo.
    import numpy as np
    from PIL import Image
    arqs = sorted((pasta / "frames").glob("f_*.png"))[:-1]
    fr = np.stack([np.asarray(Image.open(p).convert("RGB"), dtype=np.float32) for p in arqs])
    rel["medidas"] = medir(fr)

    lista = pasta / "lista.txt"
    lista.write_text("".join(f"file '{p.as_posix()}'\nduration {1/FPS:.5f}\n" for p in arqs))
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(lista), "-r", str(FPS),
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(pasta / "loop.mp4"))
    # Uma volta so: o GIF loopa sozinho (-loop 0); repetir no arquivo triplicava
    # o tamanho (7,4 MB no ensaio) sem mostrar nada novo.
    ffmpeg("-i", str(pasta / "loop.mp4"), "-filter_complex",
           f"scale={a.gif_width}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
           f"[b][p]paletteuse=dither=bayer:bayer_scale=4", "-loop", "0", str(pasta / "loop.gif"))
    # Tira de contato: 8 quadros espalhados + a emenda (ultimo | primeiro) no fim.
    idx = sorted(set(np.linspace(0, len(arqs) - 1, 8).astype(int).tolist()))
    tiles = [Image.open(arqs[i]).resize((320, 320 * fr.shape[1] // fr.shape[2])) for i in idx]
    tiles += [Image.open(arqs[-1]).resize(tiles[0].size), Image.open(arqs[0]).resize(tiles[0].size)]
    folha = Image.new("RGB", (tiles[0].width * 5, tiles[0].height * 2))
    for k, t in enumerate(tiles):
        folha.paste(t, ((k % 5) * t.width, (k // 5) * t.height))
    folha.save(pasta / "contato.png")

    (pasta / "relatorio.json").write_text(json.dumps(rel, indent=2, ensure_ascii=False))
    m = rel["medidas"]
    print(f"  emenda: razao {m['razao_emenda']} (limite {RAZAO_EMENDA_MAX}) -> "
          f"{'fecha' if m['fecha'] else 'NAO FECHA'}")
    print(f"  faixa da legenda: brilho {m['faixa_legenda_luma_min']}..{m['faixa_legenda_luma_max']} "
          f"(respiracao {m['faixa_legenda_respiracao']}/255)")
    print(f"  gif: {pasta / 'loop.gif'} ({(pasta / 'loop.gif').stat().st_size / 2**20:.1f} MB)")
    print("  decida pela contato.png: 2 ultimos quadros sao a emenda (ultimo | primeiro)")


if __name__ == "__main__":
    main()
