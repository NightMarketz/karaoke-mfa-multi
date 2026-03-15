"""
06_textgrid_to_ass.py — Gera arquivo .ASS de karaokê sincronizado.

Modo CTC (preferido): lê word_timing_fixed.json ou word_timing.json
Modo Legacy: lê TextGrid do MFA (fallback)

Adlibs: se adlibs_timing.json existir, são renderizados na mesma posição
da letra com estilo Adlib (itálico, cor laranja, highlight igual ao principal).

Inputs  (via --job-id):
  work/jobs/{job_id}/05_alignment/word_timing_fixed.json  ← preferido
  work/jobs/{job_id}/05_alignment/word_timing.json
  work/jobs/{job_id}/05_alignment/adlibs_timing.json      ← opcional
  input/jobs/{job_id}/lyrics.txt

Outputs (via --job-id):
  work/jobs/{job_id}/06_ass/karaoke.ass
  outputs/{job_id}.mp4
"""
import re
import sys
import io
import json
import argparse
from pathlib import Path

# Force UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths


def _progress(pct: int, msg: str = ""):
    """Emite linha de progresso parseável pelo server.py."""
    if msg:
        print(f"PROGRESS: {pct} | {msg}", flush=True)
    else:
        print(f"PROGRESS: {pct}", flush=True)





def format_ass_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


# ── Modo CTC ──────────────────────────────────────────────────────────────────

def build_ass_from_ctc(char_timing: list, lyrics_lines: list) -> tuple[list, list]:
    """
    Constrói eventos ASS a partir do char_timing.json do CTC.
    Cada entrada em char_timing é um dict com 'word', 'start', 'end', 'chars'.
    Chars é lista de {'char', 'start', 'end'}.

    Retorna (events, layer_ends) — layer_ends é passado para build_adlib_events
    para que adlibs compartilhem o mesmo sistema de anti-colisão de layers.
    """
    _progress(10, "Indexando alinhamento CTC...")

    PRE_ROLL  = 1.0
    POST_ROLL = 0.5

    # Flatten words para indexar por posição
    flat_words = []
    for entry in char_timing:
        flat_words.append(entry)

    events = []
    word_idx = 0
    total_lines = len(lyrics_lines)

    _progress(20, f"Gerando {total_lines} linhas de ASS...")

    # Layer collision tracker
    layer_ends = []

    for line_num, line in enumerate(lyrics_lines):
        words_in_line = line.split()
        if not words_in_line or word_idx >= len(flat_words):
            continue

        # Coleta mapeamentos desta linha
        line_entries = []
        for raw_word in words_in_line:
            if word_idx < len(flat_words):
                entry = dict(flat_words[word_idx])
                entry["display_word"] = raw_word # Preserva pontuação/casing
                line_entries.append(entry)
                word_idx += 1

        if not line_entries:
            continue

        line_start = line_entries[0]["start"]
        line_end   = line_entries[-1]["end"]
        start_visual = max(0.0, line_start - PRE_ROLL)
        end_visual   = line_end + POST_ROLL

        # Layer anti-collision
        layer = 0
        for i, le in enumerate(layer_ends):
            if start_visual >= le + 0.05:
                layer = i
                layer_ends[i] = end_visual
                break
        else:
            layer = len(layer_ends)
            layer_ends.append(end_visual)

        margin_v = 60 + layer * 110
        k_parts = []
        current_time = start_visual

        for entry in line_entries:
            # Gap antes da palavra
            gap = entry["start"] - current_time
            if gap > 0.005:
                gap_cs = max(1, int(round(gap * 100)))
                k_parts.append(f"{{\\k{gap_cs}}}")

            chars = entry.get("chars", [])
            if chars:
                # Modo char-level: \kf por caractere
                for ch in chars:
                    dur_cs = max(1, int(round((ch["end"] - ch["start"]) * 100)))
                    color_dur = dur_cs * 10
                    k_parts.append(
                        f"{{\\kf{dur_cs}\\t(0,{color_dur},\\1c&H00FFFF&)}}{ch['char']}"
                    )
            else:
                # Fallback word-level
                display = entry.get("display_word") or entry.get("word", "")
                dur_cs = max(1, int(round((entry["end"] - entry["start"]) * 100)))
                color_dur = dur_cs * 10
                k_parts.append(
                    f"{{\\kf{dur_cs}\\t(0,{color_dur},\\1c&H00FFFF&)}}{display}"
                )

            current_time = entry["end"]
            k_parts.append(" ")

        # Tag gap final (POST_ROLL)
        final_gap = end_visual - current_time
        if final_gap > 0.01:
            gap_cs = int(round(final_gap * 100))
            k_parts.append(f"{{\\k{gap_cs}}}")

        # Remove espaço final
        if len(k_parts) >= 2 and k_parts[-2] == " ":
            # Se o último for \k do gap, remove o espaço antes dele
            k_parts.pop(-2)
        elif k_parts and k_parts[-1] == " ":
            k_parts.pop()

        k_text = "".join(k_parts)
        start_ass = format_ass_time(start_visual)
        end_ass   = format_ass_time(end_visual)
        
        # Usa posicionamento por camada
        events.append(
            f"Dialogue: {layer},{start_ass},{end_ass},Default,,0,0,0,,"
            f"{{\\an2\\pos(640,{margin_v})}}{k_text}"
        )

        # Progress report a cada 10 linhas
        if line_num % 10 == 0:
            pct = 20 + int((line_num / total_lines) * 60)
            _progress(pct, f"Linha {line_num + 1}/{total_lines}...")

    _progress(80, "Eventos ASS gerados")
    return events, layer_ends


# ── Modo Legacy (TextGrid MFA) ────────────────────────────────────────────────

def build_ass_from_textgrid(tg_path: Path, lyrics_lines: list) -> tuple[list, list]:
    """Fallback para TextGrid do MFA — mantém compatibilidade."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from karaoke.textgrid_parser import extract_words_and_phones
        from karaoke.corrector_config import CorrectorConfig
    except ImportError as e:
        print(f"ERRO: Módulos legados não encontrados: {e}")
        sys.exit(1)

    _progress(10, "Lendo TextGrid MFA...")

    config = CorrectorConfig()
    min_word = 0.03
    max_word = config.max_word_sec_voice

    tg_content = tg_path.read_text(encoding="utf-8")

    try:
        mappings = extract_words_and_phones(tg_content)
        print(f"  {len(mappings)} palavras mapeadas com fonemas.")
    except Exception as e:
        print(f"ERRO ao extrair mapeamento: {e}")
        sys.exit(1)

    _progress(20, f"{len(mappings)} palavras carregadas")

    PRE_ROLL  = 1.0
    POST_ROLL = 0.5
    events = []
    word_idx = 0
    total_lines = len(lyrics_lines)

    # Layer collision tracker
    layer_ends = []

    for line_num, line in enumerate(lyrics_lines):
        line_words = line.split()
        if not line_words or word_idx >= len(mappings):
            continue

        line_mappings = []
        for _ in line_words:
            if word_idx < len(mappings):
                line_mappings.append(mappings[word_idx])
                word_idx += 1

        if not line_mappings:
            continue

        line_start_audio = line_mappings[0].word.start
        line_end_audio   = line_mappings[-1].word.end
        start_visual = max(0.0, line_start_audio - PRE_ROLL)
        end_visual   = line_end_audio + POST_ROLL

        # Layer anti-collision
        layer = 0
        for i, le in enumerate(layer_ends):
            if start_visual >= le + 0.05:
                layer = i
                layer_ends[i] = end_visual
                break
        else:
            layer = len(layer_ends)
            layer_ends.append(end_visual)

        margin_v = 60 + layer * 110
        k_parts = []
        current_time = start_visual

        for i, lw in enumerate(line_words):
            if word_idx - len(line_words) + i < len(mappings):
                m = line_mappings[i] if i < len(line_mappings) else None
                if not m:
                    k_parts.append(f" {lw}")
                    continue

                gap = m.word.start - current_time
                if gap > 0.001:
                    gap_cs = max(0, int(round(gap * 100)))
                    k_parts.append(f"{{\\k{gap_cs}}}" if i == 0 else f"{{\\k{gap_cs}}} ")
                elif i > 0:
                    k_parts.append("{\\k0} ")

                word_dur = max(min_word, min(max_word, m.word.duration))
                dur_cs = int(round(word_dur * 100))
                color_dur = dur_cs * 10
                k_parts.append(f"{{\\kf{dur_cs}\\t(0,{color_dur},\\1c&H00FFFF&)}}{m.word.text}")
                current_time = m.word.start + word_dur
            else:
                k_parts.append(f" {lw}")

        k_text = "".join(k_parts)
        start_ass = format_ass_time(start_visual)
        end_ass   = format_ass_time(end_visual)
        events.append(
            f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,"
            f"{{\\an2\\pos(640,{margin_v})}}{k_text}"
        )

        if line_num % 10 == 0:
            pct = 20 + int((line_num / total_lines) * 60)
            _progress(pct, f"Linha {line_num + 1}/{total_lines} (legacy)...")

    _progress(80, "Eventos ASS gerados (modo legacy)")
    return events, layer_ends


# ── Header ASS ────────────────────────────────────────────────────────────────

# Cor primária dos adlibs: laranja suave (&HAABBGGRR no ASS = &H0045A0FF em BGR)
# Highlight dos adlibs: mesmo ciano da letra principal (&H00FFFF00 = amarelo ciano)
ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Cabin,62,&H00F0F8FF,&H0000FFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0.5,0,1,2.5,1.5,2,30,30,60,1
Style: Adlib,Cabin,46,&H00A0C8FF,&H0000FFFF,&H00000000,&H96000000,-1,1,0,0,100,100,0.5,0,1,2.0,1.2,2,30,30,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# ── Adlibs ────────────────────────────────────────────────────────────────────

def build_adlib_events(adlibs: list, layer_ends: list) -> list:
    """
    Gera eventos ASS para adlibs detectados pelo Gemini (adlibs_timing.json).

    Cada adlib é renderizado com o estilo Adlib (itálico, cor laranja clara).
    O efeito \\kf é aplicado na duração total do adlib — sem char-level porque
    o Gemini retorna apenas timestamps de segmento, não por caractere.

    Adlibs usam o mesmo sistema de layer anti-colisão da letra principal,
    então nunca se sobrepõem visualmente a uma linha que já está na tela.

    Formato de entrada (adlibs_timing.json):
      [{"text": "yeah", "start": 23.4, "end": 24.1, "type": "adlib"}, ...]
    """
    PRE_ROLL  = 0.1   # adlibs têm menos pre-roll — aparecem mais "na hora"
    POST_ROLL = 0.3

    events = []

    for adlib in adlibs:
        text = adlib.get("text", "").strip()
        if not text:
            continue

        t_start = adlib.get("start", 0.0)
        t_end   = adlib.get("end",   t_start + 1.0)

        start_visual = max(0.0, t_start - PRE_ROLL)
        end_visual   = t_end + POST_ROLL

        # Layer anti-colisão: mesmo pool da letra principal
        layer = 0
        for i, le in enumerate(layer_ends):
            if start_visual >= le + 0.05:
                layer = i
                layer_ends[i] = end_visual
                break
        else:
            layer = len(layer_ends)
            layer_ends.append(end_visual)

        margin_v = 60 + layer * 110

        # kf na duração total do segmento — highlight corre da esquerda p/ direita
        dur_cs   = max(1, int(round((t_end - t_start) * 100)))
        color_dur = dur_cs * 10
        # Texto em itálico via override inline + estilo Adlib
        k_text = (
            f"{{\\i1\\kf{dur_cs}\\t(0,{color_dur},\\1c&H00FFFF&)}}{text}{{\\i0}}"
        )

        start_ass = format_ass_time(start_visual)
        end_ass   = format_ass_time(end_visual)

        events.append(
            f"Dialogue: {layer},{start_ass},{end_ass},Adlib,,0,0,0,,"
            f"{{\\an2\\pos(640,{margin_v})}}{k_text}"
        )

    return events


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print("=== Step 09: Video Rendering (ASS & MP4) ===")
    _progress(0, "Iniciando geração de legendas e vídeo...")

    word_timing_path     = kpaths.word_timing_json(job_id)
    word_timing_fixed_path = kpaths.alignment_dir(job_id) / "word_timing_fixed.json"
    fused_alignment_path = kpaths.fused_alignment_json(job_id)
    adlibs_path          = kpaths.adlibs_json(job_id)
    tg_corrected         = kpaths.alignment_dir(job_id) / "song.corrected.TextGrid"
    tg_original          = kpaths.alignment_dir(job_id) / "song.TextGrid"
    lyrics_txt           = kpaths.lyrics_txt(job_id)
    out_ass              = kpaths.final_ass(job_id)

    # ── Valida letra ──────────────────────────────────────────────────────────
    if not lyrics_txt.exists():
        print(f"ERRO: Letra não encontrada: {lyrics_txt}")
        sys.exit(1)

    lyrics_lines = [
        l.strip() for l in lyrics_txt.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    print(f"  {len(lyrics_lines)} linhas de letra carregadas")

    # ── Carrega adlibs (opcional) ─────────────────────────────────────────────
    adlibs = []
    if adlibs_path.exists():
        try:
            adlibs = json.loads(adlibs_path.read_text(encoding="utf-8"))
            # Filtra só os marcados como adlib (ignora segmentos de letra)
            adlibs = [a for a in adlibs if a.get("type") == "adlib" and a.get("text", "").strip()]
            print(f"  {len(adlibs)} adlibs carregados de adlibs_timing.json")
        except Exception as e:
            print(f"  Aviso: falha ao carregar adlibs ({e}) — continuando sem eles")
            adlibs = []
    else:
        print("  adlibs_timing.json não encontrado — adlibs desativados")

    # ── Seleciona modo de timing principal ────────────────────────────────────
    # layer_ends é compartilhado entre letra principal e adlibs para evitar
    # colisão visual — build_ass_from_ctc o recebe por referência via retorno
    if word_timing_fixed_path.exists():
        _progress(5, "Carregando word_timing_fixed.json...")
        word_timing = json.loads(word_timing_fixed_path.read_text(encoding="utf-8"))
        if word_timing:
            print(f"  Modo: Onset DTW Fixed word-level ({len(word_timing)} palavras)")
            events, layer_ends = build_ass_from_ctc(word_timing, lyrics_lines)
        else:
            print("ERRO: word_timing_fixed.json existe mas está vazio.")
            sys.exit(1)

    elif fused_alignment_path.exists():
        _progress(5, "Carregando fused_alignment.json (SOFA + ROSVOT)...")
        word_timing = json.loads(fused_alignment_path.read_text(encoding="utf-8"))
        if word_timing:
            print(f"  Modo: SOFA-ROSVOT Fused ({len(word_timing)} palavras)")
            events, layer_ends = build_ass_from_ctc(word_timing, lyrics_lines)
        else:
            print("ERRO: fused_alignment.json existe mas está vazio.")
            sys.exit(1)

    elif word_timing_path.exists():
        _progress(5, "Carregando word_timing.json...")
        word_timing = json.loads(word_timing_path.read_text(encoding="utf-8"))
        if word_timing:
            print(f"  Modo: WhisperX word-level ({len(word_timing)} palavras)")
            events, layer_ends = build_ass_from_ctc(word_timing, lyrics_lines)
        else:
            print("ERRO: word_timing.json existe mas está vazio.")
            sys.exit(1)

    elif char_timing_path.exists():
        _progress(5, "Carregando char_timing.json...")
        char_timing = json.loads(char_timing_path.read_text(encoding="utf-8"))
        if char_timing:
            print(f"  Modo: CTC (char_timing.json) - {len(char_timing)} palavras")
            events, layer_ends = build_ass_from_ctc(char_timing, lyrics_lines)
        else:
            print("ERRO: char_timing.json existe mas está vazio.")
            sys.exit(1)

    elif tg_corrected.exists() or tg_original.exists():
        tg_path = tg_corrected if tg_corrected.exists() else tg_original
        print(f"  Modo: Legacy TextGrid ({tg_path.name})")
        _progress(5, f"Carregando {tg_path.name}...")
        events, layer_ends = build_ass_from_textgrid(tg_path, lyrics_lines)

    else:
        print("ERRO: Nenhuma fonte de timing encontrada.")
        print(f"  Procurei em:")
        print(f"    {word_timing_fixed_path}")
        print(f"    {word_timing_path}")
        print(f"    {char_timing_path}")
        sys.exit(1)

    # ── Gera eventos de adlibs e injeta na timeline ───────────────────────────
    if adlibs:
        _progress(83, f"Renderizando {len(adlibs)} adlibs...")
        adlib_events = build_adlib_events(adlibs, layer_ends)
        print(f"  {len(adlib_events)} eventos de adlib gerados")

        # Mescla letra + adlibs ordenados por tempo de início
        def _event_start(ev: str) -> float:
            try:
                parts = ev.split(",", 3)
                return sum(
                    float(x) * m for x, m in
                    zip(reversed(parts[1].strip().split(":")), [1, 60, 3600])
                )
            except Exception:
                return 0.0

        all_events = events + adlib_events
        all_events.sort(key=_event_start)
        events = all_events

    # ── Escreve ASS ───────────────────────────────────────────────────────────
    _progress(85, "Escrevendo arquivo ASS...")
    out_ass.parent.mkdir(parents=True, exist_ok=True)

    with open(out_ass, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER)
        for ev in events:
            f.write(ev + "\n")

    size_kb = out_ass.stat().st_size / 1024
    lyric_count = len([e for e in events if ",Default," in e])
    adlib_count = len([e for e in events if ",Adlib," in e])
    print(f"  {lyric_count} linhas de letra + {adlib_count} adlibs ({size_kb:.1f} KB)")
    _progress(100, f"karaoke.ass gerado — {len(events)} linhas totais")
    # ── Renderiza Vídeo Final ────────────────────────────────────────────────
    _progress(90, "Renderizando vídeo final (FFmpeg)...")
    
    input_video = kpaths.input_video(job_id)
    if not input_video.exists():
        # Fallback para imagem estática se vídeo não existir
        input_video = kpaths.input_thumb(job_id)
        
    out_mp4 = kpaths.output_video(job_id)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    
    # Audio sources
    instrumental = kpaths.separation_dir(job_id) / "htdemucs" / kpaths.input_job_dir(job_id).name / "no_vocals.wav"
    vocals = kpaths.vocals_listen(job_id)

    # Command: Mix instrumental + vocals + subtitiles
    # This is a complex ffmpeg filter chain
    cmd_video = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-i", str(instrumental),
        "-i", str(vocals),
        "-filter_complex", 
        f"[1:a][2:a]amix=inputs=2:duration=first[a];[0:v]subtitles='{str(out_ass).replace('\\', '/')}'[v]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        str(out_mp4)
    ]
    
    print(f"  Encoding video to {out_mp4}...")
    try:
        subprocess.run(cmd_video, check=True, capture_output=True)
        print(f"✓ Vídeo final gerado: {out_mp4.name}")
    except subprocess.CalledProcessError as e:
        print(f"ERRO ao renderizar vídeo: {e.stderr.decode()}")
        sys.exit(1)

    _progress(100, "Video Rendering concluído.")


if __name__ == "__main__":
    main()
