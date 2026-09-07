"""
03c_gemini_transcribe.py — Transcrição livre + detecção de adlibs via Gemini API.

Roda DEPOIS do 03b (WhisperX forced alignment) e ANTES do 05c (Onset DTW).

O que faz:
  1. Divide o vocal isolado em chunks de 50s
  2. Opcionalmente lê adlib_hints da letra (parenteses Suno) e regiões
     sem palavras alinhadas (unmapped_vocal_regions do corrector) para
     alimentar o Gemini com contexto — ele confirma em vez de descobrir do zero
  3. Manda cada chunk para o Gemini com o prompt enriquecido
  4. Compara a transcrição livre com a letra fornecida
  5. Identifica adlibs (o que o Gemini ouviu mas não está na letra)
  6. Salva adlibs_timing.json com timestamps aproximados de cada adlib
  7. NÃO modifica o word_timing.json — apenas adiciona informação

Inputs  (via --job-id):
  work/jobs/{job_id}/03_vocals_clean/vocals_raw.wav
  input/jobs/{job_id}/lyrics.txt
  work/jobs/{job_id}/05_alignment/adlib_hints.json      (opcional, do lyrics_cleaner)
  work/jobs/{job_id}/05_alignment/unmapped_regions.json (opcional, do music_gap_corrector)

Outputs (via --job-id):
  work/jobs/{job_id}/05_alignment/gemini_transcript.json
  work/jobs/{job_id}/05_alignment/adlibs_timing.json

Modelo recomendado (free tier):
  gemini-1.5-flash  → 1500 req/dia, 15 req/min, suporte a audio via File API
  gemini-2.0-flash  → alternativa mais recente

  NAO usar: gemini-*-native-audio-* (sao Live API, nao generateContent)
"""

import os
import re
import sys
import io
import json
import time
import wave
import argparse
import tempfile
from pathlib import Path

# Force UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths

# ── Modelo padrão ─────────────────────────────────────────────────────────────
DEFAULT_MODEL  = "gemini-1.5-flash"
RATE_LIMIT_SLEEP = 4.5   # segundos entre chunks (free tier: 15 req/min)


# ── Progresso ─────────────────────────────────────────────────────────────────

def _progress(pct: int, msg: str = ""):
    tag = f" | {msg}" if msg else ""
    print(f"PROGRESS: {pct}{tag}", flush=True)


# ── Áudio: split em chunks WAV ────────────────────────────────────────────────

def split_wav_chunks(wav_path: Path, chunk_sec: float = 50.0) -> list:
    """
    Divide um WAV em chunks de chunk_sec segundos usando stdlib (wave).
    Retorna lista de dicts: {path, start_sec, end_sec, chunk_idx}
    """
    chunks  = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="gemini_chunks_"))

    with wave.open(str(wav_path), "rb") as wf:
        sr       = wf.getframerate()
        n_ch     = wf.getnchannels()
        sw       = wf.getsampwidth()
        n_frames = wf.getnframes()
        total_s  = n_frames / sr

        frames_chunk = int(sr * chunk_sec)
        idx = 0
        pos = 0

        while pos < n_frames:
            wf.setpos(pos)
            count = min(frames_chunk, n_frames - pos)
            data  = wf.readframes(count)

            t_start = pos / sr
            t_end   = min((pos + count) / sr, total_s)

            out = tmp_dir / f"chunk_{idx:03d}.wav"
            with wave.open(str(out), "wb") as wo:
                wo.setnchannels(n_ch)
                wo.setsampwidth(sw)
                wo.setframerate(sr)
                wo.writeframes(data)

            chunks.append({
                "path":      out,
                "start_sec": round(t_start, 3),
                "end_sec":   round(t_end,   3),
                "chunk_idx": idx,
            })
            pos += count
            idx += 1

    print(f"  {len(chunks)} chunks de ate {chunk_sec:.0f}s gerados")
    return chunks


# ── Contexto: carrega hints externos ─────────────────────────────────────────

def load_adlib_hints(hints_path: Path) -> list:
    """
    Carrega adlib_hints gerados pelo lyrics_cleaner.
    Suporta: [[line, text], ...] ou [{"line": N, "text": "..."}, ...]
    """
    if not hints_path.exists():
        return []
    try:
        raw = json.loads(hints_path.read_text(encoding="utf-8"))
        result = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                result.append({"line": item[0], "text": str(item[1])})
            elif isinstance(item, dict) and "text" in item:
                result.append(item)
        return result
    except Exception as e:
        print(f"  Aviso: falha ao carregar adlib_hints: {e}")
        return []


def load_unmapped_regions(regions_path: Path) -> list:
    """
    Carrega unmapped_vocal_regions gerados pelo music_gap_corrector.
    Suporta: [[start, end], ...] ou [{"start": x, "end": y}, ...]
    """
    if not regions_path.exists():
        return []
    try:
        raw = json.loads(regions_path.read_text(encoding="utf-8"))
        result = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                result.append((float(item[0]), float(item[1])))
            elif isinstance(item, dict):
                result.append((float(item.get("start", 0)), float(item.get("end", 0))))
        return result
    except Exception as e:
        print(f"  Aviso: falha ao carregar unmapped_regions: {e}")
        return []


def regions_in_chunk(regions: list, chunk_start: float, chunk_end: float) -> list:
    """Filtra regioes que se sobrepoem ao chunk, retorna com offset local."""
    result = []
    for s, e in regions:
        if e > chunk_start and s < chunk_end:
            local_s = round(max(s, chunk_start) - chunk_start, 2)
            local_e = round(min(e, chunk_end)   - chunk_start, 2)
            result.append((local_s, local_e))
    return result


# ── Gemini: prompt dinâmico ───────────────────────────────────────────────────

BASE_PROMPT = (
    "You are transcribing a vocal track from a song. Listen carefully and transcribe "
    "EVERYTHING you hear — including ad-libs, background vocals, filler words (oh, yeah, "
    "hey, etc.), repeated words, and any vocalizations not part of the main lyrics.\n\n"
    "Return a JSON object with this EXACT structure:\n"
    '{"transcript": "full text", "segments": ['
    '{"text": "phrase", "approx_start": 0.0, "approx_end": 2.5, "type": "lyric"}, '
    '{"text": "yeah", "approx_start": 2.8, "approx_end": 3.1, "type": "adlib"}]}\n\n'
    "Rules:\n"
    '- "type" must be "lyric" or "adlib"\n'
    '- "adlib" = anything not part of the main sung melody (fills, exclamations, background)\n'
    '- "lyric" = the main sung melody line\n'
    "- approx_start / approx_end are in seconds relative to the START of this audio clip\n"
    "- If unsure of exact words, write your best guess in [brackets]\n"
    "- Return ONLY the JSON object, no markdown, no other text"
)

HINT_SUFFIX = (
    "\n\nAdditional context — these phrases/regions are expected to appear as ad-libs. "
    "Pay special attention to them:\n{hints}"
)


def build_prompt(chunk_hint_lines: list, chunk_regions: list) -> str:
    hint_lines = list(chunk_hint_lines)
    for s, e in chunk_regions:
        hint_lines.append(f"  - Expected vocal at {s:.1f}s-{e:.1f}s (likely an ad-lib)")
    if hint_lines:
        return BASE_PROMPT + HINT_SUFFIX.format(hints="\n".join(hint_lines))
    return BASE_PROMPT


# ── Gemini: transcrição de um chunk ───────────────────────────────────────────

def transcribe_chunk(chunk_path: Path, api_key: str, model_name: str, prompt: str):
    """
    Sobe chunk para a Gemini File API e retorna JSON de transcricao.
    Rate limit inteligente: dorme apenas o delta necessario para respeitar 4.5s por request.
    Retorna None se falhar apos 3 tentativas.
    """
    try:
        import google.generativeai as genai
    except ImportError:
        print("ERRO: google-generativeai nao instalado. Execute: pip install google-generativeai")
        sys.exit(1)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    remote_file = None
    t_start = time.time()
    try:
        size_kb = chunk_path.stat().st_size / 1024
        print(f"    Upload {chunk_path.name} ({size_kb:.0f} KB)...", flush=True)
        remote_file = genai.upload_file(path=str(chunk_path), mime_type="audio/wav")

        for attempt in range(3):
            try:
                response = model.generate_content([remote_file, prompt])
                raw = response.text.strip()
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$",           "", raw)
                return json.loads(raw)

            except Exception as e:
                err = str(e).lower()
                if "429" in err or "quota" in err:
                    wait = 60 * (attempt + 1)
                    print(f"    Rate limit. Aguardando {wait}s...", flush=True)
                    time.sleep(wait)
                elif "500" in err or "503" in err:
                    wait = 10 * (attempt + 1)
                    print(f"    Erro servidor. Aguardando {wait}s...", flush=True)
                    time.sleep(wait)
                else:
                    print(f"    Erro (tentativa {attempt+1}): {e}", flush=True)
                    if attempt < 2:
                        time.sleep(5)
    finally:
        if remote_file:
            try:
                remote_file.delete()
            except Exception:
                pass
        # Rate limit inteligente: dorme apenas o delta necessario
        elapsed = time.time() - t_start
        delta = RATE_LIMIT_SLEEP - elapsed
        if delta > 0:
            time.sleep(delta)

    return None


# ── Classificação ─────────────────────────────────────────────────────────────

def normalize_word(w: str) -> str:
    return re.sub(r"[^\w']", "", w.lower()).strip("'")


def build_lyrics_vocab(lyrics_path: Path) -> set:
    text  = lyrics_path.read_text(encoding="utf-8")
    words = set()
    for line in text.splitlines():
        for w in line.split():
            nw = normalize_word(w)
            if nw:
                words.add(nw)
    return words


def classify_segments(segments: list, lyrics_vocab: set, chunk_offset: float):
    """
    Classifica segmentos em lyric / adlib.
    Retorna (lyrics_segs, adlib_segs) com timestamps absolutos.
    """
    lyric_segs = []
    adlib_segs = []

    for seg in segments:
        text     = seg.get("text", "").strip()
        seg_type = seg.get("type", "lyric")
        t_start  = round(seg.get("approx_start", 0.0) + chunk_offset, 3)
        t_end    = round(seg.get("approx_end",   0.0) + chunk_offset, 3)

        if not text:
            continue

        seg_words = [normalize_word(w) for w in text.split() if normalize_word(w)]
        in_lyrics = sum(1 for w in seg_words if w in lyrics_vocab)
        coverage  = in_lyrics / len(seg_words) if seg_words else 0

        # Adlib se Gemini marcou como adlib OU cobertura < 40% (segmento curto)
        is_adlib = seg_type == "adlib" or (coverage < 0.4 and len(seg_words) <= 3)

        entry = {
            "text":     text,
            "start":    t_start,
            "end":      t_end,
            "type":     "adlib" if is_adlib else "lyric",
            "coverage": round(coverage, 2),
        }
        (adlib_segs if is_adlib else lyric_segs).append(entry)

    return lyric_segs, adlib_segs


# ── Pipeline principal ────────────────────────────────────────────────────────

def run(
    wav_path:         Path,
    lyrics_path:      Path,
    out_dir:          Path,
    api_key:          str,
    chunk_sec:        float = 50.0,
    model_name:       str   = DEFAULT_MODEL,
    adlib_hints:      list  = None,
    unmapped_regions: list  = None,
):
    out_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = out_dir / "gemini_transcript.json"
    adlibs_path     = out_dir / "adlibs_timing.json"

    # ── Cache ─────────────────────────────────────────────────────────────────
    if transcript_path.exists() and adlibs_path.exists():
        print("  Cache encontrado — pulando Gemini.")
        adlibs = json.loads(adlibs_path.read_text(encoding="utf-8"))
        print(f"  {len(adlibs)} adlibs carregados do cache.")
        _progress(100, f"{len(adlibs)} adlibs (cache)")
        return adlibs

    adlib_hints      = adlib_hints      or []
    unmapped_regions = unmapped_regions or []

    # ── Vocabulário ───────────────────────────────────────────────────────────
    _progress(5, "Carregando letra...")
    lyrics_vocab = build_lyrics_vocab(lyrics_path)
    print(f"  Vocabulario: {len(lyrics_vocab)} palavras | "
          f"{len(adlib_hints)} hints | "
          f"{len(unmapped_regions)} regioes sem letra")

    # ── Split ─────────────────────────────────────────────────────────────────
    _progress(10, "Dividindo audio em chunks...")
    chunks = split_wav_chunks(wav_path, chunk_sec=chunk_sec)
    total  = len(chunks)

    hint_texts = [h.get("text", "") for h in adlib_hints if h.get("text")]

    # ── Transcrição ───────────────────────────────────────────────────────────
    all_transcript_segs = []
    all_adlibs          = []
    failed_chunks       = []

    for i, chunk in enumerate(chunks):
        pct = 15 + int((i / total) * 70)
        _progress(pct, f"Chunk {i+1}/{total} ({chunk['start_sec']:.0f}s-{chunk['end_sec']:.0f}s)")

        chunk_regions    = regions_in_chunk(unmapped_regions, chunk["start_sec"], chunk["end_sec"])
        chunk_hint_lines = [f'  - Expected ad-lib: "{t}"' for t in hint_texts]
        prompt           = build_prompt(chunk_hint_lines, chunk_regions)

        result = transcribe_chunk(chunk["path"], api_key, model_name, prompt)

        if result is None:
            print(f"  Aviso: chunk {i+1} falhou — ignorado.")
            failed_chunks.append(chunk["chunk_idx"])
            continue

        segs = result.get("segments", [])
        lyric_segs, adlib_segs = classify_segments(segs, lyrics_vocab, chunk["start_sec"])

        for seg in segs:
            seg["chunk_idx"] = chunk["chunk_idx"]
            seg["abs_start"] = round(seg.get("approx_start", 0) + chunk["start_sec"], 3)
            seg["abs_end"]   = round(seg.get("approx_end",   0) + chunk["start_sec"], 3)

        all_transcript_segs.extend(segs)
        all_adlibs.extend(adlib_segs)
        print(f"  Chunk {i+1}: {len(lyric_segs)} lyrics, {len(adlib_segs)} adlibs")

    # ── Limpeza ───────────────────────────────────────────────────────────────
    for chunk in chunks:
        try:
            chunk["path"].unlink(missing_ok=True)
        except Exception:
            pass
    try:
        if chunks:
            chunks[0]["path"].parent.rmdir()
    except Exception:
        pass

    # ── Salva ─────────────────────────────────────────────────────────────────
    _progress(90, "Salvando resultados...")

    transcript_path.write_text(
        json.dumps({
            "model":         model_name,
            "total_chunks":  total,
            "failed_chunks": failed_chunks,
            "segments":      all_transcript_segs,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    adlibs_path.write_text(
        json.dumps(all_adlibs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\n  {len(all_adlibs)} adlibs detectados")
    for a in all_adlibs[:10]:
        print(f"    [{a['start']:.1f}s-{a['end']:.1f}s] \"{a['text']}\"")
    if len(all_adlibs) > 10:
        print(f"    ... e mais {len(all_adlibs) - 10}")
    if failed_chunks:
        print(f"  Aviso: {len(failed_chunks)} chunks falharam: {failed_chunks}")

    _progress(100, f"{len(all_adlibs)} adlibs detectados")
    return all_adlibs


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Transcricao livre e deteccao de adlibs via Gemini API"
    )
    parser.add_argument("--job-id",    help="Job ID do pipeline")
    parser.add_argument("--wav",       help="Caminho para WAV vocal (modo standalone)")
    parser.add_argument("--lyrics",    help="Caminho para letra .txt (modo standalone)")
    parser.add_argument("--out-dir",   help="Diretorio de saida (modo standalone)")
    parser.add_argument("--api-key",   help="Gemini API key (ou env GEMINI_API_KEY)")
    parser.add_argument("--model",     default=DEFAULT_MODEL,
                        help=f"Modelo Gemini (default: {DEFAULT_MODEL})")
    parser.add_argument("--chunk-sec", type=float, default=50.0,
                        help="Duracao maxima por chunk em segundos (default: 50)")
    args = parser.parse_args()

    print("=== Step 03c: Gemini Transcription + Adlib Detection ===")

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("ERRO: GEMINI_API_KEY nao definida.")
        print("  Chave gratuita: https://aistudio.google.com/app/apikey")
        sys.exit(1)

    adlib_hints:      list = []
    unmapped_regions: list = []

    if args.job_id:
        wav_path    = kpaths.vocals_raw(args.job_id)
        lyrics_path = kpaths.lyrics_path(args.job_id)
        out_dir     = kpaths.alignment_dir(args.job_id)

        for p, label in [(wav_path, "Vocal"), (lyrics_path, "Letra")]:
            if not p.exists():
                print(f"ERRO: {label} nao encontrado: {p}"); sys.exit(1)

        adlib_hints      = load_adlib_hints(out_dir / "adlib_hints.json")
        unmapped_regions = load_unmapped_regions(out_dir / "unmapped_regions.json")

        if adlib_hints:
            preview = ", ".join(f'"{h["text"]}"' for h in adlib_hints[:5])
            print(f"  Adlib hints: {len(adlib_hints)} → {preview}")
        if unmapped_regions:
            print(f"  Regioes sem letra: {len(unmapped_regions)} segmentos VAD")

    elif args.wav and args.lyrics:
        wav_path    = Path(args.wav)
        lyrics_path = Path(args.lyrics)
        out_dir     = Path(args.out_dir) if args.out_dir else Path(".")
        for p, label in [(wav_path, "WAV"), (lyrics_path, "Letra")]:
            if not p.exists():
                print(f"ERRO: {label} nao encontrado: {p}"); sys.exit(1)
    else:
        parser.print_help()
        print("\nERRO: Use --job-id OU --wav + --lyrics")
        sys.exit(1)

    _progress(0, "Iniciando...")
    print(f"  Vocal:  {wav_path}")
    print(f"  Letra:  {lyrics_path}")
    print(f"  Saida:  {out_dir}")
    print(f"  Modelo: {args.model}")

    run(
        wav_path         = wav_path,
        lyrics_path      = lyrics_path,
        out_dir          = out_dir,
        api_key          = api_key,
        chunk_sec        = args.chunk_sec,
        model_name       = args.model,
        adlib_hints      = adlib_hints,
        unmapped_regions = unmapped_regions,
    )


if __name__ == "__main__":
    main()