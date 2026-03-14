import json, wave, sys
import numpy as np
from pathlib import Path

def get_rms_at(rms, frame_dur, t0, t1):
    f0 = max(0, int(t0 / frame_dur))
    f1 = min(len(rms)-1, int(t1 / frame_dur))
    return float(rms[f0:f1].mean()) if f1 > f0 else 0.0

def compare_timings(wav_path, timing_old_path, timing_new_path):
    # Carrega áudio e calcula RMS
    with wave.open(str(wav_path), 'rb') as wf:
        sr = wf.getframerate()
        audio = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32)
        audio /= np.abs(audio).max() + 1e-8
    
    hop_ms = 10
    win_ms = 25
    hop = int(sr * hop_ms / 1000)
    win = int(sr * win_ms / 1000)
    rms = np.array([np.sqrt(np.mean(audio[i:i+win]**2)) for i in range(0, len(audio)-win, hop)])
    fd  = hop_ms / 1000
 
    # Carrega os dois arquivos
    with open(timing_old_path, encoding='utf-8') as f: wt_old = json.load(f)
    with open(timing_new_path, encoding='utf-8') as f: wt_new = json.load(f)
 
    print(f"{'Word':<14} {'OLD start':>10} {'NEW start':>10} {'Delta':>7} {'RMS old':>8} {'RMS new':>8} {'Better?'}")
    print('-' * 80)
 
    better = 0; worse = 0; same = 0
    for old, new in zip(wt_old, wt_new):
        # Look at energy at the very start of the word (onset area)
        # We check a small window of 100ms around the start
        r_old = get_rms_at(rms, fd, old['start'], old['start'] + 0.1)
        r_new = get_rms_at(rms, fd, new['start'], new['start'] + 0.1)
        
        delta = new['start'] - old['start']
        
        if abs(delta) < 0.001:
            flag = '='
            same += 1
        elif r_new > r_old * 1.1: # 10% more energy at boundary is considered better
            flag = '[+]'
            better += 1
        else:
            flag = '[-]'
            worse += 1
            
        print(f"{old['word']:<14} {old['start']:>10.3f} {new['start']:>10.3f} {delta:>+7.3f} {r_old:>8.4f} {r_new:>8.4f} {flag}")
 
    print(f'\nBetter: {better} | Worse: {worse} | Unchanged/Anchor: {same} | Total: {len(wt_old)}')

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python compare_timing.py <song.wav> <old.json> <new.json>")
    else:
        compare_timings(sys.argv[1], sys.argv[2], sys.argv[3])
