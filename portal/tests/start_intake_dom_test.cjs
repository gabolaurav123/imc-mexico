const {JSDOM}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict'),path=require('node:path');
const base=path.join(__dirname,'..');
const html=fs.readFileSync(path.join(base,'templates/portal/start.html'),'utf8').replace(/{%[\s\S]*?%}/g,'').replace(/{{[\s\S]*?}}/g,'');
const catalogue=[{id:1,name:'Excavadoras',slug:'excavadoras',aliases:['excavadora'],fields:[],profile:{}}];
const models=[{id:7,category:1,brand:'Caterpillar',name:'320'}];
const dom=new JSDOM(html+`<script id="category-data" type="application/json">${JSON.stringify(catalogue)}</script><script id="catalogue-intake-data" type="application/json">${JSON.stringify(models)}</script>`,{runScripts:'outside-only'});
const {window}=dom,{document}=window;
window.HTMLElement.prototype.scrollIntoView=function(){};
for (const name of ['category-picker.js','start-intake.js']) window.eval(fs.readFileSync(path.join(base,'static/portal',name),'utf8'));
const $=selector=>document.querySelector(selector),form=$('#start-machine-form');
function submit(button){const event=new window.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:button});form.dispatchEvent(event);return event.defaultPrevented;}
function clickToSubmit(button){
  let captured=null;
  const capture=event=>{
    captured={prevented:event.defaultPrevented,submitter:event.submitter,data:new window.FormData(form)};
    event.preventDefault(); // Keep the test on this page after the native form submission.
  };
  form.addEventListener('submit',capture,{once:true});
  button.click();
  form.removeEventListener('submit',capture);
  return captured;
}
assert.equal($('#identifier-question').hidden,true);
assert.equal(submit($('#identifier-yes .intake-finish')),true,'implicit Enter on hidden default button never creates a draft');
assert.equal(submit($('[data-photo-answer="yes"]')),true,'hidden photo choice cannot create a draft');
const search=$('#start-category-search'); search.value='excavadora'; search.dispatchEvent(new window.Event('input',{bubbles:true}));
$('#start-category-results button').click(); $('#start-category-next').click();
assert.equal($('#start-category').value,'1'); assert.equal($('#identifier-question').hidden,false);
$('[data-identifier-answer="no"]').click();
assert.equal($('#photos-question').hidden,false,'a missing serial asks about photos before choosing a catalogue path');
const photoChoice=$('[data-photo-answer="yes"]'),photoSubmission=clickToSubmit(photoChoice);
assert.equal($('#photos-yes'),null,'there is no intermediate photo confirmation screen');
assert.equal(photoChoice.type,'submit','photo choice uses the existing native form POST');
assert.equal(form.method,'post');
assert.ok(photoSubmission,'one click on the photo choice submits the existing intake form');
assert.equal(photoSubmission.prevented,false); assert.equal(photoSubmission.submitter,photoChoice);
assert.equal(photoSubmission.data.get('entry_mode'),'photos'); assert.equal(photoSubmission.data.get('category'),'1'); assert.equal(photoSubmission.data.get('serial'),'');
$('[data-photo-answer="no"]').click();
assert.equal($('#catalogue-question').hidden,false);
$('#catalogue-brand-select').value='Caterpillar'; $('#catalogue-brand-select').dispatchEvent(new window.Event('change',{bubbles:true}));
assert.equal($('#catalogue-model-select').disabled,false); $('#catalogue-model-select').value='7'; $('#catalogue-model-select').dispatchEvent(new window.Event('change',{bubbles:true}));
assert.equal(submit($('#catalogue-question .intake-finish')),false); assert.equal($('#catalogue-model').value,'7'); assert.equal($('#start-entry-mode').value,'catalogue');
$('#catalogue-manual-toggle').click(); $('#catalogue-manual-brand').value='Marca conocida'; $('#catalogue-manual-model').value='Modelo conocido';
assert.equal(submit($('#catalogue-question .intake-finish')),false); assert.equal($('#start-entry-mode').value,'manual_identity');
$('#catalogue-question [data-photo-back]').click(); $('#photos-question [data-identifier-back]').click(); $('[data-identifier-answer="yes"]').click();
assert.equal(submit($('#identifier-yes .intake-finish')),true,'yes must choose plate or typed input before creating a draft');
$('[data-identifier-choice="plate"]').click();
assert.equal(submit($('#identifier-yes .intake-finish')),false); assert.equal($('#start-entry-mode').value,'plate'); assert.equal($('#start-serial').value,'');
$('[data-identifier-choice="typed"]').click(); $('#typed-serial').value='  SERIAL-QA-001  '; $('#typed-serial').dispatchEvent(new window.Event('input',{bubbles:true}));
assert.equal(submit($('#identifier-yes .intake-finish')),false); assert.equal($('#start-serial').value,'SERIAL-QA-001');
// The AI can identify the type from a serial or photographs alone.
$('#start-category').value='';
assert.equal(submit($('#identifier-yes .intake-finish')),false,'serial-only entry permits an unknown category');
$('#typed-serial').value=''; $('#typed-serial').dispatchEvent(new window.Event('input',{bubbles:true}));
assert.equal(submit($('#identifier-yes .intake-finish')),true,'typed serial still requires a value');
assert.equal($('#typed-serial').validity.valid,false);
$('#identifier-yes [data-identifier-back]').click(); $('[data-identifier-answer="no"]').click();
const optionalTypeSubmission=clickToSubmit(photoChoice);
assert.ok(optionalTypeSubmission,'abandoning an invalid typed serial does not block the photos route');
assert.equal(optionalTypeSubmission.prevented,false,'photo-only entry permits an unknown category');
assert.equal(optionalTypeSubmission.data.get('category'),''); assert.equal(optionalTypeSubmission.data.get('entry_mode'),'photos'); assert.equal(optionalTypeSubmission.data.get('serial'),'');
$('[data-photo-answer="no"]').click();
assert.equal($('#type-question').hidden,false,'catalogue route retains its category requirement');
dom.window.close();console.log('Start intake DOM PASS: direct native photo entry, optional AI type, serial, plate, catalogue, manual identity, and guards.');
