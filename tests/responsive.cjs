const {site,assert}=require('./helpers.cjs');
(async()=>{
 await site(async page=>{
  for(const theme of ['light','dark']){
   await page.setViewportSize({width:1440,height:1000});
   if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#theme').click();
   for(const width of [3440,1920,1440,1024,768,390,320]){
    await page.setViewportSize({width,height:1000});
    await page.locator('[data-view="explorer"]').click();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${theme} ${width}`);
    const search=await page.locator('#search').boundingBox();assert.ok(search.x>=0&&search.x+search.width<=width);
    await page.locator('[data-view="comparison"]').click();await page.locator('[data-compare-mode="devices"]').click();
    const before=await page.locator('#main').boundingBox();
    const button=await page.locator('.compare-empty .button').boundingBox();assert.ok(button.height<=44);
    await page.locator('[data-compare-mode="rubrics"]').click();const after=await page.locator('#main').boundingBox();
    assert.equal(before.width,after.width);assert.equal(before.x,after.x);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Rubric overflow '+width);
    await page.locator('.footer-about').click();assert.ok(await page.locator('#about-view').isVisible());
   }
  }
 });
 console.log('320-3440px layouts in both themes, compact buttons and no comparison-width jump passed');
})().catch(e=>{console.error(e);process.exit(1);});
