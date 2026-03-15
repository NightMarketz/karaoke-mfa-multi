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
from karaoke.textgrid_parser import parse_textgrid, WordMapping, Interval

def _progress(pct: int, msg: str = ""):
    """Emits progress line for server.py observability."""
    if msg:
        print(f"PROGRESS: {pct} | {msg}", flush=True)
    else:
        print(f"PROGRESS: {pct}", flush=True)

def load_sofa_phones(tg_path: Path):
    """Loads phone intervals from a SOFA-generated TextGrid."""
    if not tg_path.exists():
        print(f"ERROR: TextGrid not found: {tg_path}")
        return []
    
    content = tg_path.read_text(encoding='utf-8')
    tiers = parse_textgrid(content)
    
    for tier in tiers:
        if tier.name == 'phones':
            # Filter out silence/empty
            from karaoke.textgrid_parser import SILENCE_TOKENS
            return [p for p in tier.intervals if p.text.strip() not in SILENCE_TOKENS]
    
    print("WARNING: 'phones' tier not found in TextGrid.")
    return []

def load_rosvot_notes(json_path: Path):
    """Loads note/word candidates from ROSVOT JSON."""
    if not json_path.exists():
        print(f"ERROR: ROSVOT JSON not found: {json_path}")
        return []
        
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # ROSVOT usually returns a list of notes or words.
    # Adjust based on observed schema.
    if isinstance(data, dict):
        return data.get('notes') or data.get('words') or []
    return data

def fuse_alignments(notes, phones):
    """
    Fuses ROSVOT notes with SOFA phone-level timing.
    Matches phones to the closest/overlapping notes.
    """
    fused_results = []
    _progress(50, "Merging phones with notes...")
    
    p_idx = 0
    num_phones = len(phones)
    
    for n in notes:
        n_start = n['start']
        n_end = n['end']
        
        # Collect phones that belong to this note's temporal window
        note_phones = []
        while p_idx < num_phones:
            p = phones[p_idx]
            
            # If phone starts after note ends, we possibly stop OR check next note
            if p.start >= n_end - 0.001:
                break
                
            # If phone ends before note starts, skip it
            if p.end <= n_start + 0.001:
                p_idx += 1
                continue
            
            # Phone overlaps with note
            note_phones.append({
                'phone': p.text,
                'start': round(p.start, 3),
                'end': round(p.end, 3)
            })
            p_idx += 1
            
        fused_results.append({
            'word': n.get('word') or n.get('text', ''),
            'start': round(n_start, 3),
            'end': round(n_end, 3),
            'phones': note_phones,
            'pitch': n.get('pitch', 0),
            'confidence': n.get('confidence', 1.0)
        })
        
    return fused_results

def main():
    parser = argparse.ArgumentParser(description="Fuse SOFA TextGrid phones with ROSVOT JSON notes.")
    parser.add_argument('--job-id', help="Job ID to process")
    # Add manual overrides for convenience
    parser.add_argument('--sofa-tg', help="Path to SOFA TextGrid (overrides default)")
    parser.add_argument('--rosvot-json', help="Path to ROSVOT JSON (overrides default)")
    parser.add_argument('--output', help="Path to output fused JSON (overrides default)")
    
    args = parser.parse_args()
    
    if args.job_id:
        sofa_tg = kpaths.sofa_textgrid(args.job_id)
        rosvot_json = kpaths.rosvot_json(args.job_id)
        output_path = kpaths.fused_alignment_json(args.job_id)
    else:
        sofa_tg = Path(args.sofa_tg) if args.sofa_tg else None
        rosvot_json = Path(args.rosvot_json) if args.rosvot_json else None
        output_path = Path(args.output) if args.output else None
        
    if not sofa_tg or not rosvot_json or not output_path:
        print("ERROR: Must provide --job-id or explicit paths (--sofa-tg, --rosvot-json, --output).")
        sys.exit(1)
        
    _progress(10, "Loading SOFA phones...")
    phones = load_sofa_phones(sofa_tg)
    
    _progress(30, "Loading ROSVOT notes...")
    notes = load_rosvot_notes(rosvot_json)
    
    if not phones:
        print("WARNING: No phones loaded from TextGrid. Output will only contain word level.")
    if not notes:
        print("ERROR: No notes loaded from ROSVOT. Execution aborted.")
        sys.exit(1)
        
    fused = fuse_alignments(notes, phones)
    
    _progress(90, "Saving results...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(fused, f, indent=2, ensure_ascii=False)
        
    _progress(100, f"Successfully fused results to {output_path.name}")
    print(f"Fusion complete. Output: {output_path}")

if __name__ == "__main__":
    main()
