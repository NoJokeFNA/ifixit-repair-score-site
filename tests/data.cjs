const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const devices = JSON.parse(fs.readFileSync(path.join(root, 'devices_with_scores.json')));
const rubric = JSON.parse(fs.readFileSync(path.join(root, 'rubric.json')));
const names = new Set();
for (const device of devices) {
  assert.equal(typeof device.name, 'string');
  assert(device.name.trim());
  assert(!names.has(device.name), `Duplicate device: ${device.name}`);
  names.add(device.name);
  assert(device.brand === null || (typeof device.brand === 'string' && device.brand.trim()));
  for (const field of ['repairability_score', 'france_repairability_score']) {
    const value = device[field];
    assert(value === null || (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 10), `${device.name}: invalid ${field}`);
  }
  const wikiPath = device.wiki_namespace === 'WIKI' ? 'Wiki' : 'Device';
  assert(device.link === null || device.link.startsWith(`https://www.ifixit.com/${wikiPath}/`));
  if (wikiPath === 'Wiki') assert(Number.isInteger(device.wikiid) && device.wikiid > 0, `${device.name}: missing verified wiki identity`);
  assert(!device.scorecard_version || rubric.versions.includes(device.scorecard_version));
  for (const teardown of device.teardown_urls) {
    assert(teardown.url.startsWith('https://www.ifixit.com/'));
    assert.equal(typeof teardown.title, 'string');
  }
}

function parseCsv(text) {
  const rows = []; let row = [], field = '', quoted = false;
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') {field += '"'; index++;}
      else quoted = !quoted;
    } else if (!quoted && char === ',') {row.push(field); field = '';}
    else if (!quoted && char === '\n') {row.push(field.replace(/\r$/, '')); rows.push(row); row = []; field = '';}
    else field += char;
  }
  if (field || row.length) {row.push(field.replace(/\r$/, '')); rows.push(row);}
  return rows;
}

(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox']});
  try {
    for (const colorScheme of ['dark', 'light']) {
      const context = await browser.newContext({viewport: {width: 1920, height: 1080}, colorScheme});
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.hostname !== 'site.test') return route.abort();
        return route.fulfill({path: path.join(root, url.pathname === '/' ? 'index.html' : url.pathname)});
      });
      await page.goto('http://site.test/?brand=Fairphone');
      await page.waitForFunction(() => document.querySelector('#brandFilter').value === 'Fairphone' && document.querySelectorAll('#rubricTable tr').length);
      const expected = devices.filter(device => device.brand === 'Fairphone' && device.repairability_score !== null).sort((a, b) => a.name.localeCompare(b.name));
      assert(expected.length > 0, 'Fairphone manufacturer data is missing');
      assert.equal(await page.locator('#deviceTable tr').count(), expected.length);
      assert((await page.locator('#deviceTable').innerText()).includes('Fairphone 5'));
      await page.locator('#moreOptionsToggle').click();
      async function downloadText(name) {
        await page.locator('#exportBtn').click();
        const pending = page.waitForEvent('download');
        await page.getByRole('menuitem', {name: `Export ${name}`, exact: true}).click();
        const download = await pending;
        return fs.readFileSync(await download.path(), 'utf8');
      }
      const csv = parseCsv(await downloadText('CSV'));
      assert.deepEqual(csv.shift(), ['name', 'brand', 'repairability_score', 'france_repairability_score', 'scoring_rubric', 'link']);
      assert.equal(csv.length, expected.length, 'CSV duplicated devices');
      expected.forEach((device, index) => assert.deepEqual(csv[index], [
        device.name, device.brand, String(device.repairability_score),
        String(device.france_repairability_score ?? ''), String(device.scorecard_version ?? ''), device.link
      ]));
      assert.deepEqual(JSON.parse(await downloadText('JSON')), expected);
      await page.locator('#segAll').click();
      assert.equal(await page.locator('#deviceTable tr').count(), devices.filter(device => device.brand === 'Fairphone').length);
      await page.locator('#toggleRubricTable').click();
      const rootStyle = await page.evaluate(() => ({scheme: getComputedStyle(document.documentElement).colorScheme, color: getComputedStyle(document.documentElement).scrollbarColor}));
      assert.equal(rootStyle.scheme, colorScheme);
      assert.notEqual(rootStyle.color, 'auto');
      for (const selector of ['#rubricTableContainer', '.device-table-scroll', '#rubricModal']) {
        const style = await page.locator(selector).evaluate(element => ({width: getComputedStyle(element).scrollbarWidth, color: getComputedStyle(element).scrollbarColor}));
        assert.equal(style.width, 'thin');
        assert.equal(style.color, rootStyle.color);
      }
      if (process.env.WEB_TEST_OUTPUT) {
        fs.mkdirSync(process.env.WEB_TEST_OUTPUT, {recursive: true});
        await page.locator('.chart-section').screenshot({path: path.join(process.env.WEB_TEST_OUTPUT, `scrollbars-${colorScheme}.png`)});
      }
      assert.deepEqual(errors, []);
      console.log(`${colorScheme}: Fairphone brand/model, CSV/JSON fields and matching scrollbars passed`);
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
