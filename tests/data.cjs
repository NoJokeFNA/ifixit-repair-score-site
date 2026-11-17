const {site,json,assert,fs} = require('./helpers.cjs');
const devices=json('devices_with_scores.json'),rubric=json('rubric.json'),images=json('images.json');
const names=new Set();
for(const d of devices){
 assert.equal(typeof d.name,'string');assert.ok(!names.has(d.name));names.add(d.name);
 for(const key of ['repairability_score','france_repairability_score'])assert.ok(d[key]===null||(typeof d[key]==='number'&&Number.isFinite(d[key])&&d[key]>=0&&d[key]<=10),d.name+' '+key);
 assert.ok(!d.scorecard_version||rubric.versions.includes(d.scorecard_version));
 assert.ok(d.link===null||d.link.startsWith('https://www.ifixit.com/'));
 for(const t of d.teardown_urls)assert.ok(t.url.startsWith('https://www.ifixit.com/'));
}
function parseCsv(text){const rows=[];let row=[],field='',quoted=false;for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}else if(c===','&&!quoted){row.push(field);field='';}else if(c==='\n'&&!quoted){row.push(field.replace(/\r$/,''));rows.push(row);row=[];field='';}else field+=c;}if(field||row.length){row.push(field.replace(/\r$/,''));rows.push(row);}return rows;}
(async()=>{
 await site(async page=>{
  await page.locator('#brand').selectOption('Fairphone');
  const expected=devices.filter(d=>d.brand==='Fairphone'&&typeof d.repairability_score==='number');
  const pending=page.waitForEvent('download');await page.locator('#export').click();
  const dl=await pending;const csv=parseCsv(fs.readFileSync(await dl.path(),'utf8').replace(/^\uFEFF/,''));
  assert.deepEqual(csv.shift(),['Device','Manufacturer','iFixit score','French repairability index','French index status','Rubric','iFixit source']);
  assert.equal(csv.length,expected.length);assert.equal(new Set(csv.map(r=>r[0])).size,expected.length);
  for(const r of csv){const d=expected.find(d=>d.name===r[0]);assert.ok(d);assert.equal(r[2],String(d.repairability_score));assert.equal(r[6],d.link);}
  await page.locator('#reset').click();
  for(const theme of ['light','dark']){
   if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#theme').click();
   const before=await page.locator('#main').boundingBox();await page.locator('[data-view="comparison"]').click();
   await page.locator('[data-compare-mode="rubrics"]').click();const after=await page.locator('#main').boundingBox();assert.equal(before.width,after.width);
   assert.equal(await page.locator('html').evaluate(e=>getComputedStyle(e).scrollbarGutter),'stable');
   assert.notEqual(await page.locator('html').evaluate(e=>getComputedStyle(e).scrollbarColor),'auto');
   await page.locator('[data-view="explorer"]').click();
  }
 });
 const {root,path}=require('./helpers.cjs');
 for(const image of Object.values(images))if(image.local)assert.ok(fs.existsSync(path.join(root,image.local)),image.local);
 console.log('Device data, image assets, CSV alignment, separate models and themed stable scrollbars passed');
})().catch(e=>{console.error(e);process.exit(1);});
