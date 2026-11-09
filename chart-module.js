(function () {
  'use strict';

  let myChart = null;

  function prefersReducedMotion() {
    try { return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (_) { return false; }
  }

  function renderChart(data) {
    const chartError = document.getElementById('chartError');
    chartError && chartError.classList.add('hidden');

    const devices = Array.isArray(data) ? data : [];
    const buckets = Array(11).fill(0);
    devices.forEach(device => {
      const score = device.repairability_score;
      if (Number.isInteger(score) && score >= 0 && score <= 10) buckets[score]++;
    });
    const total = buckets.reduce((sum, count) => sum + count, 0);
    const unscored = devices.length - total;
    const number = new Intl.NumberFormat('en-US');
    const summary = document.getElementById('chartSummary');
    if (summary) {
      summary.textContent = total
        ? `${number.format(total)} scored ${total === 1 ? 'device' : 'devices'}`
        : 'No scored devices in this selection';
      if (unscored) summary.textContent += ` / ${number.format(unscored)} without an iFixit score`;
    }
    const caption = document.getElementById('chartCaption');
    if (caption) caption.textContent = 'iFixit score distribution. ' + buckets.map((count, score) =>
      `${score}/10: ${number.format(count)} ${count === 1 ? 'device' : 'devices'}`
    ).join('; ') + '.';

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
    const active = document.getElementById('scoreFilter')?.value;
    const hasSelection = active !== undefined && active !== '';
    // Same ranges and colors as the table badges: 0-4, 5-7 and 8-10.
    const colors = buckets.map((_, score) => score >= 8 ? [0, 188, 125] : score >= 5 ? [239, 177, 0] : [255, 32, 86]);
    const barColor = (index, hover = false) => {
      const alpha = hover || !hasSelection || active === String(index) ? 1 : 0.28;
      return `rgba(${colors[index].join(',')},${alpha})`;
    };
    const textColor = isLight ? '#334155' : '#cbd5e1';
    const selectedColor = isLight ? '#0f172a' : '#f8fafc';
    const fontFamily = getComputedStyle(canvas).fontFamily;

    const countLabels = {
      id: 'scoreCounts',
      afterDatasetsDraw(chart) {
        const {ctx, chartArea} = chart;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        const fontSize = chart.width < 480 ? 10 : 11;
        chart.getDatasetMeta(0).data.forEach((bar, index) => {
          const selected = active === String(index);
          ctx.fillStyle = selected ? selectedColor : textColor;
          ctx.globalAlpha = !hasSelection || selected ? 1 : 0.55;
          ctx.font = `${selected ? 700 : 500} ${fontSize}px ${fontFamily}`;
          ctx.fillText(number.format(buckets[index]), bar.x, Math.max(chartArea.top + fontSize, bar.y - 7));
        });
        ctx.restore();
      }
    };

    myChart = new Chart(ctx, {
      type: 'bar',
      plugins: [countLabels],
      data: {
        labels: buckets.map((_, score) => String(score)),
        datasets: [{
          label: 'Devices',
          data: buckets,
          backgroundColor: buckets.map((_, index) => barColor(index)),
          hoverBackgroundColor: buckets.map((_, index) => barColor(index, true)),
          borderRadius: 4,
          borderSkipped: 'bottom',
          borderWidth: buckets.map((_, index) => active === String(index) ? 2 : 0),
          borderColor: selectedColor,
          maxBarThickness: 40,
          barPercentage: 0.78,
          categoryPercentage: 0.85
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {padding: {top: 18, left: 2, right: 2}},
        interaction: {mode: 'index', intersect: false, axis: 'x'},
        plugins: {
          legend: {display: false},
          tooltip: {
            backgroundColor: isLight ? '#ffffff' : '#0f172a',
            titleColor: selectedColor,
            bodyColor: textColor,
            cornerRadius: 8,
            padding: 10,
            borderColor: isLight ? '#cbd5e1' : '#475569',
            borderWidth: 1,
            displayColors: false,
            callbacks: {
              title: items => `iFixit score ${items[0].label}/10`,
              label: context => {
                const count = context.raw ?? 0;
                const pct = total ? ((count / total) * 100).toFixed(1) : '0.0';
                return `${number.format(count)} ${count === 1 ? 'device' : 'devices'} (${pct}% of scored devices)`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: {display: false},
            border: {color: isLight ? '#cbd5e1' : '#334155'},
            ticks: {
              autoSkip: false,
              maxRotation: 0,
              color: context => active === String(context.index) ? selectedColor : textColor,
              font: context => ({family: fontFamily, size: 11, weight: active === String(context.index) ? '700' : '400'}),
              padding: 8
            }
          },
          y: {
            display: false,
            beginAtZero: true,
            grace: '18%',
            suggestedMax: 1
          }
        },
        animation: {duration: prefersReducedMotion() ? 0 : 300, easing: 'easeOutCubic'},
        onHover: (event, elements) => {
          if (event.native?.target) event.native.target.style.cursor = elements.length ? 'pointer' : 'default';
        },
        onClick: (event, elements) => {
          if (elements.length && typeof window.setScoreFilter === 'function') {
            const score = elements[0].index;
            window.setScoreFilter(active === String(score) ? null : score);
          }
        }
      }
    });
  }

  window.ChartModule = {renderChart};
})();
