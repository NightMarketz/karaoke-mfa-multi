"""
publi_cenas.py — banco de prova das 6 cenas da "Publi".

Nao e estagio do pipeline: e a bancada para VER se a direcao de arte funciona
antes de escrever qualquer laco de multi-cena. Roda direto, sem job.

    python scripts/publi_cenas.py            # gera as 6
    python scripts/publi_cenas.py 3 6        # so as cenas 3 e 6

A espinha e verde -> vermelho, que e a propria letra: o print de ganho no story
contra o extrato no vermelho. A cena 6 repete o enquadramento da 1 com a cor
trocada — e o reconhecimento do plano que fecha o arco.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from karaoke.background import ANIMA_SUFFIX, generate_image

WORKFLOW = Path(__file__).resolve().parent.parent / "config" / "comfy_workflow_anima.json"
OUT = Path(__file__).resolve().parent.parent / "work" / "cenas_publi"

# O andaime de producao crava "no humans". A cena 4 e sobre o povo, entao ela
# troca o prefixo. Manter isso explicito aqui — e a excecao que prova que o
# andaime fixo nao serve para todo plano.
PREFIX_SEM_GENTE = "masterpiece, best quality, safe, no humans, scenery, "
PREFIX_COM_GENTE = "masterpiece, best quality, safe, crowd, scenery, "

CENAS = [
    (1, "anzol-verde", PREFIX_SEM_GENTE,
     "bedroom, indoors, night, dark room, (green glow:2), phone screen light, "
     "backlighting, green theme, cold colors, smartphone on bed, rumpled blanket, "
     "curtain, window"),

    (2, "queda-verde", PREFIX_SEM_GENTE,
     "stairwell, indoors, night, (green glow:2), dim lighting, green theme, "
     "monochrome, handrail, concrete wall, from above, looking down, "
     "vanishing point, spiral"),

    (3, "cenario-revelado", PREFIX_SEM_GENTE,
     "film set, backstage, indoors, night, (harsh work light:2), spotlight, "
     "desaturated, mansion facade from behind, scaffolding, plywood, "
     "stage light, tripod, cables on floor, from behind"),

    (4, "o-povo", PREFIX_COM_GENTE,
     "outdoors, city street, night, (phone screen glow:2), rim light, "
     "dark, cold colors, silhouette, from behind, many people seen from behind, "
     "faceless, small glowing screens, bus stop"),

    (5, "ausencia-cinza", PREFIX_SEM_GENTE,
     "bedroom, indoors, morning, overcast, (grey light:2), soft lighting, "
     "desaturated, muted color, empty bed, rumpled blanket, curtain, window, "
     "dust in sunbeam"),

    (6, "extrato-vermelho", PREFIX_SEM_GENTE,
     "bedroom, indoors, night, dark room, (red glow:2), phone screen light, "
     "backlighting, red theme, smartphone on bed, rumpled blanket, curtain, "
     "window"),
]


def luminancia(p: Path):
    """Media da faixa onde a legenda cai e do centro. Sem PIL nao mede."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    a = np.asarray(Image.open(p).convert("L"), dtype=float)
    h, w = a.shape
    faixa = a[int(h * .72):int(h * .95), int(w * .15):int(w * .85)]
    centro = a[int(h * .30):int(h * .70), int(w * .30):int(w * .70)]
    return faixa.mean(), centro.mean()


def main():
    quais = {int(a) for a in sys.argv[1:]} or {c[0] for c in CENAS}
    OUT.mkdir(parents=True, exist_ok=True)
    for num, nome, prefixo, tags in CENAS:
        if num not in quais:
            continue
        destino = OUT / f"{num}_{nome}.png"
        prompt = f"{prefixo}{tags}{ANIMA_SUFFIX}"
        t0 = time.monotonic()
        try:
            generate_image(prompt, destino, WORKFLOW)
        except Exception as e:
            print(f"  cena {num} {nome}: FALHOU ({type(e).__name__}: {e})")
            continue
        dt = time.monotonic() - t0
        lum = luminancia(destino)
        extra = (f" | legenda {lum[0]:.0f}/255 centro {lum[1]:.0f}/255"
                 if lum else "")
        print(f"  cena {num} {nome}: {dt:.0f}s{extra} -> {destino.name}")


if __name__ == "__main__":
    main()
