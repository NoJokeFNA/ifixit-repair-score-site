const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const chartVersion = require('../package.json').devDependencies['chart.js'];
assert.match(chartVersion, /^\d+\.\d+\.\d+$/, 'Chart.js must stay pinned to an exact version');

(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox']});
  try {
    for (const future of [false, true]) {
      const rubric = JSON.parse(fs.readFileSync(path.join(root, 'rubric.json')));
      if (future) {
        rubric.versions.push('3.0');
        rubric.criteria.forEach(c => c.included.push(false));
        rubric.criteria.push({name: 'Battery Longevity', included: rubric.versions.map(v => v === '3.0'), weights: {'3.0': '25%'}, notes: {'3.0': 'Future criterion'}});
        rubric.factors_not_considered.push({version: '3.0', items: []});
        rubric.revisions.push({version: '3.0', items: ['New criterion added']});
      }
      const context = await browser.newContext();
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.hostname !== 'site.test') return route.abort();
        if (url.pathname === '/rubric.json') return route.fulfill({json: rubric});
        return route.fulfill({path: path.join(root, url.pathname === '/' ? 'index.html' : url.pathname)});
      });
      await page.goto('http://site.test/');
      await page.waitForFunction(() => window.Chart?.getChart('repairabilityChart') && document.querySelectorAll('.rubric-version-button').length);
      assert.equal(await page.evaluate(() => Chart.version), chartVersion);
      await page.locator('#toggleRubricTable').click();
      assert.equal(await page.locator('.rubric-version-button').count(), rubric.versions.length);
      for (const version of rubric.versions) {
        const button = page.getByRole('button', {name: `Show details for version ${version}`, exact: true});
        await button.click();
        assert.equal(await page.locator('#rubricModalTitle').innerText(), `Rubric ${version}`);
        const details = await page.locator('#modalContent').innerText();
        for (const criterion of rubric.criteria) {
          assert(details.includes(criterion.name));
          if (criterion.notes?.[version]) assert(details.includes(criterion.notes[version]));
          if (criterion.included[rubric.versions.indexOf(version)]) {
            assert(details.includes(`Weight: ${criterion.weights?.[version] ?? 'N/A'}`));
          }
        }
        for (const revision of rubric.revisions.find(r => r.version === version)?.items || []) assert(details.includes(revision));
        if (!future && version === '2.4' && process.env.WEB_TEST_OUTPUT) {
          await page.locator('#rubricModal').screenshot({path: path.join(process.env.WEB_TEST_OUTPUT, 'rubric-2.4-details.png')});
        }
        if (version === '3.0') {
          assert(details.includes('25%'));
          assert(details.includes('Future criterion'));
          assert(details.includes('New criterion added'));
        }
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#rubricModal').evaluate(el => el.open), false);
      }
      const lastVersion = rubric.versions.at(-1);
      assert((await page.locator('#latestRubricLink').getAttribute('href')).endsWith(`v${lastVersion}`));
      for (const width of [1920, 768, 390, 320]) {
        await page.setViewportSize({width, height: 1000});
        for (const light of [false, true]) {
          await page.evaluate(value => document.body.classList.toggle('theme-light', value), light);
          assert((await page.locator('.score-chart').boundingBox()).height <= 240);
          await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth, null, {timeout: 5000});
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `Rubric overflow at ${width}px (${light ? 'light' : 'dark'}, future=${future})`);
          if (!future && process.env.WEB_TEST_OUTPUT) {
            await page.locator('.chart-section').screenshot({path: path.join(process.env.WEB_TEST_OUTPUT, `rubric-${width}-${light ? 'light' : 'dark'}.png`)});
          }
          const button = page.getByRole('button', {name: `Show details for version ${lastVersion}`, exact: true});
          await button.focus();
          await page.keyboard.press('Enter');
          assert.equal(await page.locator('#rubricModal').evaluate(el => el.open), true);
          await page.keyboard.press('Escape');
        }
      }
      const header = page.locator('[data-sort-key="scoring_rubric"]');
      for (const ascending of [true, false]) {
        await header.focus();
        await page.keyboard.press('Enter');
        const versions = await page.locator('#deviceTable .rubric-version').allTextContents();
        const expected = [...versions].sort((a, b) => (a === '—' ? '' : a).localeCompare(b === '—' ? '' : b, undefined, {numeric: true}));
        if (!ascending) expected.reverse();
        assert.deepEqual(versions, expected);
      }
      assert.deepEqual(errors, []);
      console.log(`${future ? 'Future' : 'Current'} rubric: ${rubric.versions.length} versions, details, layout, keyboard and sorting passed`);
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
