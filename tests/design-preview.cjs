const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = (score, name='Test source') => ({name, score, url:'https://www.indicereparabilite.fr/produit/test/', last_updated:'01/01/2025'});
const device = (name, score, france=null, extra={}) => ({name, title:name.replaceAll(' ', '_'), brand:'Test', link:'https://www.ifixit.com/Device/Test', repairability_score:score, scorecard_version:'1.6', france_repairability_score:france, france_repairability:france===null?{status:'not_found',score:null,sources:[]}:{status:'matched',score:france,sources:[source(france)]}, teardown_urls:[], ...extra});
const fixture = [
 device('Fairphone 5',10,9.3,{brand:'Fairphone'}),
 device('Fairphone 4',10,null,{brand:'Fairphone'}),
 device('iPhone 13',6,6.2,{brand:'Apple',model_identification:{model_numbers:['A2633','A2482'],variants:[{name:'A2633 Global'},{name:'A2482 US'}]}}),
 device('Unscored device',null),
 device('Conflicting device',3,null,{france_repairability:{status:'conflicting',score:null,sources:[source(6),source(7)]}}),
 device('Ambiguous device',5,null,{france_repairability:{status:'ambiguous',score:null,sources:[source(8)]}}),
 device('Unverified device',7,9,{france_repairability:{status:'matched',score:9,sources:[{...source(9),url:'https://example.org/fake-source'}]}}),
 device('Zero score device',0,0)
];
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',args:['--no-sandbox']});
 try {
  const context=await browser.newContext({viewport:{width:1440,height:1100}});
  let unavailable=false;
  await context.route('**/*',route=>{
   const url=new URL(route.request().url());
   if(url.hostname!=='site.test')return route.abort();
   if(url.pathname==='/devices_with_scores.json')return route.fulfill({status:unavailable?503:200,contentType:'application/json',body:JSON.stringify(fixture)});
   const pathname=url.pathname.endsWith('/')?url.pathname+'index.html':url.pathname;
   const file=path.resolve(root,'.'+pathname);
   if(!file.startsWith(root+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
   return route.fulfill({path:file,contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.woff2')?'font/woff2':file.endsWith('.png')?'image/png':'text/html'});
  });
  const page=await context.newPage(), errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('https://site.test/design-preview/');
  await page.waitForFunction(()=>document.querySelector('#total-stat').textContent==='8');
  assert.equal(await page.locator('#ifixit-stat').textContent(),'7');
  assert.equal(await page.locator('#france-stat').textContent(),'3');
  assert.equal(await page.locator('header .info-card').count(),2);
  assert.equal(await page.locator('header details').count(),0);
  await page.locator('#availability').selectOption('france');assert.equal(await page.locator('#result-count').textContent(),'3');
  await page.locator('#availability').selectOption('both');assert.equal(await page.locator('#result-count').textContent(),'3');
  await page.locator('#availability').selectOption('all');assert.equal(await page.locator('#result-count').textContent(),'8');
  await page.locator('#search').fill('A2482');assert.equal(await page.locator('#rows .device-name').textContent(),'iPhone 13');
  await page.getByRole('button',{name:'iPhone 13',exact:true}).click();
  assert.match(await page.locator('#dialog-body').textContent(),/A2633 Global/);assert.match(await page.locator('#dialog-body').textContent(),/A2482 US/);
  await page.keyboard.press('Escape');
  for(const [query,reason] of [['Conflicting','different scores'],['Ambiguous','exact model'],['Unverified','not passed source verification'],['Unscored','No verified French']]){
   await page.locator('#search').fill(query);await page.locator('#rows [data-source]').click();assert.match(await page.locator('#dialog-body').textContent(),new RegExp(reason));await page.keyboard.press('Escape');
  }
  await page.locator('#search').fill('Zero');assert.equal(await page.locator('#rows .score').count(),2);assert.match(await page.locator('#rows').textContent(),/0\/10/);
  await page.locator('#reset').click();
  for(const name of ['Fairphone 5','Fairphone 4','iPhone 13'])await page.getByRole('checkbox',{name:'Compare '+name,exact:true}).check();
  await page.getByRole('checkbox',{name:'Compare Ambiguous device',exact:true}).click();assert.equal(await page.locator('#rows input:checked').count(),3);
  await page.locator('#compare').click();assert.equal(await page.locator('.compare-card').count(),3);assert.match(await page.locator('.compare-grid').textContent(),/9.3/);
  for(const width of [320,390,768,1024,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Comparison overflow at '+width);}
  await page.keyboard.press('Escape');await page.locator('#clear-selection').click();
  await page.locator('#search').fill('no-such-model');assert(await page.locator('#empty').isVisible());await page.locator('#empty-reset').click();
  await page.locator('[data-score="10"]').click();assert.equal(await page.locator('#result-count').textContent(),'2');await page.locator('[data-score="10"]').click();
  await page.locator('#brand').selectOption('Fairphone');
  const downloaded=page.waitForEvent('download');await page.locator('#export').click();const download=await downloaded;assert.equal(fs.readFileSync(await download.path(),'utf8').trim().split('\r\n').length,3);
  await page.locator('#reset').click();
  const row=page.locator('#rows tr').filter({hasText:'Fairphone 5'});const before=(await row.boundingBox()).height;await row.locator('[data-source]').click();assert.equal((await row.boundingBox()).height,before);assert.equal(await page.locator('.source-entry').count(),1);await page.keyboard.press('Escape');
  for(const width of [320,390,768,1024,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Library overflow at '+width);for(const card of await page.locator('header .info-card').all())assert(await card.isVisible());}
  await page.goto('https://site.test/design-preview/?compare=Fairphone_5%7CiPhone_13');await page.waitForSelector('.compare-card');assert.equal(await page.locator('.compare-card').count(),2);
  unavailable=true;await page.goto('https://site.test/design-preview/');await page.waitForSelector('#load-error:not([hidden])');unavailable=false;await page.locator('#retry').click();await page.waitForFunction(()=>document.querySelector('#result-count').textContent==='7');
  assert.deepEqual(errors,[]);await context.close();console.log('Design preview passed: independent verified scores, variants, filters, CSV, comparison, deep links, source dialog, retry and five responsive widths.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
