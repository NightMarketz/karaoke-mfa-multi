# karaoke/render_cmd.py
"""Monta o comando ffmpeg do render final. Sem subprocess — so a lista de args."""
from pathlib import Path

FLAT_BG = "color=c=#08090f:s=1280x720"
WORK_W, WORK_H = 1408, 792      # 10% acima de 1280x720: folga para o zoom
OUT_W, OUT_H = 1280, 720


def _escape(p) -> str:
    """Caminho seguro dentro de um filtergraph do ffmpeg.

    Barra normal, e dois-pontos virando UMA barra invertida. O valor tem de
    ir entre aspas simples no filtro. Medido de fato contra o binario real
    (ffmpeg 8.1-full_build-www.gyan.dev) com um caminho absoluto do Windows
    via subprocess.run (sem shell, sem tradução de path do MSYS): sem escape
    falha ("Error applying option 'original_size'"), e com DUAS barras
    invertidas falha ("Error parsing a filter description... Invalid
    argument") — so a UNICA barra invertida realmente roda (rc=0, arquivo de
    saida gerado). Vale igual para sendcmd=f= e subtitles=.
    """
    return str(p).replace("\\", "/").replace(":", "\\:")


def build_render_cmd(bg_png, audio_inputs, ass_path: Path, out_mp4: Path,
                     duration: float, sendcmd_path) -> list:
    """
    bg_png:       Path do PNG de fundo, ou None para o fundo chapado.
    audio_inputs: [instrumental, vocais] — mixados com amix.
    sendcmd_path: Path do bounce.txt, ou None para nenhum movimento.
    """
    cmd = ["ffmpeg", "-y", "-hide_banner"]

    if bg_png is not None:
        cmd += ["-loop", "1", "-i", str(bg_png)]
    else:
        cmd += ["-f", "lavfi", "-i", FLAT_BG]

    for a in audio_inputs:
        cmd += ["-i", str(a)]

    amix = f"[1:a][2:a]amix=inputs={len(audio_inputs)}:duration=first[a];"

    filtros = []
    if bg_png is not None:
        filtros.append(f"scale={WORK_W}:{WORK_H}")
        if sendcmd_path is not None:
            filtros.append(f"sendcmd=f='{_escape(sendcmd_path)}'")
        filtros.append(f"crop={WORK_W}:{WORK_H}")
        # O scale DEPOIS do crop e o que fixa a resolucao de saida. Sem ele o
        # comando do sendcmd nao produz efeito visivel — verificado no ffmpeg 8.1.
        filtros.append(f"scale={OUT_W}:{OUT_H}")
    filtros.append("format=yuv420p")
    filtros.append(f"subtitles='{_escape(ass_path)}'")

    chain = "[0:v]" + ",".join(filtros) + "[v]"

    cmd += [
        "-filter_complex", amix + chain,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(out_mp4),
    ]
    return cmd
