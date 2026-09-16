const {JSDOM,VirtualConsole}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict');
const path=require('node:path'),{execFileSync}=require('node:child_process');
const html=execFileSync(process.env.PYTHON || 'python',[path.join(__dirname,'render_quick_fixture.py')],{cwd:path.resolve(__dirname,'../..'),encoding:'utf8',maxBuffer:4*1024*1024,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
const script=fs.readFileSync(path.join(__dirname,'../static/portal/app.js'),'utf8');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const response=(status,result)=>({ok:status>=200&&status<300,status,headers:{get:()=> 'application/json'},json:async()=>result});
let checks=0;
function pass(name){checks++;console.log('PASS '+name);}
function setup(fetcher,options={}){
 const errors=[],console=new VirtualConsole();console.on('jsdomError',e=>{if(!e.message.includes('navigation'))errors.push(e.message);});
 const dom=new JSDOM(html,{url:'https://test.invalid/panel/maquinarias/test/'+(options.query||''),runScripts:'outside-only',virtualConsole:console});
 const w=dom.window,doc=w.document;w.HTMLElement.prototype.scrollIntoView=function(){};w.fetch=fetcher;w.confirm=()=>true;
 Object.defineProperty(w.navigator,'onLine',{value:true,writable:true});
 const state=JSON.parse(doc.querySelector('#machine-state').textContent);
 Object.assign(state,options.state||{});state.data={...state.data,...options.data};
 if(options.readonly){state.editable=false;doc.querySelector('#wizard').dataset.editable='false';}
 doc.querySelector('#machine-state').textContent=JSON.stringify(state);
 doc.querySelectorAll('[data-field],[data-top-field]').forEach(input=>{const key=input.dataset.field||input.dataset.topField,value=input.dataset.topField?state[key]:state.data[key];if(input.type==='checkbox')input.checked=Boolean(value);else input.value=value??(key==='currency'?'MXN':'');});
 if(options.job){const node=doc.createElement('script');node.id='current-job';node.type='application/json';node.textContent=JSON.stringify(options.job);doc.body.append(node);}
 if(options.fastPoll){const original=w.setTimeout.bind(w);w.setTimeout=(fn,ms,...args)=>original(fn,ms===2500?30:ms,...args);}
 if(options.before)options.before(w);
 w.eval(script);
 return {dom,w,doc,state,errors,close(){assert.deepEqual(errors,[],'No uncaught browser JS errors');dom.window.close();}};
}
function input(ctx,id,value){const node=ctx.doc.getElementById(id);assert.ok(node,'input '+id);node.value=value;node.dispatchEvent(new ctx.w.Event(node.tagName==='SELECT'?'change':'input',{bubbles:true}));}
function click(ctx,id){ctx.doc.getElementById(id).click();}
function completed(state,extra={},metadata={}){return {id:'job',status:'completed',result:{data:extra,provenance:{},warnings:[],questions:[]},machine:{...state,revision:state.revision+1,data:{...state.data,...extra}},auto_apply:{requested:true,status:'applied',applied_fields:Object.keys(extra),skipped_fields:[],revision_before:state.revision,revision_after:state.revision+1,...metadata}};}
(async()=>{
 let saves=[],release;
 const c=setup(async(url,o)=>{assert.ok(url.endsWith('guardar/'));const body=JSON.parse(o.body);saves.push(body);if(saves.length===1)await new Promise(resolve=>release=resolve);return response(200,{revision:body.revision+1});});
 assert.equal(c.doc.querySelectorAll('[data-step-panel]').length,2);assert.equal(c.doc.querySelector('#contact-consent').checked,false);assert.equal(c.doc.querySelector('#contact-details').open,false);
 assert.equal(c.doc.querySelector('#hours').value,'0');assert.equal(c.doc.querySelector('#extra-power').value,'100 kW','populated technical field visible without category');
 input(c,'brand','Primero');await pause(900);assert.equal(saves.length,1);assert.deepEqual(saves[0].data,{brand:'Primero'});assert.deepEqual(Object.keys(saves[0].provenance),['brand']);
 input(c,'brand','Último');release();await pause(80);assert.equal(saves.length,2);assert.equal(saves[1].revision,2);assert.equal(saves[1].data.brand,'Último');assert.match(c.doc.querySelector('#preview-specs').textContent,/Horas0/);
 input(c,'model','');await pause(900);assert.ok(Object.hasOwn(saves[2].data,'model'));assert.equal(saves[2].data.model,null,'intentional clear protected');c.close();pass('2 steps, contact opt-in, technical fields without category, zero, partial autosave and in-flight edits');

 let attempts=0;
 const offline=setup(async(url,o)=>{if(++attempts===1)throw new TypeError('Network interrupted');return response(200,{revision:JSON.parse(o.body).revision+1});});
 input(offline,'model','Conservado');await pause(900);assert.equal(offline.doc.querySelector('#model').value,'Conservado');assert.equal(offline.doc.querySelector('#save-retry').hidden,false);click(offline,'save-retry');await pause(30);assert.equal(attempts,2);assert.equal(offline.doc.querySelector('#save-status').textContent,'Guardado');offline.close();pass('offline save preserves input; explicit retry succeeds');

 let conflicts=0;
 const conflict=setup(async()=>{conflicts++;return response(409,{error:'Otra versión',revision:7});});input(conflict,'brand','Mi corrección');await pause(900);input(conflict,'brand','Mi siguiente corrección');await pause(900);assert.equal(conflicts,1);assert.equal(conflict.doc.querySelector('#brand').value,'Mi siguiente corrección');assert.equal(conflict.doc.querySelector('#save-retry').hidden,true);assert.match(conflict.doc.querySelector('#wizard-errors').textContent,/otra pestaña/);conflict.close();pass('unrelated revision conflict blocks overwrites and retains corrections');

 let analyzeBodies=[],analysisGate,aiState;
 const automatic=setup(async(url,o)=>{if(url.endsWith('analizar/')){analyzeBodies.push(JSON.parse(o.body));await new Promise(resolve=>analysisGate=resolve);return response(200,{id:'job',status:'running'});}if(url.includes('/api/analisis/'))return response(200,completed(aiState,{brand:'Original',model:'Modelo leído',hours:0,weight:'850 kg'}));throw Error(url);});aiState=automatic.state;
 click(automatic,'analyze-button');click(automatic,'analyze-button');await pause(10);assert.equal(analyzeBodies.length,1);assert.deepEqual(analyzeBodies[0].asset_ids,['1','2']);assert.equal(analyzeBodies[0].consent,true);assert.equal(analyzeBodies[0].auto_apply,true);assert.equal(analyzeBodies[0].revision,1);
 input(automatic,'brand','Corrección mientras analiza');analysisGate();await pause(80);assert.equal(automatic.doc.querySelector('#brand').value,'Corrección mientras analiza');assert.equal(automatic.doc.querySelector('#model').value,'Modelo leído');assert.equal(automatic.doc.querySelector('#extra-weight').value,'850 kg');assert.equal(automatic.doc.querySelector('[data-step-panel="2"]').hidden,false);assert.equal(automatic.doc.querySelectorAll('#analysis-results input').length,0);automatic.close();pass('single action consent, deduplication, image selection and AI hydration preserving dirty input');

 let ownState,saveCount=0,jobGets=0;
 const own=setup(async(url,o)=>{if(url.includes('/api/analisis/')){jobGets++;if(jobGets===1)return response(200,{id:'job',status:'running'});return response(200,completed(ownState,{model:'IA guardada'}));}if(url.endsWith('guardar/')){saveCount++;const body=JSON.parse(o.body);if(saveCount===1)return response(409,{error:'revision IA',revision:2});assert.equal(body.revision,2);assert.deepEqual(body.data,{location:'Mi ubicación humana'});return response(200,{revision:3});}throw Error(url);},{job:{id:'job',status:'running'}});ownState=own.state;input(own,'location','Mi ubicación humana');await pause(950);assert.equal(saveCount,2);assert.equal(own.doc.querySelector('#location').value,'Mi ubicación humana');assert.equal(own.doc.querySelector('#model').value,'IA guardada');assert.equal(own.doc.querySelector('#save-status').textContent,'Guardado');own.close();pass('known worker revision rebases once and saves human edits without overwriting IA fields');

 let legacyCalls=[],legacyState;
 const legacy=setup(async(url,o)=>{legacyCalls.push(url);if(url.includes('/api/analisis/'))return response(200,{id:'old',status:'completed',result:{data:{model:'Anterior'}},machine:legacyState,auto_apply:{requested:false,status:'disabled'}});if(url.endsWith('aplicar/')){const body=JSON.parse(o.body);assert.equal(body.automatic,true);assert.equal(body.job_id,'old');const j=completed(legacyState,{model:'Anterior'});return response(200,{machine:j.machine,auto_apply:j.auto_apply});}throw Error(url);},{job:{id:'old',status:'completed'},query:'?paso=5'});legacyState=legacy.state;await pause(70);assert.equal(legacyCalls.filter(u=>u.endsWith('aplicar/')).length,1);assert.equal(legacyCalls.filter(u=>u.endsWith('analizar/')).length,0);assert.equal(legacy.doc.querySelector('#model').value,'Anterior');assert.equal(legacy.w.location.search,'?paso=2');legacy.close();pass('legacy completed job reused without paid analysis; old step 5 maps to step 2');

 let readonlyCalls=[],readState;
 const readonly=setup(async(url)=>{readonlyCalls.push(url);return response(200,{id:'old',status:'completed',result:{data:{}},machine:readState,auto_apply:{requested:false,status:'disabled'}});},{readonly:true,job:{id:'old',status:'completed'}});readState=readonly.state;await pause(30);click(readonly,'analyze-button');click(readonly,'submit-machine');assert.equal(readonlyCalls.length,1);assert.equal(readonly.doc.querySelector('#brand').disabled,true);readonly.close();pass('read-only records inspect results without applying or writing');

 let submitBody,submitRelease,submitCount=0;
 const submit=setup(async(url,o)=>{if(url.endsWith('enviar/')){submitCount++;submitBody=JSON.parse(o.body);await new Promise(resolve=>submitRelease=resolve);return response(500,{error:'Prueba de respuesta recuperable'});}throw Error(url);});submit.doc.querySelector('[data-asset-action]').disabled=true;click(submit,'submit-machine');click(submit,'submit-machine');await pause(10);assert.equal(submitCount,1);assert.equal(submit.doc.querySelector('#brand').disabled,true);assert.equal(submit.doc.querySelector('[data-file-open]').disabled,true);assert.deepEqual(submitBody,{advertise_consent:true,contact_consent:false});submitRelease();await pause(30);assert.equal(submit.doc.querySelector('#submit-machine').disabled,false);assert.equal(submit.doc.querySelector('#brand').disabled,false);assert.equal(submit.doc.querySelector('#brand').value,'Original');assert.equal(submit.doc.querySelector('[data-asset-action]').disabled,false,'completed asset action unlocks after send failure');submit.close();pass('final action authorizes review once; public contact stays false; failed submit retains inputs');

 const required=setup(async()=>{throw Error('No API expected');},{state:{title:'Mi maquinaria'},data:{location:''}});click(required,'submit-machine');await pause(15);assert.equal(required.doc.activeElement.id,'location');required.doc.querySelector('#location').value='Ciudad';click(required,'submit-machine');await pause(15);assert.equal(required.doc.activeElement.id,'machine-title');assert.equal(required.doc.querySelector('#edit-information').open,true);required.close();pass('required location visible; missing title opens edit details and focuses field');

 let failState;
 const failed=setup(async(url)=>{if(url.includes('/api/analisis/'))return response(200,{id:'failed',status:'failed',error:'No pudimos leer',machine:failState});throw Error(url);},{job:{id:'failed',status:'failed'}});failState=failed.state;await pause(20);assert.equal(failed.doc.querySelector('#analyze-button').disabled,false);assert.equal(failed.doc.querySelector('#brand').value,'Original');assert.equal(failed.doc.querySelector('#asset-grid').children.length,4);click(failed,'manual-continue');assert.equal(failed.doc.querySelector('[data-step-panel="2"]').hidden,false);failed.close();pass('failed analysis keeps photos and editable manual route');

 let uploadFinish,uploadState,uploadAnalyzed=0;
 const upload=setup(async(url,o)=>{if(url.endsWith('analizar/')){uploadAnalyzed++;const body=JSON.parse(o.body);assert.ok(body.asset_ids.includes('new'));assert.equal(body.revision,2);return response(200,{id:'job',status:'running'});}if(url.includes('/api/analisis/'))return response(200,{id:'job',status:'failed',error:'Manual available'});throw Error(url);},{before(w){w.XMLHttpRequest=class extends w.EventTarget{constructor(){super();this.upload=new w.EventTarget();}open(){}setRequestHeader(){}send(){uploadFinish=()=>{this.status=200;this.responseText=JSON.stringify({id:'new',kind:'image',purpose:'general',revision:2,is_cover:false});this.dispatchEvent(new w.Event('load'));};}};}});
 const gallery=upload.doc.querySelector('#gallery-input');Object.defineProperty(gallery,'files',{value:[new upload.w.File(['sample'],'sample.jpg',{type:'image/jpeg'})]});gallery.dispatchEvent(new upload.w.Event('change'));click(upload,'analyze-button');click(upload,'analyze-button');await pause(20);assert.equal(uploadAnalyzed,0);assert.equal(typeof uploadFinish,'function');uploadFinish();await pause(50);assert.equal(uploadAnalyzed,1);upload.close();pass('preparation waits queued uploads and uses uploaded asset with latest revision');

 let resumeRelease,resumeCalls=0,resumeState;
 const resume=setup(async(url)=>{resumeCalls++;assert.ok(url.includes('/api/analisis/'));await new Promise(resolve=>resumeRelease=resolve);return response(200,completed(resumeState,{}));},{job:{id:'old',status:'completed'}});resumeState=resume.state;
 assert.equal(resume.doc.querySelector('#analyze-button').disabled,true);click(resume,'analyze-button');assert.equal(resumeCalls,1);resumeRelease();await pause(40);assert.equal(resume.doc.querySelector('#analyze-button').disabled,false);resume.close();pass('resuming completed job blocks new preparation until poll/application finishes');

 let frozenRelease,frozenCalls=[];
 const frozen=setup(async(url,o)=>{frozenCalls.push(url);if(url.endsWith('enviar/')){await new Promise(resolve=>frozenRelease=resolve);return response(200,{url:'/panel/solicitudes/'});}throw Error('mutation during sending');});
 click(frozen,'submit-machine');await pause(20);
 const dropEvent=new frozen.w.Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(dropEvent,'dataTransfer',{value:{files:[new frozen.w.File(['ignored'],'late.jpg',{type:'image/jpeg'})]}});frozen.doc.querySelector('#drop-zone').dispatchEvent(dropEvent);
 const action=frozen.doc.querySelector('[data-asset-action]');action.dispatchEvent(new frozen.w.Event('click',{bubbles:true}));
 assert.equal(frozen.doc.querySelector('#upload-queue').children.length,0);assert.equal(frozenCalls.length,1);
 const before=new frozen.w.Event('beforeunload',{cancelable:true});frozen.w.dispatchEvent(before);assert.equal(before.defaultPrevented,true);
 frozenRelease();await pause(30);const after=new frozen.w.Event('beforeunload',{cancelable:true});frozen.w.dispatchEvent(after);assert.equal(after.defaultPrevented,false);frozen.close();pass('sending blocks drop and asset mutations; success clears navigation warning');

 console.log(JSON.stringify({suite:'quick-intake-dom',checks,passed:checks,uncaughtErrors:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
