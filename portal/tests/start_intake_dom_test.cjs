const {JSDOM}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict'),path=require('node:path');
const base=path.join(__dirname,'..');
const html=fs.readFileSync(path.join(base,'templates/portal/start.html'),'utf8').replace(/{%[\s\S]*?%}/g,'').replace(/{{[\s\S]*?}}/g,'');
const categories=[{id:1,name:'Excavadoras',slug:'excavadoras',aliases:['excavadora']},{id:2,name:'Compactadores',slug:'compactadores',aliases:['compactadora']},...Array.from({length:8},(_,i)=>({id:i+3,name:`Equipo ${i+3}`,slug:`equipo-${i+3}`,aliases:[]}))];
function fixture(options={}){
  const dom=new JSDOM(html+`<script id="category-data" type="application/json">${JSON.stringify(categories)}</script>`,{runScripts:'outside-only',url:'https://portal.example/panel/maquinarias/nueva/'});
  const {window}=dom,$=selector=>window.document.querySelector(selector),submissions=[],calls=[];
  if(options.initialCategory)$('[data-intake-start]').dataset.initialCategory=options.initialCategory;
  if(options.navigationType)window.performance.getEntriesByType=()=>[{type:options.navigationType}];
  window.fetch=async url=>{calls.push(url);throw Error('The start screen must not query brands or models');};
  const form=$('#start-machine-form');
  const submit=button=>{
    const event=new window.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:button});
    form.dispatchEvent(event);
    const result={prevented:event.defaultPrevented,data:new window.FormData(form)};
    if(!result.prevented)submissions.push(result.data);
    return result;
  };
  form.requestSubmit=submit;
  for(const name of ['category-picker.js','start-intake.js'])window.eval(fs.readFileSync(path.join(base,'static/portal',name),'utf8'));
  return {dom,window,$,submissions,calls,submit:()=>submit($('#start-continue'))};
}
let f=fixture(),{$,window}=f;
assert.equal(f.submissions.length,0,'opening the selector does not create a draft');
assert.equal(f.submit().prevented,true,'an unselected type cannot continue');
assert.match($('#intake-error').textContent,/Selecciona el tipo/);
assert.equal($('#brand-question'),null,'no brand question before photos');
assert.equal($('#model-question'),null,'no model question before photos');
assert.equal($('#identify-question'),null,'no duplicate photo/serial choice before the wizard');
assert.equal($('#popular-categories').children.length,8);
$('#show-all-categories').click();assert.equal($('#popular-categories').children.length,10);
$('[data-category-id="1"]').click();
assert.equal(f.submissions.length,1,'one category click directly opens the evidence step');
assert.equal(f.submissions[0].get('category'),'1');assert.equal(f.submissions[0].get('entry_mode'),'photos');
for(const key of ['brand','model','catalogue_model','catalogue_enrichment','serial'])assert.equal(f.submissions[0].has(key),false,`${key} is not requested before evidence`);
assert.equal(f.calls.length,0,'selecting a type has no brand/model catalogue network wait');
assert.equal($('#intake-progress').hidden,false);
$('[data-category-id="2"]').click();assert.equal(f.submissions.length,1,'a second click cannot create another draft');
assert.equal($('#start-category').value,'1','duplicate clicks cannot change the in-flight category');
const back=new window.Event('pageshow');Object.defineProperty(back,'persisted',{value:true});window.dispatchEvent(back);
assert.equal(f.submissions.length,1,'browser back never submits automatically');
assert.equal($('#intake-progress').hidden,true);assert.equal($('#start-continue').hidden,false);
$('[data-category-id="2"]').click();assert.equal(f.submissions.length,2,'browser back allows a new category choice');assert.equal(f.submissions[1].get('category'),'2');f.dom.window.close();
f=fixture();({$,window}=f);
$('#start-category-search').value='compactadora';$('#start-category-search').dispatchEvent(new window.Event('input',{bubbles:true}));
assert.equal(f.submissions.length,0,'typing alone never chooses a machine');
$('#start-category-search').dispatchEvent(new window.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
assert.equal(f.submissions.length,1,'Enter selects the matching type and opens evidence');assert.equal(f.submissions[0].get('category'),'2');assert.equal(f.calls.length,0);f.dom.window.close();
f=fixture({initialCategory:'excavadoras'});assert.equal(f.submissions.length,1,'a homepage type shortcut goes directly to the evidence step');assert.equal(f.submissions[0].get('category'),'1');f.dom.window.close();
for(const navigationType of ['back_forward','reload']){
  f=fixture({initialCategory:'excavadoras',navigationType});
  assert.equal(f.submissions.length,0,'history and reload do not repeat the shortcut POST');
  assert.equal(f.$('#start-category').value,'1');assert.equal(f.$('#start-continue').hidden,false);
  assert.equal(f.submit().prevented,false,'the chosen type can be explicitly continued');f.dom.window.close();
}
f=fixture({initialCategory:'unknown'});assert.equal(f.submissions.length,0,'unknown shortcuts remain in the selector');f.dom.window.close();
console.log('Start intake DOM PASS: type-only entrance, direct evidence navigation, keyboard search, homepage shortcuts, browser back and duplicate protection.');
