import argparse
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))
from karaoke import paths
from karaoke.textgrid_parser import parse_textgrid

def main():
    parser = argparse.ArgumentParser(description="Convert MFA TextGrid to Word Timing JSON")
    parser.add_argument("--job-id", required=True, help="Job UUID")
    args = parser.parse_args()
    job_id = args.job_id
    
    print(f"=== Step 06: MFA to JSON Conversion ===")
    
    tg_path = paths.mfa_textgrid(job_id)
    if not tg_path.exists():
        print(f"ERRO: TextGrid do MFA não encontrado em: {tg_path}")
        sys.exit(1)
        
    print(f"  Lendo {tg_path.name}...")
    intervals = parse_textgrid(tg_path)
    
    word_results = []
    for interval in intervals:
        # MFA textgrid usually has words in a specific tier or just flat intervals
        # We assume they are word intervals for now
        word_results.append({
            "word": interval.text,
            "start": round(interval.start, 4),
            "end": round(interval.end, 4),
            "score": 1.0 # MFA doesn't provide per-word score easily?
        })
        
    out_json = paths.word_timing_json(job_id)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(word_results, f, indent=2, ensure_ascii=False)
        
    print(f"✓ word_timing.json gerado com {len(word_results)} palavras.")

if __name__ == "__main__":
    main()
