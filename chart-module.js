(function(){
  'use strict';

  let myChart = null;

  function prefersReducedMotion() {
    try { return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (_) { return false; }
  }

  function renderChart(data) {
    const chartError = document.getElementById('chartError');
    chartError && chartError.classList.add('hidden');

    if (!data || data.length === 0) {
      if (chartError) {
        chartError.textContent = 'No data available for chart';
        chartError.classList.remove('hidden');
      }
      return;
    }

    const buckets = Array(11).fill(0);
    data.forEach(d => {
      const s = d.repairability_score;
      if (Number.isInteger(s) && s >= 0 && s <= 10) buckets[s]++;
    });

    const canvas = document.getElementById('repairabilityChart');
    const ctx = canvas && canvas.getContext && canvas.getContext('2d');
    if (!ctx) {
      if (chartError) {
        chartError.textContent = 'Chart canvas not found';
        chartError.classList.remove('hidden');
      }
      return;
    }

    if (myChart) myChart.destroy();

    const isLight = document.body.classList.contains('theme-light');
    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight);
    gradient.addColorStop(0, isLight ? 'rgba(2,132,199,0.95)' : 'rgba(6,182,212,0.95)');
    gradient.addColorStop(1, isLight ? 'rgba(124,58,237,0.95)' : 'rgba(139,92,246,0.95)');

    const total = data.length;
    myChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10'],
        datasets: [{
          data: buckets,
          backgroundColor: gradient,
          borderRadius: 5,
          borderWidth: buckets.map((_, index) => String(index) === document.getElementById('scoreFilter')?.value ? 2 : 0),
          borderColor: isLight ? '#0f172a' : '#e2e8f0',
          barPercentage: 0.65,
          categoryPercentage: 0.8
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: isLight ? '#ffffff' : '#0f172a',
            titleColor: isLight ? '#0ea5e9' : '#67e8f9',
            bodyColor: isLight ? '#0f172a' : '#ffffff',
            cornerRadius: 10,
            padding: 12,
            borderColor: isLight ? '#0ea5e9' : '#67e8f9',
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
            grid: { display: false },
            ticks: { color: isLight ? '#475569' : '#94a3b8' },
            title: {
              display: true,
              text: 'Repairability Score',
              color: isLight ? '#0ea5e9' : '#67e8f9',
              font: { size: 11, weight: 'normal' }
            }
          },
          y: {
            beginAtZero: true,
            ticks: { precision: 0, maxTicksLimit: 6, color: isLight ? '#475569' : '#94a3b8' },
            grid: { color: isLight ? 'rgba(15,23,42,0.06)' : 'rgba(255,255,255,0.05)' },
            title: {
              display: true,
              text: 'Device count',
              color: isLight ? '#0ea5e9' : '#67e8f9',
              font: { size: 11, weight: 'normal' }
            }
          }
        },
        animation: { duration: prefersReducedMotion() ? 0 : 1200, easing: 'easeOutExpo' },
        onClick: (event, elements) => {
          if (elements.length) {
            const score = elements[0].index;
            const active = document.getElementById('scoreFilter')?.value;
            if (typeof window.setScoreFilter === 'function') {
              window.setScoreFilter(active === String(score) ? null : score);
            }
          }
        }
      }
    });
  }

  window.ChartModule = {
    renderChart
  };
})();
