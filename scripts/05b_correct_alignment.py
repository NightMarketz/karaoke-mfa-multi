"""
05b_correct_alignment.py — Step 05b: Music Gap Correction & VAD Clamping.

Reads the WhisperX word timing + vocal audio, applies VAD-based
correction to clamp drifted words and identifies unmapped vocal regions
(ad-libs) for Gemini transcription.

Inputs:
  work/jobs/{job_id}/03_vocals_clean/vocals_raw.wav
  work/jobs/{job_id}/05_alignment/word_timing.json

Outputs:
  work/jobs/{job_id}/05_alignment/word_timing.json (overwritten)
  work/jobs/{job_id}/05_alignment/unmapped_regions.json
  work/jobs/{job_id}/05_alignment/correction_report.json
"""
import json
import sys
import io
import argparse
from pathlib import Path

# Force UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths

from karaoke.vad import detect_voice
from karaoke.textgrid_parser import Interval
from karaoke.music_gap_corrector import correct_alignment, CorrectorConfig

# Logic imports

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print(f"=== Fase E.5: Music Gap Correction (Job: {job_id}) ===")

    vocals_path      = kpaths.vocals_raw(job_id)
    word_timing_path = kpaths.word_timing_json(job_id)
    out_unmapped     = kpaths.unmapped_regions_json(job_id)
    out_report       = kpaths.alignment_dir(job_id) / "correction_report.json"

    if not vocals_path.exists():
        # Fallback to separation dir if not in vocals_raw
        vocals_path = kpaths.separation_dir(job_id) / "vocals_16k.wav"
    
    if not vocals_path.exists():
        print(f"ERRO: Vocal audio não encontrado: {vocals_path}"); sys.exit(1)
    if not word_timing_path.exists():
        print(f"ERRO: word_timing.json não encontrado: {word_timing_path}"); sys.exit(1)

    # 1. Load words
    with open(word_timing_path, "r", encoding="utf-8") as f:
        word_dicts = json.load(f)
    print(f"  Palavras carregadas: {len(word_dicts)}")

    # Convert dicts back to Interval objects for the corrector
    words = [Interval(start=w["start"], end=w["end"], text=w["text"]) for w in word_dicts]

    # 2. Run VAD
    print(f"  Rodando VAD em {vocals_path.name}...")
    vad_segments, vad_stats = detect_voice(str(vocals_path))
    print(f"  Segmentos VAD detectados: {len(vad_segments)}")

    # 3. Apply Correction logic (Clamping + Ad-lib detection)
    config = CorrectorConfig()
    result = correct_alignment(words, vad_segments, config)
    
    # 4. Update word timing (preserve original metadata, only update start/end)
    for i, word in enumerate(result.words):
        original = word_dicts[i]
        # Only update if changed
        if abs(original["start"] - word.start) > 0.001 or abs(original["end"] - word.end) > 0.001:
            original["start"] = round(word.start, 4)
            original["end"]   = round(word.end, 4)
            original["vad_clamped"] = True

    # 5. Save results
    with open(word_timing_path, "w", encoding="utf-8") as f:
        json.dump(word_dicts, f, indent=2, ensure_ascii=False)
    print(f"  word_timing.json atualizado ({result.report.words_clamped} Clamped)")

    # Save regions for Gemini (Step 03c)
    with open(out_unmapped, "w", encoding="utf-8") as f:
        json.dump(result.report.unmapped_vocal_regions, f, indent=2, ensure_ascii=False)
    print(f"  Regiões sem letra salvas em: {out_unmapped.name}")

    # Save full report
    report_data = {
        "job_id": job_id,
        "words_total": len(word_dicts),
        "words_clamped": result.report.words_clamped,
        "lines_split": result.report.lines_split,
        "unmapped_regions_count": len(result.report.unmapped_vocal_regions),
        "vad_stats": vad_stats,
    }
    with open(out_report, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    print("✓ Music Gap Correction concluído")

if __name__ == "__main__":
    main()
