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
    } catch (_) { /* no-op */
    }
});

let devicesData = [];
const MAX_COMPARE = 5;
let selectedForCompare = new Set();
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

let chartModuleReady = null;

function loadChartModuleIdle() {
    if (window.ChartModule && typeof window.ChartModule.renderChart === 'function') return Promise.resolve(true);
    if (chartModuleReady) return chartModuleReady;
    chartModuleReady = new Promise(async (resolve) => {
        // Ensure Chart.js is loaded first
        try {
            await loadChartJsIdle();
        } catch (_) {
        }
        const start = () => {
            if (window.ChartModule && typeof window.ChartModule.renderChart === 'function') {
                resolve(true);
                return;
            }
            const s = document.createElement('script');
            s.src = 'chart-module.js';
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
    return chartModuleReady;
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
        const difficulty = (td.difficulty || '').toString().trim();
        const diffMap = {
            'very difficult': 'chip-vd',
            'difficult': 'chip-d',
            'moderate': 'chip-m',
            'easy': 'chip-e',
            'very easy': 'chip-ve'
        };
        const diffClass = diffMap[difficulty.toLowerCase()] || '';
        const difficultyHtml = difficulty ? `<span class="teardown-difficulty chip ${diffClass}" title="${difficulty}">${difficulty}</span>` : '';
        const ariaLabel = `${td.title}${difficulty ? ` - Difficulty: ${difficulty}` : ''}`;
        return `
            <a href="${td.url}" target="_blank" class="teardown-item ${archivedClass}" aria-label="${ariaLabel}">
                <span class="teardown-title">${td.title}</span>
                ${difficultyHtml}
                <span class="teardown-badges">${badges}</span>
            </a>
        `;
    }).join('');
}

async function loadData() {
    const tbody = document.getElementById('deviceTable');
    const chartError = document.getElementById('chartError');
    // Polished skeleton placeholder rows
    tbody.innerHTML = Array.from({length: 8}).map(() => `
      <tr class="skeleton-row">
        <td class="px-4 py-4"><span class="skeleton-box sm"></span></td>
        <td class="px-6 py-4"><span class="skeleton-box lg"></span></td>
        <td class="px-6 py-4"><span class="skeleton-box md"></span></td>
        <td class="px-6 py-4"><span class="skeleton-box md"></span></td>
        <td class="px-6 py-4"><span class="skeleton-box sm"></span></td>
      </tr>
    `).join('');
    chartError.classList.add('hidden');

    const cachedData = localStorage.getItem('devicesData');
    if (cachedData) {
        devicesData = JSON.parse(cachedData);
        renderTable();
        populateBrandFilter();
        try {
            loadChartModuleIdle().then(() => {
                if (window.ChartModule && typeof window.ChartModule.renderChart === 'function') {
                    window.ChartModule.renderChart(devicesData);
                }
            });
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
        loadChartModuleIdle().then(() => {
            if (window.ChartModule && typeof window.ChartModule.renderChart === 'function') {
                window.ChartModule.renderChart(devicesData);
            }
        });
    } catch (error) {
        console.error('Data fetch failed:', error);
        tbody.innerHTML = '<tr><td colspan="5" class="px-6 py-4 text-center text-rose-500">Failed to load data</td></tr>';
        chartError.classList.remove('hidden');
    }
}

function getFilteredData() {
    // Builds filtered dataset and also exposes the "last filtered result" for exports
    const searchValue = document.getElementById('searchInput').value.toLowerCase();
    const brandValue = document.getElementById('brandFilter').value;
    const scoreFilter = document.getElementById('scoreFilter')?.value || '';
    const includeNoScore = document.getElementById('includeNoScore')?.checked === true;

    return devicesData.filter(d => {
        const matchesSearch = d.name.toLowerCase().includes(searchValue);
        const matchesBrand = !brandValue || d.brand === brandValue;
        const matchesScore = !scoreFilter || d.repairability_score === parseInt(scoreFilter);
        const hasScoreOk = includeNoScore ? true : (d.repairability_score != null);
        return matchesSearch && matchesBrand && matchesScore && hasScoreOk;
    });
}

function sortData(data) {
    const {key, direction} = currentSort;
    return data.sort((a, b) => {
        let A = a[key], B = b[key];
        if (key === 'teardown') {
            // Sort by number of teardowns (teardown_urls length)
            A = Array.isArray(a.teardown_urls) ? a.teardown_urls.length : 0;
            B = Array.isArray(b.teardown_urls) ? b.teardown_urls.length : 0;
        }
        if (key === 'repairability_score' || key === 'teardown') {
            // Numeric comparison for score and teardown count
            A = (A ?? -1);
            B = (B ?? -1);
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
    const drawer = document.getElementById('compareDrawer');
    const countEl = document.getElementById('compareCount');

    function refreshDrawer(warn = false) {
        const n = selectedForCompare.size;
        if (countEl) countEl.textContent = `${n}/${MAX_COMPARE} selected`;
        if (drawer) {
            drawer.classList.toggle('hidden', n === 0);
            if (warn) {
                drawer.classList.add('warn');
                setTimeout(() => drawer.classList.remove('warn'), 800);
            }
        }
        const btn = document.getElementById('compareBtn');
        if (btn) btn.disabled = n < 2;
    }

    const tbody = document.getElementById('deviceTable');
    tbody.innerHTML = '';
    if (data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="px-6 py-4 text-center text-gray-500">No devices found</td></tr>';
        return;
    }

    document.querySelectorAll('.teardown-dropdown').forEach(d => d.classList.remove('show'));

    data.forEach((d, index) => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-slate-800/70 transition';
        tr.tabIndex = 0;
        const selId = `${d.name}__${d.brand ?? ''}`;

        let teardownHtml = '—';
        if (d.teardown_urls && d.teardown_urls.length > 0) {
            // Badges direkt neben dem Toggle (aggregiert über alle Teardowns)
            const aggTags = aggregateTeardownTags(d.teardown_urls);
            const toggleBadges = aggTags.map(tagBadgeTiny).join(' ');
            const ddId = `td-dd-${index}`;
            teardownHtml = `
            <span class="teardown-toggle inline-flex items-center gap-2" data-index="${index}" role="button" tabindex="0" aria-expanded="false" aria-controls="${ddId}">
                <span>Teardowns<span class="teardown-count"> (${d.teardown_urls.length})</span></span>
                <span class="inline-flex flex-wrap gap-1">${toggleBadges}</span>
            </span>
            <div class="teardown-dropdown" id="${ddId}" data-index="${index}">
                ${renderTeardownLinks(d.teardown_urls)}
            </div>`;
        }

        tr.innerHTML = `
                <td class="px-4 py-4">
                    <input type="checkbox" class="cmp" aria-label="Select ${d.name} for comparison" ${selectedForCompare.has(selId) ? 'checked' : ''}>
                </td>
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
        // wire checkbox
        setTimeout(() => {
            const cb = tr.querySelector('input.cmp');
            if (cb) {
                cb.addEventListener('change', () => {
                    if (cb.checked) {
                        if (selectedForCompare.size >= MAX_COMPARE) {
                            // Revert and warn
                            cb.checked = false;
                            notifyAction(`You can compare up to ${MAX_COMPARE} devices. Deselect one to add another.`);
                            // Visible inline warning in drawer
                            try {
                                const drawer = document.getElementById('compareDrawer');
                                if (drawer) {
                                    let msg = drawer.querySelector('#compareMsg');
                                    if (!msg) {
                                        msg = document.createElement('span');
                                        msg.id = 'compareMsg';
                                        msg.className = 'msg';
                                        const spacer = drawer.querySelector('.spacer');
                                        if (spacer && spacer.parentElement) {
                                            spacer.parentElement.insertBefore(msg, spacer);
                                        } else {
                                            drawer.appendChild(msg);
                                        }
                                    }
                                    msg.textContent = `You can compare up to ${MAX_COMPARE} devices.`;
                                    msg.classList.add('show');
                                    setTimeout(() => msg && msg.classList && msg.classList.remove('show'), 2500);
                                }
                            } catch (_) {
                            }
                            refreshDrawer(true);
                            return;
                        }
                        selectedForCompare.add(selId);
                    } else {
                        selectedForCompare.delete(selId);
                    }
                    refreshDrawer();
                });
            }
        }, 0);
        tbody.appendChild(tr);
    });

    refreshDrawer();
    document.getElementById('deviceCount').textContent = `${data.length} Devices`;

    // Portal-based dropdown handling to avoid table scrollbars
    let teardownPortalEl = null;
    let teardownPortalOpenFor = null; // reference to toggle element
    function ensurePortal() {
        if (!teardownPortalEl) {
            teardownPortalEl = document.createElement('div');
            teardownPortalEl.className = 'teardown-portal';
            teardownPortalEl.setAttribute('role', 'menu');
            const root = document.getElementById('portal-root') || document.body;
            root.appendChild(teardownPortalEl);
        }
        return teardownPortalEl;
    }

    function positionPortalRelativeToToggle(toggle) {
        const portal = ensurePortal();
        const rect = toggle.getBoundingClientRect();
        const margin = 8;
        // Defer show + measurement to next frames to avoid forced reflow
        portal.style.visibility = 'hidden';
        requestAnimationFrame(() => {
            // Show offscreen first to get accurate size
            portal.classList.add('show');
            portal.style.top = '-9999px';
            portal.style.left = '0px';
            requestAnimationFrame(() => {
                const portalWidth = portal.offsetWidth || 320;
                const portalHeight = portal.offsetHeight || 200;
                let top = rect.bottom + margin;
                let left = rect.left; // align left edges
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
            });
        });
    }

    function openPortal(toggle, html) {
        // Close any existing
        closePortal();
        const portal = ensurePortal();
        portal.innerHTML = html;
        positionPortalRelativeToToggle(toggle);
        portal.classList.add('show');
        teardownPortalOpenFor = toggle;
        toggle.setAttribute('aria-expanded', 'true');
    }

    function closePortal() {
        const portal = ensurePortal();
        portal.classList.remove('show');
        portal.innerHTML = '';
        if (teardownPortalOpenFor) {
            teardownPortalOpenFor.setAttribute('aria-expanded', 'false');
            teardownPortalOpenFor = null;
        }
    }

    document.querySelectorAll('.teardown-toggle').forEach(toggle => {
        toggle.addEventListener('click', () => {
            const index = toggle.dataset.index;
            const dropdown = document.querySelector(`.teardown-dropdown[data-index="${index}"]`);
            const isOpen = teardownPortalOpenFor === toggle;
            if (isOpen) {
                closePortal();
            } else {
                openPortal(toggle, dropdown?.innerHTML || '');
            }
        });
        toggle.addEventListener('keydown', (e) => {
            const index = toggle.dataset.index;
            const dropdown = document.querySelector(`.teardown-dropdown[data-index="${index}"]`);
            const isOpen = teardownPortalOpenFor === toggle;
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                if (isOpen) {
                    closePortal();
                } else {
                    openPortal(toggle, dropdown?.innerHTML || '');
                }
            }
            if (e.key === 'Escape') {
                closePortal();
                toggle.focus();
            }
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
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closePortal();
        }
    });
    window.addEventListener('scroll', () => {
        if (teardownPortalOpenFor) positionPortalRelativeToToggle(teardownPortalOpenFor);
    }, {capture: true, passive: true});
    window.addEventListener('resize', () => {
        if (teardownPortalOpenFor) positionPortalRelativeToToggle(teardownPortalOpenFor);
    }, {passive: true});

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
    const dirLabel = currentSort.direction === 'asc' ? 'ascending' : 'descending';
    const keyLabel = key === 'repairability_score' ? 'Score' :
        key === 'brand' ? 'Manufacturer' :
            key === 'teardown' ? 'Teardown' : 'Device';
    notifyAction(`Sorted by ${keyLabel}, ${dirLabel}. ${window.lastFiltered?.length ?? ''} results.`);
}

function injectStructuredData(list) {
    try {
        const max = 25;
        const items = (list || []).slice(0, max).map((d, i) => ({
            '@type': 'ListItem',
            position: i + 1,
            url: d.link || location.href,
            item: {
                '@type': 'Product',
                name: d.name,
                brand: d.brand ? {'@type': 'Brand', name: d.brand} : undefined,
                url: d.link || undefined,
                aggregateRating: Number.isFinite(d.repairability_score) ? {
                    '@type': 'AggregateRating',
                    ratingValue: String(d.repairability_score),
                    ratingCount: 1,
                    bestRating: '10',
                    worstRating: '0'
                } : undefined
            }
        }));
        const json = {
            '@context': 'https://schema.org',
            '@type': 'ItemList',
            itemListElement: items
        };
        let el = document.getElementById('jsonLd');
        if (!el) {
            el = document.createElement('script');
            el.type = 'application/ld+json';
            el.id = 'jsonLd';
            document.head.appendChild(el);
        }
        el.textContent = JSON.stringify(json);
    } catch (_) {
    }
}

function renderTable(options = {}) {
    const {skipChart = false} = options;
    // Close any open teardown portal before re-rendering table to avoid orphaned overlays
    const existingPortal = document.querySelector('.teardown-portal');
    if (existingPortal) {
        existingPortal.remove();
    }
    document.querySelectorAll('.teardown-toggle[aria-expanded="true"]').forEach(t => t.setAttribute('aria-expanded', 'false'));

    // Update active filter chips and save lastFiltered for exports
    let data = getFilteredData();
    data = sortData(data);
    populateTable(data);
    window.lastFiltered = data.slice();
    renderActiveFiltersChip();
    injectStructuredData(window.lastFiltered);
    if (!skipChart) {
        loadChartModuleIdle().then(() => {
            try {
                if (window.ChartModule && typeof window.ChartModule.renderChart === 'function') {
                    window.ChartModule.renderChart(data);
                }
            } catch (e) {
                console.error('Chart rendering failed:', e);
                document.getElementById('chartError').classList.remove('hidden');
            }
        });
    }
    updateSortIndicators();
}

const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// THEME MANAGEMENT
function getSystemPrefersDark() {
    try {
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    } catch (_) {
        return false;
    }
}

function getStoredTheme() {
    // Only explicit user choice 'light' | 'dark' is stored. If null, follow system.
    const v = localStorage.getItem('theme');
    return (v === 'light' || v === 'dark') ? v : null;
}

function computeActiveTheme() {
    const pref = getStoredTheme();
    if (pref === 'light') return 'light';
    if (pref === 'dark') return 'dark';
    // No explicit preference: follow OS
    return getSystemPrefersDark() ? 'dark' : 'light';
}

function applyTheme() {
    const active = computeActiveTheme();
    document.body.classList.toggle('theme-light', active === 'light');
    document.body.classList.toggle('theme-dark', active === 'dark');
    const btn = document.getElementById('themeToggle');
    if (btn) {
        const stored = getStoredTheme();
        btn.setAttribute('data-mode', active);
        btn.setAttribute('aria-checked', active === 'dark' ? 'true' : 'false');
        const label = 'Toggle theme: ' + active + (stored ? '' : ' (following system)');
        btn.setAttribute('aria-label', label);
        btn.setAttribute('title', stored ? 'Toggle color theme' : 'Following system; click to choose');
    }
    // Re-render chart with new palette if present
    try {
        const data = window.lastFiltered || devicesData || [];
        if (data.length) {
            loadChartModuleIdle().then(() => {
                if (window.ChartModule && typeof window.ChartModule.renderChart === 'function') {
                    window.ChartModule.renderChart(data);
                }
            });
        }
    } catch (_) {
    }
}

function renderChart(data) {
    // Lightweight shim to preserve API; defers to lazy-loaded chart module
    loadChartModuleIdle().then(() => {
        if (window.ChartModule && typeof window.ChartModule.renderChart === 'function') {
            try {
                window.ChartModule.renderChart(data);
            } catch (e) {
                console.error('Chart rendering failed:', e);
                const chartError = document.getElementById('chartError');
                if (chartError) chartError.classList.remove('hidden');
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

addEventListener('resize', resizeBG, {passive: true});
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
    if (document.hidden) stopBG(); else if (!prefersReducedMotion) {
        animateBG = true;
        startBG();
    }
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
            if (footerMeta) {
                footerMeta.setAttribute('title', fullTitle);
            }
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
    const includeNoScore = document.getElementById('includeNoScore')?.checked ? '1' : '';
    params.set('noscore', includeNoScore);
    // Clean empties
    ['q', 'brand', 'score', 'noscore'].forEach(k => {
        if (!params.get(k)) params.delete(k);
    });
    const qs = params.toString();
    history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
}

function queryToState() {
    const params = new URLSearchParams(location.search);
    const q = params.get('q') || '';
    const brand = params.get('brand') || '';
    const sort = params.get('sort') || '';
    const score = params.get('score') || '';
    const noscore = params.get('noscore') === '1';
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
    let cb = document.getElementById('includeNoScore');
    if (!cb) {
        cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.id = 'includeNoScore';
        cb.className = 'sr-only';
        document.body.appendChild(cb);
    }
    cb.checked = !!noscore;
}

function notifyAction(msg) {
    const live = document.getElementById('actionLive');
    if (live) {
        live.textContent = msg;
    }
}

function renderActiveFiltersChip() {
    const wrap = document.getElementById('activeFilters');
    if (!wrap) return;
    const score = document.getElementById('scoreFilter')?.value;
    wrap.innerHTML = '';
    let any = false;
    if (score !== undefined && score !== null && score !== '') {
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
        any = true;
    }
    const includeNo = document.getElementById('includeNoScore')?.checked === true;
    if (includeNo) {
        // Per request, do not show a chip for "All devices" anymore.
        // Keep 'any' unchanged; we no longer toggle based on includeNo.
    }
    wrap.classList.toggle('show', any);
}

function renderRubricTable() {
    const toggleRubricTableBtn = document.getElementById('toggleRubricTable');
    const rubricTableContainer = document.getElementById('rubricTableContainer');
    const rubricTable = document.getElementById('rubricTable');
    const rubricError = document.getElementById('rubricError');
    const modal = document.getElementById('rubricModal');
    const modalContent = document.getElementById('modalContent');

    toggleRubricTableBtn.addEventListener('click', () => {
        const isExpanded = toggleRubricTableBtn.getAttribute('aria-expanded') === 'true';
        toggleRubricTableBtn.setAttribute('aria-expanded', !isExpanded);
        toggleRubricTableBtn.textContent = isExpanded ? 'Show Rubric' : 'Hide Rubric';
        rubricTableContainer.classList.toggle('hidden');
    });

    fetch('rubric.json')
        .then(response => {
            if (!response.ok) throw new Error(`Failed to fetch rubric.json: ${response.status}`);
            return response.json();
        })
        .then(data => {
            console.log('Rubric data loaded:', data); // Debug: Confirm JSON data
            const thead = rubricTableContainer.querySelector('thead tr');
            data.versions.forEach(version => {
                const th = document.createElement('th');
                th.scope = 'col';
                th.className = 'px-2 py-1 text-center text-xs font-semibold text-gray-300 uppercase';
                th.innerHTML = `
                    ${version}
                    <button class="ml-2 p-2 bg-cyan-600 text-white rounded-lg hover:bg-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-400 transition border border-cyan-400 font-mono text-sm" aria-label="Show details for version ${version}">
                        Info
                    </button>`;
                const button = th.querySelector('button');
                button.addEventListener('click', () => {
                    console.log(`Opening modal for version ${version}`); // Debug: Confirm click
                    modalContent.innerHTML = `
                        <h3 class="text-base font-semibold text-cyan-300 font-mono">Version ${version}</h3>
                        <div class="space-y-3">
                            <div>
                                <h4 class="text-xs font-semibold text-gray-300 uppercase">Criteria</h4>
                                <div class="grid gap-2">
                                    ${data.criteria.map(c => `
                                        <div class="bg-slate-700/50 p-2 rounded-lg">
                                            <p><strong class="text-cyan-400">${c.name}</strong></p>
                                            <p>Included: ${c.included[data.versions.indexOf(version)] ? 'Yes' : 'No'}</p>
                                            <p>Weight: ${c.weights[version] || 'N/A'}</p>
                                            <p>Notes: ${c.notes[version] || 'N/A'}</p>
                                        </div>
                                    `).join('')}
                                </div>
                            </div>
                            <div>
                                <h4 class="text-xs font-semibold text-gray-300 uppercase">Factors Not Considered</h4>
                                <ul class="list-disc pl-4 text-xs text-gray-100">
                                    ${data.factors_not_considered.find(f => f.version === version)?.items.map(item => `<li>${item}</li>`).join('') || '<li>None</li>'}
                                </ul>
                            </div>
                            <div>
                                <h4 class="text-xs font-semibold text-gray-300 uppercase">Revisions</h4>
                                <ul class="list-disc pl-4 text-xs text-gray-100">
                                    ${data.revisions.find(r => r.version === version)?.items.map(item => `<li>${item}</li>`).join('') || '<li>None</li>'}
                                </ul>
                            </div>
                        </div>`;
                    modal.showModal();
                });
                thead.appendChild(th);
            });

            data.criteria.forEach(criterion => {
                const tr = document.createElement('tr');
                tr.className = 'divide-x divide-slate-700';
                const tdName = document.createElement('td');
                tdName.className = 'px-2 py-1 text-left text-xs text-gray-100';
                tdName.textContent = criterion.name;
                tr.appendChild(tdName);
                criterion.included.forEach(included => {
                    const td = document.createElement('td');
                    td.className = 'px-2 py-1 text-center text-xs';
                    td.textContent = included ? '✓' : '';
                    tr.appendChild(td);
                });
                rubricTable.appendChild(tr);
            });
        })
        .catch(error => {
            console.error('Error loading rubric data:', error);
            rubricError.classList.remove('hidden');
        });

    modal.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            modal.close();
        }
        const focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.key === 'Tab') {
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    applyTheme();
    const mm = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
    if (mm && mm.addEventListener) {
        // Only react to system changes when no explicit user choice is stored
        mm.addEventListener('change', () => {
            if (!getStoredTheme()) applyTheme();
        });
    }
    const themeBtn = document.getElementById('themeToggle');
    if (themeBtn) {
        themeBtn.addEventListener('click', () => {
            const curr = getStoredTheme();
            // Toggle only between light and dark; clicking sets explicit preference
            const next = curr === 'light' ? 'dark' : 'light';
            localStorage.setItem('theme', next);
            applyTheme();
            notifyAction(`Theme set to ${next}`);
        });
        // Long-press or right-click could reset to system in future if desired; not implemented now.
    }
    // Load Chart + chart module during idle; render only when we have data
    loadChartModuleIdle().then(() => {
        const data = window.lastFiltered || devicesData;
        if (data && data.length && window.ChartModule && typeof window.ChartModule.renderChart === 'function') {
            try {
                window.ChartModule.renderChart(data);
            } catch (_) {
            }
        }
    });
    updateFileAge();
    queryToState();
    loadData();
    const debouncedRender = debounce(() => {
        renderTable();
        stateToQuery();
        const q = document.getElementById('searchInput').value.trim();
        if (q) {
            notifyAction(`Search applied: “${q}”. ${window.lastFiltered?.length ?? ''} results.`);
        } else {
            notifyAction(`${window.lastFiltered?.length ?? ''} results.`);
        }
    }, 300);
    document.getElementById('searchInput').addEventListener('input', debouncedRender);
    document.getElementById('brandFilter').addEventListener('change', () => {
        renderTable();
        stateToQuery();
        const brand = document.getElementById('brandFilter').value || 'All manufacturers';
        notifyAction(`Filtered by ${brand}. ${window.lastFiltered?.length ?? ''} results.`);
    });

    renderRubricTable();

    // Segmented control wiring: Scored only | All devices
    function setSegmentState(includeNo) {
        // ensure hidden state element exists
        let cb = document.getElementById('includeNoScore');
        if (!cb) {
            cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.id = 'includeNoScore';
            cb.className = 'sr-only';
            document.body.appendChild(cb);
        }
        cb.checked = !!includeNo;
        const btnScored = document.getElementById('segScored');
        const btnAll = document.getElementById('segAll');
        if (btnScored && btnAll) {
            btnScored.classList.toggle('is-active', !includeNo);
            btnAll.classList.toggle('is-active', includeNo);
            btnScored.setAttribute('aria-pressed', (!includeNo).toString());
            btnAll.setAttribute('aria-pressed', (!!includeNo).toString());
        }
    }

    const btnScored = document.getElementById('segScored');
    const btnAll = document.getElementById('segAll');
    if (btnScored && btnAll) {
        // initialize from URL/hidden state post queryToState
        const initial = document.getElementById('includeNoScore')?.checked === true;
        setSegmentState(initial);
        btnScored.addEventListener('click', () => {
            setSegmentState(false);
            renderTable({skipChart: true});
            stateToQuery();
            notifyAction('Excluding devices without score');
        });
        btnAll.addEventListener('click', () => {
            setSegmentState(true);
            renderTable({skipChart: true});
            stateToQuery();
            notifyAction('Including devices without score');
        });
    }

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
            tip.setAttribute('role', 'dialog');
            tip.setAttribute('aria-modal', 'false');
            document.body.appendChild(tip);
            return tip;
        }

        function positionTip() {
            const t = ensureTip();
            t.textContent = lastUpdateFullTitle || (document.getElementById('fileAge')?.getAttribute('title') || 'Last datasource update: not available');
            // Two-phase show and measure to avoid forced reflow
            t.style.visibility = 'hidden';
            requestAnimationFrame(() => {
                t.classList.add('show');
                t.style.top = '-9999px';
                t.style.left = '0px';
                requestAnimationFrame(() => {
                    const rect = btn.getBoundingClientRect();
                    const margin = 8;
                    let top = rect.top - t.offsetHeight - margin;
                    if (top < 8) top = rect.bottom + margin;
                    let left = Math.min(Math.max(8, rect.left), window.innerWidth - t.offsetWidth - 8);
                    t.style.top = `${Math.max(8, top)}px`;
                    t.style.left = `${left}px`;
                    t.style.visibility = '';
                });
            });
        }

        function openTip() {
            ensureTip();
            positionTip();
            btn.setAttribute('aria-expanded', 'true');
        }

        function closeTip() {
            if (!tip) return;
            tip.classList.remove('show');
            btn.setAttribute('aria-expanded', 'false');
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
        window.addEventListener('resize', () => {
            if (tip && tip.classList.contains('show')) positionTip();
        }, {passive: true});
    })();

    // Density management (now via actions menu)
    function applyDensityFromStorage() {
        const mode = localStorage.getItem('density') || 'compact';
        const body = document.body;
        if (mode === 'compact') {
            body.classList.add('compact-rows');
        } else {
            body.classList.remove('compact-rows');
        }
    }

    applyDensityFromStorage();

    // Export popover (CSV / JSON)
    const exportBtn = document.getElementById('exportBtn');
    let exportPortal = null;

    function closeExportMenu() {
        if (exportPortal) {
            exportPortal.remove();
            exportPortal = null;
        }
        if (exportBtn) exportBtn.setAttribute('aria-expanded', 'false');
    }

    function openExportMenu() {
        closeExportMenu();
        // Read trigger geometry before any DOM writes to avoid forced reflow
        const rect = exportBtn.getBoundingClientRect();
        const portalRoot = document.getElementById('portal-root') || document.body;
        exportPortal = document.createElement('div');
        exportPortal.className = 'actions-menu';
        exportPortal.setAttribute('role', 'menu');
        exportPortal.innerHTML = `
            <button type="button" role="menuitem" data-action="csv">Export CSV</button>
            <button type="button" role="menuitem" data-action="json">Export JSON</button>
        `;
        portalRoot.appendChild(exportPortal);
        exportPortal.style.position = 'fixed';
        exportPortal.style.top = `${rect.bottom + 6}px`;
        exportPortal.style.left = `${Math.min(rect.left, window.innerWidth - 220)}px`;
        exportBtn.setAttribute('aria-expanded', 'true');
        exportPortal.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-action]');
            if (!btn) return;
            const action = btn.getAttribute('data-action');
            if (action === 'csv') exportCsv();
            if (action === 'json') exportJson();
            closeExportMenu();
        });
        setTimeout(() => {
            const onDocClick = (ev) => {
                if (!exportPortal) return;
                if (!ev.target.closest('.actions-menu') && ev.target !== exportBtn) {
                    closeExportMenu();
                    document.removeEventListener('click', onDocClick);
                    document.removeEventListener('keydown', onKey);
                }
            };
            const onKey = (ev) => {
                if (ev.key === 'Escape') {
                    closeExportMenu();
                    document.removeEventListener('click', onDocClick);
                    document.removeEventListener('keydown', onKey);
                }
            };
            document.addEventListener('click', onDocClick);
            document.addEventListener('keydown', onKey);
        }, 0);
    }

    if (exportBtn) {
        exportBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (exportBtn.getAttribute('aria-expanded') === 'true') closeExportMenu(); else openExportMenu();
        });
    }


    // Density toggle and Reset
    const densityBtn = document.getElementById('densityToggle');
    if (densityBtn) {
        densityBtn.addEventListener('click', () => {
            const curr = localStorage.getItem('density') || 'comfortable';
            const next = curr === 'compact' ? 'comfortable' : 'compact';
            localStorage.setItem('density', next);
            applyDensityFromStorage();
            densityBtn.textContent = `Density: ${next.charAt(0).toUpperCase()}${next.slice(1)}`;
            notifyAction(`Density set to ${next}`);
        });
        // initialize label
        const current = localStorage.getItem('density') || 'compact';
        densityBtn.textContent = `Density: ${current.charAt(0).toUpperCase()}${current.slice(1)}`;
    }
    const resetBtn = document.getElementById('resetFilters');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            document.getElementById('searchInput').value = '';
            document.getElementById('brandFilter').value = '';
            document.getElementById('scoreFilter')?.remove();
            let cb = document.getElementById('includeNoScore');
            if (!cb) {
                cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.id = 'includeNoScore';
                cb.className = 'sr-only';
                document.body.appendChild(cb);
            }
            cb.checked = false; // default: don't include no-score
            const btnScoredR = document.getElementById('segScored');
            const btnAllR = document.getElementById('segAll');
            if (btnScoredR && btnAllR) {
                btnScoredR.classList.add('is-active');
                btnAllR.classList.remove('is-active');
                btnScoredR.setAttribute('aria-pressed', 'true');
                btnAllR.setAttribute('aria-pressed', 'false');
            }
            currentSort = {key: 'name', direction: 'asc'};
            selectedForCompare.clear();
            renderTable();
            stateToQuery();
            notifyAction('Filters reset');
        });
    }


    // Comparison drawer buttons
    const cmpBtn = document.getElementById('compareBtn');
    const clearCmp = document.getElementById('clearCompare');

    function selectedRows() {
        const ids = [...selectedForCompare];
        const all = window.lastFiltered || getFilteredData();
        const byId = (d) => `${d.name}__${d.brand ?? ''}`;
        return all.filter(d => ids.includes(byId(d))).slice(0, 5);
    }

    function buildCompareModal(items) {
        let modal = document.getElementById('compareModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'compareModal';
            modal.className = 'compare-modal';
            document.body.appendChild(modal);
        }
        const content = `
              <div class="glass-card p-4" style="max-width:90vw;max-height:85vh;overflow:auto">
                <div class="flex justify-between items-center mb-3">
                  <h3 class="text-xl font-semibold text-cyan-300 font-mono">Compare devices (${items.length})</h3>
                  <button id="cmpClose" class="btn-neon px-3 py-1">Close</button>
                </div>
                <div class="grid" style="grid-template-columns: repeat(${items.length}, minmax(220px, 1fr)); gap: 12px;">
                  ${items.map(it => `
                    <article class="compare-card">
                      <div class="text-sm text-slate-400">${it.brand ?? '—'}</div>
                      <div class="text-lg font-semibold text-cyan-300 mb-1">${it.name}</div>
                      <div class="mb-2"><span class="px-2 py-1 rounded-full text-white text-sm font-semibold ${badge(it.repairability_score)}">${it.repairability_score ?? '—'}/10</span></div>
                      <div class="text-sm mb-2"><a href="${it.link}" target="_blank" class="text-cyan-400 underline">iFixit page</a></div>
                      <div class="text-sm">Teardowns:</div>
                      <div class="mt-1 space-y-1">${renderTeardownLinks(it.teardown_urls || [])}</div>
                    </article>
                  `).join('')}
                </div>
              </div>`;
        modal.innerHTML = content;
        modal.classList.add('show');
        modal.addEventListener('click', (e) => {
            if (e.target.id === 'cmpClose' || e.target === modal) {
                modal.classList.remove('show');
            }
        });
        document.addEventListener('keydown', function esc(e) {
            if (e.key === 'Escape') {
                modal.classList.remove('show');
                document.removeEventListener('keydown', esc);
            }
        });
    }

    if (cmpBtn) cmpBtn.addEventListener('click', () => {
        const items = selectedRows();
        if (selectedForCompare.size > MAX_COMPARE) {
            notifyAction(`You can compare up to ${MAX_COMPARE} devices. Showing the first ${MAX_COMPARE}.`);
        }
        if (items.length >= 2) {
            buildCompareModal(items);
        } else {
            notifyAction('Select at least 2 devices to compare.');
        }
    });
    if (clearCmp) clearCmp.addEventListener('click', () => {
        selectedForCompare.clear();
        renderTable();
        notifyAction('Selection cleared');
    });

    // Auto wide layout for ultrawide screens
    function applyWideLayoutAuto() {
        const shouldWide = window.innerWidth >= 1920; // 2K and above
        document.body.classList.toggle('layout-wide', shouldWide);
    }

    applyWideLayoutAuto();
    window.addEventListener('resize', () => {
        applyWideLayoutAuto();
    }, {passive: true});

    // Export helpers used by actions menu
    function toCsvRow(fields) {
        return fields.map(v => '"' + String(v ?? '').replaceAll('"', '""') + '"').join(',');
    }

    function exportCsv() {
        const rows = window.lastFiltered || getFilteredData();
        const header = ['name', 'brand', 'repairability_score', 'link'];
        const lines = [toCsvRow(header)];
        rows.forEach(d => lines.push(toCsvRow([d.name, d.brand ?? '', d.repairability_score ?? '', d.link ?? ''])));
        const blob = new Blob([lines.join('\r\n')], {type: 'text/csv;charset=utf-8;'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'ifixit_devices.csv';
        a.click();
        URL.revokeObjectURL(a.href);
        notifyAction('CSV exported');
    }

    function exportJson() {
        const rows = window.lastFiltered || getFilteredData();
        const blob = new Blob([JSON.stringify(rows, null, 2)], {type: 'application/json'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'ifixit_devices.json';
        a.click();
        URL.revokeObjectURL(a.href);
        notifyAction('JSON exported');
    }

    document.querySelectorAll('th[data-sort-key]').forEach(th => {
        const pulse = () => {
            th.classList.add('th-anim');
            setTimeout(() => th.classList.remove('th-anim'), 200);
        };
        th.addEventListener('click', () => {
            pulse();
            toggleSort(th.dataset.sortKey);
            stateToQuery();
        });
        th.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                pulse();
                toggleSort(th.dataset.sortKey);
                stateToQuery();
            }
        });
    });
});