
/**
 * karaoke-player.js
 * Word-fill karaoke engine.
 * Sem visualizador. Sem JASSUB. Sem bg-video.
 */

class KaraokePlayer {
    constructor() {
        this.audio = document.getElementById('audio-player');
        this.container = document.getElementById('lyrics-container');
        this.viewport = document.getElementById('lyrics-viewport');
        this.btnPlay = document.getElementById('btn-play');
        this.seekBar = document.getElementById('seek-bar');
        this.volumeBar = document.getElementById('volume-bar');
        this.offsetSlider = document.getElementById('offset-slider');
        this.offsetValue = document.getElementById('offset-value');
        this.timeCurrent = document.getElementById('time-current');
        this.timeTotal = document.getElementById('time-total');
        this.tpPlay = document.getElementById('tp-play');
        this.tpPlayIcon = document.getElementById('tp-play-icon');
        this.tpRewind = document.getElementById('tp-rewind');
        this.tpStop = document.getElementById('tp-stop');
        this.topbarTime = document.getElementById('topbar-time');
        this.playhead = document.getElementById('playhead');
        this.waveformCanvas = document.getElementById('waveform-canvas');
        this.waveformArea = document.getElementById('waveform-area');

        this.events = [];
        this.wordTiming = null;
        this.globalOffsetS = 0;
        this.isPlaying = false;
        this.animFrameId = null;
        this.currentJobId = null;
        this.audioBlobUrl = null;
        this._bindControls();
        this._bindDownloads();
    }

    _bindDownloads() {
        document.getElementById('viz-dl-ass')?.addEventListener('click', () => {
            if (this.currentJobId) window.open(`/api/result/ass?job_id=${this.currentJobId}`, '_blank');
        });
        document.getElementById('viz-dl-lyrics')?.addEventListener('click', () => {
            if (this.currentJobId) window.open(`/api/result/lyrics?job_id=${this.currentJobId}`, '_blank');
        });
    }

    // ── ASS Parser ────────────────────────────────────────────────────────

    parseASS(assText) {
        const events = [];
        for (const line of assText.split('\n')) {
            if (!line.startsWith('Dialogue:')) continue;
            const parts = line.split(',');
            if (parts.length < 10) continue;
            const start = this._parseTime(parts[1]);
            const end = this._parseTime(parts[2]);
            events.push({ start, end, words: this._parseKTags(parts.slice(9).join(','), start) });
        }
        this.events = events;
        return events;
    }

    _parseTime(s) {
        const p = s.trim().split(':');
        return (parseInt(p[0]) || 0) * 3600 + (parseInt(p[1]) || 0) * 60 + (parseFloat(p[2]) || 0);
    }

    _parseKTags(text, lineStart) {
        const re = /\{\\k[fo]?(\d+)[^}]*\}([^{]*)/g;
        const words = []; let offset = 0, m;
        while ((m = re.exec(text)) !== null) {
            const dur = parseInt(m[1]) / 100, word = m[2].trim();
            if (word) words.push({
                text: word, duration_s: dur, offset_s: offset,
                abs_start: lineStart + offset, abs_end: lineStart + offset + dur, score: 1.0
            });
            offset += dur;
        }
        if (!words.length && text.trim())
            words.push({
                text: text.trim(), duration_s: 0, offset_s: 0,
                abs_start: lineStart, abs_end: lineStart, score: 1.0
            });
        return words;
    }

    _rebuildEventsFromWordTiming() {
        const wt = this.wordTiming;
        if (!wt?.length) return;

        let wtIdx = 0;
        const WINDOW = 12;

        for (const ev of this.events) {
            const rebuilt = [];
            for (const w of ev.words) {
                const target = this._norm(w.text);
                let found = null;
                const end = Math.min(wt.length, wtIdx + WINDOW);
                for (let i = wtIdx; i < end; i++) {
                    if (this._norm(wt[i].word ?? wt[i].text) === target) {
                        found = wt[i]; wtIdx = i + 1; break;
                    }
                }
                if (found) {
                    const s = found.start ?? found.abs_start ?? w.abs_start;
                    const e = found.end ?? found.abs_end ?? w.abs_end;
                    rebuilt.push({
                        text: w.text, duration_s: Math.max(0.04, e - s),
                        offset_s: s - ev.start, abs_start: s, abs_end: e, score: found.score ?? 1.0
                    });
                } else {
                    rebuilt.push(w);
                }
            }
            if (rebuilt.length) {
                ev.start = Math.max(0, rebuilt[0].abs_start - 0.8);
                ev.end = rebuilt[rebuilt.length - 1].abs_end + 0.4;
            }
            ev.words = rebuilt;
        }
    }

    _norm(txt) {
        return (txt ?? '').toLowerCase().replace(/[^\w]/g, '');
    }

    // ── Renderer ──────────────────────────────────────────────────────────

    renderLyrics() {
        this.container.innerHTML = '';
        for (let i = 0; i < this.events.length; i++) {
            const ev = this.events[i];
            const lineEl = document.createElement('div');
            lineEl.className = 'lyric-line pending';
            lineEl.dataset.index = i;

            for (const w of ev.words) {
                const wordEl = document.createElement('span');
                wordEl.className = 'lyric-word';
                wordEl.style.opacity = w.score < 0.45 ? '0.5' : '1';

                const base = document.createElement('span');
                base.className = 'word-base'; base.textContent = w.text;

                const fill = document.createElement('span');
                fill.className = 'word-fill'; fill.textContent = w.text;
                fill.style.width = '0%';

                wordEl.appendChild(base); wordEl.appendChild(fill);
                lineEl.appendChild(wordEl);
                lineEl.appendChild(document.createTextNode('\u00a0'));
            }
            lineEl.addEventListener('click', () => {
                this.audio.currentTime = ev.start;
                this._syncAll();
            });
            this.container.appendChild(lineEl);
        }
    }

    // ── Animation loop ────────────────────────────────────────────────────

    _tick() {
        if (!this.isPlaying) return;
        const t = this.audio.currentTime;
        this._updateHighlight(t);
        this._updateControls(t);
        this._updatePlayhead(t);
        this.animFrameId = requestAnimationFrame(() => this._tick());
    }

    _updateControls(t) {
        const dur = this.audio.duration || 1, pct = (t / dur) * 100;
        if (this.seekBar) { this.seekBar.value = pct; this.seekBar.style.setProperty('--progress', pct + '%'); }
        if (this.timeCurrent) this.timeCurrent.textContent = this._fmt(t);
        if (this.topbarTime) {
            const m = Math.floor(t / 60), s = Math.floor(t % 60), cs = Math.floor((t % 1) * 100);
            this.topbarTime.textContent = `${m}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '00')}`;
        }
    }

    _updatePlayhead(t) {
        if (this.playhead)
            this.playhead.style.left = `${(t / (this.audio.duration || 1)) * 100}%`;
    }

    _updateHighlight(audioTime) {
        const ct = audioTime - this.globalOffsetS;
        const lines = this.container.children;
        let activeIdx = -1;

        for (let i = 0; i < this.events.length; i++) {
            const ev = this.events[i];
            const lineEl = lines[i];
            if (!lineEl) continue;

            const wordEls = lineEl.querySelectorAll('.lyric-word');
            lineEl.classList.remove('active-secondary');

            if (ct >= ev.start && ct <= ev.end + 0.4) {
                activeIdx = i;
                lineEl.className = 'lyric-line active';
                if (lines[i - 1]) lines[i - 1].classList.add('active-secondary');
                if (lines[i + 1]) lines[i + 1].classList.add('active-secondary');

                for (let j = 0; j < ev.words.length; j++) {
                    const w = ev.words[j];
                    const fill = wordEls[j]?.querySelector('.word-fill');
                    if (!fill) continue;
                    if (ct < w.abs_start) {
                        fill.style.width = '0%';
                    } else if (ct >= w.abs_end) {
                        fill.style.width = '100%';
                    } else {
                        const d = w.abs_end - w.abs_start;
                        fill.style.width = d > 0.001 ? `${Math.min(100, (ct - w.abs_start) / d * 100)}%` : '100%';
                    }
                }
            } else if (ct > ev.end + 0.4) {
                lineEl.className = 'lyric-line past';
                wordEls.forEach(w => { const f = w.querySelector('.word-fill'); if (f) f.style.width = '100%'; });
            } else {
                lineEl.className = 'lyric-line pending';
                wordEls.forEach(w => { const f = w.querySelector('.word-fill'); if (f) f.style.width = '0%'; });
            }
        }
        if (activeIdx >= 0) this._scrollToLine(activeIdx);
    }

    _scrollToLine(idx) {
        const lineEl = this.container.children[idx];
        if (!lineEl) return;
        const target = lineEl.offsetTop - this.viewport.offsetHeight / 2 + lineEl.offsetHeight / 2;
        const style = window.getComputedStyle(this.container).transform;
        const cur = (style && style !== 'none')
            ? new (window.DOMMatrix || window.WebKitCSSMatrix)(style).m42 : 0;

        if (Math.abs(cur - (-target)) > 600) {
            this.container.style.transition = 'none';
            this.container.style.transform = `translateY(${-target}px)`;
            this.container.offsetHeight;
            this.container.style.transition = 'transform 0.35s cubic-bezier(0.25,0.46,0.45,0.94)';
        } else {
            this.container.style.transform = `translateY(${-target}px)`;
        }
    }

    _fmt(s) {
        return `${Math.floor(s / 60)}:${Math.floor(s % 60).toString().padStart(2, '0')}`;
    }

    // ── Controls ──────────────────────────────────────────────────────────

    _bindControls() {
        this.btnPlay?.addEventListener('click', () => this.togglePlay());
        this.tpPlay?.addEventListener('click', () => this.togglePlay());
        this.tpRewind?.addEventListener('click', () => {
            this.audio.currentTime = 0;
            this._updateControls(0); this._updatePlayhead(0); this._updateHighlight(0);
        });
        this.tpStop?.addEventListener('click', () => {
            this.audio.pause(); this.audio.currentTime = 0;
            this.isPlaying = false; this._setPlayIcon(false);
            cancelAnimationFrame(this.animFrameId);
            this._updateControls(0); this._updatePlayhead(0);
        });
        this.seekBar?.addEventListener('input', () => {
            const t = (this.seekBar.value / 100) * (this.audio.duration || 0);
            this.audio.currentTime = t; this._updatePlayhead(t);
            this.seekBar.style.setProperty('--progress', this.seekBar.value + '%');
        });
        this.volumeBar?.addEventListener('input', () => { this.audio.volume = this.volumeBar.value / 100; });
        this.waveformArea?.addEventListener('click', e => {
            const rect = e.currentTarget.getBoundingClientRect();
            const t = ((e.clientX - rect.left) / rect.width) * (this.audio.duration || 0);
            this.audio.currentTime = t; this._updatePlayhead(t); this._updateControls(t);
        });
        this.audio?.addEventListener('loadedmetadata', () => {
            if (this.timeTotal) this.timeTotal.textContent = this._fmt(this.audio.duration);
            this._drawRuler(this.audio.duration);
            document.getElementById('player-ready-badge')?.classList.remove('hidden');
        });
        this.audio?.addEventListener('ended', () => {
            this.isPlaying = false; this._setPlayIcon(false);
            cancelAnimationFrame(this.animFrameId);
        });
        this.offsetSlider?.addEventListener('input', () => {
            const ms = parseInt(this.offsetSlider.value);
            if (this.offsetValue) this.offsetValue.textContent = (ms > 0 ? '+' : '') + ms + 'ms';
            this.globalOffsetS = ms / 1000;
        });
        if (this.audio && this.volumeBar) this.audio.volume = this.volumeBar.value / 100;
        this._bindShortcuts();
    }

    _bindShortcuts() {
        window.addEventListener('keydown', e => {
            // Ignore if typing in inputs
            if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;

            if (e.code === 'Space') {
                e.preventDefault();
                this.togglePlay();
            } else if (e.code === 'ArrowRight') {
                this.audio.currentTime = Math.min(this.audio.duration, this.audio.currentTime + 5);
                this._syncAll();
            } else if (e.code === 'ArrowLeft') {
                this.audio.currentTime = Math.max(0, this.audio.currentTime - 5);
                this._syncAll();
            } else if (e.code === 'Escape') {
                this.tpStop?.click();
            }
        });
    }

    _syncAll() {
        const t = this.audio.currentTime;
        this._updateHighlight(t);
        this._updateControls(t);
        this._updatePlayhead(t);
    }

    togglePlay() {
        if (this.isPlaying) {
            this.audio.pause(); this.isPlaying = false; this._setPlayIcon(false);
            cancelAnimationFrame(this.animFrameId);
        } else {
            this.audio.play().catch(e => console.warn('play():', e));
            this.isPlaying = true; this._setPlayIcon(true); this._tick();
        }
    }

    _setPlayIcon(p) {
        const PAUSE = '<path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>';
        const PLAY = '<path d="M8 5v14l11-7z"/>';
        const svg = s => `<svg viewBox="0 0 24 24" fill="currentColor">${s}</svg>`;
        if (this.btnPlay) this.btnPlay.innerHTML = svg(p ? PAUSE : PLAY);
        if (this.tpPlayIcon) this.tpPlayIcon.innerHTML = p ? PAUSE : PLAY;
    }

    _drawRuler(duration) {
        const bar = document.getElementById('timeline-ruler-bar');
        if (!bar) return; bar.innerHTML = '';
        const step = duration > 180 ? 30 : duration > 60 ? 10 : 5;
        for (let t = 0; t <= duration; t += step) {
            const tick = document.createElement('div');
            tick.className = 'ruler-tick major'; tick.style.left = `${(t / duration) * 100}%`;
            const lbl = document.createElement('span');
            lbl.className = 'tick-label'; lbl.textContent = this._fmt(t);
            tick.appendChild(lbl); bar.appendChild(tick);
        }
    }

    _drawWaveform(canvas) {
        if (!canvas) return;
        const ctx = canvas.getContext('2d'), W = canvas.offsetWidth, H = canvas.offsetHeight;
        if (!W || !H) return;
        canvas.width = W; canvas.height = H; ctx.clearRect(0, 0, W, H);
        const g = ctx.createLinearGradient(0, 0, 0, H);
        g.addColorStop(0, 'rgba(0,212,255,0.10)'); g.addColorStop(0.5, 'rgba(0,212,255,0.22)'); g.addColorStop(1, 'rgba(0,212,255,0.10)');
        ctx.fillStyle = g;
        const bars = Math.floor(W / 3), cx = H / 2;
        for (let i = 0; i < bars; i++) {
            const x = (i / bars) * W, h = (Math.sin(i * 0.3) * 0.3 + Math.sin(i * 0.07) * 0.5 + 0.2) * cx * 0.8;
            ctx.fillRect(x, cx - h, 2, h * 2);
        }
    }

    // ── Load ──────────────────────────────────────────────────────────────

    async loadFromServer(jobId) {
        if (!jobId) return false;
        this.currentJobId = jobId;
        try {
            const [assRes, audioRes, timingRes] = await Promise.all([
                fetch(`/api/result/ass?job_id=${jobId}`),
                fetch(`/api/result/audio?job_id=${jobId}`),
                fetch(`/api/result/word_timing?job_id=${jobId}`).catch(() => ({ ok: false })),
            ]);
            if (!assRes.ok || !audioRes.ok) return false;

            const assText = await assRes.text();
            this.parseASS(assText);

            if (timingRes?.ok) {
                this.wordTiming = await timingRes.json();
                if (this.wordTiming?.length) this._rebuildEventsFromWordTiming();
            }

            this.renderLyrics();

            if (this.audioBlobUrl) { URL.revokeObjectURL(this.audioBlobUrl); this.audioBlobUrl = null; }
            this.audioBlobUrl = URL.createObjectURL(await audioRes.blob());
            this.audio.src = this.audioBlobUrl;

            setTimeout(() => this._drawWaveform(this.waveformCanvas), 300);
            return true;
        } catch (e) {
            console.error('[KaraokePlayer] loadFromServer:', e);
            return false;
        }
    }
}

window.karaokePlayer = new KaraokePlayer();
