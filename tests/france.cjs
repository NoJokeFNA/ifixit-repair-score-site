const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const devices = JSON.parse(fs.readFileSync(path.join(root, 'devices_with_scores.json')));
const source = JSON.parse(fs.readFileSync(path.join(root, 'france_devices_with_scores.json')));
const sourceByUrl = new Map(source.map(row => [row.source_url, row]));
assert(source.length > 0);
assert.equal(sourceByUrl.size, source.length, 'Duplicate source URLs');
for (const device of devices) {
  const match = device.france_repairability;
  assert(match && ['matched', 'conflicting', 'not_found'].includes(match.status), `${device.name}: missing match evidence`);
  const values = new Set();
  for (const row of match.sources) {
    const original = sourceByUrl.get(row.url);
    assert(original, `${device.name}: source URL is not in the verified source snapshot`);
    assert.equal(row.name, original.name);
    assert.equal(row.score, original.repairability_score);
    assert.equal(row.last_updated, original.last_updated);
    values.add(row.score);
  }
  if (match.status === 'matched') {
    assert.equal(values.size, 1);
    assert.equal(device.france_repairability_score, match.score);
    assert.equal([...values][0], match.score);
  } else {
    assert.equal(device.france_repairability_score, null);
    assert.equal(match.score, null);
    if (match.status === 'conflicting') assert(values.size > 1);
    else assert.equal(match.sources.length, 0);
  }
}
const getDevice = name => devices.find(device => device.name === name);
// The source snapshot above is real. Browser scenarios use fixed examples so a
// legitimate future source correction or a newly listed model does not fail CI.
const browserData = structuredClone(devices);
const testDevice = name => browserData.find(device => device.name === name);
for (const name of ['iPhone SE', 'iPhone SE 2022']) {
  Object.assign(testDevice(name), {france_repairability_score: null, france_repairability: {status: 'not_found', score: null, sources: []}});
}
const evidence = (name, score) => ({name, score, url: 'https://www.indicereparabilite.fr/produit/test-fixture/', last_updated: '01/01/2025'});
Object.assign(testDevice('iPhone SE 2020'), {france_repairability_score: 6.2, france_repairability: {status: 'matched', score: 6.2, sources: [evidence('iPhone SE 2020', 6.2)]}});
Object.assign(testDevice('iPhone 12'), {france_repairability_score: null, france_repairability: {status: 'conflicting', score: null, sources: [evidence('iPhone 12 White', 5.7), evidence('iPhone 12 Black', 6.0)]}});

(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox']});
  try {
    for (const viewport of [{width: 1920, height: 1080}, {width: 390, height: 844}]) {
      for (const colorScheme of ['dark', 'light']) {
        const context = await browser.newContext({viewport, colorScheme});
        const page = await context.newPage();
        const errors = [], external = [], popups = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('popup', popup => popups.push(popup.url()));
        await page.route('**/*', route => {
          const url = new URL(route.request().url());
          if (url.hostname !== 'site.test') {external.push(url.href); return route.abort();}
          if (url.pathname === '/devices_with_scores.json') return route.fulfill({json: browserData});
          return route.fulfill({path: path.join(root, url.pathname === '/' ? 'index.html' : url.pathname)});
        });
        await page.goto('http://site.test/');
        await page.waitForFunction(() => document.querySelector('#brandFilter').options.length > 1);
        await page.locator('#segAll').click();
        const row = name => page.locator('#deviceTable tr').filter({has: page.getByRole('link', {name, exact: true})});
        const franceCell = name => row(name).locator('td').nth(5);
        await page.locator('#searchInput').fill('iPhone 12');
        await page.waitForTimeout(350);
        assert((await franceCell('iPhone 12').innerText()).includes('Variants differ'));
        const summary = franceCell('iPhone 12').locator('summary');
        await summary.focus();
        await page.keyboard.press('Enter');
        assert.equal(await franceCell('iPhone 12').locator('details').getAttribute('open'), '');
        assert.equal(popups.length, 0, 'Opening French evidence also opened the iFixit device page');
        assert.equal(await franceCell('iPhone 12').locator('a').count(), testDevice('iPhone 12').france_repairability.sources.length);
        for (const link of await franceCell('iPhone 12').locator('a').all()) {
          assert((await link.getAttribute('href')).startsWith('https://www.indicereparabilite.fr/produit/'));
        }
        await page.locator('#searchInput').fill('iPhone SE');
        await page.waitForTimeout(350);
        assert((await franceCell('iPhone SE 2020').innerText()).includes('6.2/10'));
        for (const name of ['iPhone SE', 'iPhone SE 2022']) assert((await franceCell(name).innerText()).includes('No verified match'));
        await row('iPhone SE 2020').locator('input.cmp').check();
        await row('iPhone SE 2022').locator('input.cmp').check();
        await page.locator('#compareBtn').click();
        const compare = await page.locator('#compareModal').innerText();
        assert(compare.includes('France:') && compare.includes('6.2/10') && compare.includes('No verified match'));
        await page.locator('#cmpClose').click();
        await page.locator('#clearCompare').click();
        await page.locator('#searchInput').fill('');
        await page.waitForTimeout(350);
        const sort = page.locator('[data-sort-key="france_repairability_score"]');
        await sort.click();
        await page.waitForTimeout(100);
        let values = await page.evaluate(() => window.lastFiltered.map(device => device.france_repairability_score ?? -1));
        assert.deepEqual(values, [...values].sort((a,b) => a-b));
        await sort.focus();
        await page.keyboard.press('Enter');
        await page.waitForTimeout(100);
        values = await page.evaluate(() => window.lastFiltered.map(device => device.france_repairability_score ?? -1));
        assert.deepEqual(values, [...values].sort((a,b) => b-a));
        assert.equal(await sort.getAttribute('aria-sort'), 'descending');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        assert(await page.locator('#franceScoreHelp').isVisible());
        assert.deepEqual(errors, []);
        assert.deepEqual(external, []);
        if (process.env.WEB_TEST_OUTPUT) {
          fs.mkdirSync(process.env.WEB_TEST_OUTPUT, {recursive: true});
          await page.locator('#searchInput').fill('iPhone 12');
          await page.waitForTimeout(350);
          await franceCell('iPhone 12').locator('summary').click();
          await franceCell('iPhone 12').scrollIntoViewIfNeeded();
          await page.screenshot({path: path.join(process.env.WEB_TEST_OUTPUT, `france-${viewport.width}-${colorScheme}.png`)});
        }
        console.log(`${viewport.width} ${colorScheme}: French sources, conflicts, generations, comparison and numeric sorting passed`);
        await context.close();
      }
    }
    // A pre-fix cached SE score must not reappear or leak into exports while offline.
    const context = await browser.newContext();
    const cached = {...getDevice('iPhone SE 2022'), france_repairability_score: 6.2};
    delete cached.france_repairability;
    await context.addInitScript(device => localStorage.setItem('devicesData', JSON.stringify([device])), cached);
    const page = await context.newPage();
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.hostname !== 'site.test') return route.abort();
      if (url.pathname === '/devices_with_scores.json') return route.fulfill({status: 503, body: 'unavailable'});
      return route.fulfill({path: path.join(root, url.pathname === '/' ? 'index.html' : url.pathname)});
    });
    await page.goto('http://site.test/');
    await page.waitForFunction(() => document.querySelector('#brandFilter').options.length > 1);
    await page.locator('#segAll').click();
    assert.equal(await page.locator('#deviceTable tr td').nth(5).innerText(), '—');
    await page.locator('#moreOptionsToggle').click();
    await page.locator('#exportBtn').click();
    const menu = await page.getByRole('menu').boundingBox();
    assert(menu.y >= 0 && menu.y + menu.height <= 720, 'Export menu is outside the viewport');
    const pending = page.waitForEvent('download');
    await page.getByRole('menuitem', {name: 'Export JSON', exact: true}).click();
    const download = await pending;
    assert.equal(JSON.parse(fs.readFileSync(await download.path()))[0].france_repairability_score, null);
    await context.close();
    console.log(`All ${devices.length} devices verified against ${source.length} source records; unsafe legacy cache export blocked`);
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
