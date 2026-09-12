"""
fetch_mimic_refs.py — Baixa os clipes de referencia do modo mimic e os mede pela regua
do scorer. `input/` e gitignored: os WAVs nao viajam entre checkouts, este script sim.

  python scripts/fetch_mimic_refs.py            # baixa o que falta, converte, mede tudo
  python scripts/fetch_mimic_refs.py --check    # so mede o que ja esta em input/mimic_refs/

Regra de curadoria (medida em 2026-09-11, ver docs/superpowers/specs/...scorer...): referencia
com < MIN_ATAQUES ataques ou < MIN_DUR_S segundos faz ritmo e ataques virarem ruido — `bruh`
(0,8 s, 4 ataques) contra `screaming_goat` deu 53,1, em cima do p95 do acaso. O script nao
recusa esses clipes; marca FRAGIL para quem monta o pack decidir.

O CDN do MyInstants devolve 403 a cliente sem cara de browser; cai com os 4 cabecalhos abaixo.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import soundfile as sf  # noqa: E402

from karaoke import paths as kpaths  # noqa: E402
from karaoke.scorer import MIN_VOICED_FRAMES, score, track_from_audio  # noqa: E402

BASE = "https://www.myinstants.com/media/sounds/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Referer": "https://www.myinstants.com/en/",
    "Accept": "audio/*;q=0.9,*/*;q=0.5",
    "Range": "bytes=0-",
}
# id (casa com REF_ID_RE do server_score_addendum) -> arquivo no CDN
CLIPS = {
    "oh_no_no_no": "oh-no-no-no-no-laugh.mp3",
    "hello_there": "hello-there-general-kenobi.mp3",
    "why_are_you_running": "why-are.mp3",
    "nooo": "nooo.mp3",
    "its_a_me_mario": "its-me-mario.mp3",
    "emotional_damage": "emotional-damage-meme.mp3",
    "screaming_goat": "screaming-goat.mp3",
    "ara_ara": "ara-ara.mp3",
    "bruh": "movie_1.mp3",       # FRAGIL: 4 ataques — mantido como caso negativo
    "wow": "6_1Njp68r.mp3",      # FRAGIL: 11 frames voiced, 1 acima do minimo
}
MIN_ATAQUES = 6
MIN_DUR_S = 1.5
REF_DIR = kpaths.repos_root() / "input" / "mimic_refs"
MP3_DIR = REF_DIR / "_mp3"


def baixar(id_: str, arquivo: str) -> Path:
    dst = MP3_DIR / f"{id_}.mp3"
    if dst.exists():
        return dst
    req = urllib.request.Request(BASE + arquivo, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        dados = r.read()
        esperado = r.headers.get("Content-Length")
    if esperado and int(esperado) != len(dados):
        raise RuntimeError(f"{id_}: baixou {len(dados)} de {esperado} bytes")
    MP3_DIR.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(dados)
    return dst


def converter(mp3: Path, wav: Path) -> None:
    wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                    "-ar", "16000", "-ac", "1", str(wav)], check=True, timeout=60)


def medir(wav: Path) -> tuple[str, str]:
    a, sr = sf.read(wav, dtype="float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    t = track_from_audio(a, sr)
    auto = score(t, track_from_audio(a, sr)).total
    linha = (f"{wav.stem:22} {t.duration:5.1f}s  ataques {len(t.onsets):3d}  "
             f"voiced {t.n_voiced:3d}/{t.n_frames:<4d}  self {auto:5.1f}")
    if t.n_voiced < MIN_VOICED_FRAMES or len(t.onsets) < 2 or auto < 95:
        return linha, "REPROVADO (sem melodia ou sem ritmo)"
    if len(t.onsets) < MIN_ATAQUES or t.duration < MIN_DUR_S:
        return linha, f"FRAGIL (<{MIN_ATAQUES} ataques ou <{MIN_DUR_S}s: ritmo vira ruido)"
    return linha, "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="so mede o que ja existe")
    args = ap.parse_args()

    if not args.check:
        for id_, arquivo in CLIPS.items():
            wav = REF_DIR / f"{id_}.wav"
            if not wav.exists():
                converter(baixar(id_, arquivo), wav)

    wavs = sorted(REF_DIR.glob("*.wav"))
    if not wavs:
        print(f"nenhum WAV em {REF_DIR} — rode sem --check para baixar", file=sys.stderr)
        return 1
    contagem = {"ok": 0, "FRAGIL": 0, "REPROVADO": 0}
    for wav in wavs:
        linha, veredito = medir(wav)
        contagem[veredito.split()[0]] += 1
        print(f"{linha}  {veredito}")
    print(f"\n{len(wavs)} clipes: {contagem['ok']} ok, {contagem['FRAGIL']} frageis, "
          f"{contagem['REPROVADO']} reprovados")
    return 1 if contagem["REPROVADO"] else 0


if __name__ == "__main__":
    sys.exit(main())
