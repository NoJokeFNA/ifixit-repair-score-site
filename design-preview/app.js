'use strict';
const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[–—−]/g, '-').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = value => {try {const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : '#';}catch{return '#';}};
const format = new Intl.NumberFormat('en-US');
const PAGE_SIZE = 20;
let devices = [], filtered = [], page = 1, scoreFilter = null, selected = new Set(), toastTimer;
const has = value => typeof value === 'number' && Number.isFinite(value);
const french = d => {
 const match=d.france_repairability, score=d.france_repairability_score;
 const verified=match?.status==='matched' && has(score) && score>=0 && score<=10 && match.score===score &&
  Array.isArray(match.sources) && match.sources.length>0 && match.sources.every(source=>{
   if(!source || source.score!==score)return false;
   try{const url=new URL(source.url);return url.protocol==='https:' && url.hostname==='www.indicereparabilite.fr' && !url.username && !url.password && url.pathname.startsWith('/produit/');}catch{return false;}
  });
 return verified?score:null;
};
const scoreHTML = (n, fr = false) => has(n) ? `<span class="score ${n >= 7 ? 'high' : n >= 4 ? 'mid' : 'low'}${fr ? ' france' : ''}">${n}<small>/10</small></span>` : '<span class="missing" aria-label="No verified score">-</span>';
const external = (url, label, cls='') => `<a class="${cls}" href="${esc(safeURL(url))}" target="_blank" rel="noopener noreferrer">${esc(label)} <span aria-hidden="true"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></span></a>`;
function toast(message) {$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,3500);}
function missingReason(d) {
 const status=d.france_repairability?.status;
 if(status==='matched'&&!has(french(d)))return 'This score has not passed source verification. No score is assigned.';
 if(status==='ambiguous')return 'The exact model or regional variant could not be verified. A score is withheld until the match is clear.';
 if(status==='conflicting')return 'Matching sources report different scores. No single score is shown.';
 return 'No verified French repairability source was found for this exact device. This does not mean a score of zero.';
}
function modelNumbers(d){return [...new Set([...(d.model_identification?.model_numbers || []),...(d.france_repairability?.model_numbers || [])])];}
function showDialog(label, html) {$('#dialog-label').textContent=label;$('#dialog-body').innerHTML=html;if(!$('#detail-dialog').open)$('#detail-dialog').showModal();}
function sourceView(index) {
 const d=devices[index], data=d.france_repairability || {}, score=french(d), sources=data.sources || [];
 showDialog('FRANCE / SOURCE EVIDENCE',`<h2 id="dialog-title">${esc(d.name)}</h2><p>French repairability index. Independent of the iFixit assessment.</p>${has(score)?`<div class="dialog-actions">${scoreHTML(score,true)}</div><p>Verified device match${data.match_method==='model_number'?' using model identification':''}. ${sources.length>1?'Matching source entries agree on this score.':''}</p>`:`<p class="source-entry">${esc(missingReason(d))}</p>`}${(data.model_numbers || []).length?`<h3>Matched model numbers</h3><div class="chips">${data.model_numbers.map(m=>`<span class="chip">${esc(m)}</span>`).join('')}</div>`:''}${(data.model_reference_urls || []).length?`<div class="dialog-actions">${data.model_reference_urls.map(url=>external(url,'Model identification reference','secondary-link')).join('')}</div>`:''}${sources.map(s=>`<article class="source-entry"><div class="source-top">${external(s.url,s.name || 'Source entry')}${scoreHTML(s.score,true)}</div>${s.model?`<p>Model: ${esc(s.model)}</p>`:''}${s.last_updated?`<p>Source calculation date: ${esc(s.last_updated)}</p>`:''}</article>`).join('')}<p>Different assessment criteria can produce different iFixit and France scores. This is expected.</p>${external('https://www.indicereparabilite.fr/','About the French repairability index','secondary-link')}`);
}
function deviceView(index){
 const d=devices[index], models=modelNumbers(d), variants=(d.model_identification?.variants || []).filter(v=>v.name), teardowns=d.teardown_urls || [];
 showDialog('DEVICE / IDENTIFICATION',`<h2 id="dialog-title">${esc(d.name)}</h2><p>${esc(d.brand || d.model_identification?.brand || 'Manufacturer not listed')}</p><div class="detail-scores"><div class="detail-score"><span>iFixit repairability</span>${scoreHTML(d.repairability_score)}<p>${has(d.repairability_score)?`Rubric ${esc(d.scorecard_version || 'version not listed')}`:'No published iFixit score in this dataset.'}</p></div><div class="detail-score"><span>France repairability</span><button data-source="${index}" class="source-button" aria-label="View French score evidence">${scoreHTML(french(d),true)}<span aria-hidden="true"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></span></button><p>${has(french(d))?'Verified source evidence available.':esc(missingReason(d))}</p></div></div><p>These scores use different criteria and should be read separately.</p><div class="dialog-actions">${external(d.link,'Open device on iFixit','secondary-link')}</div>${models.length?`<h3>Identified model numbers</h3><div class="chips">${models.map(m=>`<span class="chip">${esc(m)}</span>`).join('')}</div>`:''}${variants.length?`<h3>Regional and model variants</h3><ul class="variant-list">${variants.map(v=>`<li>${esc(v.name)}</li>`).join('')}</ul>`:''}${!models.length&&!variants.length?'<h3>Model identification</h3><p>No named model variants are available in this snapshot.</p>':''}${teardowns.length?`<h3>Teardowns <span class="muted">(${teardowns.length})</span></h3>${teardowns.map(t=>`<div class="teardown">${external(t.url,t.title || 'View teardown')}<span>${esc((t.tags || []).map(tag=>({'user_contributed':'Community','featured':'Featured','archived':'Archived'}[tag] || tag)).join(' / '))}${t.difficulty?' / '+esc(t.difficulty):''}</span></div>`).join('')}`:''}`);
}
function drawHistogram(){
 const counts=Array(11).fill(0);devices.forEach(d=>{if(has(d.repairability_score))counts[Math.round(d.repairability_score)]++;});const max=Math.max(...counts,1);
 $('#histogram').innerHTML=counts.map((n,i)=>`<button data-score="${i}" class="${scoreFilter===i?'active':''}" aria-pressed="${scoreFilter===i}" aria-label="iFixit score ${i}: ${n} devices. Click to ${scoreFilter===i?'clear':'filter'}." title="${i}/10: ${n} devices" style="--bar-height:${Math.max(3,n/max*100)}%;--bar-color:${i>=7?'#a0dbba':i>=4?'#c8b384':'#bb8d8f'}"></button>`).join('');
}
function apply(resetPage=true){
 if(resetPage)page=1;
 const q=$('#search').value.toLowerCase().trim(), brand=$('#brand').value, availability=$('#availability').value;
 filtered=devices.filter(d=>(!q||d._search.includes(q))&&(!brand||d._brand===brand)&&(availability==='all'||availability==='france'&&has(french(d))||availability==='both'&&has(french(d))&&has(d.repairability_score)||availability==='scored'&&(has(d.repairability_score)||has(french(d))))&&(scoreFilter===null||has(d.repairability_score)&&Math.round(d.repairability_score)===scoreFilter));
 const sort=$('#sort').value;filtered.sort((a,b)=>{const aScore=sort==='france'?french(a):a.repairability_score,bScore=sort==='france'?french(b):b.repairability_score;return (sort==='name'?0:(has(bScore)?bScore:-1)-(has(aScore)?aScore:-1))||a.name.localeCompare(b.name);});
 page=Math.min(page,Math.max(1,Math.ceil(filtered.length/PAGE_SIZE)));renderRows();
}
function renderRows(){
 $('#result-count').textContent=format.format(filtered.length);
 $('#filter-summary').textContent=`${format.format(filtered.length)} of ${format.format(devices.length)} devices${scoreFilter!==null?' / iFixit '+scoreFilter+'/10':''}`;
 $('#empty').hidden=filtered.length>0;
 const start=(page-1)*PAGE_SIZE;
 $('#rows').innerHTML=filtered.slice(start,start+PAGE_SIZE).map(d=>{const id=d._index,models=modelNumbers(d),variantCount=(d.model_identification?.variants || []).filter(v=>v.name).length;return `<tr class="${selected.has(id)?'selected':''}"><td class="check-col"><input type="checkbox" data-select="${id}" ${selected.has(id)?'checked':''} aria-label="Compare ${esc(d.name)}"></td><td class="device-cell"><button class="device-name" data-device="${id}">${esc(d.name)}</button><div class="mobile-brand">${esc(d._brand || 'Unlisted manufacturer')}</div>${models.length?`<div class="device-sub" title="${esc(models.join(', '))}">${esc(models.slice(0,2).join(' / '))}${models.length>2?' +'+(models.length-2):''}</div>`:variantCount?`<div class="device-sub">${variantCount} named variants</div>`:''}</td><td class="brand-cell desktop-brand">${esc(d._brand || '-')}</td><td class="score-cell" data-label="iFixit">${has(d.repairability_score)?scoreHTML(d.repairability_score):`<button data-device="${id}" class="missing" aria-label="Why ${esc(d.name)} has no iFixit score" title="No published iFixit score in this dataset">-</button>`}</td><td class="score-cell" data-label="France"><button class="source-button" data-source="${id}" aria-label="${has(french(d))?'France score '+french(d)+'/10. View sources for':'Why no France score for'} ${esc(d.name)}" title="${has(french(d))?'View verified sources':esc(missingReason(d))}">${scoreHTML(french(d),true)}${has(french(d))?'<span aria-hidden="true"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></span>':''}</button></td><td class="last-col"><button class="row-more" data-device="${id}" aria-label="View ${esc(d.name)} details"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button></td></tr>`;}).join('');
 $('#page-info').textContent=filtered.length?`Showing ${format.format(start+1)}-${format.format(Math.min(start+PAGE_SIZE,filtered.length))} of ${format.format(filtered.length)}`:'0 devices';
 $('#page-number').textContent=`${page} / ${Math.max(1,Math.ceil(filtered.length/PAGE_SIZE))}`;
 $('#prev').disabled=page===1;$('#next').disabled=page*PAGE_SIZE>=filtered.length;
}
function updateSelection(){
 $('#compare-tray').hidden=selected.size===0;$('#selection-label').textContent=`${selected.size} device${selected.size===1?'':'s'} selected`;
 $('#selection-names').textContent=[...selected].map(i=>devices[i].name).join(', ');$('#compare').disabled=selected.size<2;
}
function toggleSelection(index,checked){if(checked&&selected.size>=3){toast('Compare up to 3 devices at a time. Remove one to add another.');renderRows();return;}if(checked)selected.add(index);else selected.delete(index);updateSelection();renderRows();}
function compareView(){
 const list=[...selected].map(i=>devices[i]);if(list.length<2)return;
 showDialog('SIDE BY SIDE / DEVICE COMPARISON',`<h2 id="dialog-title">A clearer view of your choices<span class="mint">.</span></h2><p>Compare the same assessment across devices. iFixit and France remain separate.</p><p class="swipe-hint">Scroll sideways to view all selected devices.</p><div class="compare-grid" style="--columns:${list.length}">${list.map(d=>`<article class="compare-card"><h3>${esc(d.name)}</h3><p>${esc(d._brand || 'Manufacturer unlisted')}</p><div class="compare-metric"><span>iFixit repairability</span>${scoreHTML(d.repairability_score)}<div class="meter"><span style="width:${has(d.repairability_score)?d.repairability_score*10:0}%"></span></div><p>${has(d.repairability_score)?'Rubric '+esc(d.scorecard_version || 'not listed'):'No published score'}</p></div><div class="compare-metric"><span>France repairability</span><button data-source="${d._index}" class="source-button" aria-label="French source evidence for ${esc(d.name)}">${scoreHTML(french(d),true)}</button><div class="meter blue"><span style="width:${has(french(d))?french(d)*10:0}%"></span></div><p>${has(french(d))?'Verified source match':'No verified score'}</p></div>${external(d.link,'iFixit device page','secondary-link')}</article>`).join('')}</div><p>Rubric versions may differ between iFixit assessments. Review the original sources for a fair comparison.</p><button class="primary share-button" id="share-comparison">Copy comparison link <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>`);
}
function reset(){ $('#search').value='';$('#brand').value='';$('#availability').value='scored';$('#sort').value='ifixit';scoreFilter=null;drawHistogram();apply(); }
function exportCSV(){
 if(!filtered.length){toast('No devices to export. Adjust your filters first.');return;}
 const cell=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
 const content=[['Device','Manufacturer','iFixit score','France score','iFixit rubric','Model numbers','iFixit URL','France source URLs'],...filtered.map(d=>[d.name,d._brand,d.repairability_score,french(d),d.scorecard_version,modelNumbers(d).join(' / '),d.link,(d.france_repairability?.sources||[]).map(s=>s.url).join(' / ')])].map(row=>row.map(v=>cell(/^[=+@\t\r-]/.test(String(v??''))?"'"+v:v)).join(',')).join('\r\n');
 const url=URL.createObjectURL(new Blob(['\uFEFF'+content],{type:'text/csv;charset=utf-8;'}));const a=document.createElement('a');a.href=url;a.download='repairability-devices.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`Exported ${format.format(filtered.length)} devices.`);
}
async function load(){
 $('#load-error').hidden=true;
 try{const response=await fetch('../devices_with_scores.json');if(!response.ok)throw new Error('Data request failed');const data=await response.json();if(!Array.isArray(data)||!data.length)throw new Error('Empty data');
 devices=data.map((d,i)=>({...d,_index:i,_brand:d.brand || d.model_identification?.brand || '',_search:[d.name,d.title,d.brand,...modelNumbers(d),...(d.model_identification?.variants || []).map(v=>v.name || '')].join(' ').toLowerCase()}));
 $('#total-stat').textContent=format.format(devices.length);$('#ifixit-stat').textContent=format.format(devices.filter(d=>has(d.repairability_score)).length);$('#france-stat').textContent=format.format(devices.filter(d=>has(french(d))).length);
 const brands=[...new Set(devices.map(d=>d._brand).filter(Boolean))].sort((a,b)=>a.localeCompare(b));$('#brand').innerHTML='<option value="">All manufacturers</option>'+brands.map(b=>`<option>${esc(b)}</option>`).join('');drawHistogram();apply();
 const params=new URLSearchParams(location.search);const titles=(params.get('compare') || '').split('|');titles.forEach(t=>{const d=devices.find(d=>d.title===t);if(d&&selected.size<3)selected.add(d._index);});updateSelection();if(selected.size>=2)compareView();
 }catch(error){$('#load-error').hidden=false;$('#filter-summary').textContent='Device data unavailable';$('#result-count').textContent='Unavailable';$('#empty').hidden=true;}
}
$('#search').addEventListener('input',()=>apply());['brand','availability','sort'].forEach(id=>$('#'+id).addEventListener('change',()=>apply()));
$('#reset').onclick=reset;$('#empty-reset').onclick=reset;$('#retry').onclick=load;$('#export').onclick=exportCSV;
$('#prev').onclick=()=>{page--;apply(false);$('#library').scrollIntoView({block:'start'});};$('#next').onclick=()=>{page++;apply(false);$('#library').scrollIntoView({block:'start'});};
$('#histogram').onclick=e=>{const b=e.target.closest('[data-score]');if(!b)return;const n=Number(b.dataset.score);scoreFilter=scoreFilter===n?null:n;drawHistogram();apply();};
$('#rows').addEventListener('change',e=>{if(e.target.matches('[data-select]'))toggleSelection(Number(e.target.dataset.select),e.target.checked);});
for(const root of [$('#rows'),$('#dialog-body')])root.addEventListener('click',e=>{const source=e.target.closest('[data-source]'),device=e.target.closest('[data-device]');if(source)sourceView(Number(source.dataset.source));else if(device)deviceView(Number(device.dataset.device));});
$('#compare').onclick=compareView;$('#clear-selection').onclick=()=>{selected.clear();updateSelection();renderRows();};$('#close-dialog').onclick=()=>$('#detail-dialog').close();
$('#detail-dialog').addEventListener('click',e=>{if(e.target!==$('#detail-dialog'))return;const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();});
$('#dialog-body').addEventListener('click',async e=>{if(!e.target.closest('#share-comparison'))return;const u=new URL(location.href);u.search='';u.searchParams.set('compare',[...selected].map(i=>devices[i].title).join('|'));u.hash='';try{await navigator.clipboard.writeText(u.href);toast('Comparison link copied.');}catch{showDialog('SHARE / COMPARISON',`<h2 id="dialog-title">Your comparison link</h2><p>Copy this link to reopen these devices together.</p><label>Comparison URL<input class="share-url" readonly value="${esc(u.href)}" style="width:100%;margin:15px 0;padding:12px;background:#1c2c37;border:1px solid #455b6a;border-radius:5px;color:#d2e1eb"></label>`);$('.share-url').select();}});
addEventListener('keydown',e=>{if(e.key==='/'&&!$('#detail-dialog').open&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)){e.preventDefault();$('#search').focus();}});
load();
