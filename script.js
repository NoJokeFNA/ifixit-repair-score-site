// Filter out noisy extension-related unhandled promise rejections seen in some browsers
// e.g., "Could not establish connection. Receiving end does not exist." which is not caused by our app.
window.addEventListener('unhandledrejection', (e) => {
    try {
        const msg = (e && e.reason && (e.reason.message || e.reason.toString())) || '';
        if (typeof msg === 'string' && msg.includes('Could not establish connection') && msg.includes('Receiving end does not exist')) {
            e.preventDefault();
            // Optional: keep console clean but allow debugging if needed
            if (typeof console !== 'undefined' && console.debug) {
                console.debug('[ignored] extension unhandledrejection:', msg);
            }
        }
    } catch (_) { /* no-op */ }
});

let devicesData = [];
let currentSort = {key: 'name', direction: 'asc'};
let myChart = null;
let lastUpdateFullTitle = '';
let chartJsReady = null;
function loadChartJsIdle() {
    if (typeof Chart !== 'undefined') return Promise.resolve(true);
    if (chartJsReady) return chartJsReady;
    chartJsReady = new Promise((resolve) => {
        const start = () => {
            const s = document.createElement('script');
            s.src = 'https://cdn.jsdelivr.net/npm/chart.js';
            s.async = true;
            s.onload = () => resolve(true);
            s.onerror = () => resolve(false);
            document.head.appendChild(s);
        };
        if ('requestIdleCallback' in window) {
            requestIdleCallback(start, {timeout: 3000});
        } else {
            setTimeout(start, 100);
        }
    });
    return chartJsReady;
}

const TAG_PRIORITY = {
    starred: 0,
    user_contributed: 1,
    archived: 2
};

function sortTags(tags = []) {
    return [...tags].sort((a, b) => (TAG_PRIORITY[a] ?? 999) - (TAG_PRIORITY[b] ?? 999));
}

function isArchivedTeardown(t) {
    return Array.isArray(t.tags) && t.tags.includes('archived');
}

function sortTeardowns(teardowns = []) {
    const withIndex = teardowns.map((t, i) => ({t, i}));
    withIndex.sort((a, b) => {
        const aArchived = isArchivedTeardown(a.t) ? 1 : 0;
        const bArchived = isArchivedTeardown(b.t) ? 1 : 0;
        if (aArchived !== bArchived) return aArchived - bArchived;
        return a.i - b.i;
    });
    return withIndex.map(x => x.t);
}

function tagBadge(tag) {
    switch (tag) {
        case 'starred':
            return '<span title="Featured Guide" class="inline-flex items-center gap-1 rounded-full bg-blue-900/40 text-blue-300 px-2 py-0.5 border border-blue-700/40 text-[10px] uppercase tracking-wide">Featured</span>';
        case 'user_contributed':
            return '<span title="Community-Contributed Guide" class="inline-flex items-center gap-1 rounded-full bg-yellow-900/30 text-yellow-300 px-2 py-0.5 border border-yellow-700/30 text-[10px] uppercase tracking-wide">Community</span>';
        case 'archived':
            return '<span title="Archived Guide" class="inline-flex items-center gap-1 rounded-full bg-amber-900/30 text-amber-300 px-2 py-0.5 border border-amber-700/30 text-[10px] uppercase tracking-wide">Archived</span>';
        default:
            return '';
    }
}

function tagBadgeTiny(tag) {
    switch (tag) {
        case 'starred':
            return '<span title="Featured Guide" class="inline-flex items-center rounded bg-blue-900/40 text-blue-300 px-1.5 py-0 border border-blue-700/40 text-[9px] uppercase tracking-wide">Featured</span>';
        case 'user_contributed':
            return '<span title="Community-Contributed Guide" class="inline-flex items-center rounded bg-yellow-900/30 text-yellow-300 px-1.5 py-0 border border-yellow-700/30 text-[9px] uppercase tracking-wide">Community</span>';
        case 'archived':
            return '<span title="Archived Guide" class="inline-flex items-center rounded bg-amber-900/30 text-amber-300 px-1.5 py-0 border border-amber-700/30 text-[9px] uppercase tracking-wide">Archived</span>';
        default:
            return '';
    }
}

function aggregateTeardownTags(teardownUrls = []) {
    const set = new Set();
    teardownUrls.forEach(td => (td.tags || []).forEach(t => set.add(t)));
    return sortTags([...set]);
}

function renderTeardownLinks(teardownUrls = []) {
    if (!teardownUrls || teardownUrls.length === 0) return '<span class="text-gray-500">—</span>';
    const sortedTeardowns = sortTeardowns(teardownUrls);
    return sortedTeardowns.map(td => {
        const tags = sortTags(td.tags || []);
        const badges = tags.map(tagBadge).filter(Boolean).join(' ');
        const archivedClass = tags.includes('archived') ? 'archived' : '';
        return `
            <a href="${td.url}" target="_blank" class="teardown-item ${archivedClass}">
                <span class="teardown-title">${td.title}</span>
                <span class="teardown-badges">${badges}</span>
            </a>
        `;
    }).join('');
}

async function loadData() {
    const tbody = document.getElementById('deviceTable');
    const chartError = document.getElementById('chartError');
    tbody.innerHTML = '<tr><td colspan="4" class="px-6 py-4 text-center"><span class="loading-spinner"></span> Loading...</td></tr>';
    chartError.classList.add('hidden');

    const cachedData = localStorage.getItem('devicesData');
    if (cachedData) {
        devicesData = JSON.parse(cachedData);
        renderTable();
        populateBrandFilter();
        try {
            if (typeof Chart !== 'undefined') {
                renderChart(devicesData);
            }
        } catch (e) {
            console.error('Chart rendering failed with cached data:', e);
            chartError.classList.remove('hidden');
        }
    }

    try {
        const res = await fetch('devices_with_scores.json');
        if (!res.ok) throw new Error('Failed to fetch data');
        devicesData = await res.json();
        localStorage.setItem('devicesData', JSON.stringify(devicesData));
        renderTable();
        populateBrandFilter();
        if (typeof Chart !== 'undefined') { renderChart(devicesData); }
    } catch (error) {
        console.error('Data fetch failed:', error);
        tbody.innerHTML = '<tr><td colspan="4" class="px-6 py-4 text-center text-rose-500">Failed to load data</td></tr>';
        chartError.classList.remove('hidden');
    }
}

function getFilteredData() {
    // Builds filtered dataset and also exposes the "last filtered result" for exports
    const searchValue = document.getElementById('searchInput').value.toLowerCase();
    const brandValue = document.getElementById('brandFilter').value;
    const scoreFilter = document.getElementById('scoreFilter')?.value || '';

    return devicesData.filter(d => {
        const matchesSearch = d.name.toLowerCase().includes(searchValue);
        const matchesBrand = !brandValue || d.brand === brandValue;
        const matchesScore = !scoreFilter || d.repairability_score === parseInt(scoreFilter);
        return matchesSearch && matchesBrand && matchesScore;
    });
}

function sortData(data) {
    const {key, direction} = currentSort;
    return data.sort((a, b) => {
        let A = a[key], B = b[key];
        if (key === 'teardown') {
            A = a.teardown_urls?.[0]?.url || '';
            B = b.teardown_urls?.[0]?.url || '';
        }
        if (key === 'repairability_score') {
            A = A ?? -1;
            B = B ?? -1;
        } else {
            A = (A || '').toString().toLowerCase();
            B = (B || '').toString().toLowerCase();
        }
        if (A < B) return direction === 'asc' ? -1 : 1;
        if (A > B) return direction === 'asc' ? 1 : -1;
        return 0;
    });
}

function populateTable(data) {
    const tbody = document.getElementById('deviceTable');
    tbody.innerHTML = '';
    if (data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="px-6 py-4 text-center text-gray-500">No devices found</td></tr>';
        return;
    }

    document.querySelectorAll('.teardown-dropdown').forEach(d => d.classList.remove('show'));

    data.forEach((d, index) => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-slate-800/70 transition';
        tr.tabIndex = 0;

        let teardownHtml = '—';
        if (d.teardown_urls && d.teardown_urls.length > 0) {
            // Badges direkt neben dem Toggle (aggregiert über alle Teardowns)
            const aggTags = aggregateTeardownTags(d.teardown_urls);
            const toggleBadges = aggTags.map(tagBadgeTiny).join(' ');
            const ddId = `td-dd-${index}`;
            teardownHtml = `
            <span class="teardown-toggle inline-flex items-center gap-2" data-index="${index}" role="button" tabindex="0" aria-expanded="false" aria-controls="${ddId}">
                <span>[Teardowns]<span class="teardown-count"> x${d.teardown_urls.length}</span></span>
                <span class="inline-flex flex-wrap gap-1">${toggleBadges}</span>
            </span>
            <div class="teardown-dropdown" id="${ddId}" data-index="${index}">
                ${renderTeardownLinks(d.teardown_urls)}
            </div>`;
        }

        tr.innerHTML = `
                <td class="px-6 py-4 font-medium">
                    <a href="${d.link}" target="_blank" class="text-cyan-400 underline">${d.name}</a>
                </td>
                <td class="px-6 py-4 font-medium teardown-cell">${teardownHtml}</td>
                <td class="px-6 py-4">${d.brand ?? '—'}</td>
                <td class="px-6 py-4">
                    <span class="px-3 py-1 rounded-full text-white text-sm font-semibold ${badge(d.repairability_score)}">
                        ${d.repairability_score ?? '—'}/10
                    </span>
                </td>`;
        tbody.appendChild(tr);
    });

    document.getElementById('deviceCount').textContent = `${data.length} Devices`;

    // Portal-based dropdown handling to avoid table scrollbars
    let teardownPortalEl = null;
    let teardownPortalOpenFor = null; // reference to toggle element
    function ensurePortal() {
        if (!teardownPortalEl) {
            teardownPortalEl = document.createElement('div');
            teardownPortalEl.className = 'teardown-portal';
            teardownPortalEl.setAttribute('role','menu');
            const root = document.getElementById('portal-root') || document.body;
            root.appendChild(teardownPortalEl);
        }
        return teardownPortalEl;
    }
    function positionPortalRelativeToToggle(toggle) {
        const portal = ensurePortal();
        const rect = toggle.getBoundingClientRect();
        const margin = 8;
        let top = rect.bottom + margin;
        let left = rect.left + 0; // align left edges
        // Temporarily show to measure width
        portal.style.visibility = 'hidden';
        portal.classList.add('show');
        const portalWidth = portal.offsetWidth || 320;
        const portalHeight = portal.offsetHeight || 200;
        // Clamp to viewport
        if (left + portalWidth + 8 > window.innerWidth) {
            left = Math.max(8, window.innerWidth - portalWidth - 8);
        }
        if (top + portalHeight + 8 > window.innerHeight) {
            const altTop = rect.top - margin - portalHeight;
            if (altTop > 8) top = altTop;
        }
        portal.style.top = `${Math.max(8, top)}px`;
        portal.style.left = `${left}px`;
        portal.style.visibility = '';
    }
    function openPortal(toggle, html) {
        // Close any existing
        closePortal();
        const portal = ensurePortal();
        portal.innerHTML = html;
        positionPortalRelativeToToggle(toggle);
        portal.classList.add('show');
        teardownPortalOpenFor = toggle;
        toggle.setAttribute('aria-expanded','true');
    }
    function closePortal() {
        const portal = ensurePortal();
        portal.classList.remove('show');
        portal.innerHTML = '';
        if (teardownPortalOpenFor) {
            teardownPortalOpenFor.setAttribute('aria-expanded','false');
            teardownPortalOpenFor = null;
        }
    }

    document.querySelectorAll('.teardown-toggle').forEach(toggle => {
        toggle.addEventListener('click', () => {
            const index = toggle.dataset.index;
            const dropdown = document.querySelector(`.teardown-dropdown[data-index="${index}"]`);
            const isOpen = teardownPortalOpenFor === toggle;
            if (isOpen) { closePortal(); }
            else { openPortal(toggle, dropdown?.innerHTML || ''); }
        });
        toggle.addEventListener('keydown', (e) => {
            const index = toggle.dataset.index;
            const dropdown = document.querySelector(`.teardown-dropdown[data-index="${index}"]`);
            const isOpen = teardownPortalOpenFor === toggle;
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (isOpen) { closePortal(); } else { openPortal(toggle, dropdown?.innerHTML || ''); } }
            if (e.key === 'Escape') { closePortal(); toggle.focus(); }
        });
    });

    function clickOutsideHandler(e) {
        const portal = document.querySelector('.teardown-portal');
        if (!portal) return;
        if (portal.classList.contains('show')) {
            if (!e.target.closest('.teardown-portal') && !e.target.closest('.teardown-toggle')) {
                closePortal();
            }
        }
    }
    document.addEventListener('click', clickOutsideHandler);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closePortal(); }});
    window.addEventListener('scroll', () => { if (teardownPortalOpenFor) positionPortalRelativeToToggle(teardownPortalOpenFor); }, {capture:true, passive:true});
    window.addEventListener('resize', () => { if (teardownPortalOpenFor) positionPortalRelativeToToggle(teardownPortalOpenFor); }, {passive:true});

    tbody.querySelectorAll('tr').forEach((row, index) => {
        row.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                row.querySelector('a')?.click();
            } else if (e.key === 'ArrowDown' && index < data.length - 1) {
                tbody.children[index + 1].focus();
            } else if (e.key === 'ArrowUp' && index > 0) {
                tbody.children[index - 1].focus();
            }
        });
    });
}

function badge(score) {
    if (score == null) return 'bg-gray-500';
    if (score >= 8) return 'bg-emerald-500';
    if (score >= 5) return 'bg-yellow-500 text-black';
    return 'bg-rose-500';
}

function populateBrandFilter() {
    const brands = [...new Set(devicesData.map(d => d.brand).filter(Boolean))].sort();
    const select = document.getElementById('brandFilter');
    select.innerHTML = '<option value="">All manufacturers</option>';
    brands.forEach(b => {
        const opt = document.createElement('option');
        opt.value = b;
        opt.textContent = b;
        select.appendChild(opt);
    });
}

function updateSortIndicators() {
    document.querySelectorAll('th[data-sort-key]').forEach(th => {
        const key = th.dataset.sortKey;
        const icon = th.querySelector('.sort-icon');
        if (key === currentSort.key) {
            icon.textContent = currentSort.direction === 'asc' ? '▲' : '▼';
            icon.classList.add('text-cyan-400');
            icon.style.transform = 'scale(1.1)';
            th.setAttribute('aria-sort', currentSort.direction === 'asc' ? 'ascending' : 'descending');
        } else {
            icon.textContent = '';
            icon.classList.remove('text-cyan-400');
            icon.style.transform = 'scale(1)';
            th.setAttribute('aria-sort', 'none');
        }
    });
}

function toggleSort(key) {
    if (currentSort.key === key) {
        currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
    } else {
        currentSort.key = key;
        currentSort.direction = 'asc';
    }
    renderTable();
}

function renderTable() {
    // Close any open teardown portal before re-rendering table to avoid orphaned overlays
    const existingPortal = document.querySelector('.teardown-portal');
    if (existingPortal) { existingPortal.remove(); }
    document.querySelectorAll('.teardown-toggle[aria-expanded="true"]').forEach(t => t.setAttribute('aria-expanded','false'));

    // Update active filter chips and save lastFiltered for exports
    let data = getFilteredData();
    data = sortData(data);
    populateTable(data);
    window.lastFiltered = data.slice();
    renderActiveFiltersChip();
    if (typeof Chart !== 'undefined') {
        try {
            renderChart(data);
        } catch (e) {
            console.error('Chart rendering failed:', e);
            document.getElementById('chartError').classList.remove('hidden');
        }
    }
    updateSortIndicators();
}

const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function renderChart(data) {
    const chartError = document.getElementById('chartError');
    chartError.classList.add('hidden');

    if (!data || data.length === 0) {
        chartError.textContent = 'No data available for chart';
        chartError.classList.remove('hidden');
        return;
    }

    const buckets = Array(11).fill(0);
    data.forEach(d => {
        const s = d.repairability_score;
        if (Number.isInteger(s) && s >= 0 && s <= 10) buckets[s]++;
    });

    const ctx = document.getElementById('repairabilityChart').getContext('2d');
    if (!ctx) {
        chartError.textContent = 'Chart canvas not found';
        chartError.classList.remove('hidden');
        return;
    }

    if (myChart) myChart.destroy();

    const gradient = ctx.createLinearGradient(0, 0, 0, 460);
    gradient.addColorStop(0, 'rgba(6,182,212,0.95)');
    gradient.addColorStop(1, 'rgba(139,92,246,0.95)');

    const total = data.length;
    myChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10'],
            datasets: [{
                data: buckets,
                backgroundColor: gradient,
                borderRadius: 14,
                barPercentage: 0.65,
                categoryPercentage: 0.8
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {display: false},
                tooltip: {
                    backgroundColor: '#0f172a',
                    titleColor: '#67e8f9',
                    bodyColor: '#fff',
                    cornerRadius: 10,
                    padding: 12,
                    borderColor: '#67e8f9',
                    borderWidth: 1,
                    callbacks: {
                        label: (ctx) => {
                            const count = ctx.raw ?? 0;
                            const pct = total ? ((count / total) * 100).toFixed(1) : '0.0';
                            return ` Count: ${count} (${pct}%)`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {display: false},
                    ticks: {color: '#94a3b8'},
                    title: {
                        display: true,
                        text: 'Repairability Score',
                        color: '#67e8f9',
                        font: {size: 14, weight: 'bold'}
                    }
                },
                y: {
                    beginAtZero: true,
                    ticks: {stepSize: 1, color: '#94a3b8'},
                    grid: {color: 'rgba(255,255,255,0.05)'},
                    title: {
                        display: true,
                        text: 'Device count',
                        color: '#67e8f9',
                        font: {size: 14, weight: 'bold'}
                    }
                }
            },
            animation: {duration: prefersReducedMotion ? 0 : 1200, easing: 'easeOutExpo'},
            onClick: (event, elements) => {
                if (elements.length) {
                    const score = elements[0].index;
                    document.getElementById('searchInput').value = '';
                    document.getElementById('brandFilter').value = '';
                    document.getElementById('scoreFilter')?.remove();
                    const scoreFilter = document.createElement('input');
                    scoreFilter.type = 'hidden';
                    scoreFilter.id = 'scoreFilter';
                    scoreFilter.value = score;
                    document.getElementById('deviceTable').parentElement.appendChild(scoreFilter);
                    renderTable();
                    stateToQuery();
                }
            }
        }
    });
}

const bg = document.getElementById('bgCanvas');
const g = bg.getContext('2d');
let P = [];

function resizeBG() {
    bg.width = innerWidth;
    bg.height = innerHeight;
    const isSmall = innerWidth < 640;
    const count = prefersReducedMotion ? 0 : (isSmall ? 28 : 60);
    P = Array.from({length: count}, () => ({
        x: Math.random() * bg.width,
        y: Math.random() * bg.height,
        r: Math.random() * 2 + 1.2,
        dx: (Math.random() - 0.5) * 0.45,
        dy: (Math.random() - 0.5) * 0.45
    }));
}

let bgRafId = null;
let animateBG = true;

function tickBG() {
    g.clearRect(0, 0, bg.width, bg.height);
    g.fillStyle = 'rgba(34,211,238,0.7)';
    g.strokeStyle = 'rgba(34,211,238,0.2)';
    g.lineWidth = 1;
    P.forEach(p => {
        g.beginPath();
        g.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        g.fill();
        p.x += p.dx;
        p.y += p.dy;
        if (p.x < 0 || p.x > bg.width) p.dx *= -1;
        if (p.y < 0 || p.y > bg.height) p.dy *= -1;
    });
    if (innerWidth >= 768) {
        P.forEach((p1, i) => {
            P.slice(i + 1).forEach(p2 => {
                const dist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
                if (dist < 100) {
                    g.beginPath();
                    g.moveTo(p1.x, p1.y);
                    g.lineTo(p2.x, p2.y);
                    g.stroke();
                }
            });
        });
    }
    if (animateBG) {
        bgRafId = requestAnimationFrame(tickBG);
    }
}

addEventListener('resize', resizeBG, {passive:true});
resizeBG();

function startBG() {
    if (!animateBG) return;
    if (bgRafId == null) {
        animateBG = true;
        bgRafId = requestAnimationFrame(tickBG);
    }
}
function stopBG() {
    animateBG = false;
    if (bgRafId != null) {
        cancelAnimationFrame(bgRafId);
        bgRafId = null;
    }
}

document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopBG(); else if (!prefersReducedMotion) { animateBG = true; startBG(); }
});

if (!prefersReducedMotion) {
    animateBG = true;
    startBG();
}

async function updateFileAge() {
    try {
        const res = await fetch('devices_with_scores.json', {method: 'HEAD'});
        const lastModified = res.headers.get('Last-Modified');
        if (lastModified) {
            const fileDate = new Date(lastModified);
            const now = new Date();
            const diffMs = now - fileDate;
            const diffMin = Math.floor(diffMs / 60000);
            const diffH = Math.floor(diffMin / 60);
            const diffD = Math.floor(diffH / 24);
            let ageStr = '';
            if (diffD > 0) ageStr = `${diffD} day(s)`;
            else if (diffH > 0) ageStr = `${diffH} hour(s)`;
            else if (diffMin > 0) ageStr = `${diffMin} minute(s)`;
            else ageStr = 'less than 1 minute';
            const fa = document.getElementById('fileAge');
            const fullTitle = `Last datasource update: ${ageStr} ago (${fileDate.toLocaleString()})`;
            lastUpdateFullTitle = fullTitle;
            fa.textContent = `Last datasource update: ${ageStr} ago`;
            fa.setAttribute('title', fullTitle);
            const footerMeta = document.querySelector('footer .container .text-center');
            if (footerMeta) { footerMeta.setAttribute('title', fullTitle); }
        } else {
            document.getElementById('fileAge').textContent = 'File age not available';
            lastUpdateFullTitle = 'Last datasource update: not available';
        }
    } catch (e) {
        document.getElementById('fileAge').textContent = 'File age not available';
        lastUpdateFullTitle = 'Last datasource update: not available';
    }
}

function debounce(fn, delay = 250) {
    let t;
    return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn.apply(null, args), delay);
    };
}

function stateToQuery() {
    // reflect score filter chip too
    const params = new URLSearchParams(location.search);
    params.set('q', document.getElementById('searchInput').value || '');
    params.set('brand', document.getElementById('brandFilter').value || '');
    params.set('sort', `${currentSort.key}:${currentSort.direction}`);
    const scoreHidden = document.getElementById('scoreFilter')?.value || '';
    params.set('score', scoreHidden);
    // Clean empties
    ['q','brand','score'].forEach(k => { if (!params.get(k)) params.delete(k); });
    const qs = params.toString();
    history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
}

function queryToState() {
    const params = new URLSearchParams(location.search);
    const q = params.get('q') || '';
    const brand = params.get('brand') || '';
    const sort = params.get('sort') || '';
    const score = params.get('score') || '';
    document.getElementById('searchInput').value = q;
    document.getElementById('brandFilter').value = brand;
    if (score) {
        const scoreFilter = document.createElement('input');
        scoreFilter.type = 'hidden';
        scoreFilter.id = 'scoreFilter';
        scoreFilter.value = score;
        document.getElementById('deviceTable').parentElement.appendChild(scoreFilter);
    }
    if (sort.includes(':')) {
        const [key, dir] = sort.split(':');
        if (key) currentSort.key = key;
        if (dir === 'asc' || dir === 'desc') currentSort.direction = dir;
    }
}

function notifyAction(msg) {
    const live = document.getElementById('actionLive');
    if (live) { live.textContent = msg; }
}

function renderActiveFiltersChip() {
    const wrap = document.getElementById('activeFilters');
    if (!wrap) return;
    const score = document.getElementById('scoreFilter')?.value;
    wrap.innerHTML = '';
    if (score !== undefined && score !== null && score !== '') {
        wrap.classList.add('show');
        const chip = document.createElement('div');
        chip.className = 'filter-chip';
        chip.innerHTML = `<span>Score: ${score}</span><button type="button" aria-label="Clear score filter">✕</button>`;
        chip.querySelector('button').addEventListener('click', () => {
            document.getElementById('scoreFilter')?.remove();
            renderTable();
            stateToQuery();
            notifyAction('Score filter cleared');
        });
        wrap.appendChild(chip);
    } else {
        wrap.classList.remove('show');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Load Chart.js during an idle period to improve FCP/TBT
    loadChartJsIdle().then(() => {
        if (devicesData && devicesData.length) {
            try { renderChart(window.lastFiltered || devicesData); } catch (_) {}
        }
    });
    updateFileAge();
    queryToState();
    loadData();
    const debouncedRender = debounce(() => { renderTable(); stateToQuery(); }, 300);
    document.getElementById('searchInput').addEventListener('input', debouncedRender);
    document.getElementById('brandFilter').addEventListener('change', () => { renderTable(); stateToQuery(); });

    // Mobile info icon tooltip
    (function setupMobileInfo() {
        const btn = document.getElementById('fileAgeInfoBtn');
        if (!btn) return;
        // Hide button on wider screens via CSS; ensure ARIA
        btn.setAttribute('aria-haspopup', 'dialog');
        btn.setAttribute('aria-expanded', 'false');
        let tip = null;
        function ensureTip() {
            if (tip) return tip;
            tip = document.createElement('div');
            tip.className = 'mobile-info-tooltip';
            tip.setAttribute('role','dialog');
            tip.setAttribute('aria-modal','false');
            document.body.appendChild(tip);
            return tip;
        }
        function positionTip() {
            const t = ensureTip();
            t.textContent = lastUpdateFullTitle || (document.getElementById('fileAge')?.getAttribute('title') || 'Last datasource update: not available');
            const rect = btn.getBoundingClientRect();
            const margin = 8;
            let top = rect.top - t.offsetHeight - margin;
            if (top < 8) top = rect.bottom + margin;
            let left = Math.min(Math.max(8, rect.left), window.innerWidth - t.offsetWidth - 8);
            t.style.top = `${Math.max(8, top)}px`;
            t.style.left = `${left}px`;
        }
        function openTip() {
            const t = ensureTip();
            t.classList.add('show');
            positionTip();
            btn.setAttribute('aria-expanded','true');
        }
        function closeTip() {
            if (!tip) return;
            tip.classList.remove('show');
            btn.setAttribute('aria-expanded','false');
        }
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (tip && tip.classList.contains('show')) closeTip(); else openTip();
        });
        document.addEventListener('click', (e) => {
            if (tip && tip.classList.contains('show')) {
                if (!e.target.closest('.mobile-info-tooltip') && e.target !== btn) closeTip();
            }
        });
        window.addEventListener('resize', () => { if (tip && tip.classList.contains('show')) positionTip(); }, {passive:true});
    })();

    // Density toggle
    const densityBtn = document.getElementById('densityToggle');
    function applyDensityFromStorage() {
        const mode = localStorage.getItem('density') || 'compact';
        const body = document.body;
        if (mode === 'compact') { body.classList.add('compact-rows'); densityBtn.textContent = 'Density: Compact'; }
        else { body.classList.remove('compact-rows'); densityBtn.textContent = 'Density: Comfortable'; }
    }
    densityBtn.addEventListener('click', () => {
        const curr = localStorage.getItem('density') || 'comfortable';
        const next = curr === 'compact' ? 'comfortable' : 'compact';
        localStorage.setItem('density', next);
        applyDensityFromStorage();
        notifyAction(`Density set to ${next}`);
    });
    applyDensityFromStorage();

    // Copy link
    document.getElementById('copyLink').addEventListener('click', async () => {
        stateToQuery();
        try {
            await navigator.clipboard.writeText(location.href);
            notifyAction('Link copied to clipboard');
        } catch (e) {
            notifyAction('Failed to copy link');
        }
    });

    // Export CSV
    function toCsvRow(fields) { return fields.map(v => '"' + String(v ?? '').replaceAll('"','""') + '"').join(','); }
    document.getElementById('exportCsv').addEventListener('click', () => {
        const rows = window.lastFiltered || getFilteredData();
        const header = ['name','brand','repairability_score','link'];
        const lines = [toCsvRow(header)];
        rows.forEach(d => lines.push(toCsvRow([d.name, d.brand ?? '', d.repairability_score ?? '', d.link ?? ''])));
        const blob = new Blob([lines.join('\r\n')], {type:'text/csv;charset=utf-8;'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'ifixit_devices.csv';
        a.click();
        URL.revokeObjectURL(a.href);
        notifyAction('CSV exported');
    });

    // Export JSON
    document.getElementById('exportJson').addEventListener('click', () => {
        const rows = window.lastFiltered || getFilteredData();
        const blob = new Blob([JSON.stringify(rows, null, 2)], {type:'application/json'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'ifixit_devices.json';
        a.click();
        URL.revokeObjectURL(a.href);
        notifyAction('JSON exported');
    });

    document.getElementById('resetFilters').addEventListener('click', () => {
        document.getElementById('searchInput').value = '';
        document.getElementById('brandFilter').value = '';
        document.getElementById('scoreFilter')?.remove();
        currentSort = {key: 'name', direction: 'asc'};
        stateToQuery();
        loadData();
    });
    document.querySelectorAll('th[data-sort-key]').forEach(th => {
        th.addEventListener('click', () => { toggleSort(th.dataset.sortKey); stateToQuery(); });
        th.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSort(th.dataset.sortKey); stateToQuery(); }
        });
    });
});