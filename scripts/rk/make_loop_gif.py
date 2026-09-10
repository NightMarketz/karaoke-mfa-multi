"""Monta o GIF em loop ping-pong de uma janela de quadros ja gerada.

Por que ping-pong e nao janela direta: nas 270 janelas medidas pelo loop_pick.py
nenhuma fecha a emenda para frente, e o criterio de razao (emenda/vizinhos) foi
reprovado pelo proprio controle negativo — sabotar o ultimo quadro deu razao 1,85,
MELHOR que a melhor janela real (2,31). Razao nao discrimina com movimento alto.

O ping-pong nao depende de limiar nenhum: a sequencia i..j, j-1..i+1 faz com que
**todo** par consecutivo do ciclo, inclusive a volta, seja um par que era vizinho
na geracao. Isso e garantia de construcao, e o assert abaixo e o que falha se eu
errar o indice (pulo de 2, ponta repetida).

    python make_loop_gif.py gifloop608_20260941 3 8           # inicio 3, n 8
    python make_loop_gif.py gifloop608_20260941 3 8 --seconds 10
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

OUT = r"C:\rk\ComfyUI\output"
FF = shutil.which("ffmpeg") or r"C:\Users\Katz\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
PAL = ("split[a][b];[a]palettegen=stats_mode=diff[p];"
       "[b][p]paletteuse=dither=bayer:bayer_scale=3")


def check_ring(seq, n):
    """Todo par consecutivo do ciclo FECHADO dista 1 no indice original. Levanta se nao."""
    ring = seq + seq[:1]
    jumps = sorted({abs(ring[i + 1] - ring[i]) for i in range(len(seq))})
    assert jumps == [1], f"ping-pong quebrado: saltos de indice {jumps}, esperado [1]"
    assert len(seq) == 2 * n - 2, f"{len(seq)} quadros, esperado {2 * n - 2}"
    return seq


def pingpong(start, n):
    ida = list(range(start, start + n))
    return check_ring(ida + ida[-2:0:-1], n)


def selfcheck():
    """Controle negativo do assert: sequencia errada TEM que levantar, senao nao e cerca."""
    ida = list(range(3, 3 + 8))
    casos = [("correta (i..j, j-1..i+1)", ida + ida[-2:0:-1], False),
             ("pontas repetidas (salto 0)", ida + ida[::-1], True),
             ("pula um na volta (salto 2)", ida + ida[-3::-1], True),
             ("volta faltando", ida, True)]
    falhas = 0
    for nome, seq, deve_levantar in casos:
        msg = ""
        try:
            check_ring(seq, 8)
            levantou = False
        except AssertionError as e:
            levantou, msg = True, str(e)[:58]
        ok = levantou == deve_levantar
        falhas += not ok
        print(f"  {'ok   ' if ok else 'FALHA'} {nome:<28} "
              f"{'levantou -> ' + msg if levantou else 'passou'}")
    print(f"{len(casos) - falhas} de {len(casos)} como previsto; "
          f"{sum(1 for c in casos if c[2])} sabotados tinham que levantar")
    return 1 if falhas else 0


def main():
    if "--selfcheck" in sys.argv:
        print("controle negativo do ping-pong:")
        return selfcheck()
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("start", type=int)
    ap.add_argument("n", type=int)
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--width", type=int, default=480)
    ap.add_argument("--height", type=int, default=704)
    ap.add_argument("--seconds", type=float, default=0.0, help="0 = um ciclo (o GIF loopa sozinho)")
    ap.add_argument("--forward", action="store_true",
                    help="loop direto i..j (so com driver periodico); a emenda passa a ser MEDIDA")
    ap.add_argument("--ratio-max", type=float, default=1.5)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.forward:
        seq = list(range(a.start, a.start + a.n))
    else:
        seq = pingpong(a.start, a.n)
    srcs = [os.path.join(OUT, f"{a.prefix}_{i:05d}_.png") for i in seq]
    falta = [s for s in srcs if not os.path.exists(s)]
    if falta:
        sys.exit(f"faltam {len(falta)} de {len(srcs)} quadros: {falta[:2]}")

    if a.forward:
        # Sem ping-pong nao ha garantia de construcao: a emenda tem que ser medida, e o
        # numero so vale porque o mesmo predicado ja foi visto vermelho (run sem driver
        # deu 3,87 e janela fora do periodo deu 1,56, ambos reprovados).
        import numpy as np
        from PIL import Image
        w = np.stack([np.array(Image.open(s).convert("RGB")) for s in srcs]).astype(np.float32)
        viz = float(np.abs(np.diff(w, axis=0)).mean())
        seam = float(np.abs(w[-1] - w[0]).mean())
        print(f"emenda medida: vizinhos {viz:.3f}, emenda {seam:.3f}, razao {seam/viz:.2f} "
              f"(limite {a.ratio_max})")
        if seam / viz > a.ratio_max:
            sys.exit(f"a janela {a.start}..{a.start + a.n - 1} nao fecha: razao {seam/viz:.2f}")

    tmp = tempfile.mkdtemp(prefix="loopgif_")
    for k, s in enumerate(srcs):
        shutil.copy(s, os.path.join(tmp, f"f_{k:03d}.png"))

    out = a.out or rf"C:\rk\{a.prefix}_loop.gif"
    cmd = [FF, "-y", "-v", "error"]
    if a.seconds:
        loops = int(a.seconds * a.fps / len(seq))          # ciclos inteiros, sem corte no meio
        cmd += ["-stream_loop", str(max(0, loops - 1))]
        out = a.out or rf"C:\rk\{a.prefix}_loop{int(a.seconds)}s.gif"
    cmd += ["-framerate", str(a.fps), "-i", os.path.join(tmp, "f_%03d.png"),
            "-filter_complex", f"scale={a.width}:{a.height}:flags=lanczos,{PAL}",
            "-loop", "0", out]
    subprocess.run(cmd, check=True)
    shutil.rmtree(tmp, ignore_errors=True)

    nf = len(seq) * (int(a.seconds * a.fps / len(seq)) if a.seconds else 1)
    print(f"{out}  {os.path.getsize(out)/1048576:.2f} MB  {nf} quadros "
          f"({len(seq)} unicos x {nf//len(seq)})  {a.width}x{a.height} @ {a.fps} fps "
          f"= {nf/a.fps:.2f} s por volta")
    return 0


if __name__ == "__main__":
    sys.exit(main())
