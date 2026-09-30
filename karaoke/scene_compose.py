"""
Compositor da cena reativa: 4 loops + mascara da fogueira + partitura ->
background_scene.mp4. Imagem e video entram e saem pelo ffmpeg (sem PIL).

Spec: docs/superpowers/specs/2026-09-30-cena-reativa-design.md
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np

ARQUIVOS_LOOP = ("calmo.mp4", "tensao.mp4", "climax.mp4", "escuro.mp4")
# letra do 09: camada 0 nas linhas 8-48, camada 1 em 118-158 de 720 (medido)
FAIXA_TOPO = (0.0, 0.25)
# ponytail: os 4 loops inteiros em RAM (~100 MB cada a 832x480x81). Ler por
# pipe quadro a quadro se um pacote em 720p+ estourar a memoria.


def _sonda(mp4: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate", "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(num) / float(den)


def _decodifica(arq: Path, w: int, h: int, pix: str, extra=()) -> np.ndarray:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(arq), *extra,
         "-f", "rawvideo", "-pix_fmt", pix, "-"],
        capture_output=True, check=True).stdout
    canais = 3 if pix == "rgb24" else 1
    return np.frombuffer(out, np.uint8).reshape(-1, h, w, canais)


def carregar_pacote(pasta: Path):
    pasta = Path(pasta)
    for nome in (*ARQUIVOS_LOOP, "fogo_mask.png"):
        if not (pasta / nome).exists():
            raise FileNotFoundError(f"pacote de cena incompleto: falta {pasta / nome}")
    ref = _sonda(pasta / ARQUIVOS_LOOP[0])
    w, h, fps = ref
    loops = []
    for nome in ARQUIVOS_LOOP:
        if _sonda(pasta / nome) != ref:
            raise ValueError(f"{nome}: {_sonda(pasta / nome)} difere de "
                             f"{ARQUIVOS_LOOP[0]}: {ref} (largura, altura, fps)")
        loops.append(_decodifica(pasta / nome, w, h, "rgb24"))
    contagens = [len(l) for l in loops]
    if len(set(contagens)) != 1:
        nome = ARQUIVOS_LOOP[contagens.index(min(contagens))]
        raise ValueError(f"{nome}: numero de quadros difere ({dict(zip(ARQUIVOS_LOOP, contagens))})")
    masc = _decodifica(pasta / "fogo_mask.png", w, h, "gray", ("-vf", f"scale={w}:{h}"))
    meta_p = pasta / "scene.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    return loops, masc[0, :, :, 0].astype(np.float32) / 255.0, fps, meta


def misturar(quadros, w, ganho, mascara):
    f = np.tensordot(np.asarray(w, np.float32), quadros.astype(np.float32), axes=1)
    f *= (1.0 + (ganho - 1.0) * mascara)[..., None]
    return np.clip(np.rint(f), 0, 255).astype(np.uint8)


def compor(loops, mascara, w_todos, g_todos, fps, saida: Path):
    w_todos = np.asarray(w_todos)
    if w_todos.ndim != 2 or w_todos.shape[1] != len(ARQUIVOS_LOOP):
        raise ValueError(f"pesos com forma {w_todos.shape}, esperado (N, 4)")
    n_loop, h, w, _ = loops[0].shape
    a, b = int(h * FAIXA_TOPO[0]), int(h * FAIXA_TOPO[1])
    saida = Path(saida)
    tmp = saida.with_name(saida.stem + ".tmp.mp4")
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", str(tmp)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    faixa = []
    try:
        pilha = np.empty((4, h, w, 3), np.uint8)
        for i in range(len(w_todos)):
            for k in range(4):
                pilha[k] = loops[k][i % n_loop]
            q = misturar(pilha, w_todos[i], float(g_todos[i]), mascara)
            faixa.append(float(q[a:b].mean()))
            enc.stdin.write(q.tobytes())
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError(f"ffmpeg falhou: {enc.stderr.read().decode(errors='replace')[-1000:]}")
    except BaseException:
        if enc.poll() is None:
            enc.kill()
        enc.wait()
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, saida)
    return faixa


def fundo_do_job(scene_mp4: Path, bg_png: Path) -> Path | None:
    for p in (Path(scene_mp4), Path(bg_png)):
        if p.exists():
            return p
    return None
