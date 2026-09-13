"""
03_forced_align.py — Word + Char alignment via CTC Forced Aligner.

Inputs  (via --job-id):
  work/jobs/{job_id}/03_vocals_clean/vocals_raw.wav
  work/jobs/{job_id}/04_mfa_corpus/song.lab

Outputs (via --job-id):
  work/jobs/{job_id}/05_alignment/word_timing.json
  work/jobs/{job_id}/05_alignment/char_timing.json
  work/jobs/{job_id}/05_alignment/confidence_report.json
"""
import json
import os
import sys
import torch
import argparse
from pathlib import Path

# Enforce UTF-8 for I/O in Windows terminals
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths

# Provide a fallback try-catch in case ctc_forced_aligner requires external installs.
try:
    from ctc_forced_aligner import (
        load_audio,
        load_alignment_model,
        generate_emissions,
        get_alignments,
        get_spans,
        postprocess_results,
    )
except ImportError:
    print("ERRO: 'ctc-forced-aligner' não encontrado no ambiente.")
    print("Execute: pip install ctc-forced-aligner")
    sys.exit(1)

def _progress(pct: int, msg: str = ""):
    """Emite linha de progresso parseável pelo server.py."""
    if msg:
        print(f"PROGRESS: {pct} | {msg}", flush=True)
    else:
        print(f"PROGRESS: {pct}", flush=True)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE  = torch.float16 if DEVICE == "cuda" else torch.float32

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print("=== Step 03: CTC Forced Alignment ===")
    _progress(0, "Iniciando alinhador...")

    vocals_path  = kpaths.vocals_raw(job_id)
    lab_path     = kpaths.corpus_dir(job_id) / "song.lab"
    out_dir      = kpaths.alignment_dir(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not vocals_path.exists():
        raise FileNotFoundError(vocals_path)
    if not lab_path.exists():
        raise FileNotFoundError(lab_path)

    # 1. Carrega texto normalizado
    _progress(5, "Carregando letra normalizada...")
    transcript_words = lab_path.read_text(encoding="utf-8").split()
    print(f"  Palavras para alinhar: {len(transcript_words)}")

    # 2. Carrega modelo de alinhamento
    _progress(10, f"Carregando modelo CTC ({DEVICE})...")
    alignment_model, alignment_tokenizer, alignment_dictionary = \
        load_alignment_model(device=DEVICE, dtype=DTYPE)

    # 3. Carrega áudio
    _progress(30, "Carregando áudio (16kHz)...")
    aud_result = load_audio(str(vocals_path), target_sample_rate=16000)
    audio = aud_result[0] if isinstance(aud_result, tuple) else aud_result

    # 4. Gera emissões CTC
    _progress(40, "Iniciando Inferência CTC (GPU)...")
    emissions, stride = generate_emissions(
        alignment_model,
        audio,
        batch_size=4 if DEVICE == "cpu" else 8,
    )

    # 5. Forced alignment
    _progress(70, "Calculando alinhamento...")
    tokens_starred, spans_starred = get_alignments(
        emissions,
        transcript_words,
        alignment_dictionary,
    )
    spans = get_spans(tokens_starred, spans_starred)

    # 6. Postprocess
    _progress(85, "Processando timings finais...")
    word_results = postprocess_results(
        transcript_words, spans, stride, ass_compatible=False
    )
    char_results = postprocess_results(
        transcript_words, spans, stride, ass_compatible=True
    )

    # 7. Calcula confiança por palavra
    LOW_CONF_THRESHOLD = 0.55
    low_conf_words = [
        w for w in word_results if w.get("score", 1.0) < LOW_CONF_THRESHOLD
    ]
    mean_score = sum(w.get("score", 1.0) for w in word_results) / len(word_results)

    confidence_report = {
        "mean_score": round(mean_score, 4),
        "low_confidence_count": len(low_conf_words),
        "low_confidence_words": [
            {"word": w["word"], "start": w["start"], "score": w.get("score")}
            for w in low_conf_words[:20]
        ],
        "rescue_needed": mean_score < 0.65 or len(low_conf_words) > len(transcript_words) * 0.15,
    }

    # 8. Salva outputs
    _progress(95, "Salvando resultados...")
    out_dir.joinpath("word_timing.json").write_text(
        json.dumps(word_results, indent=2), encoding="utf-8"
    )
    out_dir.joinpath("char_timing.json").write_text(
        json.dumps(char_results, indent=2), encoding="utf-8"
    )
    out_dir.joinpath("confidence_report.json").write_text(
        json.dumps(confidence_report, indent=2), encoding="utf-8"
    )

    print(f"  Score médio de confiança: {mean_score:.3f}")
    print(f"  Palavras baixa confiança: {len(low_conf_words)}")

    _progress(100, f"Confiança: {int(mean_score*100)}%")

if __name__ == "__main__":
    main()
