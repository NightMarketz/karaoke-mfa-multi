"""Acha a melhor janela para virar GIF em loop dentro dos runs curtos de SCAIL-2.

Sem driver o personagem translada, entao emenda fechada nao e dada: e medida.

Criterio derivado do material, nao herdado. O gate.py foi escrito para ciclo FK,
onde vizinhos valem ~5; aqui valem ~1,6, e o limiar de 6,0 fica tao longe que
**uma janela embaralhada passa** (medido: vizinhos 3,58 < 6,0). Limiar que nao
reprova material quebrado nao mede nada, entao aqui o veredito e:

  1. ha movimento      : vizinhos > MOV_MIN      (senao janela congelada seria "loop perfeito")
  2. a emenda nao salta: emenda / vizinhos <= R  (emenda em unidades de um passo normal)

Cada um tem o seu controle negativo, que roda sempre e tem que ficar vermelho.

    python loop_pick.py gifloop608_                 # varre n de 8 a 16
    python loop_pick.py gifloop608_ --nmin 12 --nmax 12
"""
import argparse
import os
import random
import re
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, r"C:\rk")
from gate import gate1, strip, OUT, VIZ_MAX, SEAM_MAX

MOV_MIN = 0.5      # abaixo disso a janela esta praticamente parada
RATIO_MAX = 2.0    # emenda vale no maximo dois passos normais
CUT_MAX = 2.0      # pior par acima disso vezes a media = corte de plano dentro da janela


def groups(base):
    """Denominador vem do dono do dado: a pasta de saida, nao uma lista na mao."""
    pat = re.compile(rf"^{re.escape(base)}(.*)_\d{{5}}_\.png$")
    out = {}
    for f in sorted(os.listdir(OUT)):
        m = pat.match(f)
        if m:
            out.setdefault(m.group(1), []).append(os.path.join(OUT, f))
    return out


def metrics(a):
    """Mesma aritmetica do gate1, sobre um array ja carregado (270 janelas releriam 3k PNGs)."""
    viz = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2, 3))
    return float(viz.mean()), float(np.abs(a[-1] - a[0]).mean()), float(viz.max())


def verdict(viz, seam):
    return viz > MOV_MIN and seam / viz <= RATIO_MAX


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--nmin", type=int, default=8)
    ap.add_argument("--nmax", type=int, default=16)
    ap.add_argument("--skip", type=int, default=0,
                    help="quadros iniciais a descartar (rampa de entrada do modelo)")
    a = ap.parse_args()

    by_seed = groups(a.base)
    if not by_seed:
        sys.exit(f"nenhum frame com prefixo {a.base} em {OUT}")

    cache, rows, planned = {}, [], 0
    if a.skip:
        by_seed = {k: v[a.skip:] for k, v in by_seed.items()}
        print(f"descartando os {a.skip} primeiros quadros de cada seed (rampa de entrada)")
    for seed, files in sorted(by_seed.items()):
        arr = np.stack([np.array(Image.open(p).convert("RGB")) for p in files]).astype(np.float32)
        cache[seed] = (files, arr)
        ns = [n for n in range(a.nmin, a.nmax + 1) if n <= len(files)]
        planned += sum(len(files) - n + 1 for n in ns)
        print(f"seed {seed}: {len(files)} quadros, n de {ns[0]} a {ns[-1]} -> "
              f"{sum(len(files) - n + 1 for n in ns)} janelas", flush=True)
        for n in ns:
            for i in range(len(files) - n + 1):
                viz, seam, vmax = metrics(arr[i:i + n])
                rows.append((seed, n, i + 1, viz, seam, vmax))

    assert planned == len(rows), f"{len(rows)} avaliadas de {planned} planejadas"

    # a reimplementacao tem que bater com o gate1 original, senao o numero e de outra coisa
    s0, n0, i0 = rows[0][0], rows[0][1], rows[0][2]
    g = gate1(cache[s0][0][i0 - 1:i0 - 1 + n0])
    assert abs(g["viz"] - rows[0][3]) < 1e-6 and abs(g["seam"] - rows[0][4]) < 1e-6, \
        f"metrics() divergiu do gate1: {g['viz']} vs {rows[0][3]}"

    rows.sort(key=lambda r: r[4] / r[3])
    aprov = [r for r in rows if verdict(r[3], r[4])]
    print(f"\n{len(rows)} janelas avaliadas ({len(by_seed)} seeds x n de {a.nmin} a {a.nmax}), "
          f"{len(aprov)} passam (vizinhos>{MOV_MIN} e emenda/vizinhos<={RATIO_MAX})")
    print(f"{'seed':>10} {'n':>3} {'inicio':>7} {'vizinhos':>9} {'emenda':>8} "
          f"{'razao':>6} {'pior par':>9}  veredito")
    for seed, n, st, viz, seam, vmax in rows[:10]:
        print(f"{seed:>10} {n:>3} {st:>7} {viz:9.3f} {seam:8.3f} {seam/viz:6.2f} {vmax:9.3f}  "
              f"{'PASSA' if verdict(viz, seam) else 'reprova'}")

    print("\ncontroles negativos (todos tem que REPROVAR; verde aqui = cheque cego)")
    # O controle roda na melhor janela COM MOVIMENTO. Sabotar material parado nao
    # testa a razao: o guarda de movimento reprova antes, e a razao sai ilesa.
    mov = [r for r in rows if r[3] > MOV_MIN]
    if not mov:
        print("  nenhuma janela com movimento > MOV_MIN: a razao nao pode ser testada")
        return 1
    best = mov[0]
    print(f"  material: seed {best[0]} n={best[1]} inicio {best[2]} "
          f"(vizinhos {best[3]:.3f} — a melhor COM movimento, de {len(mov)} de {len(rows)})")
    files, arr = cache[best[0]]
    w = arr[best[2] - 1:best[2] - 1 + best[1]]

    frozen = np.repeat(w[:1], best[1], axis=0)            # 1. janela congelada
    v, s, _ = metrics(frozen)
    print(f"  congelada        : vizinhos {v:.3f} emenda {s:.3f} razao "
          f"{'n/a' if v == 0 else f'{s/v:.2f}'} -> "
          f"{'PASSOU (cheque cego)' if verdict(v, s) else 'reprovou, ok'}")

    far = w.copy()                                        # 2. ultimo quadro errado
    far[-1] = arr[(best[2] - 1 + best[1] // 2) % len(arr)]
    v, s, _ = metrics(far)
    print(f"  emenda sabotada  : vizinhos {v:.3f} emenda {s:.3f} razao {s/v:.2f} -> "
          f"{'PASSOU (cheque cego)' if verdict(v, s) else 'reprovou, ok'}")

    idx = list(range(best[1]))                            # 3. ordem embaralhada
    rnd = random.Random(0)
    while idx == list(range(best[1])):
        rnd.shuffle(idx)
    v, s, _ = metrics(w[idx])
    print(f"  ordem embaralhada: vizinhos {v:.3f} emenda {s:.3f} -> contra o gate.py herdado "
          f"(vizinhos<{VIZ_MAX} emenda<{SEAM_MAX}): "
          f"{'PASSOU — foi por isso que o limiar herdado caiu' if (v < VIZ_MAX and s < SEAM_MAX) else 'reprovou'}")

    # Escolha para o ping-pong NAO usa a razao: ela foi reprovada pelo controle acima,
    # e ranquear por ela premia janela parada (foi o que deu no 20260940). Com a emenda
    # garantida por construcao, o que sobra e: ter movimento, e nao ter corte dentro.
    print(f"\nmelhor janela por seed para ping-pong "
          f"(mais movimento, sem corte interno: pior par <= {CUT_MAX}x a media)")
    for k in sorted(cache):
        cand = [r for r in rows if r[0] == k and r[3] > MOV_MIN and r[5] <= CUT_MAX * r[3]]
        todas = [r for r in rows if r[0] == k]
        if not cand:
            print(f"  {k}: 0 de {len(todas)} janelas com movimento e sem corte — seed descartada")
            continue
        seed, n, st, viz, seam, vmax = max(cand, key=lambda r: r[3])
        ida = list(range(st - 1, st - 1 + n))
        pp = ida + ida[-2:0:-1]          # i..j, j-1..i+1 — sem repetir as pontas
        v, sm, _ = metrics(cache[seed][1][pp])
        fs = cache[seed][0][st - 1:st - 1 + n]
        # o nome carrega o indice REAL do arquivo (st + skip), senao a tira mente
        out = strip(fs, rf"C:\rk\loop_{a.base}{seed}_n{n}_s{st + a.skip}.png")
        print(f"  {seed}  n={n} inicio {st + a.skip:>2}  "
              f"({len(cand)} de {len(todas)} janelas elegiveis)")
        print(f"    janela direta: vizinhos {viz:.3f} emenda {seam:.3f} pior par {vmax:.3f}")
        print(f"    ping-pong {len(pp)} quadros: vizinhos {v:.3f} emenda {sm:.3f} "
              f"razao {sm/v:.2f}")
        print(f"    comando: python make_loop_gif.py {a.base}{seed} {st + a.skip} {n}")
        print(f"    tira: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
