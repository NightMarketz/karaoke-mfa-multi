/**
 * Karaoke Pipeline - Client Side Logic
 * Handles SSE progress updates, charts, and global UI state.
 */

document.addEventListener('DOMContentLoaded', () => {
    initGlobalProgress();
    initJobDetail();
    initCockpit();
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
                <span class="event-message mono">${message ? escapeHtml(message) : details}</span>
            </div>
        `;
    }).join('') || '<div class="event-row"><span class="mono dim">No structured events yet.</span></div>';
}

const OBSERVABILITY_TAG_DETAIL_KEYS = new Set([
    'classification',
    'tail_classification',
    'line_classification',
    'structural_tail_classification',
    'sound_type',
]);

const OBSERVABILITY_TAG_ARRAY_KEYS = new Set([
    'diagnostic_tags',
    'review_flags',
]);

const FRIENDLY_TAG_LABELS = {
    alignment_drift: 'DFT',
    early_next_line_entry_drift: 'DFT',
    final_word_after_alignment_hole: 'A-HOLE',
    false_long_tail: 'F-TAIL',
    inactive_or_false_tail: 'F-TAIL',
    line_low_vocal_evidence: 'L-VOC',
    long_structural_pause_audio_extension: 'L-PAU',
    possible_backing_or_alignment_issue: 'B/ALG?',
    possible_backing_vocal_not_in_lyrics: 'BV?',
    possible_lost_tail: 'L-TAIL?',
    possible_sustained_final_vowel: 'P-SUS',
    probable_unwritten_vowel_extension: 'U-SUS',
    review_only: 'RO',
    review_only_backing_or_drift: 'B/DFT',
    review_only_low_vocal_evidence: 'L-VOC',
    structural_pause_overridden_by_audio_tail: 'P-OVR',
    sustained_final_vowel: 'SUS',
    unwritten_interline_melisma: 'U-MEL',
    unwritten_vocal_melisma: 'VOC',
    written_melisma_extension: 'W-MEL',
};

const TAG_TITLES = {
    alignment_drift: 'Drift',
    early_next_line_entry_drift: 'Drift',
    final_word_after_alignment_hole: 'Alignment hole',
    false_long_tail: 'False tail',
    inactive_or_false_tail: 'False tail',
    line_low_vocal_evidence: 'Low vocal evidence',
    long_structural_pause_audio_extension: 'Long pause',
    possible_backing_or_alignment_issue: 'Backing/alignment?',
    possible_backing_vocal_not_in_lyrics: 'Backing vocal?',
    possible_lost_tail: 'Lost tail?',
    possible_sustained_final_vowel: 'Possible sustain',
    probable_unwritten_vowel_extension: 'Unwritten sustain',
    review_only: 'Review only',
    review_only_backing_or_drift: 'Backing/drift',
    review_only_low_vocal_evidence: 'Low vocal evidence',
    structural_pause_overridden_by_audio_tail: 'Pause override',
    sustained_final_vowel: 'Sustain',
    unwritten_interline_melisma: 'Unwritten melisma',
    unwritten_vocal_melisma: 'Vocalization',
    written_melisma_extension: 'Written melisma',
};

function formatTagLabel(value) {
    const normalized = String(value || '').replace(/\s+/g, '_').trim().toLowerCase();
    return FRIENDLY_TAG_LABELS[normalized] || String(value || '').replace(/_/g, ' ').trim().toUpperCase();
}

function formatTagTitle(value) {
    const normalized = String(value || '').replace(/\s+/g, '_').trim().toLowerCase();
    const fallback = String(value || '').replace(/_/g, ' ').trim();
    return TAG_TITLES[normalized] || (fallback ? fallback.charAt(0).toUpperCase() + fallback.slice(1) : '');
}

function renderDetailTag(value, className = 'tag-cyan') {
    const label = formatTagLabel(value);
    const title = formatTagTitle(value);
    if (!label) return '';
    return `<span class="tag ${className}" title="${escapeHtml(title)}">${escapeHtml(label)}</span>`;
}

function addClassificationTag(tags, seen, value, className = 'tag-cyan') {
    const raw = String(value || '').trim();
    if (!raw) return;
    const key = raw.replace(/\s+/g, '_').toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    tags.push(renderDetailTag(raw, className));
}

function classificationDetailTags(details) {
    const tags = [];
    const seen = new Set();
    Object.entries(details || {}).forEach(([key, value]) => {
        if (OBSERVABILITY_TAG_DETAIL_KEYS.has(key)) {
            addClassificationTag(tags, seen, value, key.includes('structural') ? 'tag-warn' : 'tag-cyan');
        } else if (OBSERVABILITY_TAG_ARRAY_KEYS.has(key) && Array.isArray(value)) {
            value.forEach(item => addClassificationTag(tags, seen, item, key === 'review_flags' ? 'tag-warn' : 'tag-purple'));
        } else if (key === 'sound_suggestion' && value && typeof value === 'object') {
            addClassificationTag(tags, seen, value.sound_type, 'tag-purple');
        }
    });
    return tags.join('');
}

function compactDetails(details) {
    const tags = classificationDetailTags(details);
    const pairs = Object.entries(details)
        .filter(([, value]) => value !== undefined && value !== null && value !== '')
        .filter(([key]) => !OBSERVABILITY_TAG_DETAIL_KEYS.has(key))
        .filter(([key]) => !OBSERVABILITY_TAG_ARRAY_KEYS.has(key))
        .slice(0, 4)
        .map(([key, value]) => {
            if (key === 'sound_suggestion' && value && typeof value === 'object') {
                const { sound_type: _soundType, ...rest } = value;
                if (!Object.keys(rest).length) return '';
                return `${escapeHtml(key)}=${escapeHtml(JSON.stringify(rest))}`;
            }
            if (Array.isArray(value)) return `${escapeHtml(key)}=${value.length}`;
            if (typeof value === 'object') return `${escapeHtml(key)}=${escapeHtml(JSON.stringify(value))}`;
            return `${escapeHtml(key)}=${escapeHtml(value)}`;
        });
    return [tags, ...pairs.filter(Boolean)].filter(Boolean).join(' ');
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function initCockpit() {
    const shell = document.querySelector('.cockpit-shell');
    if (!shell) return;

    shell.querySelectorAll('[data-file-drop]').forEach(drop => {
        const input = drop.querySelector('input[type="file"]');
        const label = drop.querySelector('span');
        const initialLabel = label ? label.textContent : '';

        const updateFileState = () => {
            const file = input && input.files && input.files[0];
            drop.classList.toggle('has-file', Boolean(file));
            if (label) label.textContent = file ? file.name : initialLabel;
        };

        if (input) input.addEventListener('change', updateFileState);

        ['dragenter', 'dragover'].forEach(eventName => {
            drop.addEventListener(eventName, event => {
                event.preventDefault();
                drop.classList.add('is-hovering');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            drop.addEventListener(eventName, event => {
                event.preventDefault();
                drop.classList.remove('is-hovering');
                if (eventName !== 'drop' || !input || !event.dataTransfer || !event.dataTransfer.files.length) {
                    return;
                }
                try {
                    input.files = event.dataTransfer.files;
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                } catch (error) {
                    updateFileState();
                }
            });
        });
    });

    const lyrics = shell.querySelector('.cockpit-lyrics');
    const counter = shell.querySelector('[data-lyrics-counter]');
    if (lyrics && counter) {
        const updateLyricsCounter = () => {
            const lyricLines = lyrics.value
                .split(/\r?\n/)
                .map(line => line.trim())
                .filter(line => line && !/^\[[^\]]+\]$/.test(line));
            const label = lyricLines.length === 1 ? 'lyric line' : 'lyric lines';
            counter.textContent = `${lyricLines.length} ${label}`;
        };
        lyrics.addEventListener('input', updateLyricsCounter);
        updateLyricsCounter();
    }
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
            let tags = [];
            try {
                tags = JSON.parse(marker.dataset.tagsJson || '[]');
            } catch (error) {
                tags = [];
            }
            const tagMarkup = Array.isArray(tags) && tags.length
                ? `<span class="review-point-tags">${tags.map(tag => {
                    const tagClass = String(tag.class || '');
                    const tagLabel = String(tag.label || '');
                    const tagTitle = String(tag.title || tag.value || tagLabel);
                    return `<span class="tag ${escapeHtml(tagClass)}" title="${escapeHtml(tagTitle)}">${escapeHtml(tagLabel)}</span>`;
                }).join('')}</span>`
                : `<strong>${escapeHtml(text)}</strong>`;
            const start = Number(marker.dataset.startS || 0);
            const end = Number(marker.dataset.endS || start);
            const windowLabel = `${formatReviewSeconds(start)} - ${formatReviewSeconds(end)}`;
            readout.innerHTML = `
                <span class="mono accent">${escapeHtml(label)}</span>
                ${tagMarkup}
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
