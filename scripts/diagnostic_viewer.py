"""
diagnostic_viewer.py — Visualizador de diagnóstico do pipeline de karaokê.

Sobe um servidor local e abre o browser com uma timeline interativa mostrando:
  - Energia RMS do áudio (waveform simplificado)
  - Onsets detectados
  - Palavras com cor por método: âncora / DTW / interpolado / VAD clamped
  - Score de confiança por palavra
  - Transcrição do Gemini (adlibs vs letra)
  - Comparação word_timing.json vs word_timing_fixed.json

Uso:
  python diagnostic_viewer.py --job-id SEU_JOB_ID
  python diagnostic_viewer.py --job-id SEU_JOB_ID --port 5001

Abre automaticamente em http://localhost:5001/
"""

import json
import math
import wave
import struct
import argparse
import threading
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

import numpy as np


# ── Paths ─────────────────────────────────────────────────────────────────────

def _job_root(job_id: str) -> Path:
    return Path(__file__).resolve().parent.parent / "work" / "jobs" / job_id

def _input_root(job_id: str) -> Path:
    return Path(__file__).resolve().parent.parent / "input" / "jobs" / job_id


# ── Carrega dados do job ───────────────────────────────────────────────────────

def load_job_data(job_id: str) -> dict:
    job_root   = _job_root(job_id)
    input_root = _input_root(job_id)
    align_dir  = job_root / "05_alignment"

    data = {
        "job_id":        job_id,
        "duration":      0,
        "rms":           [],          # [{t, v}] — ~500 pontos
        "onsets":        [],          # [t, ...]
        "words_raw":     [],          # word_timing.json
        "words_fixed":   [],          # word_timing_fixed.json
        "adlibs":        [],          # adlibs_timing.json
        "gemini":        [],          # gemini_transcript.json segments
        "lyrics_lines":  [],          # lyrics.txt
        "has_fixed":     False,
        "has_adlibs":    False,
        "has_gemini":    False,
    }

    # ── Áudio → RMS + onsets ──────────────────────────────────────────────────
    wav_path = job_root / "03_vocals_clean" / "vocals_raw.wav"
    if wav_path.exists():
        rms_arr, sr, duration = compute_rms_wav(wav_path)
        data["duration"] = duration

        # Downsample RMS para ~800 pontos para não travar o browser
        target_pts = 800
        step = max(1, len(rms_arr) // target_pts)
        fd = 0.01  # 10ms por frame (HOP_MS=10)
        data["rms"] = [
            {"t": round(i * step * fd, 3), "v": round(float(rms_arr[i * step]), 5)}
            for i in range(len(rms_arr) // step)
        ]

        # Onsets
        data["onsets"] = detect_onsets(rms_arr, fd)

    # ── word_timing.json ──────────────────────────────────────────────────────
    wt_path = align_dir / "word_timing.json"
    if wt_path.exists():
        data["words_raw"] = json.loads(wt_path.read_text(encoding="utf-8"))

    # ── word_timing_fixed.json ────────────────────────────────────────────────
    wt_fixed_path = align_dir / "word_timing_fixed.json"
    if wt_fixed_path.exists():
        data["words_fixed"] = json.loads(wt_fixed_path.read_text(encoding="utf-8"))
        data["has_fixed"] = True

    # ── adlibs_timing.json ────────────────────────────────────────────────────
    adlibs_path = align_dir / "adlibs_timing.json"
    if adlibs_path.exists():
        data["adlibs"] = json.loads(adlibs_path.read_text(encoding="utf-8"))
        data["has_adlibs"] = True

    # ── gemini_transcript.json ────────────────────────────────────────────────
    gemini_path = align_dir / "gemini_transcript.json"
    if gemini_path.exists():
        gd = json.loads(gemini_path.read_text(encoding="utf-8"))
        data["gemini"] = gd.get("segments", [])
        data["has_gemini"] = True

    # ── lyrics.txt ────────────────────────────────────────────────────────────
    lyrics_path = input_root / "lyrics.txt"
    if lyrics_path.exists():
        data["lyrics_lines"] = [
            l.strip() for l in lyrics_path.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]

    return data


def compute_rms_wav(wav_path: Path, hop_ms: int = 10, win_ms: int = 25):
    with wave.open(str(wav_path), "rb") as wf:
        sr      = wf.getframerate()
        n_ch    = wf.getnchannels()
        sw      = wf.getsampwidth()
        frames  = wf.readframes(wf.getnframes())
        total_s = wf.getnframes() / sr

    dtype = np.int16 if sw == 2 else np.int32
    audio = np.frombuffer(frames, dtype=dtype).astype(np.float32)
    if n_ch > 1:
        audio = audio.reshape(-1, n_ch).mean(axis=1)
    audio /= (np.abs(audio).max() + 1e-8)

    hop = int(sr * hop_ms / 1000)
    win = int(sr * win_ms / 1000)
    rms = np.array([
        float(np.sqrt(np.mean(audio[i:i+win]**2)))
        for i in range(0, len(audio) - win, hop)
    ])
    return rms, sr, total_s


def detect_onsets(rms: np.ndarray, frame_dur: float,
                  threshold: float = 0.008, min_gap: float = 0.08,
                  energy_min: float = 0.02) -> list:
    drms   = np.diff(rms)
    onsets = []
    last   = -1
    for i, d in enumerate(drms):
        t = i * frame_dur
        if d > threshold and rms[i+1] > energy_min and (t - last) > min_gap:
            onsets.append(round(t, 3))
            last = t
    return onsets


# ── HTML ───────────────────────────────────────────────────────────────────────

def build_html(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Karaokê Diagnostic — {data['job_id']}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;600&display=swap');

  :root {{
    --bg:        #0a0b0f;
    --surface:   #12141a;
    --border:    #1e2130;
    --text:      #c8ccd8;
    --muted:     #4a5070;
    --accent:    #4f8aff;

    /* método cores */
    --anchor:    #38e8a0;
    --dtw:       #f5c842;
    --interp:    #ff6b6b;
    --clamped:   #c084fc;
    --adlib:     #fb923c;
    --gemini:    #38bdf8;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    overflow-x: hidden;
  }}

  header {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 20px;
    position: sticky;
    top: 0;
    z-index: 100;
  }}

  header h1 {{
    font-family: 'Space Mono', monospace;
    font-size: 14px;
    color: var(--accent);
    letter-spacing: 0.05em;
  }}

  header span {{
    font-size: 11px;
    color: var(--muted);
    font-family: 'Space Mono', monospace;
  }}

  .stats {{
    margin-left: auto;
    display: flex;
    gap: 16px;
  }}

  .stat {{
    display: flex;
    flex-direction: column;
    align-items: flex-end;
  }}

  .stat-val {{
    font-family: 'Space Mono', monospace;
    font-size: 16px;
    font-weight: 700;
    color: var(--text);
  }}

  .stat-lbl {{
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }}

  /* ── LEGENDA ── */
  .legend {{
    padding: 10px 24px;
    display: flex;
    gap: 20px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    flex-wrap: wrap;
  }}

  .legend-item {{
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--muted);
    cursor: pointer;
    user-select: none;
    transition: color 0.15s;
  }}

  .legend-item:hover {{ color: var(--text); }}
  .legend-item.off {{ opacity: 0.3; }}

  .dot {{
    width: 10px; height: 10px;
    border-radius: 2px;
    flex-shrink: 0;
  }}

  /* ── CONTROLES ── */
  .controls {{
    padding: 10px 24px;
    display: flex;
    gap: 16px;
    align-items: center;
    border-bottom: 1px solid var(--border);
  }}

  .controls label {{
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}

  .controls input[type=range] {{
    width: 120px;
    accent-color: var(--accent);
  }}

  .btn {{
    background: var(--border);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 5px 12px;
    border-radius: 4px;
    font-size: 11px;
    cursor: pointer;
    font-family: 'Space Mono', monospace;
    transition: background 0.15s;
  }}
  .btn:hover {{ background: var(--accent); color: #fff; }}

  /* ── TIMELINE ── */
  #timeline-wrap {{
    position: relative;
    overflow-x: scroll;
    overflow-y: hidden;
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    cursor: grab;
  }}

  #timeline-wrap:active {{ cursor: grabbing; }}

  #timeline-canvas {{
    display: block;
    image-rendering: pixelated;
  }}

  /* ── TOOLTIP ── */
  #tooltip {{
    position: fixed;
    background: #1a1d2a;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 11px;
    pointer-events: none;
    z-index: 999;
    display: none;
    max-width: 280px;
    line-height: 1.6;
  }}

  #tooltip .word {{ font-family: 'Space Mono', monospace; font-size: 14px; font-weight: 700; }}
  #tooltip .meta {{ color: var(--muted); }}
  #tooltip .method {{ font-size: 11px; padding: 2px 6px; border-radius: 3px; font-weight: 600; }}

  /* ── PAINEL INFERIOR ── */
  .bottom {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0;
    height: 280px;
  }}

  .panel {{
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 12px 16px;
  }}

  .panel:last-child {{ border-right: none; }}

  .panel-title {{
    font-family: 'Space Mono', monospace;
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 10px;
    position: sticky;
    top: 0;
    background: var(--bg);
    padding: 4px 0;
  }}

  .word-row {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 6px;
    border-radius: 3px;
    cursor: pointer;
    transition: background 0.1s;
  }}
  .word-row:hover {{ background: var(--surface); }}
  .word-row.active {{ background: #1e2a3a; }}

  .word-text {{
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    min-width: 90px;
    color: var(--text);
  }}

  .word-text-gemini {{
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    min-width: 140px;
    color: var(--text);
  }}

  .word-time {{
    font-size: 10px;
    color: var(--muted);
    min-width: 80px;
    font-family: 'Space Mono', monospace;
  }}

  .score-bar {{
    height: 4px;
    width: 60px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
  }}

  .score-fill {{ height: 100%; border-radius: 2px; }}

  .method-badge {{
    font-size: 9px;
    padding: 1px 5px;
    border-radius: 2px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}

  /* scrollbar */
  ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  ::-webkit-scrollbar-track {{ background: var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
</style>
</head>
<body>

<header>
  <h1>◈ KARAOKÊ DIAGNOSTIC</h1>
  <span id="job-id-label"></span>
  <div class="stats">
    <div class="stat"><span class="stat-val" id="s-total">—</span><span class="stat-lbl">Palavras</span></div>
    <div class="stat"><span class="stat-val" id="s-anchors">—</span><span class="stat-lbl">Âncoras</span></div>
    <div class="stat"><span class="stat-val" id="s-interp">—</span><span class="stat-lbl">Interpoladas</span></div>
    <div class="stat"><span class="stat-val" id="s-onsets">—</span><span class="stat-lbl">Onsets</span></div>
    <div class="stat"><span class="stat-val" id="s-dur">—</span><span class="stat-lbl">Duração</span></div>
  </div>
</header>

<div class="legend">
  <div class="legend-item" data-layer="rms">
    <div class="dot" style="background:#2a3a5a"></div> RMS waveform
  </div>
  <div class="legend-item" data-layer="onsets">
    <div class="dot" style="background:#ffffff33"></div> Onsets
  </div>
  <div class="legend-item" data-layer="anchor">
    <div class="dot" style="background:var(--anchor)"></div> Âncora WhisperX
  </div>
  <div class="legend-item" data-layer="dtw">
    <div class="dot" style="background:var(--dtw)"></div> Corrigido DTW
  </div>
  <div class="legend-item" data-layer="interp">
    <div class="dot" style="background:var(--interp)"></div> Interpolado
  </div>
  <div class="legend-item" data-layer="clamped">
    <div class="dot" style="background:var(--clamped)"></div> VAD clamped
  </div>
  <div class="legend-item" data-layer="adlib">
    <div class="dot" style="background:var(--adlib)"></div> Adlib detectado
  </div>
  <div class="legend-item" data-layer="gemini">
    <div class="dot" style="background:var(--gemini)"></div> Gemini livre
  </div>
</div>

<div class="controls">
  <label>Zoom</label>
  <input type="range" id="zoom-slider" min="1" max="24" value="4" step="0.5">
  <span id="zoom-label" style="font-family:monospace;font-size:11px;color:var(--muted)">4×</span>
  <label style="margin-left:8px">Altura</label>
  <input type="range" id="height-slider" min="80" max="350" value="160" step="10">
  <button class="btn" id="btn-fit">Fit tudo</button>
  <button class="btn" id="btn-raw">Ver RAW</button>
  <button class="btn" id="btn-fixed">Ver FIXED</button>
  <span id="cursor-time" style="margin-left:auto;font-family:monospace;font-size:11px;color:var(--muted)"></span>
</div>

<div id="timeline-wrap">
  <canvas id="timeline-canvas"></canvas>
</div>

<div id="tooltip"></div>

<div class="bottom">
  <div class="panel">
    <div class="panel-title" id="list-title">Palavras — word_timing_fixed.json</div>
    <div id="word-list"></div>
  </div>
  <div class="panel">
    <div class="panel-title">Gemini Transcript</div>
    <div id="gemini-list"></div>
  </div>
</div>

<script>
const DATA = {data_json};

// ── Estado ────────────────────────────────────────────────────────────────────
const state = {{
  zoom: 4,
  height: 160,
  showFixed: DATA.has_fixed,
  layers: {{
    rms: true, onsets: true, anchor: true,
    dtw: true, interp: true, clamped: true,
    adlib: true, gemini: true,
  }},
  hoveredWord: null,
  selectedTime: null,
}};

const COLORS = {{
  anchor:  '#38e8a0',
  dtw:     '#f5c842',
  interp:  '#ff6b6b',
  clamped: '#c084fc',
  adlib:   '#fb923c',
  gemini:  '#38bdf8',
  rms:     '#1e3560',
  onset:   'rgba(255,255,255,0.15)',
}};

// ── Classifica palavra ─────────────────────────────────────────────────────────
function wordClass(w) {{
  if (w.method === 'anchor') return 'anchor';
  if (w.method === 'dtw')    return 'dtw';
  if (w.vad_clamped)         return 'clamped';
  if (w.interpolated)        return 'interp';
  // WhisperX sem método definido: usa score
  if ((w.score || 0) >= 0.5 && !w.interpolated) return 'anchor';
  return 'interp';
}}

// ── Stats ─────────────────────────────────────────────────────────────────────
function updateStats() {{
  const words = state.showFixed && DATA.has_fixed ? DATA.words_fixed : DATA.words_raw;
  document.getElementById('job-id-label').textContent = DATA.job_id;
  document.getElementById('s-total').textContent = words.length;
  document.getElementById('s-anchors').textContent = words.filter(w => wordClass(w) === 'anchor').length;
  document.getElementById('s-interp').textContent  = words.filter(w => w.interpolated).length;
  document.getElementById('s-onsets').textContent  = DATA.onsets.length;
  const dur = DATA.duration;
  document.getElementById('s-dur').textContent = dur > 0
    ? Math.floor(dur/60) + ':' + String(Math.floor(dur%60)).padStart(2,'0')
    : '—';
}}

// ── Canvas ────────────────────────────────────────────────────────────────────
const wrap   = document.getElementById('timeline-wrap');
const canvas = document.getElementById('timeline-canvas');
const ctx    = canvas.getContext('2d');

const PX_PER_SEC = 80;   // base — multiplicado pelo zoom
const ROW_H      = 20;   // altura de cada linha de palavras
const WAVE_FRAC  = 0.45; // fração da altura para o waveform

let canvasW = 0;

function secToPx(t)  {{ return t * PX_PER_SEC * state.zoom; }}
function pxToSec(px) {{ return px / (PX_PER_SEC * state.zoom); }}

function resize() {{
  const h = state.height;
  canvasW = Math.max(wrap.clientWidth, secToPx(DATA.duration) + 40);
  canvas.width  = canvasW;
  canvas.height = h;
  canvas.style.height = h + 'px';
  wrap.style.height   = (h + 2) + 'px';
  draw();
}}

function draw() {{
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const waveH = Math.floor(h * WAVE_FRAC);
  const wordY = waveH + 4;

  // ── Background grid (segundos) ────────────────────────────────────────────
  ctx.strokeStyle = '#1a1d26';
  ctx.lineWidth = 1;
  const secStep = state.zoom < 3 ? 10 : state.zoom < 8 ? 5 : 1;
  for (let s = 0; s <= DATA.duration; s += secStep) {{
    const x = secToPx(s);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
    if (x < w - 20) {{
      ctx.fillStyle = '#2a3050';
      ctx.font = '9px Space Mono, monospace';
      ctx.fillText(formatTime(s), x + 2, 10);
    }}
  }}

  // ── RMS waveform ──────────────────────────────────────────────────────────
  if (state.layers.rms && DATA.rms.length > 0) {{
    const maxRMS = Math.max(...DATA.rms.map(p => p.v)) || 1;
    ctx.fillStyle = COLORS.rms;
    ctx.beginPath();
    ctx.moveTo(0, waveH);
    for (const pt of DATA.rms) {{
      const x = secToPx(pt.t);
      const barH = (pt.v / maxRMS) * waveH * 0.92;
      ctx.lineTo(x, waveH - barH);
    }}
    ctx.lineTo(secToPx(DATA.duration), waveH);
    ctx.closePath();
    ctx.fill();

    // Linha de brilho no topo
    ctx.strokeStyle = '#2a5080';
    ctx.lineWidth = 1;
    ctx.beginPath();
    const maxV = Math.max(...DATA.rms.map(p => p.v)) || 1;
    DATA.rms.forEach((pt, i) => {{
      const x = secToPx(pt.t);
      const y = waveH - (pt.v / maxV) * waveH * 0.92;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }});
    ctx.stroke();
  }}

  // ── Separador waveform / palavras ─────────────────────────────────────────
  ctx.strokeStyle = '#1e2130';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, waveH + 1);
  ctx.lineTo(w, waveH + 1);
  ctx.stroke();

  // ── Onsets ────────────────────────────────────────────────────────────────
  if (state.layers.onsets) {{
    ctx.strokeStyle = COLORS.onset;
    ctx.lineWidth = 1;
    for (const t of DATA.onsets) {{
      const x = secToPx(t);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, waveH);
      ctx.stroke();
    }}
  }}

  // ── Palavras ───────────────────────────────────────────────────────────────
  const words = state.showFixed && DATA.has_fixed ? DATA.words_fixed : DATA.words_raw;

  // Duas fileiras: fileira 0 = palavras, fileira 1 = score bars
  for (const w_ of words) {{
    const cls  = wordClass(w_);
    if (!state.layers[cls]) continue;

    const x1 = secToPx(w_.start);
    const x2 = secToPx(w_.end);
    const bw  = Math.max(2, x2 - x1 - 1);
    const col = COLORS[cls];

    // Bloco da palavra
    ctx.fillStyle = col + '28';
    ctx.fillRect(x1, wordY, bw, ROW_H - 2);
    ctx.strokeStyle = col;
    ctx.lineWidth = w_ === state.hoveredWord ? 2 : 1;
    ctx.strokeRect(x1, wordY, bw, ROW_H - 2);

    // Texto da palavra (só se couber)
    if (bw > 20) {{
      ctx.fillStyle = col;
      ctx.font = `${{bw > 50 ? 11 : 9}}px Space Mono, monospace`;
      ctx.save();
      ctx.rect(x1 + 2, wordY, bw - 4, ROW_H - 2);
      ctx.clip();
      ctx.fillText(w_.word, x1 + 3, wordY + 13);
      ctx.restore();
    }}

    // Score bar abaixo
    const scoreY = wordY + ROW_H;
    const score  = w_.score || 0;
    ctx.fillStyle = '#1a1d26';
    ctx.fillRect(x1, scoreY, bw, 4);
    ctx.fillStyle = scoreColor(score);
    ctx.fillRect(x1, scoreY, bw * score, 4);
  }}

  // ── Adlibs ────────────────────────────────────────────────────────────────
  if (state.layers.adlib && DATA.has_adlibs) {{
    const adlibY = wordY + ROW_H + 8;
    for (const a of DATA.adlibs) {{
      if (a.type !== 'adlib') continue;
      const x1 = secToPx(a.start);
      const x2 = secToPx(a.end);
      const bw  = Math.max(2, x2 - x1 - 1);
      ctx.fillStyle = COLORS.adlib + '30';
      ctx.fillRect(x1, adlibY, bw, ROW_H - 2);
      ctx.strokeStyle = COLORS.adlib;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.strokeRect(x1, adlibY, bw, ROW_H - 2);
      ctx.setLineDash([]);
      if (bw > 20) {{
        ctx.fillStyle = COLORS.adlib;
        ctx.font = '9px Space Mono, monospace';
        ctx.save();
        ctx.rect(x1 + 2, adlibY, bw - 4, ROW_H - 2);
        ctx.clip();
        ctx.fillText(a.text, x1 + 3, adlibY + 12);
        ctx.restore();
      }}
    }}
  }}

  // ── Gemini segments ───────────────────────────────────────────────────────
  if (state.layers.gemini && DATA.has_gemini) {{
    const geminiY = wordY + ROW_H * 2 + 12;
    for (const seg of DATA.gemini) {{
      const t0 = seg.abs_start || (seg.approx_start || 0);
      const t1 = seg.abs_end   || (seg.approx_end   || 0);
      const x1 = secToPx(t0);
      const x2 = secToPx(t1);
      const bw  = Math.max(2, x2 - x1 - 1);
      const isAdlib = seg.type === 'adlib';
      const col = isAdlib ? COLORS.adlib : COLORS.gemini;
      ctx.fillStyle = col + '20';
      ctx.fillRect(x1, geminiY, bw, ROW_H - 2);
      ctx.strokeStyle = col + '80';
      ctx.lineWidth = 1;
      ctx.strokeRect(x1, geminiY, bw, ROW_H - 2);
      if (bw > 16) {{
        ctx.fillStyle = col;
        ctx.font = '9px DM Sans, sans-serif';
        ctx.save();
        ctx.rect(x1 + 2, geminiY, bw - 4, ROW_H - 2);
        ctx.clip();
        ctx.fillText(seg.text || '', x1 + 3, geminiY + 12);
        ctx.restore();
      }}
    }}
  }}

  // ── Cursor de tempo selecionado ───────────────────────────────────────────
  if (state.selectedTime !== null) {{
    const x = secToPx(state.selectedTime);
    ctx.strokeStyle = '#ffffff60';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
    ctx.setLineDash([]);
  }}
}}

function scoreColor(s) {{
  if (s >= 0.8) return '#38e8a0';
  if (s >= 0.5) return '#f5c842';
  if (s >= 0.3) return '#ff9a3c';
  return '#ff6b6b';
}}

function formatTime(s) {{
  const m = Math.floor(s / 60);
  const ss = (s % 60).toFixed(1);
  return m + ':' + ss.padStart(4, '0');
}}

// ── Interação mouse ────────────────────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');

canvas.addEventListener('mousemove', e => {{
  const rect = canvas.getBoundingClientRect();
  const mx   = e.clientX - rect.left + wrap.scrollLeft;
  const t    = pxToSec(mx);

  document.getElementById('cursor-time').textContent = formatTime(t);

  const words = state.showFixed && DATA.has_fixed ? DATA.words_fixed : DATA.words_raw;
  const hit   = words.find(w => t >= w.start && t <= w.end);

  if (hit !== state.hoveredWord) {{
    state.hoveredWord = hit || null;
    draw();
  }}

  if (hit) {{
    const cls = wordClass(hit);
    const col = COLORS[cls];
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX + 16) + 'px';
    tooltip.style.top  = (e.clientY - 10) + 'px';
    tooltip.innerHTML = `
      <div class="word" style="color:${{col}}">${{hit.word}}</div>
      <div class="meta">
        ${{hit.start.toFixed(3)}}s → ${{hit.end.toFixed(3)}}s
        &nbsp;|&nbsp; dur: ${{(hit.end - hit.start).toFixed(3)}}s
      </div>
      <div style="margin-top:4px">
        <span class="method" style="background:${{col}}22;color:${{col}}">${{cls.toUpperCase()}}</span>
        &nbsp;
        score: <span style="color:${{scoreColor(hit.score||0)}}">${{(hit.score||0).toFixed(3)}}</span>
        ${{hit.interpolated ? '&nbsp;<span style="color:#ff6b6b;font-size:10px">interpolated</span>' : ''}}
        ${{hit.vad_clamped  ? '&nbsp;<span style="color:#c084fc;font-size:10px">vad_clamped</span>'  : ''}}
      </div>
    `;
  }} else {{
    tooltip.style.display = 'none';
  }}
}});

canvas.addEventListener('mouseleave', () => {{
  tooltip.style.display = 'none';
  state.hoveredWord = null;
  draw();
}});

canvas.addEventListener('click', e => {{
  const rect = canvas.getBoundingClientRect();
  const mx   = e.clientX - rect.left + wrap.scrollLeft;
  const t    = pxToSec(mx);
  state.selectedTime = t;
  draw();
  highlightWordAt(t);
}});

// ── Drag para scroll ───────────────────────────────────────────────────────────
let dragging = false, dragStartX = 0, dragScrollX = 0;
canvas.addEventListener('mousedown', e => {{
  dragging = true;
  dragStartX  = e.clientX;
  dragScrollX = wrap.scrollLeft;
}});
document.addEventListener('mouseup', () => {{ dragging = false; }});
document.addEventListener('mousemove', e => {{
  if (!dragging) return;
  wrap.scrollLeft = dragScrollX - (e.clientX - dragStartX);
}});

// ── Controles ─────────────────────────────────────────────────────────────────
document.getElementById('zoom-slider').addEventListener('input', e => {{
  state.zoom = parseFloat(e.target.value);
  document.getElementById('zoom-label').textContent = state.zoom + '×';
  resize();
}});

document.getElementById('height-slider').addEventListener('input', e => {{
  state.height = parseInt(e.target.value);
  resize();
}});

document.getElementById('btn-fit').addEventListener('click', () => {{
  const availW = wrap.clientWidth - 40;
  state.zoom = availW / (DATA.duration * PX_PER_SEC);
  document.getElementById('zoom-slider').value = state.zoom;
  document.getElementById('zoom-label').textContent = state.zoom.toFixed(2) + '×';
  resize();
}});

const btnRaw   = document.getElementById('btn-raw');
const btnFixed = document.getElementById('btn-fixed');

if (DATA.has_fixed) {{
  btnRaw.style.display   = '';
  btnFixed.style.display = '';
  btnFixed.style.background = 'var(--accent)';
  btnFixed.style.color = '#fff';
}}

btnRaw.addEventListener('click', () => {{
  state.showFixed = false;
  btnRaw.style.background = 'var(--accent)'; btnRaw.style.color = '#fff';
  btnFixed.style.background = ''; btnFixed.style.color = '';
  document.getElementById('list-title').textContent = 'Palavras — word_timing.json (RAW)';
  draw(); buildWordList();
}});

btnFixed.addEventListener('click', () => {{
  state.showFixed = true;
  btnFixed.style.background = 'var(--accent)'; btnFixed.style.color = '#fff';
  btnRaw.style.background = ''; btnRaw.style.color = '';
  document.getElementById('list-title').textContent = 'Palavras — word_timing_fixed.json';
  draw(); buildWordList();
}});

// ── Legenda toggle ─────────────────────────────────────────────────────────────
document.querySelectorAll('.legend-item').forEach(el => {{
  el.addEventListener('click', () => {{
    const layer = el.dataset.layer;
    state.layers[layer] = !state.layers[layer];
    el.classList.toggle('off', !state.layers[layer]);
    draw();
  }});
}});

// ── Lista de palavras ──────────────────────────────────────────────────────────
function buildWordList() {{
  const words = state.showFixed && DATA.has_fixed ? DATA.words_fixed : DATA.words_raw;
  const list  = document.getElementById('word-list');
  list.innerHTML = '';
  for (const w of words) {{
    const cls  = wordClass(w);
    const col  = COLORS[cls];
    const score = w.score || 0;
    const row  = document.createElement('div');
    row.className = 'word-row';
    row.dataset.start = w.start;
    row.innerHTML = `
      <span class="word-text" style="color:${{col}}">${{w.word}}</span>
      <span class="word-time">${{w.start.toFixed(2)}}–${{w.end.toFixed(2)}}s</span>
      <div class="score-bar">
        <div class="score-fill" style="width:${{score*100}}%;background:${{scoreColor(score)}}"></div>
      </div>
      <span class="method-badge" style="background:${{col}}22;color:${{col}}">${{cls}}</span>
    `;
    row.addEventListener('click', () => scrollToTime(w.start));
    list.appendChild(row);
  }}
}}

function buildGeminiList() {{
  const list = document.getElementById('gemini-list');
  if (!DATA.has_gemini) {{
    list.innerHTML = '<span style="color:var(--muted);font-size:11px">gemini_transcript.json não encontrado.<br>Rode o step 03c primeiro.</span>';
    return;
  }}
  list.innerHTML = '';
  for (const seg of DATA.gemini) {{
    const t0  = seg.abs_start || (seg.approx_start || 0);
    const t1  = seg.abs_end   || (seg.approx_end   || 0);
    const col = seg.type === 'adlib' ? COLORS.adlib : COLORS.gemini;
    const row = document.createElement('div');
    row.className = 'word-row';
    row.innerHTML = `
      <span class="word-text-gemini" style="color:${{col}}">${{seg.text || ''}}</span>
      <span class="word-time">${{t0.toFixed(1)}}–${{t1.toFixed(1)}}s</span>
      <span class="method-badge" style="background:${{col}}22;color:${{col}}">${{seg.type||'lyric'}}</span>
    `;
    row.addEventListener('click', () => scrollToTime(t0));
    list.appendChild(row);
  }}
}}

function scrollToTime(t) {{
  state.selectedTime = t;
  draw();
  const x = secToPx(t) - wrap.clientWidth / 2;
  wrap.scrollTo({{ left: Math.max(0, x), behavior: 'smooth' }});
}}

function highlightWordAt(t) {{
  const words = state.showFixed && DATA.has_fixed ? DATA.words_fixed : DATA.words_raw;
  const hit   = words.find(w => t >= w.start && t <= w.end);
  if (!hit) return;
  document.querySelectorAll('.word-row').forEach(r => r.classList.remove('active'));
  const rows = document.querySelectorAll('.word-row');
  const idx  = words.indexOf(hit);
  if (rows[idx]) {{
    rows[idx].classList.add('active');
    rows[idx].scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
  }}
}}

// ── Init ───────────────────────────────────────────────────────────────────────
updateStats();
buildWordList();
buildGeminiList();

window.addEventListener('resize', resize);
// Fit automático na abertura
setTimeout(() => {{
  if (DATA.duration > 0) {{
    const availW = wrap.clientWidth - 40;
    const fitZoom = availW / (DATA.duration * PX_PER_SEC);
    state.zoom = Math.min(fitZoom, 4);
    document.getElementById('zoom-slider').value = state.zoom;
    document.getElementById('zoom-label').textContent = state.zoom.toFixed(2) + '×';
  }}
  resize();
}}, 100);
</script>
</body>
</html>"""


# ── HTTP Server ────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    job_data = None

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            html = build_html(self.job_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        elif self.path == "/data.json":
            data = json.dumps(self.job_data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silencia logs de request


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Karaokê Diagnostic Viewer")
    parser.add_argument("--job-id", required=True, help="Job ID do pipeline")
    parser.add_argument("--port",   type=int, default=5001, help="Porta local (default: 5001)")
    parser.add_argument("--no-browser", action="store_true", help="Não abre o browser automaticamente")
    args = parser.parse_args()

    print(f"Carregando dados do job '{args.job_id}'...")
    data = load_job_data(args.job_id)

    print(f"  Duração:    {data['duration']:.1f}s")
    print(f"  Palavras:   {len(data['words_raw'])} raw / {len(data['words_fixed'])} fixed")
    print(f"  Onsets:     {len(data['onsets'])}")
    print(f"  RMS pts:    {len(data['rms'])}")
    print(f"  Adlibs:     {len(data['adlibs'])} {'✓' if data['has_adlibs'] else '(não encontrado)'}")
    print(f"  Gemini:     {len(data['gemini'])} segmentos {'✓' if data['has_gemini'] else '(não encontrado)'}")

    Handler.job_data = data
    server = HTTPServer(("127.0.0.1", args.port), Handler)

    url = f"http://127.0.0.1:{args.port}/"
    print(f"\n✓ Servidor rodando em {url}")
    print("  Ctrl+C para parar.\n")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")


if __name__ == "__main__":
    main()
