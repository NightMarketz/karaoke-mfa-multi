"""
06_whisperx_rescue.py — Alinhamento forçado pela letra com WhisperX + wav2vec2.

Roda em modo Full quando não há confidence_report.json (sem CTC anterior).
Roda em modo Rescue quando confidence_report.rescue_needed == True.

Refinamentos v2:
  1. Detecção de onset vocal via RMS — evita que intro musical seja absorvida
  2. Normalização de hífens/apóstrofos — evita divergência de contagem de palavras
  3. Pós-processamento de baixa confiança — redistribui palavras score < 0.5

Inputs  (via --job-id):
  work/jobs/{job_id}/05_alignment/confidence_report.json
  work/jobs/{job_id}/05_alignment/word_timing.json
  work/jobs/{job_id}/05_alignment/char_timing.json
  work/jobs/{job_id}/04_mfa_corpus/song.lab
  work/jobs/{job_id}/03_vocals_clean/vocals_raw.wav
"""
import json
import sys
import io
import math
import torch
import argparse
import numpy as np
from pathlib import Path

# Force UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths

try:
    import whisperx
except ImportError:
    print("ERRO: 'whisperx' não instalado. Este passo requer o WhisperX para rodar.")
    print("Execute: pip install whisperx")
    sys.exit(1)


def _progress(pct: int, msg: str = ""):
    if msg:
        print(f"PROGRESS: {pct} | {msg}", flush=True)
    else:
        print(f"PROGRESS: {pct}", flush=True)


DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
COMPUTE_TYPE = "int8" if DEVICE == "cuda" else "float32"


# ── Fix 1: Detecção de onset vocal via RMS ────────────────────────────────────

def detect_vocal_onset(audio: np.ndarray, sr: int = 16000,
                        frame_ms: int = 20, threshold_db: float = -40.0) -> float:
    """
    Retorna o timestamp (segundos) do primeiro frame com energia vocal detectável.
    Evita que silêncios e intros musicais sejam absorvidos pela primeira palavra.
    
    threshold_db: energia mínima em dBFS para considerar como voz (-40 é conservador)
    """
    frame_size = int(sr * frame_ms / 1000)
    threshold_linear = 10 ** (threshold_db / 20.0)
    
    for i in range(0, len(audio) - frame_size, frame_size):
        frame = audio[i : i + frame_size]
        rms = math.sqrt(float(np.mean(frame.astype(np.float64) ** 2)))
        if rms > threshold_linear:
            onset_sec = i / sr
            # Recua 0.1s para não cortar o ataque da primeira sílaba
            return max(0.0, onset_sec - 0.1)
    
    return 0.0  # fallback: começo do arquivo


# ── Fix 2: Normalização de texto ──────────────────────────────────────────────

def normalize_lyrics(text: str) -> list[str]:
    """
    Normaliza a letra para corresponder ao que o wav2vec2 espera.
    - Remove pontuação que quebra palavras (hífens dentro de palavras)
    - Mantém apóstrofos dentro de palavras (don't → don't, não separa)
    - Remove pontuação no fim/início de palavras
    - Retorna lista de palavras limpas
    """
    import re
    words = []
    for raw in text.split():
        # Remove pontuação nas bordas (vírgula, ponto, exclamação, etc.)
        w = re.sub(r"^[^\w']+|[^\w']+$", "", raw)
        # Troca hífen por espaço (words-like → words like)
        if "-" in w:
            parts = [p for p in w.split("-") if p]
            words.extend(parts)
        elif w:
            words.append(w)
    return words


# ── Fix 3: Pós-processamento de baixa confiança ───────────────────────────────

def fix_low_confidence(words: list[dict],
                        score_threshold: float = 0.5,
                        max_word_duration: float = 8.0) -> list[dict]:
    """
    Corrige palavras de baixa confiança redistribuindo seus timestamps.
    
    Estratégias por caso:
    - Palavra com duração > max_word_duration: comprimir para max e distribuir espaço
    - Palavra isolada de baixa confiança entre duas boas: interpolar linearmente
    - Bloco contíguo de baixa confiança: dividir o intervalo igualmente
    """
    if not words:
        return words

    result = [dict(w) for w in words]
    n = len(result)

    # Passa 1: Comprimir palavras com duração absurda (> max_word_duration)
    for i, w in enumerate(result):
        dur = w["end"] - w["start"]
        if dur > max_word_duration:
            # Encontra o próximo start confiável
            next_start = result[i + 1]["start"] if i + 1 < n else w["end"]
            # Comprime: usa no máximo max_word_duration ou o espaço disponível
            new_end = min(w["start"] + max_word_duration, next_start - 0.05)
            result[i]["end"] = round(max(w["start"] + 0.1, new_end), 4)
            result[i]["score"] = round(result[i].get("score", 0.0) * 0.5, 4)  # penaliza

    # Passa 2: Interpolar palavras de baixa confiança entre âncoras boas
    i = 0
    while i < n:
        w = result[i]
        if w.get("score", 1.0) >= score_threshold:
            i += 1
            continue

        # Encontra início e fim do bloco de baixa confiança
        block_start_idx = i
        while i < n and result[i].get("score", 1.0) < score_threshold:
            i += 1
        block_end_idx = i  # exclusive

        # Âncoras
        anchor_start = result[block_start_idx - 1]["end"] if block_start_idx > 0 else result[block_start_idx]["start"]
        anchor_end   = result[block_end_idx]["start"] if block_end_idx < n else result[block_end_idx - 1]["end"]

        block_size = block_end_idx - block_start_idx
        if block_size <= 0 or anchor_end <= anchor_start:
            continue

        # Distribui igualmente
        slot = (anchor_end - anchor_start) / block_size
        for j in range(block_size):
            idx = block_start_idx + j
            new_start = round(anchor_start + j * slot, 4)
            new_end   = round(anchor_start + (j + 1) * slot - 0.01, 4)
            result[idx]["start"] = new_start
            result[idx]["end"]   = new_end
            result[idx]["interpolated"] = True

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print("=== Step 06: WhisperX Alinhamento Forçado v2 ===")
    _progress(0, "Checando modo de operação...")

    conf_path        = kpaths.alignment_dir(job_id) / "confidence_report.json"
    word_timing_path = kpaths.word_timing_json(job_id)
    char_timing_path = kpaths.char_timing_json(job_id)
    vocals_path      = kpaths.vocals_raw(job_id)
    lab_path         = kpaths.corpus_dir(job_id) / "song.lab"

    full_alignment_mode = not conf_path.exists()

    # ═══════════════════════════════════════════════════════
    # MODO FULL — sem CTC anterior, faz alinhamento completo
    # ═══════════════════════════════════════════════════════
    if full_alignment_mode:
        print("  [Modo Full] Alinhamento forçado pela letra com WhisperX.")

        if not lab_path.exists():
            print(f"ERRO: Letra não encontrada em {lab_path}")
            sys.exit(1)
        if not vocals_path.exists():
            print(f"ERRO: Áudio não encontrado em {vocals_path}")
            sys.exit(1)

        _progress(5, "Lendo letra e áudio...")
        raw_lyrics = lab_path.read_text(encoding="utf-8").strip()

        # Fix 2: Normalizar texto antes de tudo
        all_words = normalize_lyrics(raw_lyrics)
        print(f"  Letra: {len(raw_lyrics.split())} palavras brutas → {len(all_words)} normalizadas")

        try:
            audio_full = whisperx.load_audio(str(vocals_path))
            sr = 16000
            audio_duration = len(audio_full) / sr

            # Fix 1: Detectar onset vocal real
            _progress(10, "Detectando onset vocal...")
            vocal_onset = detect_vocal_onset(audio_full, sr)
            print(f"  Onset vocal detectado: {vocal_onset:.2f}s (áudio total: {audio_duration:.1f}s)")

            # Monta segmentos da letra ancorados após o onset
            # Distribui as palavras proporcionalmente no intervalo [onset, end]
            usable_duration = audio_duration - vocal_onset
            words_per_seg = 10
            n_segs = max(1, math.ceil(len(all_words) / words_per_seg))

            segments = []
            for i in range(n_segs):
                chunk_words = all_words[i * words_per_seg : (i + 1) * words_per_seg]
                seg_start = vocal_onset + (i / n_segs) * usable_duration
                seg_end   = vocal_onset + ((i + 1) / n_segs) * usable_duration
                segments.append({
                    "text":  " ".join(chunk_words),
                    "start": round(seg_start, 3),
                    "end":   round(seg_end, 3),
                    "words": [{"word": w} for w in chunk_words],
                })

            _progress(15, "Carregando modelo de alinhamento WhisperX...")
            align_model, metadata = whisperx.load_align_model(
                language_code="en", device=DEVICE
            )

            _progress(40, f"Alinhando {len(all_words)} palavras pela letra...")
            wx_aligned = whisperx.align(
                segments, align_model, metadata,
                audio_full, device=DEVICE, return_char_alignments=True
            )

            raw_words = []
            raw_chars = []

            for seg in wx_aligned.get("segments", []):
                for ww in seg.get("words", []):
                    if "start" not in ww or "end" not in ww:
                        continue
                    raw_words.append({
                        "word":  ww["word"],
                        "start": round(ww["start"], 4),
                        "end":   round(ww["end"],   4),
                        "score": round(ww.get("score", 1.0), 4),
                    })
                    for ch in ww.get("chars", []):
                        if "start" in ch and "end" in ch:
                            raw_chars.append({
                                "char":  ch["char"],
                                "word":  ww["word"],
                                "start": round(ch["start"], 4),
                                "end":   round(ch["end"],   4),
                                "score": round(ch.get("score", 1.0), 4),
                            })

            if not raw_words:
                print("ERRO: WhisperX não retornou nenhuma palavra alinhada.")
                sys.exit(1)

            # Fix 3: Corrigir baixa confiança
            _progress(80, "Aplicando correção de baixa confiança...")
            low_before = sum(1 for w in raw_words if w.get("score", 1.0) < 0.5)
            final_words = fix_low_confidence(raw_words)
            low_after = sum(1 for w in final_words if w.get("score", 1.0) < 0.5 and not w.get("interpolated"))
            interpolated = sum(1 for w in final_words if w.get("interpolated"))
            print(f"  Score < 0.5: {low_before} → {low_after} restantes ({interpolated} interpoladas)")

            # Stats finais
            scores = [w["score"] for w in final_words]
            avg_score = sum(scores) / len(scores) if scores else 0
            print(f"  Score médio: {avg_score:.3f} | Palavras: {len(final_words)}")

            _progress(95, "Salvando timings...")
            word_timing_path.parent.mkdir(parents=True, exist_ok=True)
            word_timing_path.write_text(json.dumps(final_words, indent=2), encoding="utf-8")
            if raw_chars:
                char_timing_path.write_text(json.dumps(raw_chars, indent=2), encoding="utf-8")
            elif char_timing_path.exists():
                char_timing_path.unlink()

            print(f"  ✅ {len(final_words)} palavras alinhadas pela letra.")
            _progress(100, f"{len(final_words)} palavras alinhadas | score médio {avg_score:.2f}")
            return

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  Falha no alinhamento forçado: {e}")
            sys.exit(1)

    # ═══════════════════════════════════════════════════════
    # MODO RESCUE — realinha só segmentos de baixa confiança
    # ═══════════════════════════════════════════════════════
    conf_report = json.loads(conf_path.read_text(encoding="utf-8"))
    if not conf_report.get("rescue_needed", False):
        print("  Rescue não necessário. Pulando.")
        _progress(100, "Rescue não necessário")
        return

    word_timing = json.loads(word_timing_path.read_text(encoding="utf-8"))
    char_timing = json.loads(char_timing_path.read_text(encoding="utf-8")) if char_timing_path.exists() else []

    LOW_CONF    = 0.55
    CONTEXT_SEC = 0.5

    bad_words = [w for w in word_timing if w.get("score", 1.0) < LOW_CONF]
    regions   = []
    if bad_words:
        r_start = bad_words[0]["start"] - CONTEXT_SEC
        r_end   = bad_words[0]["end"]   + CONTEXT_SEC
        r_words = [bad_words[0]]
        for w in bad_words[1:]:
            if w["start"] - CONTEXT_SEC <= r_end:
                r_end = max(r_end, w["end"] + CONTEXT_SEC)
                r_words.append(w)
            else:
                regions.append((max(0, r_start), r_end, r_words))
                r_start = w["start"] - CONTEXT_SEC
                r_end   = w["end"]   + CONTEXT_SEC
                r_words = [w]
        regions.append((max(0, r_start), r_end, r_words))

    print(f"  {len(regions)} regiões para rescue ({len(bad_words)} palavras)")
    if not regions:
        _progress(100, "Nenhuma região detectada")
        return

    _progress(10, "Carregando modelo de alinhamento WhisperX...")
    try:
        align_model, metadata = whisperx.load_align_model(language_code="en", device=DEVICE)
        audio_full = whisperx.load_audio(str(vocals_path))
    except Exception as e:
        print(f"  Falha ao inicializar WhisperX: {e}")
        return

    sr = 16000
    total_regions = len(regions)
    for idx, (r_start, r_end, bad) in enumerate(regions):
        pct = 30 + int((idx / total_regions) * 60)
        _progress(pct, f"Resgatando região {idx+1}/{total_regions} ({r_start:.1f}s)...")

        chunk = audio_full[int(r_start * sr) : int(r_end * sr)]
        chunk_dur = len(chunk) / sr

        # Monta segmentos forçados pela letra da região
        region_words = normalize_lyrics(" ".join(w["word"] for w in bad))
        n_segs = max(1, math.ceil(len(region_words) / 5))
        segments = []
        for i in range(n_segs):
            cw = region_words[i * 5 : (i + 1) * 5]
            segments.append({
                "text":  " ".join(cw),
                "start": round((i / n_segs) * chunk_dur, 3),
                "end":   round(((i + 1) / n_segs) * chunk_dur, 3),
                "words": [{"word": w} for w in cw],
            })

        try:
            wx_aligned = whisperx.align(
                segments, align_model, metadata,
                chunk, device=DEVICE, return_char_alignments=True
            )
        except Exception as e:
            print(f"  Aviso: falha no whisperx em {r_start:.1f}-{r_end:.1f}s ({e})")
            continue

        word_search_start = 0
        char_search_start = 0
        for seg in wx_aligned.get("segments", []):
            for ww in seg.get("words", []):
                if "start" not in ww or "end" not in ww:
                    continue
                ww["start"]   = round(ww["start"] + r_start, 4)
                ww["end"]     = round(ww["end"]   + r_start, 4)
                ww["rescued"] = True
                for ch in ww.get("chars", []):
                    if "start" in ch and "end" in ch:
                        ch["start"] = round(ch["start"] + r_start, 4)
                        ch["end"]   = round(ch["end"]   + r_start, 4)
                for i in range(word_search_start, len(word_timing)):
                    orig = word_timing[i]
                    if orig["word"].lower().strip(".,!?") == ww["word"].lower().strip(".,!?"):
                        if r_start <= orig.get("start", r_start) <= r_end:
                            word_timing[i] = {k: v for k, v in ww.items() if k != "chars"}
                            word_search_start = i + 1
                            break
                for j in range(char_search_start, len(char_timing)):
                    orig_c = char_timing[j]
                    if orig_c["word"].lower().strip(".,!?") == ww["word"].lower().strip(".,!?"):
                        if r_start <= orig_c.get("start", r_start) <= r_end:
                            char_timing[j] = ww
                            char_search_start = j + 1
                            break

    _progress(95, "Salvando timings resgatados...")
    word_timing_path.write_text(json.dumps(word_timing, indent=2), encoding="utf-8")
    if char_timing:
        char_timing_path.write_text(json.dumps(char_timing, indent=2), encoding="utf-8")
    elif char_timing_path.exists():
        char_timing_path.unlink()

    rescued = sum(1 for w in word_timing if w.get("rescued"))
    print(f"  ✅ {rescued} palavras resgatadas pelo WhisperX.")
    _progress(100, f"{rescued} palavras resgatadas")


if __name__ == "__main__":
    main()
