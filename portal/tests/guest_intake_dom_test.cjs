const {JSDOM,VirtualConsole}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict');
const path=require('node:path'),{execFileSync}=require('node:child_process');

const html=execFileSync(process.env.PYTHON||'python',[path.join(__dirname,'render_quick_fixture.py'),'--guest'],{
  cwd:path.resolve(__dirname,'../..'),encoding:'utf8',maxBuffer:4*1024*1024,
  env:{...process.env,PYTHONIOENCODING:'utf-8'}
});
const script=fs.readFileSync(path.join(__dirname,'../static/portal/app.js'),'utf8');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const response=(status,body)=>({ok:status>=200&&status<300,status,headers:{get:()=> 'application/json'},json:async()=>body});

const errors=[],virtualConsole=new VirtualConsole();
virtualConsole.on('jsdomError',error=>{if(!error.message.includes('navigation'))errors.push(error.message);});
const dom=new JSDOM(html,{url:'https://test.invalid/invitados/guest-draft-fixture/',runScripts:'outside-only',virtualConsole});
const w=dom.window,doc=w.document;
w.HTMLElement.prototype.scrollIntoView=function(){};
const calls=[];
const state=JSON.parse(doc.querySelector('#machine-state').textContent);
const completed={id:'job-guest',status:'completed',result:{data:{model:'320D'},provenance:{},warnings:[],questions:[]},
  machine:{...state,revision:2,data:{...state.data,model:'320D'}},
  auto_apply:{requested:true,status:'applied',applied_fields:['model'],skipped_fields:[],revision_before:1,revision_after:2}};
let finishUpload;
w.XMLHttpRequest=class extends w.EventTarget {
  constructor(){super();this.upload=new w.EventTarget();}
  open(){}
  setRequestHeader(){}
  send(){finishUpload=()=>{this.status=201;this.responseText=JSON.stringify({id:'new-guest-asset',kind:'image',purpose:'general',position:4,is_cover:false,revision:3});this.dispatchEvent(new w.Event('load'));};}
};
w.fetch=async(url,options={})=>{
  calls.push({url:String(url),method:options.method||'GET',body:options.body&&JSON.parse(options.body)});
  assert.match(String(url),/^\/api\/invitados\/guest-draft-fixture\//,'guest flow never calls an authenticated machine API');
  if(String(url).endsWith('/guardar/')) return response(200,{revision:2,saved_at:'2026-09-25T00:00:00Z',machine:{...state,revision:2}});
  if(String(url).endsWith('/analizar/')) return response(200,{id:'job-guest',status:'queued'});
  if(String(url).endsWith('/analisis/job-guest/')) return response(200,completed);
  throw Error(String(url));
};
w.eval(script);

(async()=>{
  const wizard=doc.querySelector('#wizard');
  assert.equal(wizard.dataset.guest,'guest-draft-fixture');
  assert.equal(wizard.dataset.apiBase,'/api/invitados/guest-draft-fixture/');
  assert.equal(wizard.dataset.maxImages,'3');
  assert.equal(doc.querySelector('#download-draft-pdf'),null,'temporary draft cannot export a PDF');
  assert.equal(doc.querySelector('[data-open-sheet]'),null,'temporary draft cannot open a normal internal sheet');
  assert.ok(doc.querySelector('#guest-save-result'),'claim CTA is present');

  doc.querySelector('#analyze-button').click();
  await wait(35);
  const analysis=calls.find(call=>call.url.endsWith('/analizar/'));
  assert.ok(analysis,'guest analysis endpoint requested');
  assert.equal(analysis.body.auto_apply,true);
  assert.equal(analysis.body.research,true);
  assert.equal(analysis.body.mode,'analysis');
  assert.equal(calls.filter(call=>call.url.includes('/aplicar/')).length,0,'guest never uses the normal apply API');
  assert.equal(doc.querySelector('#model').value,'320D','poll hydrates the guest machine result');
  assert.equal(doc.querySelector('[data-step-panel="2"]').hidden,false,'completed polling displays the result');

  // A claim CTA must not jump to registration while a file remains in the
  // upload chain.  Make a dirty edit only after the upload started, so the
  // observed save is caused by the CTA after uploadsReady resolves.
  const gallery=doc.querySelector('#gallery-input');
  Object.defineProperty(gallery,'files',{value:[new w.File(['sample'],'guest.jpg',{type:'image/jpeg'})]});
  gallery.dispatchEvent(new w.Event('change'));
  await wait(15);
  assert.equal(typeof finishUpload,'function','guest upload is in progress');
  const savesBefore=calls.filter(call=>call.url.endsWith('/guardar/')).length;
  doc.querySelector('#brand').value='CAT corregida';
  doc.querySelector('#brand').dispatchEvent(new w.Event('input',{bubbles:true}));
  doc.querySelector('#submit-machine').click();
  await wait(20);
  assert.equal(calls.filter(call=>call.url.endsWith('/guardar/')).length,savesBefore,'CTA waits for its upload before saving or claiming');
  finishUpload();
  await wait(50);
  assert.ok(calls.filter(call=>call.url.endsWith('/guardar/')).length>savesBefore,'guest CTA saves after the pending upload completes');
  assert.equal(calls.filter(call=>call.url.endsWith('/enviar/')).length,0,'guest CTA never submits for review');
  assert.equal(calls.filter(call=>/\/api\/maquinarias\/|\/api\/analisis\//.test(call.url)).length,0,'no login-required API was requested');
  assert.deepEqual(errors,[],'guest wizard has no browser runtime errors when PDF controls are absent');
  dom.window.close();
  console.log('Guest intake DOM PASS: private base, poll/autofill, claim CTA, no PDF and no authenticated APIs.');
})().catch(error=>{console.error(error);process.exitCode=1;});
