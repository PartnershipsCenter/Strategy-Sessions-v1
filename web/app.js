/* Conference Exhibitor Scanner — Frontend JS */

let currentScoringRunId = null;
let currentResults = [];
let sortDirection = 'desc';

// ── Scan ────────────────────────────────────────────────────────

async function startScan() {
    const icp = document.getElementById('icp-input').value.trim();
    const url = document.getElementById('url-input').value.trim();
    const name = document.getElementById('name-input').value.trim();
    const forceRescrape = document.getElementById('force-rescrape').checked;

    if (!icp) {
        alert('Please enter your Ideal Customer Profile (ICP)');
        return;
    }
    if (!url) {
        alert('Please enter a conference exhibitor list URL');
        return;
    }

    // Disable form
    document.getElementById('scan-btn').disabled = true;
    document.getElementById('scan-btn').textContent = 'Scanning...';

    // Show progress, hide results
    document.getElementById('progress-section').style.display = 'block';
    document.getElementById('results-section').style.display = 'none';
    resetProgress();

    try {
        // Start scan
        const resp = await fetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url,
                icp,
                conference_name: name,
                force_rescrape: forceRescrape,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Failed to start scan');
        }

        const data = await resp.json();
        const runId = data.run_id;

        // Connect to SSE for progress
        await listenProgress(runId);

    } catch (err) {
        showError(err.message);
    } finally {
        document.getElementById('scan-btn').disabled = false;
        document.getElementById('scan-btn').textContent = 'Scan Exhibitors';
    }
}

// ── Progress SSE ────────────────────────────────────────────────

function resetProgress() {
    ['scrape_list', 'scrape_details', 'enrich', 'score'].forEach(stage => {
        const el = document.getElementById(`stage-${stage}`);
        el.className = 'stage';
        document.getElementById(`status-${stage}`).textContent = '';
    });
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-message').textContent = 'Starting...';
}

async function listenProgress(runId) {
    return new Promise((resolve, reject) => {
        const evtSource = new EventSource(`/api/scan/${runId}/progress`);
        const stageOrder = ['scrape_list', 'scrape_details', 'store', 'enrich', 'score'];
        let activeStage = '';

        evtSource.onmessage = async (event) => {
            const data = JSON.parse(event.data);
            const { stage, message, current, total } = data;

            // Update progress message
            document.getElementById('progress-message').textContent = message;

            // Update progress bar
            if (total > 0) {
                const pct = Math.round((current / total) * 100);
                document.getElementById('progress-bar').style.width = pct + '%';
            }

            // Map store stage to scrape_list for UI
            const uiStage = stage === 'store' ? 'scrape_list' : stage;

            // Update stage states
            if (['scrape_list', 'scrape_details', 'enrich', 'score'].includes(uiStage)) {
                if (uiStage !== activeStage) {
                    // Mark previous as done
                    if (activeStage) {
                        const prev = document.getElementById(`stage-${activeStage}`);
                        prev.className = 'stage done';
                    }
                    activeStage = uiStage;
                    document.getElementById(`stage-${uiStage}`).className = 'stage active';
                }

                // Update status text
                const statusEl = document.getElementById(`status-${uiStage}`);
                if (total > 0) {
                    statusEl.textContent = `${current}/${total}`;
                }
            }

            // Handle completion
            if (stage === 'complete') {
                evtSource.close();
                // Mark all stages done
                ['scrape_list', 'scrape_details', 'enrich', 'score'].forEach(s => {
                    document.getElementById(`stage-${s}`).className = 'stage done';
                });
                document.getElementById('progress-bar').style.width = '100%';

                if (data.scoring_run_id) {
                    currentScoringRunId = data.scoring_run_id;
                    await loadResults(data.scoring_run_id, data.conference_name);
                }
                loadHistory();
                resolve();
            }

            if (stage === 'error') {
                evtSource.close();
                showError(message);
                reject(new Error(message));
            }
        };

        evtSource.onerror = () => {
            evtSource.close();
            reject(new Error('Connection lost'));
        };
    });
}

// ── Results ─────────────────────────────────────────────────────

async function loadResults(scoringRunId, conferenceName) {
    try {
        const resp = await fetch(`/api/results/${scoringRunId}`);
        const data = await resp.json();
        currentResults = data.results;

        document.getElementById('results-section').style.display = 'block';
        document.getElementById('results-title').textContent =
            `Results — ${conferenceName || 'Conference'}`;
        document.getElementById('results-summary').textContent =
            `${data.count} exhibitors scored. Showing top matches for your ICP.`;

        renderResults(currentResults);
    } catch (err) {
        showError('Failed to load results: ' + err.message);
    }
}

function renderResults(results) {
    const tbody = document.getElementById('results-body');
    tbody.innerHTML = '';

    results.forEach((r, i) => {
        const tr = document.createElement('tr');
        tr.className = 'result-row';

        // Score class
        let scoreClass = 'score-low';
        if (r.score >= 8) scoreClass = 'score-high';
        else if (r.score >= 5) scoreClass = 'score-mid';

        // Company name — clickable link to website if available
        const companyNameHtml = r.website_url
            ? `<a href="${escAttr(r.website_url)}" target="_blank" rel="noopener" class="company-link" onclick="event.stopPropagation()">${escHtml(r.company_name)}</a>`
            : `<span>${escHtml(r.company_name)}</span>`;

        // Quick links (inline, compact)
        const quickLinks = [];
        if (r.website_url)
            quickLinks.push(`<a href="${escAttr(r.website_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Website</a>`);
        if (r.linkedin_url)
            quickLinks.push(`<a href="${escAttr(r.linkedin_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">LinkedIn</a>`);
        if (r.contact_url)
            quickLinks.push(`<a href="${escAttr(r.contact_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Contact</a>`);

        // CIS leaders
        let cisBadge = '';
        if (r.russian_speaking_leaders) {
            cisBadge = `<span class="cis-badge">\u{1F1F7}\u{1F1FA} ${escHtml(r.russian_speaking_leaders)}</span>`;
        }

        tr.innerHTML = `
            <td class="col-rank">${r.rank}</td>
            <td class="col-score"><span class="score-badge ${scoreClass}">${r.score}</span></td>
            <td class="col-company">
                <div class="company-name">${companyNameHtml}</div>
                ${r.booth_location ? `<div class="booth-tag">${escHtml(r.booth_location)}</div>` : ''}
            </td>
            <td class="col-summary">${escHtml(r.summary || r.description || '')}</td>
            <td class="col-links">
                <div class="link-list">${quickLinks.join('')}</div>
            </td>
        `;

        // Click row to expand detail panel
        tr.addEventListener('click', () => toggleDetail(tr, r));
        tbody.appendChild(tr);
    });
}

function toggleDetail(row, r) {
    // If already expanded, collapse
    const existing = row.nextElementSibling;
    if (existing && existing.classList.contains('detail-row')) {
        existing.remove();
        row.classList.remove('expanded');
        return;
    }

    // Collapse any other open detail
    const openDetail = document.querySelector('.detail-row');
    if (openDetail) {
        openDetail.previousElementSibling.classList.remove('expanded');
        openDetail.remove();
    }

    row.classList.add('expanded');

    const detailTr = document.createElement('tr');
    detailTr.className = 'detail-row';

    // Build detail content
    const links = [];
    if (r.website_url)
        links.push(`<a href="${escAttr(r.website_url)}" target="_blank" rel="noopener">${escHtml(r.website_url)}</a>`);
    if (r.linkedin_url)
        links.push(`<a href="${escAttr(r.linkedin_url)}" target="_blank" rel="noopener">${escHtml(r.linkedin_url)}</a>`);
    if (r.contact_url)
        links.push(`<a href="${escAttr(r.contact_url)}" target="_blank" rel="noopener">${escHtml(r.contact_url)}</a>`);
    if (r.detail_page_url)
        links.push(`<a href="${escAttr(r.detail_page_url)}" target="_blank" rel="noopener">Conference page</a>`);

    const cats = (r.categories || []).map(c => `<span class="cat-tag">${escHtml(c)}</span>`).join('');

    let cisBadge = '';
    if (r.russian_speaking_leaders) {
        cisBadge = `<div class="detail-field"><strong>CIS Contact:</strong> \u{1F1F7}\u{1F1FA} ${escHtml(r.russian_speaking_leaders)}</div>`;
    }

    detailTr.innerHTML = `
        <td colspan="5" class="detail-cell">
            <div class="detail-panel">
                <div class="detail-grid">
                    <div class="detail-main">
                        ${r.reasoning ? `<div class="detail-field"><strong>Why this matches:</strong> ${escHtml(r.reasoning)}</div>` : ''}
                        ${r.description ? `<div class="detail-field"><strong>Description:</strong> ${escHtml(r.description)}</div>` : ''}
                        ${cats ? `<div class="detail-field"><strong>Categories:</strong> ${cats}</div>` : ''}
                        ${cisBadge}
                    </div>
                    <div class="detail-links">
                        <strong>Links</strong>
                        ${links.map(l => `<div>${l}</div>`).join('')}
                        ${r.booth_location ? `<div class="detail-booth">Booth: ${escHtml(r.booth_location)}</div>` : ''}
                    </div>
                </div>
            </div>
        </td>
    `;

    row.after(detailTr);
}

function sortResults(field) {
    sortDirection = sortDirection === 'desc' ? 'asc' : 'desc';
    currentResults.sort((a, b) => {
        const diff = a[field] - b[field];
        return sortDirection === 'desc' ? -diff : diff;
    });
    // Re-rank
    currentResults.forEach((r, i) => r.rank = i + 1);
    renderResults(currentResults);
}

// ── Export ───────────────────────────────────────────────────────

function exportCSV() {
    if (!currentScoringRunId) return;
    window.open(`/api/export/${currentScoringRunId}`, '_blank');
}

// ── New Scan ────────────────────────────────────────────────────

function newScan() {
    document.getElementById('results-section').style.display = 'none';
    document.getElementById('progress-section').style.display = 'none';
    document.getElementById('url-input').value = '';
    document.getElementById('url-input').focus();
}

// ── History ─────────────────────────────────────────────────────

async function loadHistory() {
    const container = document.getElementById('history-list');
    try {
        const resp = await fetch('/api/conferences');
        const data = await resp.json();

        if (!data.conferences || data.conferences.length === 0) {
            container.innerHTML = '<p class="muted">No conferences scraped yet</p>';
            return;
        }

        container.innerHTML = data.conferences.map(c => `
            <div class="history-item">
                <div>
                    <span class="history-item-name">${escHtml(c.name)}</span>
                    <span class="history-item-meta"> — ${c.total_exhibitors || 0} exhibitors</span>
                </div>
                <span class="history-item-meta">${formatDate(c.created_at)}</span>
            </div>
        `).join('');
    } catch {
        container.innerHTML = '<p class="muted">Failed to load history</p>';
    }
}

// ── Helpers ─────────────────────────────────────────────────────

function escHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escAttr(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
              .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
        return new Date(dateStr).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric'
        });
    } catch {
        return dateStr;
    }
}

function showError(message) {
    const existing = document.querySelector('.error-message');
    if (existing) existing.remove();

    const div = document.createElement('div');
    div.className = 'error-message';
    div.textContent = message;
    document.getElementById('progress-section').appendChild(div);
}

// ── Init ────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', loadHistory);
