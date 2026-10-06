const {JSDOM}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict'),path=require('node:path');
const base=path.join(__dirname,'..');
const html=fs.readFileSync(path.join(base,'templates/portal/start.html'),'utf8').replace(/{%[\s\S]*?%}/g,'').replace(/{{[\s\S]*?}}/g,'');
const categories=[{id:1,name:'Excavadoras',slug:'excavadoras',aliases:['excavadora']},{id:2,name:'Compactadores',slug:'compactadores',aliases:['compactadora']}];
const pause=()=>new Promise(resolve=>setTimeout(resolve,0));
function fixture(responder,options={}){
  const dom=new JSDOM(html+`<script id="category-data" type="application/json">${JSON.stringify(categories)}</script>`,{runScripts:'outside-only',url:'https://portal.example/panel/maquinarias/nueva/'});
  const {window}=dom,$=selector=>window.document.querySelector(selector),calls=[];
  $('[data-intake-start]').dataset.catalogueUrl='/api/maquinarias/catalogo/descubrir/';
  if(options.initialCategory)$('[data-intake-start]').dataset.initialCategory=options.initialCategory;
  window.fetch=async(url,options)=>{calls.push(url); const value=await responder(new URL(url,window.location.origin),options);return {ok:true,headers:{get:()=> 'application/json'},json:async()=>value};};
  for(const name of ['category-picker.js','start-intake.js'])window.eval(fs.readFileSync(path.join(base,'static/portal',name),'utf8'));
  const form=$('#start-machine-form');
  function submit(button){const event=new window.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:$(button)});form.dispatchEvent(event);return {prevented:event.defaultPrevented,data:new window.FormData(form)};}
  return {dom,window,$,calls,submit};
}
const defaultResponse=url=>url.searchParams.get('stage')==='brands'?{items:[{id:11,label:'Caterpillar'}],total:1,has_more:false}:{items:[{id:77,label:'320',has_specs:true}],total:1,has_more:false};
(async()=>{
  let f=fixture(defaultResponse),{$,window}=f;
  assert.equal(f.calls.length,0,'initial page does not download all model rows');
  assert.equal($('#catalogue-intake-data'),null,'the full model catalogue is not embedded');
  assert.equal(f.submit('[data-entry-route=photos]').prevented,true,'hidden routes cannot create drafts');
  assert.equal(f.submit('#catalogue-generate').prevented,true,'a partial identity cannot create a catalogue draft');
  $('[data-category-id="1"]').click();await pause();
  assert.equal($('#brand-question').hidden,false,'a type immediately opens its brands');
  assert.equal($('#start-category').value,'1');assert.match(f.calls[0],/stage=brands/);
  $('#catalogue-brand-results button').click();await pause();
  assert.equal($('#model-question').hidden,false);assert.match(f.calls[1],/brand=11/);
  assert.equal($('#catalogue-generate').disabled,true);
  $('#catalogue-model-results button').click();
  assert.equal($('#catalogue-generate').disabled,false);assert.equal($('#catalogue-model').value,'77');
  assert.match($('#selection-summary').textContent,/Excavadoras.*Caterpillar.*320/);
  $('[data-browse-back=brand]').click();assert.equal($('#brand-question').hidden,false);
  $('#catalogue-brand-results button').click();await pause();assert.equal(f.calls.length,2,'back navigation reuses current-page cache');
  assert.equal($('#catalogue-model').value,'','changing a parent invalidates the selected model');
  $('#catalogue-model-results button').click();
  const created=f.submit('#catalogue-generate');assert.equal(created.prevented,false);assert.equal(created.data.get('entry_mode'),'catalogue');assert.equal(created.data.get('catalogue_enrichment'),'1');assert.equal(created.data.get('catalogue_model'),'77');
  assert.equal(f.submit('#catalogue-generate').prevented,true,'double submission cannot create duplicate drafts');f.dom.window.close();
  f=fixture(defaultResponse);({$,window}=f);$('[data-category-id="1"]').click();await pause();$('#catalogue-brand-results button').click();await pause();$('#catalogue-model-results button').click();
  const photoLabel=$('[data-entry-route=photos]').textContent;
  $('#identify-with-photos').click();const photoSubmit=f.submit('[data-entry-route=photos]');assert.equal(photoSubmit.prevented,false);
  const photoPageShow=new window.Event('pageshow');Object.defineProperty(photoPageShow,'persisted',{value:true});window.dispatchEvent(photoPageShow);
  assert.equal($('[data-entry-route=photos]').textContent,photoLabel,'bfcache restores the photo button label');assert.equal($('#catalogue-model').value,'77','bfcache restores the selected model id');
  $('#return-catalogue').click();assert.equal($('#model-question').hidden,false);assert.equal(f.submit('#catalogue-generate').prevented,false,'returning to the catalogue keeps the selected model submit-ready');f.dom.window.close();
  f=fixture(defaultResponse);({$,window}=f);$('#identify-with-photos').click();const serialLabel=$('[data-entry-route=serial]').textContent;$('#typed-serial').value='ABC12345';assert.equal(f.submit('[data-entry-route=serial]').prevented,false);
  const serialPageShow=new window.Event('pageshow');Object.defineProperty(serialPageShow,'persisted',{value:true});window.dispatchEvent(serialPageShow);
  assert.equal($('[data-entry-route=serial]').textContent,serialLabel,'bfcache restores the serial button label');f.dom.window.close();
  for(const route of ['photos','plate','serial']){
    f=fixture(defaultResponse);({$,window}=f);$('#identify-with-photos').click();
    assert.equal($('#identify-question').hidden,false);
    if(route==='serial'){assert.equal(f.submit('[data-entry-route=serial]').prevented,true);$('#typed-serial').value='ABC12345';}
    const result=f.submit(`[data-entry-route=${route}]`);assert.equal(result.prevented,false);assert.equal(result.data.get('entry_mode'),route);
    assert.equal(result.data.get('serial'),route==='serial'?'ABC12345':'');f.dom.window.close();
  }
  let releaseOld;
  f=fixture(url=>url.searchParams.get('category')==='1'?new Promise(resolve=>{releaseOld=resolve;}):{items:[{id:22,label:'BOMAG'}],total:1,has_more:false});({$}=f);
  $('[data-category-id="1"]').click();$('[data-browse-back=category]').click();$('[data-category-id="2"]').click();await pause();
  releaseOld({items:[{id:11,label:'Wrong stale Caterpillar'}],total:1,has_more:false});await pause();
  assert.equal($('#catalogue-brand-results').textContent,'BOMAG','late response cannot populate another category');f.dom.window.close();
  f=fixture(()=>{throw new Error('Catálogo no disponible');});({$}=f);$('[data-category-id="1"]').click();await pause();
  assert.equal($('#brand-status').textContent,'Catálogo no disponible');assert.equal($('#catalogue-brand-results button').textContent,'Reintentar');
  $('#identify-with-photos').click();assert.equal(f.submit('[data-entry-route=photos]').prevented,false,'catalogue outage retains photo entry');f.dom.window.close();
  f=fixture(defaultResponse);({$}=f);$('[data-category-id="1"]').click();await pause();$('#catalogue-brand-results button').click();await pause();
  $('#identify-with-photos').click();$('#return-catalogue').click();
  assert.equal($('#start-category').value,'1','fallback keeps the category selection');assert.equal($('#known-brand').value,'Caterpillar','fallback keeps the brand selection');assert.equal($('#model-question').hidden,false,'fallback returns to the next unresolved catalogue step');f.dom.window.close();
  let pageTwoAttempts=0;
  f=fixture(url=>{
    if(url.searchParams.get('stage')!=='brands')return defaultResponse(url);
    if(url.searchParams.get('page')==='1')return {items:[{id:11,label:'Caterpillar'}],total:2,has_more:true};
    pageTwoAttempts++;if(pageTwoAttempts===1)throw new Error('Página dos no disponible');
    return {items:[{id:12,label:'Komatsu'}],total:2,has_more:false};
  });({$}=f);$('[data-category-id="1"]').click();await pause();$('#more-brands').click();await pause();
  assert.equal($('#catalogue-brand-results').textContent,'CaterpillarReintentar','a failed second page preserves the first page');$('#catalogue-brand-results button.link-button').click();await pause();
  assert.equal($('#catalogue-brand-results').textContent,'CaterpillarKomatsu','retry keeps prior rows and loads page two');assert.equal(pageTwoAttempts,2,'retry asks for page two again');f.dom.window.close();
  f=fixture(defaultResponse);({$,window}=f);$('[data-category-id="1"]').click();await pause();$('#catalogue-brand-results button').click();await pause();
  let quickSubmission;const form=$('#start-machine-form');form.requestSubmit=button=>{const event=new window.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:button});form.dispatchEvent(event);quickSubmission={prevented:event.defaultPrevented,data:new window.FormData(form)};};
  $('#brand-question [data-quick-entry]').click();
  assert.equal(quickSubmission.prevented,false,'quick photo entry from brand submits immediately');assert.equal(quickSubmission.data.get('entry_mode'),'photos');assert.equal(quickSubmission.data.get('category'),'1');assert.equal(quickSubmission.data.get('brand'),'Caterpillar');f.dom.window.close();
  f=fixture(defaultResponse,{initialCategory:'compactadores'});({$}=f);await pause();
  assert.equal($('#start-category').value,'2','initial category slug preselects the intended scope');assert.equal($('#brand-question').hidden,false);f.dom.window.close();
  f=fixture(defaultResponse);({$,window}=f);$('#start-category-search').value='compactadora';$('#start-category-search').dispatchEvent(new window.Event('input',{bubbles:true}));$('#start-category-results button').click();await pause();
  assert.equal($('#start-category').value,'2','existing category alias search opens exact scope');f.dom.window.close();
  console.log('Start intake DOM PASS: catalogue-first cascade, bounded lazy load, cache, stale requests, alternate routes, explicit selection and duplicate guards.');
})().catch(error=>{console.error(error);process.exitCode=1;});
