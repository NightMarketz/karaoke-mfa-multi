"""
07_qc_report.py — QC Report based on ASS validation.

Validates the final .ass file for overlapping lines, negative duration \kf tags,
and output metrics for the frontend.
"""
import sys
import io
import re
import json
import argparse
# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths

# Force UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def time_to_sec(ass_time: str) -> float:
    # "0:01:23.45" -> 83.45
    parts = ass_time.split(':')
    h = float(parts[0])
    m = float(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print("=== Fase I: Relatório Cirúrgico de Quality Control (ASS) ===")
    
    ass_path = kpaths.final_ass(job_id)
    out_json = kpaths.qc_json(job_id)
    lyrics_file = kpaths.lyrics_path(job_id)
    
    if not ass_path.exists():
        print(f"ERRO: Arquivo ASS não encontrado em {ass_path}")
        sys.exit(1)
        
    with open(ass_path, "r", encoding="utf-8") as f:
        ass_content = f.read()

    # Parse Events
    events = []
    for line in ass_content.splitlines():
        if line.startswith("Dialogue:"):
            # Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
            parts = line[10:].split(",", 9)
            if len(parts) >= 10:
                layer = int(parts[0].strip())
                start_sec = time_to_sec(parts[1].strip())
                end_sec = time_to_sec(parts[2].strip())
                text = parts[9]
                events.append({"layer": layer, "start": start_sec, "end": end_sec, "text": text})

    total_lines = len(events)
    if total_lines == 0:
        print("ERRO CRÍTICO: Zero linhas de diálogo no ASS.")
        sys.exit(1)
        
    overlapping_events = 0
    lines_without_kf = 0
    negative_kf = 0
    duration_mismatches = 0
    total_sung_words = 0
    
    # Layer-aware overlap tracker: layer_id -> last_end_time
    layer_last_ends = {}
    
    for ev in events:
        layer = ev["layer"]
        prev_end = layer_last_ends.get(layer, -1.0)
        
        if ev["start"] < prev_end - 0.05: # Allow rounding delta
            overlapping_events += 1
            
        kf_tags = re.findall(r'\\kf([\-\d]+)', ev["text"])
        if not kf_tags:
            lines_without_kf += 1
        else:
            for kf in kf_tags:
                if int(kf) < 0:
                    negative_kf += 1
            
            # \kf with positive values
            total_kf_cs = sum(int(x) for x in kf_tags if int(x) > 0)
            k_tags = re.findall(r'\\k([\-\d]+)', ev["text"])
            total_k_cs = sum(int(x) for x in k_tags if int(x) > 0)
            
            total_tags_sec = (total_k_cs + total_kf_cs) / 100.0
            line_dur = ev["end"] - ev["start"]
            
            if abs(total_tags_sec - line_dur) > 0.2:
                duration_mismatches += 1
                
        # Count words properly by stripping ASS tags
        clean_text = re.sub(r'\{[^\}]+\}', '', ev["text"])
        words = clean_text.split()
        total_sung_words += len(words)
                
        layer_last_ends[layer] = ev["end"]
        
    print(f"Linhas validadas       : {total_lines}")
    print(f"Linhas sem \\kf         : {lines_without_kf}")
    print(f"Tags \\kf negativas     : {negative_kf}")
    print(f"Eventos sobrepostos    : {overlapping_events}")
    print(f"Erros de Tag Duration  : {duration_mismatches}")
    
    # Calculate word coverage based on original lyrics
    input_word_count = 0
    if lyrics_file.exists():
        with open(lyrics_file, "r", encoding="utf-8") as f:
            input_word_count = len(f.read().split())
            
    word_coverage = round((total_sung_words / max(input_word_count, 1)) * 100, 2)
    print(f"Palavras da letra base : {input_word_count}")
    print(f"Palavras no timing ASS : {total_sung_words} (~{word_coverage}%)")

    metrics = {
        "total_lines": total_lines,
        "lines_without_kf": lines_without_kf,
        "negative_kf": negative_kf,
        "overlapping_events": overlapping_events,
        "duration_mismatches": duration_mismatches,
        "word_coverage_percent": word_coverage
    }
    
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics}, f, indent=2)
        
    if overlapping_events > 0 or lines_without_kf > total_lines * 0.1 or negative_kf > 0:
        print("\n❌ ERRO FATAL (QUALITY GATE FAILED) ❌")
        print("Violações críticas no formato ou fluxo do ASS encontradas.")
        sys.exit(1)
        
    print("\n✅ GATE DE QUALIDADE APROVADO!")

if __name__ == "__main__":
    main()
