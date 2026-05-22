/**
 * Karaoke Pipeline - Client Side Logic
 * Handles SSE progress updates, charts, and global UI state.
 */

document.addEventListener('DOMContentLoaded', () => {
    initGlobalProgress();
    initJobDetail();
});

function initGlobalProgress() {
    const activeJobs = document.querySelectorAll('.job-card.status-running, #progress-section');

    activeJobs.forEach(el => {
        const jobId = el.dataset.jobId || (window.JOB_DATA && window.JOB_DATA.id);
        if (!jobId) return;

        const eventSource = new EventSource(`/job/${jobId}/stream`);
        const fill = el.querySelector('.progress-fill');
        const stageLabel = el.querySelector('.status-stage, .stage-label');
        const pctLabel = el.querySelector('.status-pct, .job-card-status .mono.dim');
        const failureMessage = el.querySelector('.failure-message');

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
                if (window.JOB_DATA && window.JOB_DATA.id === jobId) {
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
            if (typeof window.refreshObservabilityTimeline === 'function') {
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

    const load = () => {
        fetch(url)
            .then(response => {
                if (!response.ok) throw new Error(`events ${response.status}`);
                return response.json();
            })
            .then(renderObservabilityTimeline)
            .catch(error => {
                const summary = document.getElementById('observability-summary');
                if (summary) summary.textContent = `EVENTS UNAVAILABLE: ${error.message}`;
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
    const failures = Array.isArray(summary.failures) ? summary.failures.length : 0;
    const warnings = Array.isArray(summary.warnings) ? summary.warnings.length : 0;

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
                <span class="event-time mono">${escapeHtml(time)}</span>
                <span class="event-stage mono">${escapeHtml(stage)}</span>
                <span class="event-name mono">${escapeHtml(name)}</span>
                <span class="event-message mono">${escapeHtml(message || details)}</span>
            </div>
        `;
    }).join('') || '<div class="event-row"><span class="mono dim">No structured events yet.</span></div>';
}

function compactDetails(details) {
    const pairs = Object.entries(details)
        .filter(([, value]) => value !== undefined && value !== null && value !== '')
        .slice(0, 4)
        .map(([key, value]) => `${key}=${Array.isArray(value) ? value.length : value}`);
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
