"""
05_gap_analysis.py — Step 05: Detecção de gaps e silêncios musicais.

Analisa o alinhamento (MFA ou Fused) e o áudio para encontrar inconsistências
onde palavras foram alinhadas sobre silêncios ou partes instrumentais.
"""
import argparse
import sys
import json
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import karaoke.paths as kpaths
from karaoke.textgrid_parser import parse_textgrid
# from karaoke.music_gap_corrector import analyze_gaps 

def _progress(pct: int, msg: str = ""):
    print(f"PROGRESS: {pct} | {msg}", flush=True)

def mfa_to_word_timing(tg_path: Path):
    """Converte TextGrid do MFA para lista de dicionários compatible com word_timing.json."""
    intervals = parse_textgrid(tg_path)
    return [
        {
            "word": interval.text,
            "start": round(interval.start, 4),
            "end": round(interval.end, 4),
            "score": 1.0
        }
        for interval in intervals if interval.text.strip()
    ]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print(f"=== Step 05: Gap Analysis for {job_id} ===")
    _progress(0, "Iniciando análise de gaps...")

    tg_path = kpaths.mfa_textgrid(job_id)
    out_json = kpaths.word_timing_json(job_id)
    vocals_raw = kpaths.vocals_raw(job_id)

    # 1. Loading / Initial Conversion
    word_timing = []
    if out_json.exists():
        print(f"  Carregando alinhamento existente (SOFA/Fused) de {out_json.name}...")
        with open(out_json, 'r', encoding='utf-8') as f:
            word_timing = json.load(f)
    elif tg_path.exists():
        print(f"  Convertendo TextGrid do MFA ({tg_path.name}) para JSON...")
        word_timing = mfa_to_word_timing(tg_path)
    else:
        print(f"ERRO: Nenhum alinhamento encontrado (TextGrid ou JSON) para o job {job_id}.")
        sys.exit(1)

    _progress(30, "Analisando energia vocal vs alinhamento (placeholder)...")
    
    # 2. Gap Analysis Logic
    # TODO: Implement actual energy-based gap detection or integration with music_gap_corrector
    # For now, we ensure the word_timing is saved
    
    _progress(80, "Salvando resultados corrigidos...")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(word_timing, f, indent=2, ensure_ascii=False)
            
    print(f"✓ word_timing.json salvo em: {out_json}")
    _progress(100, "Gap Analysis concluído.")

if __name__ == "__main__":
    main()
