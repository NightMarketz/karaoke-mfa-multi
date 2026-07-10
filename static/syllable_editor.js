'use strict';
// Syncsong-style syllable boundary reviewer.
// Loads the pending (low-confidence) syllable queue, draws the vocal waveform
// for each word window, and lets the reviewer drag/nudge boundaries, then saves
// them to /review/syllables/boundary (which rewrites highlight_segments and
// invalidates the render). The waveform peaks are computed server-side per
// visible window — the browser never decodes the whole stem.

const body = document.body;
const JOB = body.dataset.jobId;
const HAS_VOCALS = body.dataset.hasVocals === '1';
const THRESHOLD = Number(body.dataset.threshold) || 0.6;
const MIN_SEG = 0.05;      // minimum segment length (s)
const RULER = 22;          // px reserved at top of stage for the time ruler

const state = {
  queue: [],
  current: -1,
  bounds: [],   // n+1 boundary times for n segments
  texts: [],    // n segment labels
  sel: 1,       // selected boundary index
  peaks: null,  // {sample_rate, buckets:[[mn,mx]...]} for current view
  view: null,   // {t0,t1} visible time window (zoom/pan applied)
  audioEl: null,
  playing: false,
  loop: null,   // {start,end}
};

const $ = (sel, root = document) => root.querySelector(sel);
const cur = () => state.queue[state.current];
function toast(msg, isErr) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.toggle('err', !!isErr);
  t.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('show'), 1800);
}
function confClass(c) { return c == null ? '' : c >= 0.75 ? 'hi' : c >= THRESHOLD ? 'mid' : 'lo'; }

// ---- data ----------------------------------------------------------------
async function loadQueue() {
  let data;
  try {
    const r = await fetch(`/job/${JOB}/review/syllables/pending`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    data = await r.json();
  } catch (e) {
    $('#main').innerHTML =
      `<div class="empty err"><div class="big">⚠</div>Could not load the pending queue.<br><span class="dim">${escapeHtml(String(e))}</span>` +
      `<div style="margin-top:16px"><button id="retry">Retry</button></div></div>`;
    $('#retry').addEventListener('click', loadQueue);
    $('#counter').textContent = 'error';
    return;
  }
  state.queue = (data.pending || []).map(it => ({ ...it, resolved: false }));
  renderQueue();
  updateCounter();
  if (!state.queue.length) {
    $('#main').innerHTML = '<div class="empty"><div class="big">✓</div>No uncertain syllables. Nothing to review.</div>';
    return;
  }
  if (HAS_VOCALS && !state.audioEl) {
    // Stream the stem (range requests) — never decode the whole file client-side.
    const el = new Audio(`/job/${JOB}/audio/vocals`);
    el.preload = 'none';
    el.addEventListener('timeupdate', onTimeUpdate);
    el.addEventListener('ended', stop);
    state.audioEl = el;
  }
  select(0);
}

let _peaksSeq = 0;
async function loadPeaks() {
  const seq = ++_peaksSeq;
  if (!HAS_VOCALS || state.current < 0) { state.peaks = null; drawWave(); return; }
  const { t0, t1 } = state.view;
  try {
    const r = await fetch(`/job/${JOB}/audio/vocals/peaks?start=${t0.toFixed(3)}&end=${t1.toFixed(3)}&buckets=900`);
    const peaks = await r.json();
    if (seq !== _peaksSeq) return;          // a newer view won the race
    state.peaks = peaks;
  } catch (e) { if (seq === _peaksSeq) state.peaks = null; }
  drawWave();
}
let _peaksTimer = null;
function loadPeaksSoon() { clearTimeout(_peaksTimer); _peaksTimer = setTimeout(loadPeaks, 90); }

function updateCounter() {
  const n = state.queue.filter(it => !it.resolved).length;
  $('#counter').textContent = `${n} pending`;
}

function renderQueue() {
  const q = $('#queue');
  q.innerHTML = '';
  state.queue.forEach((it, i) => {
    const div = document.createElement('div');
    div.className = 'qitem' + (i === state.current ? ' active' : '') + (it.resolved ? ' resolved' : '');
    div.innerHTML = `<span class="word-t">${escapeHtml(it.word_text || '·')}</span>` +
      `<span class="conf ${confClass(it.min_confidence)}">${it.min_confidence.toFixed(2)}</span>`;
    div.addEventListener('click', () => select(i));
    q.appendChild(div);
  });
}

// ---- editor --------------------------------------------------------------
let els = null;
function ensureEditor() {
  if (els) return;
  const tpl = $('#editor-tpl').content.cloneNode(true);
  $('#main').innerHTML = '';
  $('#main').appendChild(tpl);
  els = {
    ctx: $('#ctx'), word: $('#wordline'), stage: $('#stage'), canvas: $('#wave'),
    segs: $('#segs'), playhead: $('#playhead'), phlabel: $('#phlabel'),
    seglist: $('#seglist'), scrollbar: $('#scrollbar'), thumb: $('#scrollthumb'),
  };
  $('#play').addEventListener('click', togglePlay);
  $('#nudgeL').addEventListener('click', () => nudge(-0.1));
  $('#nudgeR').addEventListener('click', () => nudge(0.1));
  $('#split').addEventListener('click', splitAtPlayhead);
  $('#merge').addEventListener('click', mergeSelected);
  $('#reset').addEventListener('click', () => { loadSegments(cur()); renderSegments(); drawWave(); });
  $('#save').addEventListener('click', () => save(false));
  $('#accept').addEventListener('click', () => save(true));
  $('#skip').addEventListener('click', () => advance());
  $('#zoomIn').addEventListener('click', () => zoomView(1.4));
  $('#zoomOut').addEventListener('click', () => zoomView(1 / 1.4));
  $('#zoomFit').addEventListener('click', () => { state.view = baseWin(cur()); refreshView(); });
  els.stage.addEventListener('wheel', onWheel, { passive: false });
  els.thumb.addEventListener('pointerdown', startScroll);
  window.addEventListener('resize', () => { drawWave(); updateScrollbar(); });
}

// ---- view / zoom / pan ---------------------------------------------------
function baseWin(it) {
  // Adaptive zoom: pad proportional to the word span (floor/cap) so short words
  // are not squeezed into a sliver by a fixed pad, and long words keep context.
  const span = Math.max(0.05, it.word_end - it.word_start);
  const pad = Math.min(0.6, Math.max(0.12, span * 0.6));
  return { t0: Math.max(0, it.word_start - pad), t1: it.word_end + pad };
}
function fullExt(it) {
  // Pannable extent: the word plus generous context on each side.
  const span = Math.max(0.05, it.word_end - it.word_start);
  const ctx = Math.min(2.0, Math.max(0.5, span * 1.5));
  return { f0: Math.max(0, it.word_start - ctx), f1: it.word_end + ctx };
}
function clampView(v) {
  const { f0, f1 } = fullExt(cur());
  let span = v.t1 - v.t0;
  const maxSpan = f1 - f0;
  if (span >= maxSpan) return { t0: f0, t1: f1 };
  if (v.t0 < f0) { v.t1 += f0 - v.t0; v.t0 = f0; }
  if (v.t1 > f1) { v.t0 -= v.t1 - f1; v.t1 = f1; }
  return v;
}
function zoomView(factor, centerT) {
  const v = state.view;
  const c = centerT == null ? (v.t0 + v.t1) / 2 : centerT;
  const r = (c - v.t0) / (v.t1 - v.t0);
  let span = (v.t1 - v.t0) / factor;
  const ext = fullExt(cur());
  span = Math.max(0.08, Math.min(ext.f1 - ext.f0, span));
  state.view = clampView({ t0: c - r * span, t1: c - r * span + span });
  refreshView();
}
function panView(dt) { state.view = clampView({ t0: state.view.t0 + dt, t1: state.view.t1 + dt }); refreshView(); }
function refreshView() { renderSegments(); drawWave(); updateScrollbar(); loadPeaksSoon(); }

function onWheel(e) {
  e.preventDefault();
  if (e.shiftKey) panView((state.view.t1 - state.view.t0) * (e.deltaY > 0 ? 0.12 : -0.12));
  else zoomView(e.deltaY < 0 ? 1.18 : 1 / 1.18, xToT(e.clientX));
}
function startScroll(e) {
  e.preventDefault();
  const rect = els.scrollbar.getBoundingClientRect();
  const ext = fullExt(cur());
  const span = state.view.t1 - state.view.t0;
  const startX = e.clientX, startT0 = state.view.t0;
  const move = ev => {
    const dt = ((ev.clientX - startX) / rect.width) * (ext.f1 - ext.f0);
    state.view = clampView({ t0: startT0 + dt, t1: startT0 + dt + span });
    refreshView();
  };
  const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}
function updateScrollbar() {
  if (!els) return;
  const ext = fullExt(cur());
  const total = ext.f1 - ext.f0;
  const left = ((state.view.t0 - ext.f0) / total) * 100;
  const w = ((state.view.t1 - state.view.t0) / total) * 100;
  els.thumb.style.left = Math.max(0, left) + '%';
  els.thumb.style.width = Math.min(100, w) + '%';
}

const win = () => state.view;
const tToPct = (t) => { const { t0, t1 } = state.view; return ((t - t0) / (t1 - t0)) * 100; };
const xToT = (clientX) => {
  const { t0, t1 } = state.view;
  const rect = els.stage.getBoundingClientRect();
  const f = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  return t0 + f * (t1 - t0);
};

function loadSegments(it) {
  const segs = it.segments.slice().sort((a, b) => a.start - b.start);
  state.bounds = [segs[0].start];
  state.texts = [];
  state.confs = [];
  segs.forEach(s => { state.bounds.push(s.end); state.texts.push(s.text || ''); state.confs.push(s.confidence); });
  state.sel = Math.min(1, state.bounds.length - 1);
  state.loop = { start: it.word_start, end: it.word_end };
}

function select(i) {
  if (i < 0 || i >= state.queue.length) return;
  stop();
  state.current = i;
  ensureEditor();
  const it = state.queue[i];
  loadSegments(it);
  state.view = baseWin(it);
  els.ctx.innerHTML = `<b>${escapeHtml(it.line_text || '')}</b> · word [${it.word_start.toFixed(2)}–${it.word_end.toFixed(2)}s] · min conf <span style="color:var(--${confClass(it.min_confidence) === 'hi' ? 'good' : confClass(it.min_confidence) === 'mid' ? 'warn' : 'bad'})">${it.min_confidence.toFixed(2)}</span>`;
  els.word.textContent = it.word_text || '';
  renderQueue();
  renderSegments();
  updateScrollbar();
  loadPeaks();
}

// ---- canvas: waveform + ruler --------------------------------------------
function niceStep(span, targetTicks) {
  const raw = span / targetTicks;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / mag;
  const step = (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * mag;
  return step;
}
function drawWave() {
  if (!els || state.current < 0) return;
  const c = els.canvas;
  const dpr = window.devicePixelRatio || 1;
  const rect = els.stage.getBoundingClientRect();
  c.width = rect.width * dpr; c.height = rect.height * dpr;
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = rect.width, H = rect.height;
  ctx.clearRect(0, 0, W, H);
  const { t0, t1 } = state.view;
  const it = cur();

  // word-span shading (full height)
  ctx.fillStyle = 'rgba(0,245,255,0.05)';
  const wx0 = (tToPct(it.word_start) / 100) * W, wx1 = (tToPct(it.word_end) / 100) * W;
  ctx.fillRect(wx0, 0, wx1 - wx0, H);

  // waveform (below the ruler band)
  const midY = (RULER + H) / 2, amp = (H - RULER) / 2 - 2;
  const buckets = state.peaks && Array.isArray(state.peaks.buckets) ? state.peaks.buckets : null;
  if (buckets && buckets.length) {
    ctx.fillStyle = 'rgba(0,245,255,0.45)';
    const n = buckets.length;
    for (let x = 0; x < W; x++) {
      const k = Math.min(n - 1, Math.floor(n * x / W));
      const mn = buckets[k][0], mx = buckets[k][1];
      const y0 = midY - mx * amp, y1 = midY - mn * amp;
      ctx.fillRect(x, y0, 1, Math.max(1, y1 - y0));
    }
  } else {
    ctx.fillStyle = '#7a7a94';
    ctx.font = '12px monospace';
    ctx.fillText(HAS_VOCALS ? 'loading waveform…' : 'waveform unavailable', 10, midY);
  }

  // time ruler (ticks + labels) over the top band
  ctx.fillStyle = 'rgba(7,7,13,0.85)';
  ctx.fillRect(0, 0, W, RULER);
  ctx.strokeStyle = 'rgba(0,245,255,0.15)';
  ctx.beginPath(); ctx.moveTo(0, RULER - 0.5); ctx.lineTo(W, RULER - 0.5); ctx.stroke();
  const span = t1 - t0;
  const step = niceStep(span, Math.max(3, Math.floor(W / 90)));
  const dec = step < 0.1 ? 3 : step < 1 ? 2 : step < 10 ? 1 : 0;
  ctx.fillStyle = '#7a7a94';
  ctx.font = '10px monospace';
  ctx.strokeStyle = 'rgba(122,122,148,0.35)';
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) {
    const x = (tToPct(t) / 100) * W;
    ctx.beginPath(); ctx.moveTo(x, RULER - 6); ctx.lineTo(x, RULER); ctx.stroke();
    ctx.fillText(t.toFixed(dec) + 's', Math.min(W - 30, x + 3), 12);
  }
}

// ---- segments / handles --------------------------------------------------
function renderSegments() {
  const segs = els.segs;
  segs.innerHTML = '';
  const n = state.texts.length;
  for (let i = 0; i < n; i++) {
    const div = document.createElement('div');
    const cc = confClass(state.confs && state.confs[i]);
    div.className = 'seg' + (cc ? ' c' + cc : '') + (i === state.sel || i === state.sel - 1 ? ' selseg' : '');
    div.style.left = tToPct(state.bounds[i]) + '%';
    div.style.width = (tToPct(state.bounds[i + 1]) - tToPct(state.bounds[i])) + '%';
    div.innerHTML = `<span class="lbl">${escapeHtml(state.texts[i] || '·')}</span>`;
    segs.appendChild(div);
  }
  // boundary handles — outer (word-edge) handles marked .edge
  for (let b = 0; b < state.bounds.length; b++) {
    const h = document.createElement('div');
    const edge = b === 0 || b === state.bounds.length - 1;
    h.className = 'handle' + (b === state.sel ? ' sel' : '') + (edge ? ' edge' : '');
    h.style.left = tToPct(state.bounds[b]) + '%';
    h.dataset.b = b;
    h.title = state.bounds[b].toFixed(3) + 's' + (edge ? ' (word edge)' : '');
    h.addEventListener('pointerdown', startDrag);
    segs.appendChild(h);
  }
  renderSegList();
}

function renderSegList() {
  const list = els.seglist;
  list.innerHTML = '';
  for (let i = 0; i < state.texts.length; i++) {
    const conf = state.confs ? state.confs[i] : null;
    const cc = confClass(conf);
    const row = document.createElement('div');
    row.className = 'segrow' + (cc ? ' c' + cc : '');
    row.innerHTML =
      `<span class="dot"></span>` +
      `<input class="txt" value="${escapeHtml(state.texts[i])}" data-i="${i}">` +
      `<span class="rng">${state.bounds[i].toFixed(2)}–${state.bounds[i + 1].toFixed(2)}s (${(state.bounds[i + 1] - state.bounds[i]).toFixed(2)}s)</span>` +
      (conf != null ? `<span class="c" style="color:var(--${cc === 'hi' ? 'good' : cc === 'mid' ? 'warn' : 'bad'})">c ${conf.toFixed(2)}</span>` : '');
    row.querySelector('input').addEventListener('input', e => { state.texts[i] = e.target.value; });
    list.appendChild(row);
  }
}

// ---- boundary editing ----------------------------------------------------
function clampBound(b, t) {
  const it = cur();
  const lo = b === 0 ? it.word_start : state.bounds[b - 1] + MIN_SEG;
  const hi = b === state.bounds.length - 1 ? it.word_end : state.bounds[b + 1] - MIN_SEG;
  return Math.min(hi, Math.max(lo, t));
}
function setBound(b, t) {
  state.bounds[b] = round3(clampBound(b, t));
  renderSegments();
}
function startDrag(e) {
  e.preventDefault();
  const b = Number(e.currentTarget.dataset.b);
  state.sel = b;
  renderSegments();
  const move = ev => setBound(b, xToT(ev.clientX));
  const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}
function nudge(dt) {
  if (state.sel < 0 || state.sel >= state.bounds.length) state.sel = 1;
  setBound(state.sel, state.bounds[state.sel] + dt);
}
function splitAtPlayhead() {
  const t = state.audioEl ? state.audioEl.currentTime : (state.loop.start + state.loop.end) / 2;
  for (let i = 0; i < state.texts.length; i++) {
    if (t > state.bounds[i] + MIN_SEG && t < state.bounds[i + 1] - MIN_SEG) {
      const txt = state.texts[i];
      const mid = Math.max(1, Math.round(txt.length / 2));
      state.texts.splice(i, 1, txt.slice(0, mid), txt.slice(mid));
      state.bounds.splice(i + 1, 0, round3(t));
      if (state.confs) state.confs.splice(i, 1, state.confs[i], state.confs[i]);
      state.sel = i + 1;
      renderSegments();
      return;
    }
  }
  toast('Move the playhead inside a segment to split');
}
function mergeSelected() {
  const b = state.sel;
  if (b <= 0 || b >= state.bounds.length - 1) { toast('Select an internal boundary to merge'); return; }
  state.texts.splice(b - 1, 2, (state.texts[b - 1] || '') + (state.texts[b] || ''));
  if (state.confs) state.confs.splice(b - 1, 2, Math.min(state.confs[b - 1], state.confs[b]));
  state.bounds.splice(b, 1);
  state.sel = Math.min(b, state.bounds.length - 1);
  renderSegments();
}

// ---- playback ------------------------------------------------------------
function togglePlay() { state.playing ? stop() : play(); }
function play() {
  if (!state.audioEl) { toast('No audio to play'); return; }
  state.audioEl.currentTime = state.loop.start;
  state.audioEl.play();
  state.playing = true;
  const p = $('#play'); if (p) p.textContent = '❚❚ Pause';
}
function stop() {
  if (state.audioEl) state.audioEl.pause();
  state.playing = false;
  const p = $('#play'); if (p) p.innerHTML = '▶ Play loop <span class="dim">(space)</span>';
  if (els && els.playhead) els.playhead.style.opacity = 0;
}
function onTimeUpdate() {
  if (!state.audioEl || state.current < 0 || !els) return;
  const t = state.audioEl.currentTime;
  if (state.playing && t >= state.loop.end + 0.12) { state.audioEl.currentTime = state.loop.start; return; }
  const { t0, t1 } = state.view;
  if (t >= t0 && t <= t1) {
    els.playhead.style.left = tToPct(t) + '%';
    els.playhead.style.opacity = 1;
    if (els.phlabel) els.phlabel.textContent = t.toFixed(2) + 's';
  } else els.playhead.style.opacity = 0;
}

// ---- persistence ---------------------------------------------------------
async function save(acceptAsIs) {
  const it = cur();
  const segments = [];
  for (let i = 0; i < state.texts.length; i++) {
    segments.push({ text: (state.texts[i] || '').trim() || it.word_text.charAt(i) || '·',
                    start: state.bounds[i], end: state.bounds[i + 1] });
  }
  try {
    const r = await fetch(`/job/${JOB}/review/syllables/boundary`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ line_id: it.line_id, word_id: it.word_id, segments }),
    });
    if (!r.ok) { const e = await r.json().catch(() => ({})); toast('Rejected: ' + (e.error || r.status), true); return; }
    it.resolved = true;
    toast(acceptAsIs ? 'Accepted' : 'Saved · render invalidated');
    advance();
  } catch (e) { toast('Save failed: ' + e, true); }
}
function advance() {
  renderQueue();
  const next = state.queue.findIndex((it, i) => i > state.current && !it.resolved);
  const any = next >= 0 ? next : state.queue.findIndex(it => !it.resolved);
  if (any >= 0) select(any);
  else { stop(); $('#main').innerHTML = '<div class="empty"><div class="big">✓</div>All pending syllables reviewed.<br><span class="dim">Re-run render (s06/s07) to apply.</span></div>'; els = null; }
  updateCounter();
}

// ---- keyboard ------------------------------------------------------------
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  if (state.current < 0) return;
  const step = e.shiftKey ? 0.1 : 0.02;
  switch (e.key) {
    case ' ': e.preventDefault(); togglePlay(); break;
    case 'ArrowLeft': e.preventDefault(); nudge(-step); break;
    case 'ArrowRight': e.preventDefault(); nudge(step); break;
    case 'Tab': e.preventDefault(); state.sel = (state.sel + 1) % state.bounds.length; renderSegments(); break;
    case 'ArrowUp': e.preventDefault(); select(state.current - 1); break;
    case 'ArrowDown': e.preventDefault(); select(state.current + 1); break;
    case 'Enter': e.preventDefault(); save(false); break;
    case '+': case '=': e.preventDefault(); zoomView(1.4); break;
    case '-': case '_': e.preventDefault(); zoomView(1 / 1.4); break;
  }
});

// ---- utils ---------------------------------------------------------------
function round3(t) { return Math.round(t * 1000) / 1000; }
function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

loadQueue();
