"""
fetch_ui_sfx.py — Baixa os 2 efeitos sonoros de UI (ding de pontuacao, aplauso da tela
final). web/sfx/ e' gitignored como input/: o mp3 de terceiro nao viaja no git, este
script sim (mesmo motivo e mesmos headers de scripts/fetch_mimic_refs.py).

  python scripts/fetch_ui_sfx.py

Diferenca chave pro fetch_mimic_refs.py: sem curadoria (MIN_ATAQUES/MIN_DUR_S) — estes
sons so tocam, nunca sao pontuados pelo scorer, entao a regua dele nao se aplica. Fica
em mp3 (sem converter pra wav 16k mono): e' playback puro no browser via <audio>/Audio(),
sem motivo pra pagar ffmpeg.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from karaoke import paths as kpaths  # noqa: E402

BASE = "https://www.myinstants.com/media/sounds/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Referer": "https://www.myinstants.com/en/",
    "Accept": "audio/*;q=0.9,*/*;q=0.5",
    "Range": "bytes=0-",
}
# nome local (o que party.html/mimic.html tocam) -> arquivo no CDN do MyInstants
CLIPS = {
    "ding": "ding-sound-effect_1.mp3",       # myinstants.com/en/instant/correct-ding/
    "aplauso": "applause-4.mp3",             # myinstants.com/en/instant/applause/
}
SFX_DIR = kpaths.repos_root() / "web" / "sfx"


def baixar(nome: str, arquivo: str) -> Path:
    dst = SFX_DIR / f"{nome}.mp3"
    if dst.exists():
        return dst
    req = urllib.request.Request(BASE + arquivo, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        dados = r.read()
        esperado = r.headers.get("Content-Length")
    if esperado and int(esperado) != len(dados):
        raise RuntimeError(f"{nome}: baixou {len(dados)} de {esperado} bytes")
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(dados)
    return dst


def main() -> int:
    for nome, arquivo in CLIPS.items():
        dst = baixar(nome, arquivo)
        print(f"{dst.relative_to(kpaths.repos_root())}  {dst.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
