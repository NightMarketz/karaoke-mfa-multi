"""Monta o video de fundo a partir de varias cenas, com crossfade entre elas.

Decomposicao proposital: em vez de complicar a cadeia de filtros do render (que
ja carrega crop comandado, sendcmd, format e subtitles), este modulo produz UM
video de fundo. O render passa a receber video no lugar de imagem em loop e nao
muda em mais nada.

Sem subprocess aqui — so a lista de argumentos, para dar para testar a cadeia
inteira sem rodar o encoder.
"""
from pathlib import Path

# Duracao do crossfade. Curto o bastante para nao borrar a virada de secao,
# longo o bastante para nao piscar. ponytail: constante ate alguem reclamar.
FADE_S = 1.0


def build_scene_video_cmd(segmentos, out_path: Path, total_s: float,
                          largura: int, altura: int, fade_s: float = FADE_S) -> list:
    """Comando ffmpeg que costura os segmentos num video de fundo.

    segmentos: [(Path do png, inicio_s), ...] em ordem crescente de inicio.
               O primeiro TEM de comecar em 0 — o video precisa existir desde
               o frame zero, senao o render fica sem fundo no comeco.
    total_s:   duracao final do video (fim da ultima secao).

    O xfade encadeia: a transicao k acontece no instante de inicio do segmento
    k, em tempo ABSOLUTO, porque a saida de cada xfade herda a linha de tempo
    da primeira entrada. Cada entrada precisa durar o proprio trecho MAIS o
    fade, senao o ffmpeg reclama de offset alem do fim do stream.
    """
    if not segmentos:
        raise ValueError("nenhum segmento — um video de fundo vazio nao existe")
    inicios = [s for _, s in segmentos]
    if inicios != sorted(inicios):
        raise ValueError(f"segmentos fora de ordem: {inicios}")
    if abs(inicios[0]) > 1e-6:
        raise ValueError(f"o primeiro segmento comeca em {inicios[0]}s, tem de ser 0")
    if total_s <= inicios[-1]:
        raise ValueError(f"total {total_s}s nao cobre o ultimo inicio {inicios[-1]}s")

    # Duracao de cada entrada: o trecho ate o proximo inicio, mais o fade que
    # sera consumido na transicao. O ultimo vai ate o fim.
    fronteiras = inicios[1:] + [total_s]
    duracoes = [fim - ini + fade_s for ini, fim in zip(inicios, fronteiras)]

    cmd = ["ffmpeg", "-y", "-hide_banner"]
    for (png, _), dur in zip(segmentos, duracoes):
        cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)]

    # Normaliza toda entrada para o mesmo tamanho e SAR: xfade recusa streams
    # com geometria diferente, e as cenas podem vir de modelos distintos.
    partes = [f"[{i}:v]scale={largura}:{altura},setsar=1,format=yuv420p[c{i}]"
              for i in range(len(segmentos))]

    atual = "c0"
    for k in range(1, len(segmentos)):
        saida = f"x{k}"
        partes.append(
            f"[{atual}][c{k}]xfade=transition=fade:duration={fade_s:.3f}"
            f":offset={inicios[k]:.3f}[{saida}]")
        atual = saida

    cmd += [
        "-filter_complex", ";".join(partes),
        "-map", f"[{atual}]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-t", f"{total_s:.3f}",
        str(out_path),
    ]
    return cmd


def segmentos_de_secoes(secoes, mapa_cenas, dir_cenas: Path) -> list:
    """Cruza [(nome_secao, inicio_s)] com {nome_secao: arquivo} -> segmentos.

    Secoes que repetem (refrao voltando) apontam para a MESMA imagem de
    proposito: o reconhecimento do plano e o que faz o arco fechar.
    """
    fora = sorted({n for n, _ in secoes} - set(mapa_cenas))
    if fora:
        raise KeyError(f"secoes sem cena atribuida: {fora}")
    segmentos = []
    for nome, inicio in secoes:
        png = dir_cenas / mapa_cenas[nome]
        if not png.exists():
            raise FileNotFoundError(f"cena ausente para {nome}: {png}")
        # Secoes seguidas na mesma imagem viram um segmento so — cortar para
        # a propria imagem seria um crossfade invisivel e trabalho a toa.
        if segmentos and segmentos[-1][0] == png:
            continue
        segmentos.append((png, float(inicio)))
    return segmentos
