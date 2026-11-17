const {site,json,root,device,assert,fs,path}=require('./helpers.cjs');
const photos=Object.values(json('images.json')).filter(photo=>photo.local&&fs.existsSync(path.join(root,photo.local))).slice(0,2);
assert.equal(photos.length,2);
const first={...photos[0],large:'https://guide-images.cdn.ifixit.com/igi/test-first.large'},second={...photos[1],large:'https://guide-images.cdn.ifixit.com/igi/test-second.large'};
(async()=>{
 await site(async page=>{
  await page.locator('#device-rows .device-photo-button').first().click();await page.locator('#close-photo').click();
  await page.locator('#device-rows .device-photo-button').nth(1).click();
  await page.waitForFunction(()=>!document.querySelector('#enlarged-photo').hidden);
  assert.equal(await page.locator('#photo-title').innerText(),'Photo Beta');
  await page.waitForTimeout(400);
  assert.equal(await page.locator('#enlarged-photo').getAttribute('src'),second.large);
  assert.equal(await page.locator('#photo-dialog').evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)');
  await page.locator('#photo-zoom-in').click();assert.equal(await page.locator('#photo-zoom-level').innerText(),'140%');
  await page.locator('#photo-fit').click();await page.locator('#enlarged-photo').dblclick();assert.equal(await page.locator('#photo-zoom-level').innerText(),'250%');
  await page.keyboard.press('0');assert.equal(await page.locator('#photo-zoom-level').innerText(),'100%');
  await page.keyboard.press('Escape');assert.ok(!await page.locator('#photo-dialog').isVisible());
 },{overrides:{'devices_with_scores.json':[device('Photo Alpha',10),device('Photo Beta',9)],'images.json':{'Photo_Alpha':first,'Photo_Beta':second}},external:async route=>{
  const image=route.request().url()===first.large?first:second;
  if(image===first)await new Promise(resolve=>setTimeout(resolve,250));
  await route.fulfill({contentType:'image/jpeg',body:fs.readFileSync(path.join(root,image.local))});
 }});
 console.log('Image identity under delayed loads, frameless viewer, zoom and keyboard dismissal passed');
})().catch(e=>{console.error(e);process.exit(1);});
