import argparse
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))
from karaoke import paths
from karaoke.textgrid_parser import parse_textgrid, select_word_tier, list_tier_names

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
    # parse_textgrid recebe o TEXTO do TextGrid e devolve List[Tier] — nao um Path,
    # e nao uma lista plana de intervalos. Um TextGrid do MFA traz dois tiers
    # ("words" e "phones"); iterar tudo junto misturaria fonema com palavra.
    tiers = parse_textgrid(tg_path.read_text(encoding="utf-8"))
    print(f"  Tiers encontrados: {list_tier_names(tiers)}")
    word_tier = select_word_tier(tiers)
    print(f"  Tier de palavras: {word_tier.name}")

    word_results = []
    for interval in word_tier.speech_intervals:
        word_results.append({
            "word": interval.text,
            "start": round(interval.start, 4),
            "end": round(interval.end, 4),
            # O MFA nao expoe score por palavra; 1.0 marca "ancora do alinhador",
            # que e o que 08_onset_dtw.py usa para decidir em quem confiar.
            "score": 1.0
        })
        
    out_json = paths.word_timing_json(job_id)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(word_results, f, indent=2, ensure_ascii=False)
        
    print(f"✓ word_timing.json gerado com {len(word_results)} palavras.")

if __name__ == "__main__":
    main()
