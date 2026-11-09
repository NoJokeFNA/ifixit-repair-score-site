const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
// Fixed distributions keep percentages, zeros and empty states independent of live data updates.
const fixture = [0, 5, 5, 8, 8, 8, null, null, null, null, null, null].map((score, index) => ({
  name: `Test phone ${index}`, title: `Test_phone_${index}`, brand: score === null ? 'Unscored' : 'Scored',
  link: 'https://www.ifixit.com/Device/Test', repairability_score: score,
  teardown_urls: [], france_repairability_score: null,
  france_repairability: {status: 'not_found', score: null, sources: []}
}));
(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox']});
  try {
    for (const width of [320, 390, 1440]) {
      for (const colorScheme of ['dark', 'light']) {
        const context = await browser.newContext({viewport: {width, height: 900}, colorScheme, reducedMotion: 'reduce'});
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.addInitScript(() => {
          window.chartText = [];
          const fillText = CanvasRenderingContext2D.prototype.fillText;
          CanvasRenderingContext2D.prototype.fillText = function (text, x, y, ...args) {
            if (this.canvas.id === 'repairabilityChart') window.chartText.push({text: String(text), x, y});
            return fillText.call(this, text, x, y, ...args);
          };
        });
        await page.route('**/*', route => {
          const url = new URL(route.request().url());
          if (url.hostname !== 'site.test') return route.abort();
          if (url.pathname === '/devices_with_scores.json') return route.fulfill({contentType: 'application/json', body: JSON.stringify(fixture)});
          const file = url.pathname === '/' ? '/index.html' : url.pathname;
          return route.fulfill({path: root + file, contentType: {'.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.woff2': 'font/woff2', '.png': 'image/png'}[path.extname(file)] || 'text/html'});
        });
        await page.goto('http://site.test/');
        await page.waitForFunction(() => window.Chart?.getChart('repairabilityChart') && document.querySelector('#chartSummary').textContent === '6 scored devices');
        await page.locator('#segAll').click();
        await page.waitForFunction(() => document.querySelector('#chartSummary').textContent === '6 scored devices / 6 without an iFixit score');
        const caption = await page.locator('#chartCaption').textContent();
        assert(caption.includes('0/10: 1 device') && caption.includes('5/10: 2 devices') && caption.includes('8/10: 3 devices'));
        const painted = await page.evaluate(() => {
          const chart = Chart.getChart('repairabilityChart');
          window.chartText = []; chart.stop(); chart.update('none');
          return {labels: window.chartText, bars: chart.getDatasetMeta(0).data.map(bar => ({x: bar.x, y: bar.y})), height: chart.height};
        });
        for (const [index, count] of [[0, 1], [5, 2], [8, 3]]) {
          const bar = painted.bars[index];
          assert(painted.labels.some(label => label.text === String(count) && Math.abs(label.x - bar.x) < 1 && label.y >= 11 && label.y < bar.y && label.y <= painted.height), 'Device count missing or clipped above score '+index);
        }
        await page.locator('#repairabilityChart').scrollIntoViewIfNeeded();
        const barPoint = await page.evaluate(() => {
          const chart = Chart.getChart('repairabilityChart'), bar = chart.getDatasetMeta(0).data[8];
          return {x: bar.x, y: (bar.y + bar.base) / 2};
        });
        await page.locator('#repairabilityChart').hover({position: barPoint});
        await page.waitForFunction(() => Chart.getChart('repairabilityChart').tooltip.body?.[0]?.lines[0].includes('3 devices (50.0% of scored devices)'));
        await page.locator('#repairabilityChart').click({position: barPoint});
        await page.waitForFunction(() => document.querySelector('#scoreFilter')?.value === '8');
        assert.equal(await page.locator('#deviceTable tr').count(), 3);
        await page.locator('#chartFilters button').click();
        assert.equal(await page.locator('#deviceTable tr').count(), 12);
        const zeroPoint = await page.evaluate(() => {
          const chart = Chart.getChart('repairabilityChart'), bar = chart.getDatasetMeta(0).data[0];
          return {x: bar.x, y: (bar.y + bar.base) / 2};
        });
        await page.locator('#repairabilityChart').click({position: zeroPoint});
        await page.waitForFunction(() => document.querySelector('#scoreFilter')?.value === '0');
        assert.equal(await page.locator('#deviceTable tr').count(), 1);
        await page.locator('#chartFilters button').click();
        await page.locator('#brandFilter').selectOption('Unscored');
        await page.waitForFunction(() => document.querySelector('#chartSummary').textContent === 'No scored devices in this selection / 6 without an iFixit score');
        assert.deepEqual(await page.evaluate(() => Chart.getChart('repairabilityChart').data.datasets[0].data), Array(11).fill(0));
        await page.locator('#searchInput').fill('does-not-exist');
        await page.waitForFunction(() => document.querySelector('#chartSummary').textContent === 'No scored devices in this selection');
        assert.deepEqual(await page.evaluate(() => Chart.getChart('repairabilityChart').data.datasets[0].data), Array(11).fill(0));
        assert(await page.locator('#chartError').isHidden());
        assert((await page.locator('.score-chart').boundingBox()).height <= 180);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        assert.deepEqual(errors, []);
        console.log(`${width} ${colorScheme}: visible counts, scored-only percentages, filter, zero score and empty distributions passed`);
        await context.close();
      }
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
