"""
teste_loop_fundo.py — bancada: imagem de fundo -> loop Wan -> GIF, com medicao.

Responde, com numero e tira de contato, se um fundo animado em loop serve para
o karaoke: o loop fecha? a faixa da legenda "respira"? quanto custa?

    # 1) gera a imagem (SD1.5 + LoRA) e anima
    python scripts/teste_loop_fundo.py --ckpt <checkpoint_sd15.safetensors> \
        --lora fengjing.safetensors --prompt "anime landscape, night city, rain"

    # 2) so anima uma imagem que ja existe
    python scripts/teste_loop_fundo.py --image work/algum_fundo.png

Saida em work/teste_loop/<carimbo>/: base.png, frames/, loop.mp4, loop.gif,
contato.png e relatorio.json.

O loop fecha por CONSTRUCAO (mesma imagem em start_image e end_image do
WanFirstLastFrameToVideo — README, "medido e descartado"). O modelo alto e o
SmoothMix dos workflows SVI do Civitai; o laco "循环" daqueles workflows
encadeia cenas num video longo e NAO fecha loop, por isso o grafo deles nao
e usado aqui — so os pesos.

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

from karaoke.background import (COMFY_OUTPUT_ROOT, _bust_cache, _diagnostico,
                                _post_json, resolve_comfy_host)

RAIZ = Path(__file__).resolve().parent.parent
WF_IMAGEM = RAIZ / "config" / "comfy_workflow_sd15_lora.json"
WF_LOOP = RAIZ / "config" / "comfy_workflow_wan_loop_smooth.json"
SAIDA = RAIZ / "work" / "teste_loop"

HIGH_MODEL = "smoothMixWan2214BI2V_i2vV20High.safetensors"
# SmoothMix ja vem destilado: no workflow SVI original a alta nao leva
# lightx2v. O no de LoRA fica no grafo com peso 0 para dar para ligar sem
# reeditar o JSON (--high-lora-w 1).
HIGH_LORA = "lightx2v_I2V_14B_480p_cfg_step_distill_rank128_bf16.safetensors"

# Movimento LOCAL: a tentativa anterior pediu "ambiente" e saiu rampa global
# de brilho (pico 63/255), que faz a legenda respirar.
PROMPT_MOVIMENTO = ("static camera, locked shot, gentle drifting clouds, "
                    "softly rippling water, falling rain, flickering distant "
                    "lights, constant lighting, calm seamless loop")

FPS = 16            # fps nativo do Wan
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


def _src(img: dict) -> Path:
    return COMFY_OUTPUT_ROOT / img.get("type", "output") / img.get("subfolder", "") / img["filename"]


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
    ap.add_argument("--lora", default="fengjing.safetensors")
    ap.add_argument("--lora-w", type=float, default=0.8)
    ap.add_argument("--prompt", default="anime landscape, scenery, wide shot, "
                    "night sky, lake reflection, soft light, no humans, masterpiece")
    ap.add_argument("--movimento", default=PROMPT_MOVIMENTO)
    ap.add_argument("--frames", type=int, default=49, help="4k+1: 33, 49, 81")
    ap.add_argument("--width", type=int, default=832)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--high-model", default=HIGH_MODEL)
    ap.add_argument("--high-lora-w", type=float, default=0.0)
    ap.add_argument("--gif-width", type=int, default=640)
    a = ap.parse_args()

    if (a.frames - 1) % 4:
        sys.exit("--frames tem de ser 4k+1 (33, 49, 81): o VAE do Wan comprime 4 quadros")
    if not a.image and not a.ckpt:
        sys.exit("passe --image <png> ou --ckpt <checkpoint SD1.5>")

    pasta = SAIDA / datetime.now().strftime("%Y%m%d_%H%M%S")
    (pasta / "frames").mkdir(parents=True)
    host = resolve_comfy_host()
    rel = {"host": host, "args": vars(a)}
    print(f"  host: {host} -> {pasta}")

    base = pasta / "base.png"
    if a.image:
        shutil.copy2(a.image, base)
    else:
        grafo = preencher(WF_IMAGEM.read_text(encoding="utf-8"), {
            "seed": uuid.uuid4().int % 2 ** 32, "ckpt": a.ckpt, "lora": a.lora,
            "lora_w": a.lora_w, "prompt": a.prompt})
        imgs, dt = rodar(host, grafo, limite_s=600)
        shutil.copy2(_src(imgs[0]), base)
        rel["imagem_s"] = round(dt, 1)
        print(f"  imagem: {dt:.0f}s")

    nome_input = f"teste_loop_{uuid.uuid4().hex[:8]}.png"
    shutil.copy2(base, COMFY_OUTPUT_ROOT / "input" / nome_input)
    grafo = preencher(WF_LOOP.read_text(encoding="utf-8"), {
        "seed": uuid.uuid4().int % 2 ** 32, "high_model": a.high_model,
        "high_lora": HIGH_LORA, "high_lora_w": a.high_lora_w,
        "prompt": a.movimento, "image": nome_input,
        "width": a.width, "height": a.height, "length": a.frames})
    print(f"  loop: {a.width}x{a.height}, {a.frames} quadros, alta={a.high_model}")
    imgs, dt = rodar(host, grafo, limite_s=3600)
    for i, img in enumerate(imgs):
        shutil.copy2(_src(img), pasta / "frames" / f"f_{i:04d}.png")
    rel.update(loop_s=round(dt, 1), quadros=len(imgs),
               s_por_quadro=round(dt / max(len(imgs), 1), 2))
    print(f"  MEDIDO: {len(imgs)} quadros em {dt:.0f}s ({rel['s_por_quadro']}s/quadro)")

    # WanFirstLastFrame devolve o ultimo quadro == primeiro. No loop ele
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
