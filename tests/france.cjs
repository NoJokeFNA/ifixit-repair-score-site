const {site,json,device,assert}=require('./helpers.cjs');
const sources=new Map(json('france_devices_with_scores.json').map(row=>[row.source_url,row]));
for(const d of json('devices_with_scores.json')){
 const fr=d.france_repairability;
 assert.ok(fr&&['matched','conflicting','ambiguous','not_found'].includes(fr.status),d.name);
 assert.equal(d.france_repairability_score,fr.score);
 for(const source of fr.sources){const row=sources.get(source.url);assert.ok(row,source.url);assert.equal(source.score,row.repairability_score,d.name+' source mismatch');}
 if(fr.status==='matched'){assert.ok(fr.sources.length);assert.ok(fr.sources.every(s=>s.score===fr.score));}else assert.equal(fr.score,null);
}
const source=(name,score)=>({name,score,url:'https://www.indicereparabilite.fr/produit/'+name.replaceAll(' ','-')+'/',last_updated:'2026-01-01'});
const ambiguous={status:'ambiguous',score:null,sources:[source('Example (6GB, 128GB)',9.2),source('Example (8GB, 256GB)',9.3)]};
const sheet={...source('Reviewed source',6),catalogue_score:4.8,verification:'sheet_checked',calculation_total:59.6,criterion_scores:[12.3,5.9,9.3,12,20],calculation_sheet_url:'https://www.indicereparabilite.fr/sheet.png'};
const rows=[device('Matched Phone',10,{status:'matched',score:9.3,sources:[source('Matching source',9.3)]}),device('Variant Phone',9,ambiguous),device('Conflict Phone',8,{status:'conflicting',score:null,sources:[sheet,source('Other source',5.7)]}),device('Missing Phone',7)];
(async()=>{
 await site(async page=>{
  await page.locator('#search').fill('Variant Phone');assert.ok((await page.locator('.variant-range').innerText()).includes('9.2 - 9.3'));await page.locator('.device-name').click();
  assert.equal(await page.locator('.variant-configurations>div').count(),2);
  assert.ok((await page.locator('.variant-explanation').innerText()).includes('RAM and storage'));
  await page.keyboard.press('Escape');await page.locator('#search').fill('Conflict Phone');await page.locator('.device-name').click();
  const evidence=await page.locator('.source-discrepancy').innerText();assert.ok(evidence.includes('4.8'));assert.ok(evidence.includes('59.6'));assert.ok(evidence.includes('6 / 10'));
  await page.locator('.device-french-breakdown summary').click();assert.equal(await page.locator('.device-french-breakdown>div').count(),5);
  // Hold the history traversal so a slow Back operation is reproducible.
  await page.evaluate(()=>{
   const back=history.back;
   history.back=()=>{window.finishDetailBack=()=>{history.back=back;history.back();};};
  });
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>typeof window.finishDetailBack==='function');
  assert.equal(await page.locator('#detail-dialog').isVisible(),true);
  await page.evaluate(()=>window.finishDetailBack());
  await page.locator('#search').fill('Matched Phone');await page.locator('.device-name').click();
  assert.equal(await page.locator('#detail-title').innerText(),'Matched Phone');
  assert.ok((await page.locator('.detail-scores').innerText()).includes('9.3'));await page.keyboard.press('Escape');
  await page.locator('#search').fill('Missing Phone');await page.locator('.device-name').click();assert.ok((await page.locator('#detail-content').innerText()).includes('No data'));
 },{overrides:{'devices_with_scores.json':rows,'images.json':{}}});
 console.log('French source provenance, variant configurations, conflicts, checked sheets and missing data passed');
})().catch(e=>{console.error(e);process.exit(1);});
