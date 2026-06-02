/**
 * Karaoke Pipeline - Client Side Logic
 * Handles SSE progress updates, charts, and global UI state.
 */

document.addEventListener('DOMContentLoaded', () => {
    initGlobalProgress();
    initJobDetail();
    initReviewWizard();
});

function initGlobalProgress() {
    const activeJobs = document.querySelectorAll('.job-card.status-running, #progress-section');

    activeJobs.forEach(el => {
        const jobId = el.dataset.jobId || (window.JOB_DATA && window.JOB_DATA.id);
        if (!jobId) return;

        const fill = el.querySelector('.progress-fill');
        const stageLabel = el.querySelector('.status-stage, .stage-label');
        const pctLabel = el.querySelector('.status-pct, .job-card-status .mono.dim');
        const failureMessage = el.querySelector('.failure-message');
        const isJobDetailProgress = el.id === 'progress-section';
        const currentStageText = (stageLabel && stageLabel.textContent || '').trim().toLowerCase();
        const isTerminalDetail = isJobDetailProgress
            && (currentStageText === 'done' || currentStageText === 'failed');

        if (isTerminalDetail || (isJobDetailProgress && window.JOB_DATA && window.JOB_DATA.isDone)) {
            return;
        }

        const eventSource = new EventSource(`/job/${jobId}/stream`);
        let lastStage = currentStageText;

        eventSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            const progress = data.progress || 0;
            const stage = data.stage || 'queued';

            if (fill) fill.style.width = `${progress}%`;
            if (pctLabel) pctLabel.textContent = `${progress}%`;

            if (!stageLabel) return;

            if (stage === 'done') {
                stageLabel.textContent = 'DONE';
                stageLabel.className = stageLabel.className.replace(/running|queued/, 'done');
                if (fill) fill.classList.add('done');
                eventSource.close();
                if (window.JOB_DATA && window.JOB_DATA.id === jobId && lastStage !== 'done') {
                    setTimeout(() => window.location.reload(), 1500);
                }
            } else if (stage === 'failed') {
                stageLabel.textContent = 'FAILED';
                stageLabel.className = stageLabel.className.replace(/running|queued/, 'failed');
                if (fill) fill.classList.add('failed');
                if (failureMessage && data.error) {
                    failureMessage.textContent = data.error;
                    failureMessage.hidden = false;
                }
                eventSource.close();
            } else {
                stageLabel.textContent = stage.replace(/_/g, ' ').toUpperCase();
            }
            lastStage = stage;
            if (stage !== 'done' && stage !== 'failed' && typeof window.refreshObservabilityTimeline === 'function') {
                window.refreshObservabilityTimeline();
            }
        };

        eventSource.onerror = () => {
            eventSource.close();
        };
    });
}

function initJobDetail() {
    if (!window.JOB_DATA) return;

    const { metrics } = window.JOB_DATA;
    if (metrics && metrics.per_line) {
        renderDriftChart(metrics.per_line);
    }
    initObservabilityTimeline();
}

function initObservabilityTimeline() {
    const section = document.getElementById('observability-section');
    if (!section) return;

    const url = section.dataset.eventsUrl;
    if (!url) return;
    let isLoading = false;
    let lastSignature = '';

    const load = () => {
        if (isLoading) return;
        isLoading = true;
        fetch(url)
            .then(response => {
                if (!response.ok) throw new Error(`events ${response.status}`);
                return response.json();
            })
            .then(payload => {
                const events = Array.isArray(payload.events) ? payload.events : [];
                const summary = payload.summary || {};
                const signature = JSON.stringify({
                    events: events.slice(-16).map(event => [
                        event.timestamp,
                        event.event,
                        event.stage,
                        event.level,
                        event.message,
                    ]),
                    currentValidation: summary.current_validation || null,
                    failureCount: Array.isArray(summary.failures) ? summary.failures.length : 0,
                    warningCount: Array.isArray(summary.warnings) ? summary.warnings.length : 0,
                });
                if (signature !== lastSignature) {
                    lastSignature = signature;
                    renderObservabilityTimeline(payload);
                }
            })
            .catch(error => {
                const summary = document.getElementById('observability-summary');
                if (summary) summary.textContent = `EVENTS UNAVAILABLE: ${error.message}`;
            })
            .finally(() => {
                isLoading = false;
            });
    };

    load();
    window.refreshObservabilityTimeline = load;
}

function renderObservabilityTimeline(payload) {
    const summaryEl = document.getElementById('observability-summary');
    const timelineEl = document.getElementById('event-timeline');
    if (!summaryEl || !timelineEl) return;

    const events = Array.isArray(payload.events) ? payload.events : [];
    const summary = payload.summary || {};
    const currentValidation = summary.current_validation || null;
    const failures = currentValidation
        ? currentValidation.failure_count || 0
        : (Array.isArray(summary.failures) ? summary.failures.length : 0);
    const warnings = currentValidation
        ? currentValidation.warning_count || 0
        : (Array.isArray(summary.warnings) ? summary.warnings.length : 0);

    summaryEl.innerHTML = `
        <span class="tag ${failures ? 'tag-red' : 'tag-green'}">${failures} FAIL</span>
        <span class="tag ${warnings ? 'tag-warn' : 'tag-green'}">${warnings} WARN</span>
        <span class="dim">${events.length} EVENTS</span>
    `;

    const latest = events.slice(-16).reverse();
    timelineEl.innerHTML = latest.map(event => {
        const level = event.level || 'info';
        const stage = event.stage || '';
        const name = event.event || 'event';
        const message = event.message || '';
        const details = event.details ? compactDetails(event.details) : '';
        const time = event.timestamp ? new Date(event.timestamp * 1000).toLocaleTimeString() : '';
        return `
            <div class="event-row level-${escapeHtml(level)}">
                <div class="event-meta">
                    <span class="event-time mono">${escapeHtml(time)}</span>
                    <span class="event-stage mono">${escapeHtml(stage)}</span>
                    <span class="event-name mono">${escapeHtml(name)}</span>
                </div>
                <span class="event-message mono">${escapeHtml(message || details)}</span>
            </div>
        `;
    }).join('') || '<div class="event-row"><span class="mono dim">No structured events yet.</span></div>';
}

function compactDetails(details) {
    const pairs = Object.entries(details)
        .filter(([, value]) => value !== undefined && value !== null && value !== '')
        .slice(0, 4)
        .map(([key, value]) => {
            if (Array.isArray(value)) return `${key}=${value.length}`;
            if (typeof value === 'object') return `${key}=${JSON.stringify(value)}`;
            return `${key}=${value}`;
        });
    return pairs.join(' ');
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function initReviewWizard() {
    const shell = document.querySelector('.review-shell');
    if (!shell) return;

    const player = document.querySelector('[data-review-player]');
    const loopButton = document.querySelector('[data-play-loop]');
    let loopTimer = null;

    if (player && loopButton) {
        loopButton.addEventListener('click', () => {
            const start = Number(loopButton.dataset.start || 0);
            const end = Number(loopButton.dataset.end || start + 2);
            if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;

            if (loopTimer) window.clearInterval(loopTimer);
            player.currentTime = Math.max(0, start - 0.25);
            player.play();
            loopTimer = window.setInterval(() => {
                if (player.currentTime >= end + 0.25) {
                    player.pause();
                    window.clearInterval(loopTimer);
                    loopTimer = null;
                }
            }, 80);
        });
    }

    initAudioTimelinePreview(shell, player);
}

function initAudioTimelinePreview(shell, player) {
    const timeline = shell.querySelector('[data-audio-timeline]');
    if (!timeline) return;

    const duration = Number(timeline.dataset.durationS || 0);
    const playhead = timeline.querySelector('[data-audio-playhead]');
    const activeRegion = timeline.querySelector('[data-audio-active-region]');
    const readout = timeline.querySelector('[data-audio-selection-readout]');
    const markers = Array.from(timeline.querySelectorAll('[data-timeline-marker]'));
    if (!playhead || !activeRegion || !markers.length) return;

    const setPreview = (marker) => {
        const leftPct = Number(marker.dataset.leftPct || 0);
        const widthPct = Number(marker.dataset.widthPct || 0);
        if (!Number.isFinite(leftPct) || !Number.isFinite(widthPct)) return;

        timeline.dataset.selectedPointId = marker.dataset.pointId || '';
        markers.forEach(item => {
            const isSelected = item === marker;
            item.classList.toggle('is-previewing', isSelected);
            item.setAttribute('aria-current', isSelected ? 'true' : 'false');
        });
        playhead.style.left = `${leftPct}%`;
        playhead.dataset.timeS = marker.dataset.startS || '0';
        activeRegion.style.left = `${leftPct}%`;
        activeRegion.style.width = `${Math.max(0, widthPct)}%`;

        if (readout) {
            const label = marker.dataset.label || 'POINT';
            const text = marker.dataset.text || '';
            const start = Number(marker.dataset.startS || 0);
            const end = Number(marker.dataset.endS || start);
            const windowLabel = `${formatReviewSeconds(start)} - ${formatReviewSeconds(end)}`;
            readout.innerHTML = `
                <span class="mono accent">${escapeHtml(label)}</span>
                <strong>${escapeHtml(text)}</strong>
                <span class="mono dim">${escapeHtml(windowLabel)}</span>
            `;
        }
    };

    const shouldNavigate = (event) => (
        event.defaultPrevented
        || event.button !== 0
        || event.metaKey
        || event.ctrlKey
        || event.shiftKey
        || event.altKey
    );

    markers.forEach(marker => {
        marker.addEventListener('pointerenter', () => setPreview(marker));
        marker.addEventListener('focus', () => setPreview(marker));
        marker.addEventListener('click', (event) => {
            if (shouldNavigate(event)) return;
            event.preventDefault();
            setPreview(marker);
        });
    });

    if (player && Number.isFinite(duration) && duration > 0) {
        player.addEventListener('timeupdate', () => {
            const current = Math.max(0, Math.min(duration, player.currentTime || 0));
            const leftPct = (current / duration) * 100;
            playhead.style.left = `${leftPct}%`;
            playhead.dataset.timeS = current.toFixed(3);
        });
    }
}

function formatReviewSeconds(seconds) {
    if (!Number.isFinite(seconds)) return '0.000s';
    return `${seconds.toFixed(3)}s`;
}

function renderDriftChart(data) {
    const canvas = document.getElementById('driftChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const devicePixelRatio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * devicePixelRatio;
    canvas.height = rect.height * devicePixelRatio;
    ctx.scale(devicePixelRatio, devicePixelRatio);

    const width = rect.width;
    const height = rect.height;
    const padding = 10;
    const drifts = data.map(d => d.drift);
    const maxDrift = Math.max(...drifts, 5);
    const barWidth = (width - (padding * 2)) / data.length;

    ctx.strokeStyle = 'rgba(0, 245, 255, 0.1)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i++) {
        const y = padding + ((height - padding * 2) * (i / 5));
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke();
    }

    const thresholdY = height - padding - ((3 / maxDrift) * (height - padding * 2));
    ctx.setLineDash([5, 5]);
    ctx.strokeStyle = 'rgba(255, 107, 53, 0.4)';
    ctx.beginPath();
    ctx.moveTo(padding, thresholdY);
    ctx.lineTo(width - padding, thresholdY);
    ctx.stroke();
    ctx.setLineDash([]);

    data.forEach((d, i) => {
        const val = d.drift;
        const barHeight = (val / maxDrift) * (height - padding * 2);
        const x = padding + (i * barWidth);
        const y = height - padding - barHeight;

        ctx.fillStyle = val > 3.0 ? '#FF6B35' : '#00F5FF';
        ctx.globalAlpha = val > 3.0 ? 0.9 : 0.4;
        ctx.fillRect(x + 1, y, barWidth - 2, barHeight);
        ctx.strokeStyle = ctx.fillStyle;
        ctx.globalAlpha = 1;
        ctx.strokeRect(x + 1, y, barWidth - 2, barHeight);
    });

    ctx.fillStyle = 'rgba(0, 245, 255, 0.5)';
    ctx.font = '10px "Share Tech Mono"';
    ctx.fillText('STABILITY THRESHOLD (3.0s)', padding + 5, thresholdY - 5);
}
