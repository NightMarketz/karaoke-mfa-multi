'use strict';
// Syncsong-style syllable boundary reviewer — waveform-first workspace.
// Loads the pending (low-confidence) syllable queue, draws the vocal waveform
// per word window, and lets the reviewer scrub/audition, drag/snap/nudge
// boundaries, then saves them to /review/syllables/boundary (which rewrites
// highlight_segments and invalidates the render).
//
// The waveform peaks are computed server-side per visible window — the browser
// never decodes the whole stem. Onset ticks are derived from those peaks
// (energy flux), so snapping needs no extra backend call.

const body = document.body;
const JOB = body.dataset.jobId;
const HAS_VOCALS = body.dataset.hasVocals === '1';
const THRESHOLD = Number(body.dataset.threshold) || 0.6;
const MIN_SEG = 0.05;      // minimum segment length (s)
const RULER = 22;          // px reserved at top of stage for the time ruler
const LANE = 60;           // px reserved at bottom of stage for the segment lane
const SNAP_PX = 10;        // drag snaps to an onset tick within this many px

const state = {
  queue: [],
  current: -1,
  bounds: [],   // n+1 boundary times for n segments
  texts: [],    // n segment labels
  confs: [],    // n per-segment confidences (null after manual split/merge)
  sel: 1,       // selected boundary index
  peaks: null,  // {sample_rate, buckets:[[mn,mx]...]} for current view
  onsets: [],   // candidate onset times (s) derived from peaks
  view: null,   // {t0,t1} visible time window (zoom/pan applied)
  audioEl: null,
  playing: false,
  loop: null,   // {start,end} playback loop
  rate: 1,      // playback speed
  dirty: false, // unsaved edits on the current word
  filter: 'pending', // queue filter: pending | worst | all
  undo: [],     // local undo stack for the current word (snapshots)
  origKey: '',  // signature of the word's original segments (for dirty check)
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
function confMark(c) { const k = confClass(c); return k === 'hi' ? '✓' : k === 'mid' ? '~' : k === 'lo' ? '!' : ''; }
function confVar(c) { const k = confClass(c); return k === 'hi' ? 'good' : k === 'mid' ? 'warn' : 'bad'; }
function setDirty(v) { state.dirty = v; document.body.classList.toggle('dirty', v); }
function segKey() { return JSON.stringify([state.bounds, state.texts]); }
function recomputeDirty() { setDirty(segKey() !== state.origKey); }

// ---- local undo (per word) -----------------------------------------------
function snapshot() { return { bounds: state.bounds.slice(), texts: state.texts.slice(), confs: state.confs.slice(), sel: state.sel }; }
function pushUndo() { state.undo.push(snapshot()); if (state.undo.length > 60) state.undo.shift(); }
function undo() {
  if (!state.undo.length) { toast('Nada para desfazer'); return; }
  const s = state.undo.pop();
  state.bounds = s.bounds; state.texts = s.texts; state.confs = s.confs; state.sel = s.sel;
  recomputeDirty();
  renderSegments();
}

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
  updateProgress();
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
  if (!HAS_VOCALS || state.current < 0) { state.peaks = null; state.onsets = []; drawWave(); return; }
  const { t0, t1 } = state.view;
  const q = `start=${t0.toFixed(3)}&end=${t1.toFixed(3)}`;
  try {
    // Peaks + server-side onsets in parallel. Onsets are computed at full audio
    // resolution server-side (spectral flux); fall back to the client heuristic
    // if that route is unavailable or errors.
    const [peaks, onsetResp] = await Promise.all([
      fetch(`/job/${JOB}/audio/vocals/peaks?${q}&buckets=900`).then(r => r.json()),
      fetch(`/job/${JOB}/audio/vocals/onsets?${q}`).then(r => r.ok ? r.json() : null).catch(() => null),
    ]);
    if (seq !== _peaksSeq) return;          // a newer view won the race
    state.peaks = peaks;
    if (onsetResp && Array.isArray(onsetResp.onsets)) state.onsets = onsetResp.onsets;
    else computeOnsets();                   // fallback: derive from peaks buckets
  } catch (e) { if (seq === _peaksSeq) { state.peaks = null; state.onsets = []; } }
  drawWave();
}
let _peaksTimer = null;
function loadPeaksSoon() { clearTimeout(_peaksTimer); _peaksTimer = setTimeout(loadPeaks, 90); }

// Fallback onset detector (used only when the server /onsets route is
// unavailable): prominent peaks in the positive energy flux of the peaks
// buckets. Smoothed to kill micro-wiggles, thresholded on flux mean+2σ, then
// picked strongest-first with a ~45ms minimum spacing (min-syllable scale) so
// short high-resolution windows don't produce a forest of noise ticks.
function computeOnsets() {
  state.onsets = [];
  const p = state.peaks;
  if (!p || !Array.isArray(p.buckets) || !p.buckets.length) return;
  const b = p.buckets, n = b.length;
  const raw = new Array(n);
  for (let i = 0; i < n; i++) raw[i] = Math.max(Math.abs(b[i][0]), Math.abs(b[i][1]));
  const eng = new Array(n);           // moving-average smooth (radius 2)
  for (let i = 0; i < n; i++) {
    let s = 0, c = 0;
    for (let j = Math.max(0, i - 2); j <= Math.min(n - 1, i + 2); j++) { s += raw[j]; c++; }
    eng[i] = s / c;
  }
  const flux = new Array(n).fill(0);
  for (let i = 1; i < n; i++) flux[i] = Math.max(0, eng[i] - eng[i - 1]);
  let m = 0; for (const f of flux) m += f; m /= n;
  let v = 0; for (const f of flux) v += (f - m) * (f - m); v /= n;
  const thr = m + 2.0 * Math.sqrt(v);
  const { t0, t1 } = state.view, span = t1 - t0;
  const minGap = Math.max(2, Math.floor(0.045 * n / span));   // >= ~45ms between onsets
  const cand = [];
  for (let i = 2; i < n - 2; i++) {
    if (flux[i] >= thr && flux[i] >= flux[i - 1] && flux[i] > flux[i + 1] && eng[i] > 0.06) {
      cand.push({ i, f: flux[i] });
    }
  }
  cand.sort((a, b) => b.f - a.f);      // strongest first, enforce spacing, cap
  const chosen = [];
  for (const c of cand) {
    if (chosen.length >= 16) break;
    if (chosen.every(k => Math.abs(k - c.i) >= minGap)) chosen.push(c.i);
  }
  chosen.sort((a, b) => a - b);
  state.onsets = chosen.map(i => t0 + (i / n) * span);
}

function updateProgress() {
  const total = state.queue.length;
  const done = state.queue.filter(it => it.resolved).length;
  const left = total - done;
  $('#counter').textContent = total ? `${left} pending · ${done}/${total} done` : '—';
  const fill = $('#pfill'); if (fill) fill.style.width = total ? (done / total * 100) + '%' : '0';
}

function qitemEl(it, i) {
  const div = document.createElement('div');
  div.className = 'qitem' + (i === state.current ? ' active' : '') + (it.resolved ? ' resolved' : '');
  const cc = confClass(it.min_confidence);
  div.innerHTML = `<span class="word-t">${escapeHtml(it.word_text || '·')}</span>` +
    `<span class="conf ${cc}"><span>${confMark(it.min_confidence)}</span>${it.min_confidence.toFixed(2)}</span>`;
  div.addEventListener('click', () => select(i));
  return div;
}
// Build the display list: a flat worst-first list ('worst') or verses grouped
// by line, each group ordered by reading position and floated up by its worst
// confidence.
function queueSections() {
  const rows = state.queue.map((it, idx) => ({ it, idx }));
  if (state.filter === 'worst') {
    return [{ header: null, rows: rows.filter(r => !r.it.resolved).sort((a, b) => a.it.min_confidence - b.it.min_confidence) }];
  }
  const visible = state.filter === 'all' ? rows : rows.filter(r => !r.it.resolved);
  const groups = new Map();
  for (const r of visible) {
    const k = r.it.line_id || '';
    if (!groups.has(k)) groups.set(k, { line_text: r.it.line_text, rows: [], worst: 1, total: 0 });
    const g = groups.get(k);
    g.rows.push(r); g.worst = Math.min(g.worst, r.it.min_confidence);
  }
  const arr = [...groups.values()];
  arr.forEach(g => g.rows.sort((a, b) => a.it.word_start - b.it.word_start));
  arr.sort((a, b) => a.worst - b.worst);
  return arr.map(g => ({ header: g, rows: g.rows }));
}
function renderQueue() {
  const q = $('#queue');
  q.innerHTML = '';
  let shown = 0;
  for (const sect of queueSections()) {
    if (sect.header) {
      const done = sect.rows.filter(r => r.it.resolved).length;
      const h = document.createElement('div');
      h.className = 'qgroup';
      h.innerHTML = `<span class="gt">${escapeHtml(sect.header.line_text || '(sem verso)')}</span>` +
        `<span class="gc">${sect.rows.length - done}/${sect.rows.length}</span>`;
      q.appendChild(h);
    }
    for (const r of sect.rows) { q.appendChild(qitemEl(r.it, r.idx)); shown++; }
  }
  if (!shown) q.innerHTML = '<div class="qempty">Nada aqui neste filtro.</div>';
}
function setupFilters() {
  document.querySelectorAll('#filters .chip').forEach(b => {
    b.addEventListener('click', () => {
      state.filter = b.dataset.f;
      document.querySelectorAll('#filters .chip').forEach(x => x.classList.toggle('on', x === b));
      renderQueue();
    });
  });
}
function setupHelp() {
  const m = $('#shortcuts');
  $('#help').addEventListener('click', () => { m.hidden = !m.hidden; });
  $('#closeHelp').addEventListener('click', () => { m.hidden = true; });
  m.addEventListener('click', e => { if (e.target === m) m.hidden = true; });
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
    scrub: $('#scrub'), segs: $('#segs'), playhead: $('#playhead'), phlabel: $('#phlabel'),
    seglist: $('#seglist'), scrollbar: $('#scrollbar'), thumb: $('#scrollthumb'),
  };
  $('#play').addEventListener('click', playWord);
  $('#rate').addEventListener('click', cycleRate);
  $('#nudgeL').addEventListener('click', () => nudge(-0.1));
  $('#nudgeR').addEventListener('click', () => nudge(0.1));
  $('#split').addEventListener('click', splitAtPlayhead);
  $('#merge').addEventListener('click', mergeSelected);
  $('#undo').addEventListener('click', undo);
  $('#reset').addEventListener('click', resetWord);
  $('#save').addEventListener('click', () => save(false));
  $('#accept').addEventListener('click', () => save(true));
  $('#skip').addEventListener('click', skip);
  $('#zoomIn').addEventListener('click', () => zoomView(1.4));
  $('#zoomOut').addEventListener('click', () => zoomView(1 / 1.4));
  $('#zoomFit').addEventListener('click', () => { state.view = baseWin(cur()); refreshView(); });
  els.stage.addEventListener('wheel', onWheel, { passive: false });
  els.scrub.addEventListener('pointerdown', startScrub);
  els.thumb.addEventListener('pointerdown', startScroll);
  window.addEventListener('resize', () => { layout(); drawWave(); renderSegments(); updateScrollbar(); });
}

function layout() {
  if (!els) return;
  const H = els.stage.getBoundingClientRect().height;
  els.scrub.style.top = RULER + 'px';
  els.scrub.style.height = (H - LANE - RULER) + 'px';
}

// ---- view / zoom / pan ---------------------------------------------------
function baseWin(it) {
  // Adaptive zoom: pad proportional to the word span (floor/cap).
  const span = Math.max(0.05, it.word_end - it.word_start);
  const pad = Math.min(0.6, Math.max(0.12, span * 0.6));
  return { t0: Math.max(0, it.word_start - pad), t1: it.word_end + pad };
}
function fullExt(it) {
  const span = Math.max(0.05, it.word_end - it.word_start);
  const ctx = Math.min(2.0, Math.max(0.5, span * 1.5));
  return { f0: Math.max(0, it.word_start - ctx), f1: it.word_end + ctx };
}
function clampView(v) {
  const { f0, f1 } = fullExt(cur());
  const maxSpan = f1 - f0;
  if (v.t1 - v.t0 >= maxSpan) return { t0: f0, t1: f1 };
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
  els.thumb.style.left = Math.max(0, (state.view.t0 - ext.f0) / total * 100) + '%';
  els.thumb.style.width = Math.min(100, (state.view.t1 - state.view.t0) / total * 100) + '%';
}

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
  state.origKey = segKey();
}

function select(i) {
  if (i < 0 || i >= state.queue.length) return;
  stop();
  state.current = i;
  ensureEditor();
  const it = state.queue[i];
  loadSegments(it);
  state.undo = [];
  setDirty(false);
  state.view = baseWin(it);
  els.ctx.innerHTML = `<b>${escapeHtml(it.line_text || '')}</b> · word [${it.word_start.toFixed(2)}–${it.word_end.toFixed(2)}s] · min conf <span style="color:var(--${confVar(it.min_confidence)})">${it.min_confidence.toFixed(2)}</span>`;
  els.word.textContent = it.word_text || '';
  renderQueue();
  layout();
  renderSegments();
  updateScrollbar();
  loadPeaks();
}

// ---- canvas: waveform + ruler + onset ticks ------------------------------
function niceStep(span, targetTicks) {
  const raw = span / targetTicks;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / mag;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * mag;
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
  const laneTop = H - LANE;
  ctx.clearRect(0, 0, W, H);
  const { t0, t1 } = state.view;
  const it = cur();

  // word-span shading (full height)
  ctx.fillStyle = 'rgba(0,245,255,0.05)';
  const wx0 = (tToPct(it.word_start) / 100) * W, wx1 = (tToPct(it.word_end) / 100) * W;
  ctx.fillRect(wx0, 0, wx1 - wx0, H);

  // segment lane background
  ctx.fillStyle = 'rgba(255,255,255,0.02)';
  ctx.fillRect(0, laneTop, W, LANE);
  ctx.strokeStyle = 'rgba(0,245,255,0.15)';
  ctx.beginPath(); ctx.moveTo(0, laneTop + 0.5); ctx.lineTo(W, laneTop + 0.5); ctx.stroke();

  // waveform (between ruler and lane)
  const midY = (RULER + laneTop) / 2, amp = (laneTop - RULER) / 2 - 2;
  const buckets = state.peaks && Array.isArray(state.peaks.buckets) ? state.peaks.buckets : null;
  if (buckets && buckets.length) {
    ctx.fillStyle = 'rgba(0,245,255,0.45)';
    const n = buckets.length;
    for (let x = 0; x < W; x++) {
      const k = Math.min(n - 1, Math.floor(n * x / W));
      const y0 = midY - buckets[k][1] * amp, y1 = midY - buckets[k][0] * amp;
      ctx.fillRect(x, y0, 1, Math.max(1, y1 - y0));
    }
  } else {
    ctx.fillStyle = '#7a7a94';
    ctx.font = '12px monospace';
    ctx.fillText(HAS_VOCALS ? 'loading waveform…' : 'waveform unavailable', 10, midY);
  }

  // onset ticks (snap targets) just above the lane divider
  if (state.onsets.length) {
    ctx.fillStyle = 'rgba(123,47,190,0.85)';
    for (const o of state.onsets) {
      if (o < t0 || o > t1) continue;
      const x = (tToPct(o) / 100) * W;
      ctx.fillRect(x - 0.75, laneTop - 10, 1.5, 10);
    }
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
  const H = els.stage.getBoundingClientRect().height;
  for (let i = 0; i < n; i++) {
    const div = document.createElement('div');
    const cc = confClass(state.confs[i]);
    div.className = 'seg' + (cc ? ' c' + cc : '') + (i === state.sel || i === state.sel - 1 ? ' selseg' : '');
    div.style.left = tToPct(state.bounds[i]) + '%';
    div.style.width = (tToPct(state.bounds[i + 1]) - tToPct(state.bounds[i])) + '%';
    const mark = confMark(state.confs[i]);
    div.innerHTML = `<span class="lbl">${escapeHtml(state.texts[i] || '·')}</span>` +
      (mark ? `<span class="cmark">${mark}</span>` : '');
    div.title = 'Click to hear this syllable';
    div.addEventListener('pointerdown', e => { e.stopPropagation(); playSegment(i); });
    segs.appendChild(div);
  }
  // boundary handles — focusable sliders; outer (word-edge) handles marked .edge
  for (let b = 0; b < state.bounds.length; b++) {
    const h = document.createElement('div');
    const edge = b === 0 || b === state.bounds.length - 1;
    h.className = 'handle' + (b === state.sel ? ' sel' : '') + (edge ? ' edge' : '');
    h.style.left = tToPct(state.bounds[b]) + '%';
    h.dataset.b = b;
    h.tabIndex = 0;
    h.setAttribute('role', 'slider');
    h.setAttribute('aria-label', `Boundary ${b + 1} of ${state.bounds.length}${edge ? ' (word edge)' : ''}`);
    h.setAttribute('aria-valuemin', cur().word_start.toFixed(3));
    h.setAttribute('aria-valuemax', cur().word_end.toFixed(3));
    h.setAttribute('aria-valuenow', state.bounds[b].toFixed(3));
    h.title = state.bounds[b].toFixed(3) + 's' + (edge ? ' (word edge)' : '');
    h.addEventListener('pointerdown', startDrag);
    h.addEventListener('focus', () => { if (state.sel !== b) { state.sel = b; renderSegments(); } });
    segs.appendChild(h);
  }
  renderSegList();
}

function renderSegList() {
  const list = els.seglist;
  list.innerHTML = '';
  for (let i = 0; i < state.texts.length; i++) {
    const conf = state.confs[i];
    const cc = confClass(conf);
    const row = document.createElement('div');
    row.className = 'segrow' + (cc ? ' c' + cc : '');
    row.innerHTML =
      `<button class="mini" title="Hear syllable" data-play="${i}">▶</button>` +
      `<span class="dot"></span>` +
      `<input class="txt" value="${escapeHtml(state.texts[i])}" data-i="${i}" aria-label="Syllable ${i + 1} text">` +
      `<span class="rng">${state.bounds[i].toFixed(2)}–${state.bounds[i + 1].toFixed(2)}s (${(state.bounds[i + 1] - state.bounds[i]).toFixed(2)}s)</span>` +
      (conf != null ? `<span class="c" style="color:var(--${confVar(conf)})">${confMark(conf)} ${conf.toFixed(2)}</span>` : '');
    const inp = row.querySelector('input');
    let edited = false;                       // one undo snapshot per editing session
    inp.addEventListener('focus', () => { edited = false; });
    inp.addEventListener('input', e => {
      if (!edited) { pushUndo(); edited = true; }
      state.texts[i] = e.target.value; recomputeDirty();
    });
    row.querySelector('[data-play]').addEventListener('click', () => playSegment(i));
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
  recomputeDirty();
  renderSegments();
}
function snapTime(t) {
  if (!state.onsets.length) return t;
  const rect = els.stage.getBoundingClientRect();
  const tol = SNAP_PX / (rect.width / (state.view.t1 - state.view.t0));
  let best = t, bd = tol;
  for (const o of state.onsets) { const d = Math.abs(o - t); if (d < bd) { bd = d; best = o; } }
  return best;
}
function startDrag(e) {
  e.preventDefault();
  e.currentTarget.focus();
  pushUndo();
  const b = Number(e.currentTarget.dataset.b);
  state.sel = b;
  renderSegments();
  const move = ev => setBound(b, ev.shiftKey ? xToT(ev.clientX) : snapTime(xToT(ev.clientX)));
  const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}
function nudge(dt) {
  if (state.sel < 0 || state.sel >= state.bounds.length) state.sel = 1;
  pushUndo();
  setBound(state.sel, state.bounds[state.sel] + dt);
}
function splitAtPlayhead() {
  const t = state.audioEl ? state.audioEl.currentTime : (state.loop.start + state.loop.end) / 2;
  for (let i = 0; i < state.texts.length; i++) {
    if (t > state.bounds[i] + MIN_SEG && t < state.bounds[i + 1] - MIN_SEG) {
      pushUndo();
      const txt = state.texts[i];
      const mid = Math.max(1, Math.round(txt.length / 2));
      state.texts.splice(i, 1, txt.slice(0, mid), txt.slice(mid));
      state.bounds.splice(i + 1, 0, round3(t));
      state.confs.splice(i, 1, state.confs[i], state.confs[i]);
      state.sel = i + 1;
      recomputeDirty();
      renderSegments();
      return;
    }
  }
  toast('Move the playhead inside a segment to split');
}
function mergeSelected() {
  const b = state.sel;
  if (b <= 0 || b >= state.bounds.length - 1) { toast('Select an internal boundary to merge'); return; }
  pushUndo();
  state.texts.splice(b - 1, 2, (state.texts[b - 1] || '') + (state.texts[b] || ''));
  const ca = state.confs[b - 1], cb = state.confs[b];
  state.confs.splice(b - 1, 2, ca == null || cb == null ? null : Math.min(ca, cb));
  state.bounds.splice(b, 1);
  state.sel = Math.min(b, state.bounds.length - 1);
  recomputeDirty();
  renderSegments();
}
function resetWord() {
  if (segKey() === state.origKey) return;   // nothing to reset
  pushUndo();
  const orig = state.origKey;
  loadSegments(cur());
  state.origKey = orig;                      // keep the original signature stable
  recomputeDirty();
  renderSegments(); drawWave();
}

// ---- playback ------------------------------------------------------------
function cycleRate() {
  state.rate = state.rate === 1 ? 0.5 : 1;
  if (state.audioEl) state.audioEl.playbackRate = state.rate;
  const btn = $('#rate'); if (btn) { btn.textContent = state.rate + '×'; btn.classList.toggle('on', state.rate !== 1); }
}
function togglePlay() { state.playing ? stop() : playWord(); }
function playWord() {
  const it = cur();
  playLoop(it.word_start, it.word_end);
}
function playSegment(i) {
  if (i < 0 || i >= state.texts.length) return;
  state.sel = Math.min(i + 1, state.bounds.length - 1);
  renderSegments();
  playLoop(state.bounds[i], state.bounds[i + 1]);
}
function playLoop(start, end) {
  if (!state.audioEl) { toast('No audio to play'); return; }
  state.loop = { start, end };
  state.audioEl.playbackRate = state.rate;
  state.audioEl.currentTime = start;
  state.audioEl.play();
  state.playing = true;
  const p = $('#play'); if (p) p.textContent = '❚❚ Stop';
}
function stop() {
  if (state.audioEl) state.audioEl.pause();
  state.playing = false;
  const p = $('#play'); if (p) p.innerHTML = '▶ Word <span class="dim">(space)</span>';
  if (els && els.playhead) els.playhead.style.opacity = 0;
}
function seekTo(t) {
  if (!state.audioEl) return;
  state.audioEl.currentTime = Math.max(0, t);
  els.playhead.style.left = tToPct(t) + '%';
  els.playhead.style.opacity = 1;
  if (els.phlabel) els.phlabel.textContent = t.toFixed(2) + 's';
}
function startScrub(e) {
  e.preventDefault();
  seekTo(xToT(e.clientX));
  const move = ev => seekTo(xToT(ev.clientX));
  const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
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
    setDirty(false);
    toast(acceptAsIs ? 'Accepted' : 'Saved · render invalidated');
    advance();
  } catch (e) { toast('Save failed: ' + e, true); }
}
function skip() {
  if (state.dirty && !window.confirm('Discard unsaved edits on this word?')) return;
  setDirty(false);
  advance();
}
function advance() {
  renderQueue();
  const next = state.queue.findIndex((it, i) => i > state.current && !it.resolved);
  const any = next >= 0 ? next : state.queue.findIndex(it => !it.resolved);
  if (any >= 0) select(any);
  else { stop(); $('#main').innerHTML = '<div class="empty"><div class="big">✓</div>All pending syllables reviewed.<br><span class="dim">Re-run render (s06/s07) to apply.</span></div>'; els = null; }
  updateProgress();
}

// ---- keyboard ------------------------------------------------------------
document.addEventListener('keydown', e => {
  const typing = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
  // globals that work even when a button/handle is focused (but not while typing)
  if (!typing) {
    if (e.key === '?') { e.preventDefault(); const m = $('#shortcuts'); m.hidden = !m.hidden; return; }
    if (e.key === 'Escape') { const m = $('#shortcuts'); if (m && !m.hidden) { m.hidden = true; return; } }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); undo(); return; }
  }
  if (['INPUT', 'TEXTAREA', 'BUTTON'].includes(e.target.tagName)) return;  // let native controls handle keys
  if (state.current < 0) return;
  const step = e.shiftKey ? 0.1 : 0.02;
  switch (e.key) {
    case ' ': e.preventDefault(); togglePlay(); break;
    case 'ArrowLeft': e.preventDefault(); nudge(-step); break;
    case 'ArrowRight': e.preventDefault(); nudge(step); break;
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

setupFilters();
setupHelp();
loadQueue();
