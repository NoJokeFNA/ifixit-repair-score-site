const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const output = process.env.WEB_TEST_OUTPUT;
if (output) fs.mkdirSync(output, {recursive: true});
const viewports = [
  ['ultrawide', 3440, 1440], ['fullhd', 1920, 1080], ['hd', 1280, 720],
  ['tablet', 768, 1024], ['tablet-landscape', 1024, 768], ['mobile', 390, 844], ['small-mobile', 320, 740]
];
(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox']});
  try {
    for (const [name, width, height] of viewports) {
      for (const colorScheme of ['dark', 'light']) {
        const context = await browser.newContext({viewport: {width, height}, colorScheme});
        const page = await context.newPage();
        const errors = [], external = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/*', route => {
          const url = new URL(route.request().url());
          if (url.hostname !== 'site.test') {external.push(url.href); return route.abort();}
          const file = url.pathname === '/' ? '/index.html' : url.pathname;
          const contentType = {'.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.json': 'application/json', '.png': 'image/png'}[path.extname(file)] || 'text/html';
          return route.fulfill({path: root + file, contentType});
        });
        await page.goto('http://site.test/');
        await page.waitForFunction(() => window.Chart?.getChart('repairabilityChart') && document.querySelector('#deviceTable .rubric-version'));
        await page.evaluate(() => document.fonts.ready);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${name}: page overflow`);
        assert.equal(await page.locator('.dashboard-legend').getAttribute('open'), null);
        assert.equal(await page.locator('body > header details').count(), 0);
        assert.equal(await page.locator('body > header .header-info').count(), 2);
        for (const card of await page.locator('body > header .header-info').all()) assert(await card.isVisible());
        const search = await page.locator('#searchInput').boundingBox();
        await page.locator('#searchInput').scrollIntoViewIfNeeded();
        await page.waitForFunction(() => {
          const rect = document.querySelector('#searchInput').getBoundingClientRect();
          return rect.top >= -1 && rect.bottom <= innerHeight + 1;
        });
        const visibleSearch = await page.locator('#searchInput').boundingBox();
        assert(visibleSearch.y >= -1 && visibleSearch.y + visibleSearch.height <= height + 1, `${name}: search cannot be reached`);
        if (width >= 2560) assert((await page.locator('.table-section').boundingBox()).width > 1900);
        const columnKeys = await page.locator('.device-table th[data-sort-key]').evaluateAll(headers => headers.map(th => th.dataset.sortKey));
        assert.deepEqual(columnKeys, ['name', 'teardown', 'brand', 'repairability_score', 'france_repairability_score', 'scoring_rubric']);
        await page.locator('.dashboard-legend summary').click();
        assert(await page.locator('.tags-legend').isVisible());
        await page.locator('.dashboard-legend summary').click();
        await page.locator('#moreOptionsToggle').scrollIntoViewIfNeeded();
        const optionsBefore = await page.locator('#moreOptionsToggle').boundingBox();
        await page.locator('#moreOptionsToggle').click();
        assert(await page.locator('#exportBtn').isVisible());
        const optionsOpen = await page.locator('#moreOptionsToggle').boundingBox();
        assert(Math.abs(optionsBefore.x - optionsOpen.x) < 1 && Math.abs(optionsBefore.y - optionsOpen.y) < 1, `${name}: More options moved when opened`);
        await page.locator('#moreOptionsToggle').click();
        const optionsClosed = await page.locator('#moreOptionsToggle').boundingBox();
        assert(Math.abs(optionsBefore.x - optionsClosed.x) < 1 && Math.abs(optionsBefore.y - optionsClosed.y) < 1, `${name}: More options moved when closed`);
        const unfiltered = await page.locator('#deviceTable tr').count();
        await page.locator('#brandFilter').selectOption('Apple');
        await page.locator('#searchInput').fill('iPhone');
        await page.waitForTimeout(350);
        async function clickBar(score) {
          await page.locator('#repairabilityChart').scrollIntoViewIfNeeded();
          const point = await page.evaluate(score => {
            const chart = Chart.getChart('repairabilityChart');
            chart.stop(); chart.update('none');
            const bar = chart.getDatasetMeta(0).data[score];
            return {x: bar.x, y: (bar.y + bar.base) / 2};
          }, score);
          const expected = await page.locator('#scoreFilter').count() && await page.locator('#scoreFilter').inputValue() === String(score) ? null : String(score);
          await page.locator('#repairabilityChart').click({position: point});
          await page.waitForFunction(expected => (document.getElementById('scoreFilter')?.value ?? null) === expected, expected);
        }
        await clickBar(6);
        await page.waitForFunction(() => document.getElementById('scoreFilter')?.value === '6');
        assert.equal(await page.locator('#brandFilter').inputValue(), 'Apple');
        assert.equal(await page.locator('#searchInput').inputValue(), 'iPhone');
        assert(await page.locator('#chartFilters').isVisible());
        assert(await page.locator('#activeFilters').isVisible());
        assert((await page.locator('#chartFilters').innerText()).includes('6/10'));
        assert((await page.evaluate(() => Chart.getChart('repairabilityChart').data.datasets[0].data.filter(n => n > 0).length)) > 1, 'Other score bars disappeared');
        await page.locator('#themeToggle').click();
        await page.waitForFunction(() => Chart.getChart('repairabilityChart').data.datasets[0].data.filter(n => n > 0).length > 1);
        assert.equal(await page.locator('#scoreFilter').inputValue(), '6');
        await page.locator('#themeToggle').click();
        await clickBar(6);
        await page.waitForFunction(() => !document.getElementById('scoreFilter'));
        await clickBar(6);
        await page.locator('#chartFilters button').click();
        assert.equal(await page.locator('#scoreFilter').count(), 0);
        assert(!new URL(page.url()).searchParams.has('score'));
        await clickBar(6);
        await page.reload();
        await page.waitForFunction(() => window.Chart?.getChart('repairabilityChart') && document.querySelector('#activeFilters.show'));
        assert.equal(await page.locator('#scoreFilter').inputValue(), '6');
        await page.locator('#activeFilters button').click();
        assert.equal(await page.locator('#scoreFilter').count(), 0);
        await page.locator('#moreOptionsToggle').click();
        await page.locator('#resetFilters').click();
        assert.equal(await page.locator('#searchInput').inputValue(), '');
        assert.equal(await page.locator('#brandFilter').inputValue(), '');
        assert.equal(await page.locator('#deviceTable tr').count(), unfiltered);
        await page.locator('#moreOptionsToggle').click();
        await page.evaluate(() => scrollTo(0, 0));
        if (output) {
          await page.screenshot({path: path.join(output, `responsive-${name}-${colorScheme}.png`)});
          await page.locator('.device-table-scroll').scrollIntoViewIfNeeded();
          await page.screenshot({path: path.join(output, `responsive-${name}-${colorScheme}-table.png`)});
        }
        assert.deepEqual(external, [], 'The dashboard requested an external asset');
        assert.deepEqual(errors, []);
        console.log(`${name} ${colorScheme}: layout, local assets and score filter passed; search at ${Math.round(search.y)}px`);
        await context.close();
      }
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
