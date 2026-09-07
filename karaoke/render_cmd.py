# karaoke/render_cmd.py
"""Monta o comando ffmpeg do render final. Sem subprocess — so a lista de args."""
from pathlib import Path

OUT_W, OUT_H = 1280, 720
WORK_W, WORK_H = 1408, 792      # 10% acima de 1280x720: folga para o zoom
# Derivado das constantes de proposito: hardcodar 1280x720 aqui deixava o ramo
# chapado driftar do ilustrado sem nada acusar.
FLAT_BG = f"color=c=#08090f:s={OUT_W}x{OUT_H}"


def _escape(p) -> str:
    """Caminho seguro dentro de um filtergraph do ffmpeg.

    Barra normal, e dois-pontos virando barra invertida. O valor tem de ir
    entre aspas simples no filtro. Medido de fato contra o binario real
    (ffmpeg 8.1-full_build-www.gyan.dev) via subprocess.run com lista de
    args (sem shell), caminho absoluto do Windows, com e sem espaco no
    caminho: sem escape falha ("Error applying option 'original_size'" /
    "Invalid argument"). UMA barra invertida e DUAS barras invertidas rodam
    as duas (rc=0, arquivo valido gerado) — usamos uma por ser a mais
    simples que ja funciona. Vale igual para sendcmd=f= e subtitles=.

    Aviso: medir isso numa linha de comando do bash da resultado ERRADO — o
    quoting do shell come um nivel de barra antes do ffmpeg ver a string. So
    conta medicao via subprocess.run com lista de args (o caminho real de
    producao).
    """
    return str(p).replace("\\", "/").replace(":", "\\:")


# Fundo em video ja tem linha de tempo propria; "-loop 1" nele congelaria o
# primeiro frame e as cenas nunca virariam — sem erro nenhum do ffmpeg. Fundo
# em imagem PRECISA do loop, senao vira um frame so. Ha teste para as duas.
_EXT_VIDEO = (".mp4", ".mov", ".mkv", ".webm")


def build_render_cmd(bg_png, audio_inputs, ass_path: Path, out_mp4: Path,
                     duration: float, sendcmd_path) -> list:
    """
    bg_png:       Path do fundo — PNG (entra em loop) ou video de cenas com
                  crossfade (entra como esta), ou None para o fundo chapado.
    audio_inputs: [instrumental, vocais] — mixados com amix.
    sendcmd_path: Path do bounce.txt, ou None para nenhum movimento.
    """
    cmd = ["ffmpeg", "-y", "-hide_banner"]

    if bg_png is not None:
        if Path(bg_png).suffix.lower() in _EXT_VIDEO:
            cmd += ["-i", str(bg_png)]
        else:
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
