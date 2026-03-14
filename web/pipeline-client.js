// ═══════════════════════════════════════════════════════════════════════
// KARAOKE STUDIO — DAW UI Controller
// ═══════════════════════════════════════════════════════════════════════

const STEPS = [
    { id: 1, name: 'Pré-processar Áudio' },
    { id: 2, name: 'Separar Stems (Demucs)' },
    { id: 3, name: 'Preparar Corpus' },
    { id: 4, name: 'Alinhamento CTC' },
    { id: 5, name: 'Resgate WhisperX' },
    { id: 6, name: 'Detecção Adlibs' },
    { id: 7, name: 'VAD Clamping' },
    { id: 8, name: 'Filtro de Preview/Onsets' },
    { id: 9, name: 'Refinamento de Onsets' },
    { id: 10, name: 'Gerar Subtitles (ASS)' },
    { id: 11, name: 'Controle de Qualidade' },
    { id: 12, name: 'Mixagem Final' },
    { id: 13, name: 'Renderizar Vídeo' },
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
    stepStates: {},    // id → { status, elapsed }
    stepTimers: {},    // id → interval
    stepStartTime: {}, // id → Date
    logLines: [],
    currentJobId: null,
    currentStage: 'ingest' // ingest | process | view
};

// ── Stage Management ──────────────────────────────────────────────────
function switchStage(stage) {
    state.currentStage = stage;

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

    // Fix name if provided by server
    if (detail && typeof detail === 'string' && !name) { /* ignore */ }
    if (name) {
        const n1 = sstep.querySelector('.step-label');
        if (n1) n1.textContent = name;
        const n2 = ptrack.querySelector('.p-track-name');
        if (n2) n2.textContent = name;
    }

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

    // Update fill bar for running
    const fill = document.getElementById(`ptrack-fill-${id}`);
    if (fill) {
        let pct = 0;
        let showText = labels[status] || status;

        if (status === 'running') {
            pct = 60; // Indeterminate fallback
            showText = 'processing...';

            if (detail && detail.startsWith('[')) {
                // Parses "[50%] Doing X"
                const match = detail.match(/^\[(\d+)%\]\s*(.*)/);
                if (match) {
                    pct = parseInt(match[1], 10);
                    showText = match[2] || `Aguarde (${pct}%)`;
                } else {
                    showText = detail;
                }
            } else if (detail) {
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
    document.getElementById('master-progress-fill').style.width = pct + '%';
}

function setStepStatus(id, status, detail, elapsed) {
    state.stepStates[id] = { status, elapsed: elapsed || 0 };
    updateStep(id, status, detail, elapsed);
}

// ── Events ──────────────────────────────────────────────────────────── (Replaced by switchStage)

// ── Upload Area ────────────────────────────────────────────────────────
const uploadArea = document.getElementById('upload-area');
const audioInput = document.getElementById('audio-input');
const uploadText = document.getElementById('upload-text');

uploadArea.addEventListener('click', () => audioInput.click());
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
    // Update badge
    uploadArea.querySelector('.upload-zone-badge').className = 'upload-zone-badge badge-ready';
    uploadArea.querySelector('.upload-zone-badge').textContent = 'ready';
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

stemMultiArea.addEventListener('click', () => stemsInput.click());
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
            <svg viewBox="0 0 24 24" width="14" height="14" fill="var(--green)" style="flex-shrink:0"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
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

// End of standard listeners block

document.getElementById('btn-clean-lyrics').addEventListener('click', async () => {
    const text = lyricsInput.value.trim();
    if (!text) return;
    // Preserve original lyrics (with parentheticals) for adlib hint extraction
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
                    // Normalize standard backend APIError format
                    resp.error = parsed.error || `HTTP ${xhr.status}`;
                    resp.code = parsed.code || 'UNKNOWN_ERROR';
                    resp.details = parsed.details || null;
                }
            } catch (e) {
                if (!resp.ok) {
                    const raw = xhr.responseText;
                    // Use raw response if it looks like a short message, otherwise generic error
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
    document.getElementById('error-detail').classList.remove('visible');
    clearLog();

    // Status
    setStatus('running', 'Processing...');
    addLog('Pipeline iniciado', 'info');

    try {
        const form = new FormData();
        form.append('audio', state.selectedFile);
        form.append('lyrics', lyricsInput.value);
        // Send raw lyrics (with parentheticals) for adlib hint extraction
        if (state.rawLyrics) {
            form.append('lyrics_raw', state.rawLyrics);
        }
        form.append('lang', document.getElementById('lang-select').value);

        // Include stems in the main request
        const hasStems = state.stems.length > 0;
        if (hasStems) {
            addLog(`Preparando ${state.stems.length} stems para upload...`, 'info');
            for (const stem of state.stems) {
                // Determine form key based on category for backend mapping
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
            document.getElementById('ptrack-status-1').textContent = `Upload: ${pct}%`;
        });

        if (!res.ok) {
            const msg = res.code ? `[${res.code}] ${res.error}` : res.error;
            throw new Error(msg || 'Erro ao iniciar pipeline');
        }

        state.currentJobId = res.job_id;

        // If stems were preloaded, backend skips 1 and 2
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
            const status = dataStatus || dataState; // Backend uses status or state sometimes

            // Mark all past steps as done (only if pending)
            for (let i = 1; i < step; i++) {
                if (state.stepStates[i] && state.stepStates[i].status === 'pending') {
                    setStepStatus(i, 'done');
                }
            }

            // Start timer for running steps
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
            // Auto-advance to player
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

function showErrorDetail(detail) {
    const el = document.getElementById('error-detail');
    const textEl = document.getElementById('error-detail-text');

    if (!detail) {
        textEl.textContent = "Erro desconhecido e sem detalhes.";
    } else if (typeof detail === 'string') {
        textEl.textContent = detail;
    } else {
        // Structured error representation
        let out = `Mensagem: ${detail.message || 'Sem mensagem'}\n`;
        if (detail.code) out += `Código: ${detail.code}\n`;
        if (detail.script) out += `Script: ${detail.script}\n`;
        if (detail.exit_code) out += `Exit Code: ${detail.exit_code}\n`;

        if (detail.raw_tail) {
            out += `\n--- ÚLTIMAS LINHAS (LOG) ---\n${detail.raw_tail}`;
        }
        textEl.textContent = out;
    }

    el.classList.add('visible');
}

// ── Status ─────────────────────────────────────────────────────────────
function setStatus(state_, text) {
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');
    dot.className = `status-dot ${state_}`;
    txt.textContent = text;
}

// ── Log ────────────────────────────────────────────────────────────────
function addLog(text, type = 'info') {
    const now = new Date();
    const ts = `${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
    const out = document.getElementById('log-output');
    const line = document.createElement('div');
    line.className = `log-line ${type}`;
    line.innerHTML = `<span class="log-time">${ts}</span><span class="log-text">${text}</span>`;
    out.appendChild(line);
    out.scrollTop = out.scrollHeight;
    state.logLines.push({ ts, text, type });
}

function clearLog() {
    document.getElementById('log-output').innerHTML = '';
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
    const icons = {
        success: '<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>',
        error: '<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>',
        info: '<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M13 9h-2V7h2m0 10h-2v-6h2m-1-9A10 10 0 0 0 2 12a10 10 0 0 0 10 10 10 10 0 0 0 10-10A10 10 0 0 0 12 2z"/></svg>',
    };
    const el = document.createElement('div');
    el.className = `notif ${type}`;
    el.innerHTML = `
    <div class="notif-icon">${icons[type]}</div>
    <div class="notif-body">
      <div class="notif-title">${title}</div>
      ${msg ? `<div class="notif-msg">${msg}</div>` : ''}
    </div>
  `;
    document.getElementById('notification').appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// ── Init Routing ────────────────────────────────────────────────────────
async function _init() {
    initPipelineUI();

    const path = window.location.pathname; // "/", "/process/xxx", "/karaoke/xxx"
    const parts = path.split('/').filter(Boolean);

    if (parts[0] === 'process' && parts[1]) {
        state.currentJobId = parts[1];

        // Switch to process stage
        switchStage('process');

        listenProgress();
        return;
    }

    if (parts[0] === 'karaoke' && parts[1]) {
        state.currentJobId = parts[1];

        try {
            const res = await fetch(`/api/result/check?job_id=${state.currentJobId}`);
            if (res.ok) {
                const data = await res.json();
                if (data.lyrics) {
                    lyricsInput.value = data.lyrics;
                    lyricsInput.dispatchEvent(new Event('input'));
                }
                if (data.has_results) {
                    // Switch to player automatically after validating
                    if (window.karaokePlayer) {
                        const ok = await window.karaokePlayer.loadFromServer(state.currentJobId);
                        if (ok) {
                            switchStage('view');
                        }
                    }
                }
            }
        } catch (e) { }
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

        // Reset sidebar and tracks
        STEPS.forEach(s => setStepStatus(s.id, 'pending', ''));

        setStatus('running', 'Processando Música Completa...');
        addLog('🚀 Promovido para Pipeline Full. Retomando processamento...', 'info');

        // Restart SSE
        listenProgress();
    });
}

// ── Promote UI ──────────────────────────────────────────────────────────
window.showPromoteButton = function(jobId) {
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
            btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 14px; margin-right: 6px; display: inline-block; vertical-align: middle;"><path d="M5 13l4 4L19 7"></path></svg> Promover para Completa';
            
            // Dispatch event for UI to reset and listen to progress
            window.dispatchEvent(new CustomEvent('karaoke:promoted', { detail: { jobId } }));
        } catch (e) {
            btn.disabled = false;
            btn.innerHTML = 'Erro! Tentar Novamente';
            addLog('Erro ao promover: ' + e.message, 'error');
        }
    };
};

// Run init on dom load
document.addEventListener('DOMContentLoaded', _init);
