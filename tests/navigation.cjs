const {site,device,assert}=require('./helpers.cjs');
const rows=[device('Older Phone',6),device('Newer Phone',6),device('No Rubric',7)];
rows[0].scorecard_version='2.3';rows[2].scorecard_version=null;
const fresh={updated_at:new Date().toISOString()};
const overrides={'devices_with_scores.json':rows,'images.json':{},'data-status.json':fresh};
const params=page=>new URL(page.url()).searchParams;
(async()=>{
 await site(async page=>{
  await page.locator('#search').fill('Phone');await page.locator('#brand').selectOption('Example');await page.locator('#page-size').selectOption('25');
  assert.equal(params(page).get('q'),'Phone');assert.equal(params(page).get('brand'),'Example');assert.equal(params(page).get('size'),'25');
  const link=await page.locator('.device-name').first().getAttribute('href');assert.ok(link.includes('device='));
  const listURL=page.url();await page.locator('.device-name').first().click();
  assert.equal(params(page).get('device'),'Older_Phone');assert.equal(await page.locator('#detail-title').textContent(),'Older Phone');
  await page.goBack();await page.locator('#detail-dialog').waitFor({state:'hidden'});assert.equal(page.url(),listURL);assert.equal(await page.locator('#search').inputValue(),'Phone');
  await page.goForward();await page.locator('#detail-dialog').waitFor({state:'visible'});assert.equal(await page.locator('#detail-title').textContent(),'Older Phone');
  await page.reload();await page.locator('#detail-dialog').waitFor({state:'visible'});assert.equal(await page.locator('#detail-title').textContent(),'Older Phone');
  await page.locator('#close-detail').click();await page.waitForFunction(()=>!new URL(location.href).searchParams.has('device'));
  assert.equal(await page.locator('#brand').inputValue(),'Example');assert.equal(await page.locator('#page-size').inputValue(),'25');
  await page.locator('.row-select').first().check();await page.locator('.row-select').nth(1).check();await page.locator('#open-comparison').click();
  assert.equal(params(page).get('view'),'comparison');assert.equal(params(page).getAll('compare').length,2);
  assert.ok((await page.locator('.comparison-context').innerText()).includes('different rubric versions'));assert.equal(await page.locator('.rubric-caution').count(),2);
  await page.locator('.comparison-revisions summary').click();assert.ok((await page.locator('.comparison-revisions').innerText()).includes('Tools:'));
  await page.reload();await page.locator('.compare-card').first().waitFor();assert.equal(await page.locator('.compare-card').count(),2);
  await page.locator('.comparison-context [data-rubric-compare]').click();assert.equal(params(page).get('mode'),'rubrics');assert.equal(params(page).get('left'),'2.3');assert.equal(params(page).get('right'),'2.4');
  await page.locator('#rubric-left').selectOption('2.2');assert.equal(params(page).get('left'),'2.2');await page.reload();await page.locator('#rubric-diff').waitFor();assert.equal(await page.locator('#rubric-left').inputValue(),'2.2');
  await page.goBack();assert.equal(await page.locator('#rubric-left').inputValue(),'2.3');
  assert.ok((await page.locator('#dataset-updated').textContent()).startsWith('Updated '));assert.equal(await page.locator('#dataset-freshness').isVisible(),false);
 },{overrides});
 // Stable source identity survives a changed dataset order; a shared link needs no localStorage.
 await site(async page=>{
  assert.equal(await page.locator('#detail-title').textContent(),'Older Phone');assert.equal(await page.locator('#page-size').inputValue(),'10');
  await page.locator('#close-detail').click();await page.waitForFunction(()=>!new URL(location.href).searchParams.has('device'));
  assert.equal(await page.locator('#search').inputValue(),'Older');assert.equal(await page.locator('#device-rows tr').count(),1);
 },{query:'?q=Older&size=10&device=Older_Phone',overrides:{...overrides,'devices_with_scores.json':[...rows].reverse()}});
 await site(async page=>{
  assert.equal(await page.locator('#detail-dialog').isVisible(),false);assert.equal(await page.locator('#page-size').inputValue(),'8');assert.ok(!params(page).has('device'));assert.ok(!params(page).has('score'));
  assert.ok((await page.locator('#dataset-freshness').innerText()).includes('48 hours'));
 },{query:'?device=missing&size=999&page=-2&score=NaN&view=bad',overrides:{...overrides,'data-status.json':{updated_at:'2020-01-01T00:00:00Z'}}});
 await site(async page=>{
  await page.locator('#dataset-freshness').waitFor();assert.ok((await page.locator('#dataset-freshness').innerText()).includes('could not be verified'));
 },{overrides:{...overrides,'data-status.json':{updated_at:'invalid'}}});
 await site(async page=>{
  await page.locator('[data-chart-system="french"]').click();await page.locator('[data-scope="all"]').click();assert.equal(params(page).get('system'),'french');assert.equal(params(page).get('scope'),'all');
  await page.reload();await page.waitForFunction(()=>document.querySelector('#histogram').dataset.system==='french');assert.equal(await page.locator('[data-scope="all"]').getAttribute('aria-pressed'),'true');
  await page.locator('[data-view="method"]').first().click();await page.locator('[data-method-system="french"]').first().click();
  assert.equal(params(page).get('method'),'french');await page.reload();await page.locator('#french-rubric-panel').waitFor();assert.equal(await page.locator('#ifixit-rubric-panel').isVisible(),false);
 },{overrides});
 await site(async page=>{
  await page.locator('.row-select').first().check();await page.locator('.row-select').nth(1).check();await page.locator('#open-comparison').click();
  assert.ok((await page.locator('.comparison-context').innerText()).includes('missing'));
 },{overrides:{...overrides,'devices_with_scores.json':[rows[2],rows[1]]}});
 console.log('Stable share links, reload, history, comparison context, invalid routes and data freshness passed');
})().catch(error=>{console.error(error);process.exit(1);});
