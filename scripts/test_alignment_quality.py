import json
import sys
from pathlib import Path

def analyze_alignment(timing_path):
    if not Path(timing_path).exists():
        print(f"File not found: {timing_path}")
        return

    with open(timing_path, encoding='utf-8') as f:
        wt = json.load(f)

    total = len(wt)
    if total == 0:
        print("Empty timing file.")
        return

    interpolated = sum(1 for w in wt if w.get('interpolated'))
    high_score = sum(1 for w in wt if w.get('score', 0) >= 0.5 and not w.get('interpolated'))
    avg_score = sum(w.get('score', 0) for w in wt) / total
    dtw_fixed = sum(1 for w in wt if w.get('method') == 'dtw')
    anchors = sum(1 for w in wt if w.get('method') == 'anchor')

    print(f"Analysis for: {timing_path}")
    print(f"Total Words:       {total}")
    print(f"WhisperX Interp:   {interpolated} ({interpolated/total*100:.1f}%)")
    print(f"WhisperX Anchors:  {high_score}")
    print(f"Avg Score:         {avg_score:.3f}")
    if dtw_fixed or anchors:
        print(f"DTW Fixed:         {dtw_fixed}")
        print(f"DTW Anchors:       {anchors}")
    
    print("\nLong interpolation sequences:")
    run = 0
    for i, w in enumerate(wt):
        if w.get('interpolated'):
            run += 1
        else:
            if run > 3:
                print(f"  {run} words interpolated ending at index {i-1}")
                print(f"  ({wt[i-run]['word']} ... {wt[i-1]['word']})")
            run = 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_alignment_quality.py <word_timing.json>")
    else:
        analyze_alignment(sys.argv[1])
