const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const json = name => JSON.parse(fs.readFileSync(path.join(root, name), 'utf8'));

async function site(run, options = {}) {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox']});
  const context = await browser.newContext({viewport: options.viewport || {width: 1440, height: 1000}, hasTouch: !!options.touch});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.hostname !== 'site.test') return options.external ? options.external(route) : route.abort();
    const name = decodeURIComponent(url.pathname.replace(/^\/repair-scores\//, '')) || 'index.html';
    if (Object.hasOwn(options.overrides || {}, name)) {
      return route.fulfill({contentType: 'application/json', body: JSON.stringify(options.overrides[name])});
    }
    const file = path.resolve(root, name);
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) return route.fulfill({status: 404, body: 'Not found'});
    return route.fulfill({path: file});
  });
  try {
    await page.goto('http://site.test/repair-scores/'+(options.query||''));
    await page.waitForFunction(() => /^\d/.test(document.querySelector('#result-count')?.textContent || ''));
    await run(page, context);
    assert.deepEqual(errors, [], 'Uncaught browser errors');
  } finally { await browser.close(); }
}

function device(name, score, french = {status: 'not_found', score: null, sources: []}) {
  return {name, title: name.replaceAll(' ', '_'), repairability_score: score, brand: 'Example',
    link: 'https://www.ifixit.com/Device/' + name.replaceAll(' ', '_'), teardown_urls: [],
    france_repairability_score: french.score, france_repairability: french,
    model_identification: {model_numbers: [], variants: []}, scorecard_version: '2.4'};
}

module.exports = {site, json, root, device, assert, fs, path};
