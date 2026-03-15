// ═══════════════════════════════════════════════════════════════════════
// KARAOKE STUDIO — DAW UI Controller
// ═══════════════════════════════════════════════════════════════════════

const STEPS = [
    { id: 1, name: 'Preparação de Mídia' },
    { id: 2, name: 'Isolamento Vocal' },
    { id: 3, name: 'Limpeza Vocal' },
    { id: 4, name: 'Alinhamento MFA' },
    { id: 5, name: 'Análise de Gaps' },
    { id: 6, name: 'Resgate de Alinhamento' },
    { id: 7, name: 'Refinamento Gemini' },
    { id: 8, name: 'Alinhamento Onset DTW' },
    { id: 9, name: 'Renderização de Vídeo' },
    { id: 10, name: 'Controle de Qualidade' },
    { id: 11, name: 'Limpeza de Sistema' },
    { id: 12, name: 'Notificação' },
    { id: 13, name: 'Conclusão Processo' }
];

// ── Global Error Handling ──────────────────────────────────────────────
window.addEventListener('error', (event) => {
    console.error("Unhandled Error:", event.error);
    notify('Erro Inesperado', 'error', event.message || 'Um erro inesperado ocorreu na interface.');
});

window.addEventListener('unhandledrejection', (event) => {
    console.error("Unhandled Promise Rejection:", event.reason);
    const msg = event.reason?.message || event.reason || 'Falha em operação assíncrona.';
    notify('Erro de Rede/Promessa', 'error', msg);
});

// ── State ──────────────────────────────────────────────────────────────
const state = {
    selectedFile: null,
    stems: [],
    pipelineRunning: false,
    stepStates: {},
    stepTimers: {},
    stepStartTime: {},
    logLines: [],
    currentJobId: null,
    currentStage: 'ingest'
};

// ── Stage Management ──────────────────────────────────────────────────
function switchStage(stage) {
    state.currentStage = stage;

    // FIX #7: Controla visibilidade dos sidebar steps via CSS
    document.body.setAttribute('data-stage', stage);

    // Update Stepper
    document.querySelectorAll('.step-stage').forEach(el => {
        const s = el.dataset.stage;
        el.classList.remove('active', 'completed');

        const stages = ['ingest', 'process', 'view'];
        const currentIdx = stages.indexOf(stage);
        const elIdx = stages.indexOf(s);

        if (s === stage) el.classList.add('active');
        if (elIdx < currentIdx) el.classList.add('completed');
    });

    // Update Panels
    document.querySelectorAll('.stage-panel').forEach(el => {
        el.classList.toggle('active', el.id === `stage-${stage}`);
    });

    // Specific Stage Actions
    if (stage === 'process') {
        const pipelineTabDot = document.getElementById('pipeline-tab-dot');
        if (pipelineTabDot) pipelineTabDot.style.background = '#00d4ff';
    }

    if (stage === 'view') {
        if (window.karaokePlayer?.visualizer) {
            window.karaokePlayer.visualizer.start();
            setTimeout(() => window.karaokePlayer.visualizer._resize(), 100);
        }
    } else {
        window.karaokePlayer?.visualizer?.stop();
    }
}

// ── Init Pipeline UI ──────────────────────────────────────────────────
function initPipelineUI() {
    const sidebarSteps = document.getElementById('sidebar-steps');
    const tracks = document.getElementById('pipeline-tracks');

    STEPS.forEach(step => {
        state.stepStates[step.id] = { status: 'pending', elapsed: 0 };

        // Sidebar step
        const s = document.createElement('div');
        s.className = 'pipeline-step pending';
        s.id = `sstep-${step.id}`;
        s.innerHTML = `
      <div class="step-indicator"><div class="dot"></div></div>
      <span class="step-label">${step.name}</span>
      <span class="step-time" id="sstep-time-${step.id}"></span>
    `;
        sidebarSteps.appendChild(s);

        // Track row
        const t = document.createElement('div');
        t.className = 'p-track pending';
        t.id = `ptrack-${step.id}`;
        t.innerHTML = `
      <div class="p-track-label">
        <span class="p-track-num">${String(step.id).padStart(2, '0')}</span>
        <span class="p-track-name">${step.name}</span>
      </div>
      <div class="p-track-bar">
        <div class="p-track-fill" id="ptrack-fill-${step.id}"></div>
        <span class="p-track-status" id="ptrack-status-${step.id}">—</span>
        <span class="p-track-elapsed" id="ptrack-elapsed-${step.id}"></span>
      </div>
    `;
        tracks.appendChild(t);
    });
}

function updateStep(id, status, detail, elapsed) {
    const sstep = document.getElementById(`sstep-${id}`);
    const ptrack = document.getElementById(`ptrack-${id}`);
    const statusEl = document.getElementById(`ptrack-status-${id}`);
    const elapsedEl = document.getElementById(`ptrack-elapsed-${id}`);
    const sstime = document.getElementById(`sstep-time-${id}`);

    if (!sstep || !ptrack) return;

    // Remove all state classes
    ['pending', 'running', 'done', 'error', 'skipped'].forEach(c => {
        sstep.classList.remove(c);
        ptrack.classList.remove(c);
    });

    sstep.classList.add(status);
    ptrack.classList.add(status);

    const labels = {
        pending: '—',
        running: 'processing...',
        done: detail || 'done',
        error: 'failed',
        skipped: 'cached ↩',
    };

    if (statusEl) statusEl.textContent = labels[status] || status;
    if (elapsedEl && elapsed) elapsedEl.textContent = `${elapsed}s`;
    if (sstime && elapsed) sstime.textContent = `${elapsed}s`;

    // Update fill bar
    const fill = document.getElementById(`ptrack-fill-${id}`);
    if (fill) {
        let pct = 0;
        let showText = labels[status] || status;

        if (status === 'running') {
            pct = 60;
            showText = 'processing...';

            if (detail && typeof detail === 'string' && detail.startsWith('[')) {
                const match = detail.match(/^\[(\d+)%\]\s*(.*)/);
                if (match) {
                    pct = parseInt(match[1], 10);
                    showText = match[2] || `Aguarde (${pct}%)`;
                } else {
                    showText = detail;
                }
            } else if (detail && typeof detail === 'string') {
                showText = detail;
            }
            if (statusEl) statusEl.textContent = showText;
            fill.style.width = pct + '%';
        } else if (status === 'skipped') {
            fill.style.width = '100%';
            if (statusEl) statusEl.textContent = detail ? `pulado (${detail})` : 'pulado';
        } else if (status === 'done') {
            fill.style.width = '100%';
            if (statusEl) statusEl.textContent = detail || labels[status];
        } else if (status === 'error') {
            fill.style.width = '100%';
            if (statusEl) statusEl.textContent = 'falhou';
        }
    }

    // Update master progress
    const doneCount = Object.values(state.stepStates).filter(s => s.status === 'done' || s.status === 'skipped').length;
    const pct = (doneCount / STEPS.length) * 100;
    const masterFill = document.getElementById('master-progress-fill');
    if (masterFill) masterFill.style.width = pct + '%';
}

function setStepStatus(id, status, detail, elapsed) {
    state.stepStates[id] = { status, elapsed: elapsed || 0 };
    updateStep(id, status, detail, elapsed);
}

// ── Upload Area ────────────────────────────────────────────────────────
const uploadArea = document.getElementById('upload-area');
const audioInput = document.getElementById('audio-input');
const uploadText = document.getElementById('upload-text');

// FIX #8: Click handler sem double-trigger (input está display:none, JS controla)
uploadArea.addEventListener('click', (e) => {
    if (e.target !== audioInput) {
        audioInput.click();
    }
});
uploadArea.addEventListener('dragover', e => { e.preventDefault(); uploadArea.classList.add('dragover'); });
uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
uploadArea.addEventListener('drop', e => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    if (e.dataTransfer.files[0]) setMainFile(e.dataTransfer.files[0]);
});
audioInput.addEventListener('change', () => {
    if (audioInput.files[0]) setMainFile(audioInput.files[0]);
});

function setMainFile(file) {
    state.selectedFile = file;
    uploadArea.classList.add('filled');
    uploadText.innerHTML = `
    <div class="upload-zone-filename">${file.name}</div>
    <div class="upload-zone-hint">${(file.size / 1024 / 1024).toFixed(1)} MB</div>
  `;
    // FIX #1: Badge exists in HTML, safe to update
    const badge = uploadArea.querySelector('.upload-zone-badge');
    if (badge) {
        badge.className = 'upload-zone-badge badge-ready';
        badge.textContent = 'ready';
        badge.style.display = '';
    }
    checkReady();
}

// ── Stems ──────────────────────────────────────────────────────────────
const STEM_CATEGORY_MAP = {
    "lead": "vocals", "vocal": "vocals", "vox": "vocals", "voice": "vocals",
    "backing": "other", "bgv": "other", "harmony": "other",
    "drum": "drums", "kick": "drums", "snare": "drums", "perc": "drums",
    "bass": "bass",
    "guitar": "other", "key": "other", "keyboard": "other",
    "synth": "other", "piano": "other", "strings": "other",
};

function classifyStem(filename) {
    let name = filename.toLowerCase().replace(/\.[^/.]+$/, "");
    name = name.replace(/^\d+\s*/, '');
    for (const [key, cat] of Object.entries(STEM_CATEGORY_MAP)) {
        if (name.includes(key)) return cat;
    }
    return "other";
}

const stemMultiArea = document.getElementById('stems-multi-area');
const stemsInput = document.getElementById('stems-input');
const stemsList = document.getElementById('stems-list');

// FIX #8: Click handler sem double-trigger para stems
stemMultiArea.addEventListener('click', (e) => {
    if (e.target !== stemsInput) {
        stemsInput.click();
    }
});
stemMultiArea.addEventListener('dragover', e => { e.preventDefault(); stemMultiArea.classList.add('dragover'); });
stemMultiArea.addEventListener('dragleave', () => stemMultiArea.classList.remove('dragover'));
stemMultiArea.addEventListener('drop', e => {
    e.preventDefault();
    stemMultiArea.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) addStems(Array.from(e.dataTransfer.files));
});
stemsInput.addEventListener('change', () => {
    if (stemsInput.files.length > 0) addStems(Array.from(stemsInput.files));
});

function addStems(files) {
    for (const file of files) {
        state.stems.push({
            file,
            category: classifyStem(file.name),
            id: Date.now() + Math.random()
        });
    }
    renderStems();
}

window.removeStem = function (id) {
    state.stems = state.stems.filter(s => s.id !== id);
    renderStems();
};

window.updateStemCat = function (id, cat) {
    const stem = state.stems.find(s => s.id === id);
    if (stem) stem.category = cat;
    checkReady();
};

function renderStems() {
    stemsList.innerHTML = '';

    for (const stem of state.stems) {
        const el = document.createElement('div');
        el.className = 'stem-list-item';

        const isVocals = stem.category === 'vocals';
        const badge = isVocals ? `<span class="stem-li-badge req">req</span>` : `<span class="stem-li-badge opt">opt</span>`;

        el.innerHTML = `
            <svg viewBox="0 0 24 24" width="14" height="14" fill="var(--success)" style="flex-shrink:0"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
            <div class="stem-li-name" title="${stem.file.name}">${stem.file.name}</div>
            <select class="stem-li-cat" onchange="updateStemCat(${stem.id}, this.value)">
                <option value="vocals" ${stem.category === 'vocals' ? 'selected' : ''}>vocals</option>
                <option value="drums" ${stem.category === 'drums' ? 'selected' : ''}>drums</option>
                <option value="bass" ${stem.category === 'bass' ? 'selected' : ''}>bass</option>
                <option value="other" ${stem.category === 'other' ? 'selected' : ''}>other</option>
            </select>
            ${badge}
            <button class="btn-stem-rm" onclick="removeStem(${stem.id})" title="Remover">
               <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12 19 6.41z"/></svg>
            </button>
        `;
        stemsList.appendChild(el);
    }

    if (state.stems.length > 0) stemMultiArea.classList.add('filled');
    else stemMultiArea.classList.remove('filled');

    checkReady();
}

// ── Lyrics ─────────────────────────────────────────────────────────────
const lyricsInput = document.getElementById('lyrics-input');
const wordCountEl = document.getElementById('word-count');

lyricsInput.addEventListener('input', () => {
    const words = lyricsInput.value.trim().split(/\s+/).filter(Boolean).length;
    wordCountEl.textContent = `${words} palavras`;
    checkReady();
});

document.getElementById('btn-clean-lyrics').addEventListener('click', async () => {
    const text = lyricsInput.value.trim();
    if (!text) return;
    if (!state.rawLyrics) {
        state.rawLyrics = text;
    }
    const btn = document.getElementById('btn-clean-lyrics');
    btn.disabled = true;
    try {
        const res = await fetch('/api/clean_lyrics', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lyrics: text })
        });
        if (res.ok) {
            const data = await res.json();
            lyricsInput.value = data.cleaned;
            lyricsInput.dispatchEvent(new Event('input'));
            notify('Letra limpa com sucesso', 'success');
        } else {
            const data = await res.json().catch(() => ({}));
            const msg = data.error || `Erro ${res.status}`;
            notify('Falha ao limpar letra', 'error', msg);
        }
    } catch (e) {
        notify('Falha ao limpar letra', 'error', e.message);
    }
    finally { btn.disabled = false; }
});

// ── Check Ready ────────────────────────────────────────────────────────
function checkReady() {
    const hasAudio = state.selectedFile !== null;
    const hasLyrics = lyricsInput.value.trim().length > 0;
    const hasStems = state.stems.length > 0;
    const hasMainVocal = state.stems.some(s => s.category === 'vocals');
    const stemValid = !hasStems || hasMainVocal;
    const ready = hasAudio && hasLyrics && stemValid && !state.pipelineRunning;
    document.getElementById('btn-generate').disabled = !ready;
}

// ── Progress Utils ──────────────────────────────────────────────────────
function _uploadWithProgress(url, formData, onProgress) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url);
        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                onProgress(pct);
            }
        };
        xhr.onload = () => {
            let resp = { ok: xhr.status >= 200 && xhr.status < 300 };
            try {
                const parsed = JSON.parse(xhr.responseText);
                resp = { ...resp, ...parsed };
                if (!resp.ok) {
                    resp.error = parsed.error || `HTTP ${xhr.status}`;
                    resp.code = parsed.code || 'UNKNOWN_ERROR';
                    resp.details = parsed.details || null;
                }
            } catch (e) {
                if (!resp.ok) {
                    const raw = xhr.responseText;
                    resp.error = (raw && raw.length < 200 && !raw.includes('<!DOCTYPE'))
                        ? raw
                        : `HTTP ${xhr.status}: Erro Interno (veja console)`;
                }
            }
            resolve(resp);
        };
        xhr.onerror = () => reject(new Error('Falha de rede ao tentar fazer upload.'));
        xhr.send(formData);
    });
}

// ── Generate ───────────────────────────────────────────────────────────
document.getElementById('btn-generate').addEventListener('click', async () => {
    if (!state.selectedFile || state.pipelineRunning) return;

    state.pipelineRunning = true;
    checkReady();

    const btn = document.getElementById('btn-generate');
    btn.classList.add('running');
    btn.innerHTML = '<span class="spin">↻</span>&nbsp; Processando...';

    // Switch to process stage
    switchStage('process');

    // Reset steps
    STEPS.forEach(s => setStepStatus(s.id, 'pending'));

    // FIX #6: Usar style.display em vez de classList
    const errorPanel = document.getElementById('error-detail');
    if (errorPanel) errorPanel.style.display = 'none';

    clearLog();

    // Status
    setStatus('running', 'Processing...');
    addLog('Pipeline iniciado', 'info');

    try {
        const form = new FormData();
        form.append('audio', state.selectedFile);
        form.append('lyrics', lyricsInput.value);
        if (state.rawLyrics) {
            form.append('lyrics_raw', state.rawLyrics);
        }
        form.append('lang', document.getElementById('select-lang').value);
        form.append('aligner', document.getElementById('select-aligner').value);

        // Include stems
        const hasStems = state.stems.length > 0;
        if (hasStems) {
            addLog(`Preparando ${state.stems.length} stems para upload...`, 'info');
            for (const stem of state.stems) {
                let key = 'stem_other';
                if (stem.category === 'vocals') key = 'stem_vocals';
                else if (stem.category === 'drums') key = 'stem_drums';
                else if (stem.category === 'bass') key = 'stem_bass';
                form.append(key, stem.file);
            }
        }

        // Preview Mode
        const previewCheckbox = document.getElementById('preview-checkbox');
        if (previewCheckbox && previewCheckbox.checked) {
            form.append('preview_mode', 'true');
            form.append('preview_duration', document.getElementById('preview-duration').value);
            form.append('preview_start', document.getElementById('preview-start').value);
            state.previewMode = true;
        } else {
            state.previewMode = false;
        }

        const res = await _uploadWithProgress('/api/generate', form, (pct) => {
            const statusEl = document.getElementById('ptrack-status-1');
            if (statusEl) statusEl.textContent = `Upload: ${pct}%`;
        });

        if (!res.ok) {
            const msg = res.code ? `[${res.code}] ${res.error}` : res.error;
            throw new Error(msg || 'Erro ao iniciar pipeline');
        }

        state.currentJobId = res.job_id;

        if (res.stems_preloaded) {
            addLog('Stems fornecidos. Pulando etapas de separação.', 'success');
            setStepStatus(1, 'skipped', 'fornecido');
            setStepStatus(2, 'skipped', 'fornecido');
        }

        if (res.preview_mode) {
            state.previewMode = true;
            addLog(`Modo Preview ativado: ${res.preview_duration}s`, 'info');
        }

        window.history.pushState({}, '', `/process/${state.currentJobId}`);
        listenProgress();
    } catch (e) {
        onPipelineError(e.message);
    }
});

// ── SSE Progress ────────────────────────────────────────────────────────
function listenProgress() {
    const src = new EventSource(`/api/progress?job_id=${state.currentJobId}`);

    src.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === 'keepalive') return;

        if (data.type === 'step') {
            const { step, status: dataStatus, state: dataState, detail, name } = data;
            const status = dataStatus || dataState;

            // Mark past steps as done
            for (let i = 1; i < step; i++) {
                if (state.stepStates[i] && state.stepStates[i].status === 'pending') {
                    setStepStatus(i, 'done');
                }
            }

            if (status === 'running') {
                if (state.stepStates[step]?.status !== 'running') {
                    state.stepStartTime[step] = state.stepStartTime[step] || Date.now();
                    addLog(`▶ ${name || `Passo ${step}`}`, 'info');
                }
            } else if (status === 'done') {
                const elapsed = state.stepStartTime[step]
                    ? Math.round((Date.now() - state.stepStartTime[step]) / 1000)
                    : null;
                setStepStatus(step, 'done', detail, elapsed);
                addLog(`✓ ${name || `Passo ${step}`}${elapsed ? ` (${elapsed}s)` : ''}`, 'success');
                if (detail) addLog(detail, 'info');
                return;
            } else if (status === 'error') {
                setStepStatus(step, 'error', detail?.message || detail || 'Erro');

                const errName = name || `Passo ${step}`;
                const errMsg = detail?.message || (typeof detail === 'string' ? detail.substring(0, 80) : 'Falha');
                const errCode = detail?.code ? ` [${detail.code}]` : "";

                addLog(`✗ ${errName}${errCode}: ${errMsg}`, 'error');
                showErrorDetail(detail);
                return;
            }

            setStepStatus(step, status, detail);
        }

        if (data.type === 'final') {
            src.close();
            if (data.state === 'done') {
                onPipelineDone();
            } else {
                onPipelineError(data.error);
                if (data.detail) showErrorDetail(data.detail);
            }
        }
    };

    src.onerror = () => {
        src.close();
        setTimeout(async () => {
            try {
                const res = await fetch(`/api/status?job_id=${state.currentJobId}`);
                const s = await res.json();
                if (s.state === 'done') onPipelineDone();
                else if (s.state === 'error') onPipelineError(s.error);
                else if (s.state === 'running') onPipelineError("Conexão SSE perdida. Pipeline pode ainda estar rodando no backend.");
            } catch (_) { onPipelineError('Conexão perdida com o servidor'); }
        }, 1000);
    };
}

async function onPipelineDone() {
    state.pipelineRunning = false;
    setStatus('done', 'Done');
    addLog('Pipeline concluído com sucesso!', 'success');
    notify('Karaokê gerado com sucesso!', 'success', 'Clique em Player para assistir');
    document.getElementById('btn-generate').classList.remove('running');
    document.getElementById('btn-generate').innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> Gerar Karaokê';
    checkReady();

    if (state.previewMode && window.showPromoteButton) {
        window.showPromoteButton(state.currentJobId);
    }

    if (window.karaokePlayer) {
        const ok = await window.karaokePlayer.loadFromServer(state.currentJobId);
        if (ok) {
            window.history.pushState({}, '', `/karaoke/${state.currentJobId}`);
            switchStage('view');
        } else {
            onPipelineError("Resultados não encontrados no servidor para o job atual.");
        }
    }
}

function onPipelineError(msg) {
    state.pipelineRunning = false;
    setStatus('error', 'Error');
    notify('Falha no pipeline', 'error', msg?.substring(0, 80));
    document.getElementById('btn-generate').classList.remove('running');
    document.getElementById('btn-generate').innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M8 5v14l11-7z"/></svg> Gerar Karaokê';
    checkReady();
}

// FIX #6: Usar style.display em vez de classList
function showErrorDetail(detail) {
    const el = document.getElementById('error-detail');
    const textEl = document.getElementById('error-detail-text');

    if (!el || !textEl) return;

    if (!detail) {
        textEl.textContent = "Erro desconhecido e sem detalhes.";
    } else if (typeof detail === 'string') {
        textEl.textContent = detail;
    } else {
        let out = `Mensagem: ${detail.message || 'Sem mensagem'}\n`;
        if (detail.code) out += `Código: ${detail.code}\n`;
        if (detail.script) out += `Script: ${detail.script}\n`;
        if (detail.exit_code) out += `Exit Code: ${detail.exit_code}\n`;

        if (detail.raw_tail) {
            out += `\n--- ÚLTIMAS LINHAS (LOG) ---\n${detail.raw_tail}`;
        }
        textEl.textContent = out;
    }

    el.style.display = 'block';
}

// ── Status ─────────────────────────────────────────────────────────────
function setStatus(state_, text) {
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');
    if (dot) dot.className = `status-dot ${state_}`;
    if (txt) txt.textContent = text;
}

// ── Log ────────────────────────────────────────────────────────────────
function addLog(text, type = 'info') {
    const now = new Date();
    const ts = `${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
    const out = document.getElementById('log-output');
    if (!out) return;
    const line = document.createElement('div');
    line.className = `log-line ${type}`;
    line.innerHTML = `<span class="log-time">${ts}</span> <span class="log-text">${text}</span>`;
    out.appendChild(line);
    out.scrollTop = out.scrollHeight;
    state.logLines.push({ ts, text, type });
}

function clearLog() {
    const out = document.getElementById('log-output');
    if (out) out.innerHTML = '';
    state.logLines = [];
}

document.getElementById('btn-clear-log').addEventListener('click', clearLog);
document.getElementById('btn-copy-log').addEventListener('click', () => {
    const text = state.logLines.map(l => `[${l.ts}] ${l.text}`).join('\n');
    navigator.clipboard?.writeText(text).then(() => {
        notify('Log copiado', 'info');
    }).catch(() => {
        notify('Falha ao copiar log', 'error');
    });
});

// ── Clear cache ─────────────────────────────────────────────────────────
document.getElementById('btn-clear-cache').addEventListener('click', async () => {
    if (!confirm('Limpar todos os arquivos temporários?')) return;
    try {
        const res = await fetch('/api/clear_cache', { method: 'POST' });
        if (res.ok) {
            window.location.href = '/';
        } else {
            const data = await res.json().catch(() => ({}));
            const msg = data.error || 'Falha ao limpar cache';
            notify('Erro ao limpar cache', 'error', msg);
        }
    } catch (e) {
        notify('Falha na conexão', 'error', e.message);
    }
});

// ── Notification ────────────────────────────────────────────────────────
function notify(title, type = 'info', msg = '') {
    const container = document.getElementById('notification');
    if (!container) {
        console.warn('notify: #notification container not found');
        return;
    }
    const icons = {
        success: '<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>',
        error: '<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>',
        info: '<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M13 9h-2V7h2m0 10h-2v-6h2m-1-9A10 10 0 0 0 2 12a10 10 0 0 0 10 10 10 10 0 0 0 10-10A10 10 0 0 0 12 2z"/></svg>',
    };
    const el = document.createElement('div');
    el.className = `notif ${type}`;
    el.innerHTML = `
    <div class="notif-icon">${icons[type] || icons.info}</div>
    <div class="notif-body">
      <div class="notif-title">${title}</div>
      ${msg ? `<div class="notif-msg">${msg}</div>` : ''}
    </div>
  `;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// ── Init Routing ────────────────────────────────────────────────────────
async function _init() {
    if (typeof KaraokePlayer !== 'undefined') {
        window.karaokePlayer = new KaraokePlayer();
    }
    initPipelineUI();

    const path = window.location.pathname;
    const parts = path.split('/').filter(Boolean);

    if (parts[0] === 'process' && parts[1]) {
        state.currentJobId = parts[1];
        switchStage('process');
        listenProgress();
        return;
    }

    if (parts[0] === 'karaoke' && parts[1]) {
        state.currentJobId = parts[1];
        switchStage('view');
        if (window.karaokePlayer) {
            window.karaokePlayer.loadFromServer(state.currentJobId);
        }
        return;
    }

    checkReady();

    // Bind Stage buttons
    document.querySelectorAll('.step-stage').forEach(el => {
        el.style.cursor = 'pointer';
        el.addEventListener('click', () => switchStage(el.dataset.stage));
    });

    // Handle promotion event
    window.addEventListener('karaoke:promoted', (e) => {
        state.previewMode = false;
        state.currentJobId = e.detail.jobId;

        STEPS.forEach(s => setStepStatus(s.id, 'pending', ''));
        setStatus('running', 'Processando Música Completa...');
        addLog('🚀 Promovido para Pipeline Full. Retomando processamento...', 'info');
        listenProgress();
    });
}

// ── Promote UI ──────────────────────────────────────────────────────────
window.showPromoteButton = function (jobId) {
    const banner = document.getElementById('promote-banner');
    if (!banner) return;
    banner.style.display = 'flex';

    const btn = document.getElementById('btn-promote');
    btn.onclick = async () => {
        btn.disabled = true;
        btn.innerHTML = 'Promovendo...';
        try {
            const res = await fetch('/api/promote_preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId })
            });
            if (!res.ok) throw new Error(await res.text());

            banner.style.display = 'none';
            btn.disabled = false;
            btn.innerHTML = 'Promover para Completa';

            window.dispatchEvent(new CustomEvent('karaoke:promoted', { detail: { jobId } }));
        } catch (e) {
            btn.disabled = false;
            btn.innerHTML = 'Erro! Tentar Novamente';
            addLog('Erro ao promover: ' + e.message, 'error');
        }
    };
};

document.addEventListener('DOMContentLoaded', _init);