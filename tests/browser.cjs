const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const output=process.env.WEB_TEST_OUTPUT || '/tmp/ifixit-web-check';
fs.mkdirSync(output,{recursive:true});
const chartPath=process.env.CHART_JS_PATH;
assert(chartPath, 'Set CHART_JS_PATH to a local Chart.js UMD distribution');
(async()=>{
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',args:['--no-sandbox']});
async function run(name,w,h,opts={}) {
 const context=await browser.newContext({viewport:{width:w,height:h},deviceScaleFactor:1});
 const errors=[]; const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',async route=>{
 const u=new URL(route.request().url());
 if(u.hostname==='cdn.jsdelivr.net') return opts.noChart ? route.abort() : route.fulfill({path:chartPath,contentType:'text/javascript'});
 if(u.hostname!=='site.test')return route.abort();
 const path=u.pathname==='/'?'/index.html':u.pathname;
 if(path==='/devices_with_scores.json' && route.request().method()!=='HEAD'){
 if(opts.fail && !opts.recovered)return route.fulfill({status:503,body:'unavailable'});
 if(opts.slow)await new Promise(r=>setTimeout(r,1200));
 }

 if(!fs.existsSync(root+path))return route.fulfill({status:404,body:''});
 return route.fulfill({path:root+path,contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':path.endsWith('.json')?'application/json':'text/html'});
 });
 await context.addInitScript(({opts,data})=>{
 if(opts.cache)localStorage.setItem('devicesData',JSON.stringify(data));
 if(opts.corrupt)localStorage.setItem('devicesData','{bad');
 if(opts.block)Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Blocked','SecurityError')}});
 if(opts.quota)Storage.prototype.setItem=function(){throw new DOMException('Full','QuotaExceededError')};
 },{opts,data:JSON.parse(fs.readFileSync(root+'/devices_with_scores.json'))});
 await page.goto('http://site.test/'+(opts.brand?'?brand=Apple':''));
 await page.waitForTimeout(3500);
 const result=await page.evaluate(()=>({rows:document.querySelectorAll('#deviceTable tr[data-name], #deviceTable tr').length,brands:document.querySelector('#brandFilter').options.length,text:document.querySelector('#deviceTable').innerText.slice(0,90),brand:document.querySelector('#brandFilter').value,overflow:document.documentElement.scrollWidth>innerWidth,chart:!!window.Chart?.getChart('repairabilityChart'),clipped:[...document.querySelectorAll('button,input,select,h1,h2')].filter(e=>{const r=e.getBoundingClientRect();return r.width&& (r.right>innerWidth+1||r.left< -1)}).map(e=>e.id||e.textContent.slice(0,20))}));
 console.log(name,JSON.stringify({...result,errors}));
 assert.equal(errors.length,0,name+' browser errors');
 if(!opts.fail || opts.cache) {
   assert(result.brands>1 && !result.text.includes('Failed to load'),name+' data');
   if(!opts.noChart) assert(result.chart,name+' chart');
   assert.equal(result.overflow,false,name+' horizontal overflow');
   assert.deepEqual(result.clipped,[],name+' clipped controls');
 }
 if(opts.brand) assert.equal(result.brand,'Apple');
 if(opts.fail && !opts.cache) {
   assert(result.text.includes('Failed to load data'));
   opts.recovered=true;
   await page.locator('#retryData').click();
   await page.waitForFunction(()=>document.querySelector('#brandFilter').options.length>1);
 }
 if(opts.cache && opts.fail) assert((await page.locator('#actionLive').innerText()).includes('cached'));
 if(name==='fullhd') {
   await page.locator('[data-sort-key="france_repairability_score"]').click();
   assert.equal(await page.locator('[data-sort-key="france_repairability_score"]').getAttribute('aria-sort'),'ascending');
   await page.locator('#searchInput').fill('iPhone 16');
   await page.waitForTimeout(400);
   assert((await page.locator('#deviceTable').innerText()).includes('iPhone 16'));
   await page.reload();
   await page.waitForTimeout(1500);
   assert.equal(await page.locator('#searchInput').inputValue(),'iPhone 16');
 }
 await page.screenshot({path:output+'/'+name+'.png',fullPage:false});
 await context.close();
}
for(const [name,w,h] of [['fullhd',1920,1080],['ultrawide',3440,1440],['mobile',390,844],['small-mobile',320,740],['tablet',768,1024]])await run(name,w,h,{slow:true});
for(const opts of [{corrupt:true},{block:true},{quota:true},{cache:true,fail:true},{brand:true},{fail:true},{noChart:true}])await run(Object.keys(opts).join('-'),390,844,opts);
await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
