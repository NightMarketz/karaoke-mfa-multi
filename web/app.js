/**
 * app.js — Karaoke Studio frontend logic.
 *
 * Handles file upload, job polling/SSE, and preview player.
 */

// ── Config ──────────────────────────────────────────────────

const API = '/api';
const STAGES = ['input', 'demixing', 'transcribing', 'aligning', 'analyzing', 'generating', 'rendering'];
const STAGE_LABELS = {
    queued: 'Queued',
    input: 'Validating',
    demixing: 'Separating vocals',
    transcribing: 'Transcribing',
    aligning: 'Aligning phonemes',
    analyzing: 'Analyzing lyrics',
    generating: 'Generating subtitles',
    rendering: 'Rendering video',
    done: 'Complete',
};

// ── State ───────────────────────────────────────────────────

let currentPreviewJob = null;
let sseConnections = {};

// ── DOM ─────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── Init ────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initUpload();
    initRefresh();
    checkOllama();
    loadJobs();

    // Auto-refresh every 10s
    setInterval(loadJobs, 10000);
});

// ── Ollama Health ───────────────────────────────────────────

async function checkOllama() {
    try {
        const resp = await fetch('http://localhost:11434/api/tags', {
            mode: 'no-cors',
            signal: AbortSignal.timeout(3000),
        });
        // no-cors means we can't read the response, but no error = server is up
        $('#ollamaStatus').className = 'status-dot online';
        $('#ollamaLabel').textContent = 'Ollama connected';
    } catch {
        $('#ollamaStatus').className = 'status-dot offline';
        $('#ollamaLabel').textContent = 'Ollama offline';
    }
}

// ── Upload ──────────────────────────────────────────────────

function initUpload() {
    const dropZone = $('#dropZone');
    const fileInput = $('#fileInput');

    // Click to browse
    dropZone.addEventListener('click', () => fileInput.click());

    // File selected
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            uploadFile(e.target.files[0]);
        }
    });

    // Drag events
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            uploadFile(e.dataTransfer.files[0]);
        }
    });
}

async function uploadFile(file) {
    const progressEl = $('#uploadProgress');
    const fileNameEl = $('#uploadFileName');
    const percentEl = $('#uploadPercent');
    const fillEl = $('#uploadFill');

    progressEl.classList.remove('hidden');
    fileNameEl.textContent = file.name;
    percentEl.textContent = '0%';
    fillEl.style.width = '0%';

    const formData = new FormData();
    formData.append('file', file);

    try {
        // Use XMLHttpRequest for progress tracking
        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                percentEl.textContent = `${pct}%`;
                fillEl.style.width = `${pct}%`;
            }
        });

        const response = await new Promise((resolve, reject) => {
            xhr.onload = () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(JSON.parse(xhr.responseText));
                } else {
                    reject(new Error(`Upload failed: ${xhr.status}`));
                }
            };
            xhr.onerror = () => reject(new Error('Upload network error'));
            xhr.open('POST', `${API}/jobs`);
            xhr.send(formData);
        });

        // Upload complete
        percentEl.textContent = 'Processing...';
        fillEl.style.width = '100%';

        // Start SSE for this job
        startSSE(response.job_id);

        // Refresh job list
        setTimeout(loadJobs, 500);

        // Hide upload progress after 2s
        setTimeout(() => {
            progressEl.classList.add('hidden');
            $('#fileInput').value = '';
        }, 2000);

    } catch (err) {
        percentEl.textContent = `Error: ${err.message}`;
        fillEl.style.width = '0%';
        fillEl.style.background = 'var(--accent-red)';
    }
}

// ── Jobs ────────────────────────────────────────────────────

function initRefresh() {
    $('#refreshBtn').addEventListener('click', loadJobs);
}

async function loadJobs() {
    try {
        const resp = await fetch(`${API}/jobs`);
        const jobs = await resp.json();
        renderJobs(jobs);
    } catch (err) {
        console.error('Failed to load jobs:', err);
    }
}

function renderJobs(jobs) {
    const list = $('#jobsList');

    if (!jobs.length) {
        list.innerHTML = '<div class="empty-state"><p>No jobs yet. Upload a file to get started.</p></div>';
        return;
    }

    list.innerHTML = jobs.map(job => {
        const status = job.status || {};
        const stage = status.stage || 'unknown';
        const hasError = !!status.error;
        const isDone = stage === 'done';

        // Build stage pips
        const pips = STAGES.map(s => {
            const stageIdx = STAGES.indexOf(s);
            const currentIdx = STAGES.indexOf(stage);

            let cls = 'stage-pip';
            if (hasError && stageIdx === currentIdx) cls += ' error';
            else if (isDone || stageIdx < currentIdx) cls += ' complete';
            else if (stageIdx === currentIdx) cls += ' active';
            return `<div class="${cls}" title="${STAGE_LABELS[s] || s}"></div>`;
        }).join('');

        // Badge
        let badgeCls = 'queued';
        let badgeText = 'QUEUED';
        if (isDone) { badgeCls = 'done'; badgeText = 'DONE'; }
        else if (hasError) { badgeCls = 'failed'; badgeText = 'FAILED'; }
        else if (stage !== 'queued' && stage !== 'unknown') { badgeCls = 'running'; badgeText = STAGE_LABELS[stage] || stage; }

        const duration = job.duration ? `${Math.round(job.duration)}s` : '';

        return `
            <div class="job-item" data-job-id="${job.job_id}" onclick="onJobClick('${job.job_id}')">
                <span class="job-id">${job.job_id}</span>
                <div class="job-info">
                    <div class="job-filename">${escapeHtml(job.filename)}</div>
                    <div class="job-meta">
                        ${duration ? `<span>${duration}</span>` : ''}
                        <div class="job-stages">${pips}</div>
                    </div>
                </div>
                <span class="job-badge ${badgeCls}">${badgeText}</span>
                <div class="job-actions">
                    ${isDone ? `<button class="btn btn-sm" onclick="event.stopPropagation(); previewJob('${job.job_id}')" title="Preview">▶</button>` : ''}
                    ${hasError ? `<button class="btn btn-sm" onclick="event.stopPropagation(); retryJob('${job.job_id}')" title="Retry">↻</button>` : ''}
                    <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation(); deleteJob('${job.job_id}')" title="Delete">✕</button>
                </div>
            </div>
        `;
    }).join('');

    // Start SSE for any running jobs
    jobs.forEach(job => {
        const stage = (job.status || {}).stage;
        if (stage && stage !== 'done' && !sseConnections[job.job_id]) {
            startSSE(job.job_id);
        }
    });
}

// ── SSE ─────────────────────────────────────────────────────

function startSSE(jobId) {
    if (sseConnections[jobId]) return;

    const source = new EventSource(`${API}/jobs/${jobId}/status`);
    sseConnections[jobId] = source;

    source.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateJobUI(jobId, data);

            if (data.stage === 'done' || data.error) {
                source.close();
                delete sseConnections[jobId];
                loadJobs(); // Final refresh
            }
        } catch (err) {
            console.error('SSE parse error:', err);
        }
    };

    source.onerror = () => {
        source.close();
        delete sseConnections[jobId];
    };
}

function updateJobUI(jobId, status) {
    const item = document.querySelector(`[data-job-id="${jobId}"]`);
    if (!item) {
        loadJobs();
        return;
    }

    // Update stage pips
    const pips = item.querySelectorAll('.stage-pip');
    const currentIdx = STAGES.indexOf(status.stage);
    const hasError = !!status.error;

    pips.forEach((pip, i) => {
        pip.className = 'stage-pip';
        if (hasError && i === currentIdx) pip.classList.add('error');
        else if (status.stage === 'done' || i < currentIdx) pip.classList.add('complete');
        else if (i === currentIdx) pip.classList.add('active');
    });

    // Update badge
    const badge = item.querySelector('.job-badge');
    if (badge) {
        if (status.stage === 'done') {
            badge.className = 'job-badge done';
            badge.textContent = 'DONE';
        } else if (hasError) {
            badge.className = 'job-badge failed';
            badge.textContent = 'FAILED';
        } else {
            badge.className = 'job-badge running';
            badge.textContent = STAGE_LABELS[status.stage] || status.stage;
        }
    }
}

// ── Job Actions ─────────────────────────────────────────────

function onJobClick(jobId) {
    previewJob(jobId);
}

async function previewJob(jobId) {
    const section = $('#preview-section');
    const video = $('#videoPlayer');

    // Check if output files exist
    try {
        const resp = await fetch(`${API}/jobs/${jobId}`);
        const job = await resp.json();
        const files = job.files || [];
        const hasVideo = files.some(f => f.name === 'output.mp4');
        const hasAss = files.some(f => f.name === 'output.ass');
        const hasInstrumental = files.some(f => f.name === 'instrumental.wav');

        if (hasVideo) {
            video.src = `${API}/jobs/${jobId}/files/output.mp4`;
            section.classList.remove('hidden');
            currentPreviewJob = jobId;

            // Setup download buttons
            $('#downloadMp4').onclick = () => downloadFile(jobId, 'output.mp4');
            $('#downloadAss').onclick = () => downloadFile(jobId, 'output.ass');
            $('#closePreview').onclick = () => {
                section.classList.add('hidden');
                video.pause();
                video.src = '';
                currentPreviewJob = null;
            };

        } else if (hasInstrumental) {
            // Audio-only preview
            video.src = `${API}/jobs/${jobId}/files/instrumental.wav`;
            section.classList.remove('hidden');
            currentPreviewJob = jobId;
        }

    } catch (err) {
        console.error('Preview error:', err);
    }
}

async function retryJob(jobId) {
    try {
        await fetch(`${API}/jobs/${jobId}/retry`, { method: 'POST' });
        loadJobs();
    } catch (err) {
        console.error('Retry error:', err);
    }
}

async function deleteJob(jobId) {
    if (!confirm(`Delete job ${jobId}?`)) return;

    try {
        await fetch(`${API}/jobs/${jobId}`, { method: 'DELETE' });
        loadJobs();
    } catch (err) {
        console.error('Delete error:', err);
    }
}

function downloadFile(jobId, filename) {
    const a = document.createElement('a');
    a.href = `${API}/jobs/${jobId}/files/${filename}`;
    a.download = filename;
    a.click();
}

// ── Utils ───────────────────────────────────────────────────

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
