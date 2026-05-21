/**
 * Karaoke Pipeline — Client Side Logic
 * Handles SSE progress updates, charts, and global UI state.
 */

document.addEventListener('DOMContentLoaded', () => {
    initGlobalProgress();
    initJobDetail();
});

/**
 * Real-time status updates for the Dashboard and Detail page
 */
function initGlobalProgress() {
    // Collect all cards/sections that need live updates
    const activeJobs = document.querySelectorAll('.job-card.status-running, #progress-section');
    
    activeJobs.forEach(el => {
        const jobId = el.dataset.jobId || (window.JOB_DATA && window.JOB_DATA.id);
        if (!jobId) return;

        const eventSource = new EventSource(`/job/${jobId}/stream`);
        
        const fill = el.querySelector('.progress-fill');
        const stageLabel = el.querySelector('.status-stage, .stage-label');
        const pctLabel = el.querySelector('.status-pct, .job-card-status .mono.dim');

        eventSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            const progress = data.progress || 0;
            const stage = data.stage || 'queued';

            if (fill) fill.style.width = `${progress}%`;
            if (pctLabel) pctLabel.textContent = `${progress}%`;

            if (stageLabel) {
                if (stage === 'done') {
                    stageLabel.textContent = '✓ COMPLETE';
                    stageLabel.className = stageLabel.className.replace(/running|queued/, 'done');
                    if (fill) fill.classList.add('done');
                    eventSource.close();
                    // Reload if we are on the detail page to show player
                    if (window.JOB_DATA && window.JOB_DATA.id === jobId) {
                        setTimeout(() => window.location.reload(), 1500);
                    }
                } else if (stage === 'failed') {
                    stageLabel.textContent = '✗ FAILED';
                    stageLabel.className = stageLabel.className.replace(/running|queued/, 'failed');
                    if (fill) fill.classList.add('failed');
                    eventSource.close();
                } else {
                    stageLabel.textContent = stage.replace(/_/g, ' ').toUpperCase();
                }
            }
        };

        eventSource.onerror = () => {
            eventSource.close();
        };
    });
}

/**
 * Initialization for the Job Detail page
 */
function initJobDetail() {
    if (!window.JOB_DATA) return;
    
    const { metrics } = window.JOB_DATA;
    if (metrics && metrics.per_line) {
        renderDriftChart(metrics.per_line);
    }
}

/**
 * Renders the drift calibration chart using Canvas
 */
function renderDriftChart(data) {
    const canvas = document.getElementById('driftChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const devicePixelRatio = window.devicePixelRatio || 1;
    
    // Resize for high DPI
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * devicePixelRatio;
    canvas.height = rect.height * devicePixelRatio;
    ctx.scale(devicePixelRatio, devicePixelRatio);

    const W = rect.width;
    const H = rect.height;
    const padding = 10;
    
    const drifts = data.map(d => d.drift);
    const maxDrift = Math.max(...drifts, 5); // Minimum 5s scale
    const barWidth = (W - (padding * 2)) / data.length;
    
    // Colors
    const colorCyan = '#00F5FF';
    const colorWarn = '#FF6B35';
    const colorLine = 'rgba(0, 245, 255, 0.1)';

    // Draw background grid
    ctx.strokeStyle = colorLine;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i++) {
        const y = padding + ((H - padding * 2) * (i / 5));
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(W - padding, y);
        ctx.stroke();
    }

    // Draw 3s Threshold Line
    const thresholdY = H - padding - ((3 / maxDrift) * (H - padding * 2));
    ctx.setLineDash([5, 5]);
    ctx.strokeStyle = 'rgba(255, 107, 53, 0.4)';
    ctx.beginPath();
    ctx.moveTo(padding, thresholdY);
    ctx.lineTo(W - padding, thresholdY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw Bars
    data.forEach((d, i) => {
        const val = d.drift;
        const barHeight = (val / maxDrift) * (H - padding * 2);
        const x = padding + (i * barWidth);
        const y = H - padding - barHeight;

        ctx.fillStyle = val > 3.0 ? colorWarn : colorCyan;
        ctx.globalAlpha = val > 3.0 ? 0.9 : 0.4;
        
        ctx.fillRect(x + 1, y, barWidth - 2, barHeight);
        
        // Hover effect or subtle outline
        ctx.strokeStyle = ctx.fillStyle;
        ctx.globalAlpha = 1;
        ctx.strokeRect(x + 1, y, barWidth - 2, barHeight);
    });

    // Add Label
    ctx.fillStyle = 'rgba(0, 245, 255, 0.5)';
    ctx.font = '10px "Share Tech Mono"';
    ctx.fillText('STABILITY THRESHOLD (3.0s)', padding + 5, thresholdY - 5);
}
