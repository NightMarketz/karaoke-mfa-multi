import json, wave, sys, io, argparse
import numpy as np
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths

# Force UTF-8 for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
 
# ── CONFIGURAÇÕES ──────────────────────────────────────────────────────────
SCORE_THRESHOLD  = 0.5    # só confia em palavras com score >= isso
ONSET_THRESHOLD  = 0.008  # sensibilidade do detector de onsets
MIN_GAP          = 0.08   # gap mínimo entre onsets (80ms)
ENERGY_MIN       = 0.02   # RMS mínimo para contar como onset
WINDOW_MS        = 25     # janela de análise em ms
HOP_MS           = 10     # passo entre janelas em ms
 
# ── PASSO 1: Carregar o áudio ───────────────────────────────────────────────
def load_audio(wav_path):
    with wave.open(str(wav_path), 'rb') as wf:
        sr     = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        audio  = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
        audio /= np.abs(audio).max() + 1e-8
    return audio, sr
 
# ── PASSO 2: Calcular RMS frame a frame ────────────────────────────────────
def compute_rms(audio, sr):
    hop = int(sr * HOP_MS  / 1000)
    win = int(sr * WINDOW_MS / 1000)
    rms = []
    for i in range(0, len(audio) - win, hop):
        chunk = audio[i:i+win]
        rms.append(float(np.sqrt(np.mean(chunk**2))))
    return np.array(rms), hop / sr  # retorna array e segundos por frame
 
# ── PASSO 3: Detectar onsets ────────────────────────────────────────────────
# Um onset é detectado quando:
#   a) A derivada do RMS é positiva acima do threshold
#   b) O RMS atual está acima do mínimo de energia
#   c) Passou o gap mínimo desde o último onset
def detect_onsets(rms, frame_dur):
    drms   = np.diff(rms)
    onsets = []
    last   = -1
    for i, d in enumerate(drms):
        t = i * frame_dur
        if (d > ONSET_THRESHOLD
                and rms[i+1] > ENERGY_MIN
                and (t - last) > MIN_GAP):
            onsets.append(t)
            last = t
    return np.array(onsets)
 
# ── PASSO 4: Separar âncoras de palavras não-alinhadas ──────────────────────
# Âncoras: score >= SCORE_THRESHOLD E não interpolated
# Não-alinhadas: tudo que o WhisperX não encontrou com confiança
def split_anchors(word_timing):
    anchors    = []  # lista de índices das âncoras
    for i, w in enumerate(word_timing):
        is_anchor = (w.get('score', 0) >= SCORE_THRESHOLD
                     and not w.get('interpolated', False))
        if is_anchor:
            anchors.append(i)
    return anchors
 
# ── PASSO 5: DTW simples entre onsets e palavras ────────────────────────────
# Dado N onsets e M palavras, encontra o melhor mapeamento.
# Cada palavra recebe o onset mais próximo, sem repetição.
def dtw_assign(onsets_in_window, n_words):
    if len(onsets_in_window) == 0:
        return None  # sem onsets, não há como alinhar
    
    n_onsets = len(onsets_in_window)
    
    # Se há mais palavras que onsets, distribui onsets uniformemente
    if n_words >= n_onsets:
        # Usa todos os onsets e adiciona pontos intermediários
        step = (onsets_in_window[-1] - onsets_in_window[0]) / max(n_words-1, 1)
        return [onsets_in_window[0] + i*step for i in range(n_words)]
    
    # Caso normal: mais onsets que palavras
    # Seleciona N onsets espaçados uniformemente do array de onsets
    indices = np.linspace(0, n_onsets-1, n_words, dtype=int)
    return [float(onsets_in_window[idx]) for idx in indices]
 
# ── PASSO 6: Processar cada segmento entre âncoras ─────────────────────────
def fix_segment(word_timing, seg_start_idx, seg_end_idx,
                t_window_start, t_window_end, onsets):
    # Pega as palavras deste segmento (excluindo as âncoras dos extremos)
    words_to_fix = word_timing[seg_start_idx:seg_end_idx]
    n = len(words_to_fix)
    if n == 0:
        return
    
    # Filtra onsets dentro da janela de tempo deste segmento
    mask = (onsets >= t_window_start - 0.05) & (onsets <= t_window_end + 0.05)
    window_onsets = onsets[mask]
    
    # Pede ao DTW os timestamps para N palavras
    timestamps = dtw_assign(window_onsets, n)
    
    if timestamps is None:
        # Sem onsets: distribui uniformemente na janela (melhor que nada)
        dur = (t_window_end - t_window_start) / (n + 1)
        timestamps = [t_window_start + dur * (i+1) for i in range(n)]
    
    # Atualiza os timestamps das palavras
    for i, w in enumerate(words_to_fix):
        t_start = timestamps[i]
        t_end   = timestamps[i+1] if i+1 < len(timestamps) else t_window_end
        # Garante que t_end > t_start
        if t_end <= t_start:
            t_end = t_start + 0.15
        w['start']  = round(t_start, 4)
        w['end']    = round(t_end, 4)
        w['method'] = 'dtw'
 
# ── PASSO 7: Função principal ───────────────────────────────────────────────
def main(wav_path, timing_in, timing_out):
    print('Carregando áudio...')
    audio, sr = load_audio(wav_path)
    
    print('Calculando RMS...')
    rms, frame_dur = compute_rms(audio, sr)
    
    print('Detectando onsets...')
    onsets = detect_onsets(rms, frame_dur)
    print(f'  {len(onsets)} onsets detectados')
    
    print('Carregando word_timing.json...')
    with open(timing_in, encoding='utf-8') as f:
        wt = json.load(f)
    
    print('Encontrando âncoras...')
    anchors = split_anchors(wt)
    print(f'  {len(anchors)} âncoras confiáveis de {len(wt)} palavras')
    
    # Marca âncoras com method='anchor'
    for i in anchors:
        wt[i]['method'] = 'anchor'
    
    # Processa segmento antes da primeira âncora
    if anchors and anchors[0] > 0:
        t_end = wt[anchors[0]]['start']
        t_start = max(0, t_end - 5.0)  # janela de até 5s antes
        fix_segment(wt, 0, anchors[0], t_start, t_end, onsets)
    
    # Processa segmentos entre âncoras
    for a_idx in range(len(anchors) - 1):
        seg_start = anchors[a_idx] + 1      # palavra após âncora esquerda
        seg_end   = anchors[a_idx + 1]      # até a próxima âncora (exclusive)
        t_win_start = wt[anchors[a_idx]]['end']
        t_win_end   = wt[anchors[a_idx + 1]]['start']
        fix_segment(wt, seg_start, seg_end, t_win_start, t_win_end, onsets)
    
    # Processa segmento após a última âncora
    if anchors and anchors[-1] < len(wt) - 1:
        t_start = wt[anchors[-1]]['end']
        t_end   = t_start + 30.0  # janela de até 30s depois
        fix_segment(wt, anchors[-1]+1, len(wt), t_start, t_end, onsets)
    
    # Salva resultado
    with open(timing_out, 'w', encoding='utf-8') as f:
        json.dump(wt, f, indent=2, ensure_ascii=False)
    
    fixed = sum(1 for w in wt if w.get('method') == 'dtw')
    kept  = sum(1 for w in wt if w.get('method') == 'anchor')
    print(f'Salvo em {timing_out}')
    print(f'  {kept} âncoras mantidas, {fixed} palavras corrigidas pelo DTW')
 
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Onset-based DTW alignment correction')
    parser.add_argument('--job-id', help='Job ID from the pipeline')
    parser.add_argument('--wav', help='Path to vocal WAV file (standalone mode)')
    parser.add_argument('--timing-in', help='Path to input word_timing.json (standalone mode)')
    parser.add_argument('--timing-out', help='Path to output fixed word_timing.json (standalone mode)')
    
    args = parser.parse_args()

    if args.job_id:
        wav_path    = kpaths.vocals_raw(args.job_id)
        timing_in   = kpaths.word_timing_json(args.job_id)
        timing_out  = timing_in # overwriting for consistency with pipeline
        
        if not wav_path.exists():
            wav_path = kpaths.separation_dir(args.job_id) / "vocals_16k.wav"
            
        main(wav_path, timing_in, timing_out)
    elif args.wav and args.timing_in and args.timing_out:
        main(Path(args.wav), Path(args.timing_in), Path(args.timing_out))
    else:
        parser.print_help()
        print('\nERRO: Use --job-id OU --wav + --timing-in + --timing-out')
        sys.exit(1)
