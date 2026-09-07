"""
medir_loop_wan.py — mede o caminho rapido do WAN 2.2 (LoRA LightX2V, 4 passos).

Bancada, nao estagio: responde "quanto custa um loop de 81 frames nesta
maquina" com numero medido, e verifica se o loop DE FATO fecha.

    python scripts/medir_loop_wan.py work/cenas_publi/1_anzol-verde_seed.png

A tecnica do loop e alimentar a MESMA imagem em start_image e end_image do
WanFirstLastFrameToVideo — o fechamento e por construcao, nao por sorte.
"""
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from karaoke.background import _post_json, resolve_comfy_host

RAIZ = Path(__file__).resolve().parent.parent
WORKFLOW = RAIZ / "config" / "comfy_workflow_wan_loop.json"
COMFY = Path("C:/ComfyUI")
SAIDA = RAIZ / "work" / "loop_wan"

# Movimento ambiente: o fundo nao pode roubar a atencao da letra. Camera parada
# e o ponto — o negativo do workflow ja empurra contra pan/zoom.
PROMPT = ("subtle ambient motion, static camera, gentle flicker of the screen "
          "light, slow drifting dust, curtain swaying slightly in a draft, "
          "calm looping atmosphere")


def _ver_frames(host: str, prompt_id: str, limite_s: int) -> list:
    """Espera a fila e devolve TODOS os frames, na ordem em que sairam."""
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim:
        with urllib.request.urlopen(f"{host}/history/{prompt_id}", timeout=30) as r:
            hist = json.loads(r.read())
        if prompt_id in hist:
            entrada = hist[prompt_id] or {}
            imgs = [i for no in (entrada.get("outputs") or {}).values()
                    for i in (no or {}).get("images", [])]
            if not imgs:
                status = entrada.get("status") or {}
                raise RuntimeError(f"terminou sem frames — {status}")
            return imgs
        time.sleep(3)
    raise TimeoutError(f"nao terminou em {limite_s}s")


def main():
    if len(sys.argv) < 2:
        print("uso: medir_loop_wan.py <imagem-da-cena.png>")
        sys.exit(2)
    cena = Path(sys.argv[1])
    if not cena.exists():
        print(f"ERRO: {cena} nao existe")
        sys.exit(1)

    SAIDA.mkdir(parents=True, exist_ok=True)
    # O LoadImage le por basename de C:/ComfyUI/input — nome unico evita
    # colisao com qualquer coisa que ja esteja la.
    nome_input = f"karaoke_{uuid.uuid4().hex[:8]}_{cena.name}"
    shutil.copy2(cena, COMFY / "input" / nome_input)

    texto = WORKFLOW.read_text(encoding="utf-8")
    texto = texto.replace("%seed%", str(uuid.uuid4().int % (2 ** 32)))
    texto = texto.replace("%image%", nome_input)
    texto = texto.replace("%prompt%", json.dumps(PROMPT)[1:-1])
    grafo = json.loads(texto)
    grafo["9"]["inputs"]["filename_prefix"] = f"karaoke_loop_{uuid.uuid4().hex[:8]}"

    host = resolve_comfy_host()
    print(f"  host: {host} | fonte: {cena.name}")
    print(f"  {grafo['67']['inputs']['width']}x{grafo['67']['inputs']['height']}, "
          f"{grafo['67']['inputs']['length']} frames, "
          f"{grafo['57']['inputs']['steps']} passos (LoRA LightX2V)")

    t0 = time.monotonic()
    corpo = _post_json(f"{host}/prompt", {"prompt": grafo}, timeout=60)
    frames = _ver_frames(host, corpo["prompt_id"], limite_s=3600)
    dt = time.monotonic() - t0

    destino = SAIDA / "frames"
    shutil.rmtree(destino, ignore_errors=True)
    destino.mkdir(parents=True)
    for i, img in enumerate(frames):
        src = (COMFY / img.get("type", "output")
               / img.get("subfolder", "") / img["filename"])
        shutil.copy2(src, destino / f"f_{i:04d}.png")

    print(f"  MEDIDO: {len(frames)} frames em {dt:.0f}s "
          f"({dt / max(len(frames), 1):.2f}s por frame)")

    mp4 = SAIDA / "loop.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-framerate", "16",
         "-i", str(destino / "f_%04d.png"),
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", str(mp4)], check=True)
    print(f"  video: {mp4} ({mp4.stat().st_size / 2**20:.1f} MB, "
          f"{len(frames) / 16:.2f}s a 16fps)")

    # A verificacao que importa: o loop FECHA? Compara o ultimo frame com o
    # primeiro. Se a emenda for visivel, o efeito inteiro se perde.
    try:
        import numpy as np
        from PIL import Image
        a = np.asarray(Image.open(destino / "f_0000.png").convert("RGB"), dtype=float)
        z = np.asarray(Image.open(destino / f"f_{len(frames)-1:04d}.png").convert("RGB"), dtype=float)
        m = np.asarray(Image.open(destino / f"f_{len(frames)//2:04d}.png").convert("RGB"), dtype=float)
        d_loop = np.abs(a - z).mean()
        d_meio = np.abs(a - m).mean()
        print(f"  emenda do loop: |primeiro - ultimo| = {d_loop:.2f}/255")
        print(f"  controle:       |primeiro - meio|   = {d_meio:.2f}/255")
        print("  -> o loop fecha" if d_loop < d_meio / 2 else
              "  -> ATENCAO: emenda tao grande quanto o movimento; loop nao fecha")
    except ImportError:
        print("  (sem numpy/PIL: emenda nao verificada)")


if __name__ == "__main__":
    main()
