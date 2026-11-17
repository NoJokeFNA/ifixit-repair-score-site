const {site, json, assert} = require('./helpers.cjs');
(async () => {
  const rubric = json('rubric.json');
  await site(async page => {
    await page.waitForFunction(() => document.querySelector('#rubric-version').options.length > 0);
    await page.locator('[data-view="method"]').click();
    for (const version of rubric.versions) {
      await page.locator('#rubric-version').selectOption(version);
      const expected = rubric.criteria.filter(c => c.included[rubric.versions.indexOf(version)]).length;
      assert.equal(await page.locator('.criterion-row').count(), expected, version);
    }
    await page.locator('#method-view [data-rubric-compare]').click();
    await page.locator('#rubric-left').selectOption('2.3');
    await page.locator('#rubric-right').selectOption('2.4');
    assert.ok((await page.locator('.rubric-release').nth(0).innerText()).includes('Wireless Headphones'));
    assert.ok((await page.locator('.rubric-release').nth(1).innerText()).includes('Portable Wireless Speakers'));
    assert.deepEqual(await page.locator('.rubric-diff-table tbody tr:last-child').evaluate(e => [...e.children].map(c => getComputedStyle(c).borderBottomWidth)), ['1px', '1px', '1px']);
    await page.locator('[data-view="method"]').click();
    await page.locator('.method-system [data-method-system="french"]').click();
    await page.waitForSelector('.french-criterion');
    const method = json('french-method.json');
    assert.equal(await page.locator('.french-criterion').count(), method.criteria.length);
    assert.equal(await page.locator('.french-subcriteria>div').count(), method.criteria.reduce((n,c) => n+c.subcriteria.length,0));
    assert.ok((await page.locator('.method-edition').innerText()).includes(method.grid_version));
    assert.equal(await page.locator('.french-source-wording summary').count() >= method.criteria.length, true);
  });
  const future = structuredClone(rubric);
  future.versions.push('10.5');
  future.criteria.forEach(c => c.included.push(false));
  future.criteria.push({name:'Battery longevity',included:future.versions.map(v=>v==='10.5'),weights:{'10.5':'25%'},notes:{'10.5':'New published criterion'}});
  await site(async page => {
    await page.waitForFunction(() => document.querySelector('#rubric-version').options.length > 0);
    await page.locator('[data-view="method"]').click();
    await page.locator('#rubric-version').selectOption('10.5');
    assert.ok((await page.locator('#rubric-content').innerText()).includes('Battery longevity'));
  }, {overrides:{'rubric.json':future}});
  console.log('All iFixit versions, revision differences, future criteria and automatic French grid passed');
})().catch(error=>{console.error(error);process.exit(1);});
