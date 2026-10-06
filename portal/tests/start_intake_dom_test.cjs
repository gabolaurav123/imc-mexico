const {JSDOM}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict'),path=require('node:path');
const base=path.join(__dirname,'..');
const html=fs.readFileSync(path.join(base,'templates/portal/start.html'),'utf8').replace(/{%[\s\S]*?%}/g,'').replace(/{{[\s\S]*?}}/g,'');
const categories=[{id:1,name:'Excavadoras',slug:'excavadoras',aliases:['excavadora']},{id:2,name:'Compactadores',slug:'compactadores',aliases:['compactadora']}];
const pause=()=>new Promise(resolve=>setTimeout(resolve,0));
function fixture(responder){
  const dom=new JSDOM(html+`<script id="category-data" type="application/json">${JSON.stringify(categories)}</script>`,{runScripts:'outside-only',url:'https://portal.example/panel/maquinarias/nueva/'});
  const {window}=dom,$=selector=>window.document.querySelector(selector),calls=[];
  $('[data-intake-start]').dataset.catalogueUrl='/api/maquinarias/catalogo/descubrir/';
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
  f=fixture(defaultResponse);({$,window}=f);$('#start-category-search').value='compactadora';$('#start-category-search').dispatchEvent(new window.Event('input',{bubbles:true}));$('#start-category-results button').click();await pause();
  assert.equal($('#start-category').value,'2','existing category alias search opens exact scope');f.dom.window.close();
  console.log('Start intake DOM PASS: catalogue-first cascade, bounded lazy load, cache, stale requests, alternate routes, explicit selection and duplicate guards.');
})().catch(error=>{console.error(error);process.exitCode=1;});
