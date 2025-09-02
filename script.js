let devicesData = [];
let currentSort = {key: 'name', direction: 'asc'};
let myChart = null;

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
            renderChart(devicesData);
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
        renderChart(devicesData);
    } catch (error) {
        console.error('Data fetch failed:', error);
        tbody.innerHTML = '<tr><td colspan="4" class="px-6 py-4 text-center text-rose-500">Failed to load data</td></tr>';
        chartError.classList.remove('hidden');
    }
}

function getFilteredData() {
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
            teardownHtml = `<span class="teardown-toggle" data-index="${index}">[Teardowns]<span class="teardown-count"> x${d.teardown_urls.length}</span></span>
            <div class="teardown-dropdown" data-index="${index}">
                ${d.teardown_urls.map(g => `<a href="${g.url}" target="_blank">${g.title}</a>`).join('')}
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

    document.querySelectorAll('.teardown-toggle').forEach(toggle => {
        toggle.addEventListener('click', (e) => {
            const index = toggle.dataset.index;
            const dropdown = document.querySelector(`.teardown-dropdown[data-index="${index}"]`);
            const isShown = dropdown.classList.contains('show');
            document.querySelectorAll('.teardown-dropdown').forEach(d => d.classList.remove('show'));
            if (!isShown) {
                dropdown.classList.add('show');
            }
        });
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.teardown-toggle') && !e.target.closest('.teardown-dropdown')) {
            document.querySelectorAll('.teardown-dropdown').forEach(d => d.classList.remove('show'));
        }
    });

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
    let data = getFilteredData();
    data = sortData(data);
    populateTable(data);
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
                    borderWidth: 1
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
            animation: {duration: 1200, easing: 'easeOutExpo'},
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
    P = Array.from({length: 60}, () => ({
        x: Math.random() * bg.width,
        y: Math.random() * bg.height,
        r: Math.random() * 2 + 1.2,
        dx: (Math.random() - 0.5) * 0.45,
        dy: (Math.random() - 0.5) * 0.45
    }));
}

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
    requestAnimationFrame(tickBG);
}

addEventListener('resize', resizeBG);
resizeBG();
tickBG();

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
            document.getElementById('fileAge').textContent = `Last datasource update: ${ageStr} ago (${fileDate.toLocaleString()})`;
        } else {
            document.getElementById('fileAge').textContent = 'File age not available';
        }
    } catch (e) {
        document.getElementById('fileAge').textContent = 'File age not available';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    updateFileAge();
    loadData();
    document.getElementById('searchInput').addEventListener('input', renderTable);
    document.getElementById('brandFilter').addEventListener('change', renderTable);
    document.getElementById('resetFilters').addEventListener('click', () => {
        document.getElementById('searchInput').value = '';
        document.getElementById('brandFilter').value = '';
        document.getElementById('scoreFilter')?.remove();
        currentSort = {key: 'name', direction: 'asc'};
        loadData();
    });
    document.querySelectorAll('th[data-sort-key]').forEach(th => {
        th.addEventListener('click', () => toggleSort(th.dataset.sortKey));
    });
});