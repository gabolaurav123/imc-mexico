const {JSDOM,VirtualConsole}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict');
const path=require('node:path'),{execFileSync}=require('node:child_process');

const html=execFileSync(process.env.PYTHON||'python',[path.join(__dirname,'render_quick_fixture.py')],{
  cwd:path.resolve(__dirname,'../..'),encoding:'utf8',maxBuffer:4*1024*1024,
  env:{...process.env,PYTHONIOENCODING:'utf-8'}
});
const script=fs.readFileSync(path.join(__dirname,'../static/portal/app.js'),'utf8');
const modalScript=fs.readFileSync(path.join(__dirname,'../static/portal/share-modal.js'),'utf8');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const response=(status,body)=>({ok:status>=200&&status<300,status,headers:{get:()=> 'application/json'},json:async()=>body});
const errors=[],virtualConsole=new VirtualConsole();
virtualConsole.on('jsdomError',error=>{if(!error.message.includes('navigation'))errors.push(error.message);});
const dom=new JSDOM(html,{url:'https://test.invalid/panel/maquinarias/test/?paso=2',runScripts:'outside-only',virtualConsole});
const w=dom.window,doc=w.document;
w.HTMLElement.prototype.scrollIntoView=function(){};
w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
w.HTMLDialogElement.prototype.close=function(){this.open=false;};
const copied=[];Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async value=>copied.push(value)}});
const sheetButton=doc.createElement('button');sheetButton.type='button';sheetButton.dataset.shareMachineId='sheet-owner';sheetButton.dataset.shareRevision='7';sheetButton.dataset.shareIncludeSerial='false';sheetButton.dataset.shareIncludeContact='false';sheetButton.textContent='Compartir ficha';doc.body.append(sheetButton);
const failedSheetButton=doc.createElement('button');failedSheetButton.type='button';failedSheetButton.dataset.shareMachineId='sheet-owner';failedSheetButton.dataset.shareRevision='999';failedSheetButton.dataset.shareIncludeSerial='false';failedSheetButton.dataset.shareIncludeContact='false';failedSheetButton.textContent='Compartir ficha';doc.body.append(failedSheetButton);
const failedJsonSheetButton=doc.createElement('button');failedJsonSheetButton.type='button';failedJsonSheetButton.dataset.shareMachineId='sheet-owner';failedJsonSheetButton.dataset.shareRevision='998';failedJsonSheetButton.dataset.shareIncludeSerial='false';failedJsonSheetButton.dataset.shareIncludeContact='false';failedJsonSheetButton.textContent='Compartir ficha';doc.body.append(failedJsonSheetButton);

const state=JSON.parse(doc.querySelector('#machine-state').textContent);
state.data={...state.data,serial:'SERIE-PRIVADA-001',contact_public:'contacto@example.invalid'};
doc.querySelector('#machine-state').textContent=JSON.stringify(state);
doc.querySelectorAll('[data-field],[data-top-field]').forEach(input=>{
  const key=input.dataset.field||input.dataset.topField,value=input.dataset.topField?state[key]:state.data[key];
  if(input.type==='checkbox')input.checked=Boolean(value);else input.value=value??'';
});
const safeTemplate=doc.querySelector('.asset-card[data-asset-id="1"]');
for(let number=2;number<=11;number++){
  const card=safeTemplate.cloneNode(true);card.dataset.assetId=`safe-${number}`;card.dataset.kind='image';card.dataset.purpose='general';card.dataset.position=String(number);
  card.querySelector('a').href=`/archivos/safe-${number}/?original=1`;card.querySelector('img').src=`/archivos/safe-${number}/`;
  doc.querySelector('#asset-grid').append(card);
}

let releaseFirstSave;
const calls=[];
w.fetch=async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):null;
  calls.push({url:String(url),body});
  if(String(url).endsWith('/guardar/')){
    if(calls.filter(call=>call.url.endsWith('/guardar/')).length===1)await new Promise(resolve=>releaseFirstSave=resolve);
    return response(200,{revision:body.revision+1});
  }
  if(String(url).endsWith('/compartir/')){
    if(body.revision===999)return {ok:false,status:500,headers:{get:()=> 'text/html'},json:async()=>({})};
    if(body.revision===998)return response(500,{error:'El servidor no pudo preparar el enlace.'});
    if(body.revision===7)return response(200,{revision:8,url:'/s/ficha-propietario/'});
    if(body.action==='enable')return response(200,{revision:4,url:'/ficha/enlace-corto-prueba/'});
    if(body.action==='disable')return response(200,{revision:5});
  }
  throw Error('Unexpected request '+url);
};
w.eval(modalScript);
w.eval(script);

function input(id,value){const node=doc.getElementById(id);node.value=value;node.dispatchEvent(new w.Event('input',{bubbles:true}));}
function click(node){node.click();}

(async()=>{
  const cover=[...doc.querySelectorAll('#preview-cover a')],extras=[...doc.querySelectorAll('#preview-extra-grid a')];
  assert.equal(cover.length,4,'the carousel keeps the first four general photos');
  assert.equal(extras.length,6,'the ready sheet exposes at most six additional general photos');
  assert.deepEqual(cover.map(link=>new URL(link.href).pathname),['/archivos/1/','/archivos/safe-2/','/archivos/safe-3/','/archivos/safe-4/']);
  assert.deepEqual(extras.map(link=>new URL(link.href).pathname),['/archivos/safe-5/','/archivos/safe-6/','/archivos/safe-7/','/archivos/safe-8/','/archivos/safe-9/','/archivos/safe-10/']);
  assert.equal(doc.querySelector('#preview-cover a[href*="/archivos/2/"]'),null,'plates never enter the shared carousel');
  assert.equal(doc.querySelector('#preview-cover a[href*="/archivos/3/"]'),null,'documents never enter the shared carousel');
  assert.ok(doc.querySelector('#private-asset-grid [data-asset-id="2"]'),'the plate remains private');
  assert.ok(doc.querySelector('#private-asset-grid [data-asset-id="3"]'),'the document remains private');
  const shareButtons=[...doc.querySelectorAll('[data-share-machine]')];
  assert.equal(shareButtons.length,2,'both share entry points are available');
  const serial=doc.querySelector('#share-serial'),contact=doc.querySelector('#contact-consent');
  assert.equal(serial.closest('.share-serial-choice').hidden,false,'a saved serial has an explicit sharing choice');
  assert.equal(serial.checked,false);assert.equal(contact.checked,false);

  input('brand','Marca corregida');
  click(shareButtons[0]);
  await pause(15);
  assert.equal(calls.filter(call=>call.url.endsWith('/guardar/')).length,1,'sharing flushes the pending correction first');
  assert.equal(calls.filter(call=>call.url.endsWith('/compartir/')).length,0,'the link is not enabled from an unsaved revision');
  input('model','Modelo corregido mientras guarda');
  releaseFirstSave();
  await pause(45);
  const saves=calls.filter(call=>call.url.endsWith('/guardar/'));
  assert.equal(saves.length,2,'a correction made during the first save is retained and flushed');
  assert.deepEqual(saves[0].body.data,{brand:'Marca corregida'});
  assert.equal(saves[1].body.revision,2);
  assert.deepEqual(saves[1].body.data,{model:'Modelo corregido mientras guarda'});
  const firstEnable=calls.find(call=>call.url.endsWith('/compartir/')&&call.body.action==='enable');
  assert.deepEqual(firstEnable.body,{revision:3,action:'enable',include_serial:false,include_contact:false});
  assert.equal(doc.querySelector('#brand').value,'Marca corregida');
  assert.equal(doc.querySelector('#model').value,'Modelo corregido mientras guarda');

  const shared='https://test.invalid/ficha/enlace-corto-prueba/';
  const modal=doc.querySelector('#share-modal');
  assert.equal(modal.open,true,'the ready editor opens the share modal without navigation');
  assert.equal(doc.querySelector('#share-modal-url').value,shared);
  const whatsapp=new URL(doc.querySelector('[data-share-whatsapp]').href),facebook=new URL(doc.querySelector('[data-share-facebook]').href);
  assert.equal(whatsapp.origin,'https://wa.me');assert.match(whatsapp.searchParams.get('text'),/Borrador de prueba/);assert.match(whatsapp.searchParams.get('text'),/https:\/\/test\.invalid\/ficha\/enlace-corto-prueba\//);
  assert.equal(facebook.searchParams.get('u'),shared);
  click(doc.querySelector('[data-copy-share-link]'));await pause(5);
  assert.deepEqual(copied,[shared]);

  click(doc.querySelector('#revoke-sheet-link'));
  await pause(25);
  const revoke=calls.find(call=>call.url.endsWith('/compartir/')&&call.body.action==='disable');
  assert.deepEqual(revoke.body,{revision:4,action:'disable'});
  assert.equal(modal.open,false);

  serial.checked=true;contact.checked=true;
  click(shareButtons[1]);
  await pause(25);
  const enables=calls.filter(call=>call.url.endsWith('/compartir/')&&call.body.action==='enable');
  assert.equal(enables.length,2,'the lower share entry point follows the same flow');
  assert.deepEqual(enables[1].body,{revision:5,action:'enable',include_serial:true,include_contact:true});
  assert.equal(modal.open,true);

  click(sheetButton);await pause(15);
  assert.equal(doc.querySelector('#share-modal-url').value,'https://test.invalid/s/ficha-propietario/');
  assert.equal(sheetButton.dataset.shareSheet,'/s/ficha-propietario/');
  click(failedSheetButton);await pause(15);
  assert.equal(doc.querySelector('#share-modal-url').value,'','an HTML 500 cannot leave a stale share URL visible');
  assert.match(doc.querySelector('#share-modal-feedback').textContent,/No se pudo preparar el enlace/);
  assert.doesNotMatch(doc.querySelector('#share-modal-feedback').textContent,/conexi.n/i);
  click(failedJsonSheetButton);await pause(15);
  assert.equal(doc.querySelector('#share-modal-feedback').textContent,'El servidor no pudo preparar el enlace.');
  assert.deepEqual(errors,[],'No uncaught browser JS errors');
  dom.window.close();
  console.log('Sharing DOM PASS: pending saves, revisions, modal sharing, privacy opt-ins, copy and revocation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
