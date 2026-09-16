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
function captureDownloads(w,downloads){
 const original=w.HTMLAnchorElement.prototype.click;
 w.HTMLAnchorElement.prototype.click=function(){if(this.hasAttribute('download')&&this.id!=='download-draft-pdf'){downloads.push({url:this.href,filename:this.download});return;}return original.call(this);};
}
function completed(state,extra={},metadata={}){return {id:'job',status:'completed',result:{data:extra,provenance:{},warnings:[],questions:[]},machine:{...state,revision:state.revision+1,data:{...state.data,...extra}},auto_apply:{requested:true,status:'applied',applied_fields:Object.keys(extra),skipped_fields:[],revision_before:state.revision,revision_after:state.revision+1,...metadata}};}
(async()=>{
 let saves=[],release;
 const c=setup(async(url,o)=>{assert.ok(url.endsWith('guardar/'));const body=JSON.parse(o.body);saves.push(body);if(saves.length===1)await new Promise(resolve=>release=resolve);return response(200,{revision:body.revision+1});});
 assert.equal(c.doc.querySelectorAll('[data-step-panel]').length,2);assert.equal(c.doc.querySelector('#contact-consent').checked,false);assert.equal(c.doc.querySelector('#contact-details').open,false);assert.equal(c.doc.querySelector('#commercial-details').open,false);assert.equal(c.doc.querySelector('#location').closest('details').id,'commercial-details');assert.equal(c.doc.querySelector('#location').required,false);
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
 click(automatic,'analyze-button');click(automatic,'analyze-button');await pause(10);assert.equal(analyzeBodies.length,1);assert.deepEqual(analyzeBodies[0].asset_ids,['1','2']);assert.equal(analyzeBodies[0].consent,true);assert.equal(analyzeBodies[0].auto_apply,true);assert.equal(analyzeBodies[0].research,true);assert.equal(analyzeBodies[0].revision,1);
 input(automatic,'brand','Corrección mientras analiza');analysisGate();await pause(80);assert.equal(automatic.doc.querySelector('#brand').value,'Corrección mientras analiza');assert.equal(automatic.doc.querySelector('#model').value,'Modelo leído');assert.equal(automatic.doc.querySelector('#extra-weight').value,'850 kg');assert.equal(automatic.doc.querySelector('[data-step-panel="2"]').hidden,false);assert.equal(automatic.doc.querySelectorAll('#analysis-results input').length,0);automatic.close();pass('single action consent, deduplication, image selection and AI hydration preserving dirty input');

 let ownState,saveCount=0,jobGets=0;
 const own=setup(async(url,o)=>{if(url.includes('/api/analisis/')){jobGets++;if(jobGets===1)return response(200,{id:'job',status:'running'});return response(200,completed(ownState,{model:'IA guardada'}));}if(url.endsWith('guardar/')){saveCount++;const body=JSON.parse(o.body);if(saveCount===1)return response(409,{error:'revision IA',revision:2});assert.equal(body.revision,2);assert.deepEqual(body.data,{location:'Mi ubicación humana'});return response(200,{revision:3});}throw Error(url);},{job:{id:'job',status:'running'}});ownState=own.state;input(own,'location','Mi ubicación humana');await pause(950);assert.equal(saveCount,2);assert.equal(own.doc.querySelector('#location').value,'Mi ubicación humana');assert.equal(own.doc.querySelector('#model').value,'IA guardada');assert.equal(own.doc.querySelector('#save-status').textContent,'Guardado');own.close();pass('known worker revision rebases once and saves human edits without overwriting IA fields');

 let legacyCalls=[],legacyState;
 const legacy=setup(async(url,o)=>{legacyCalls.push(url);if(url.includes('/api/analisis/'))return response(200,{id:'old',status:'completed',result:{data:{model:'Anterior'}},machine:legacyState,auto_apply:{requested:false,status:'disabled'}});if(url.endsWith('aplicar/')){const body=JSON.parse(o.body);assert.equal(body.automatic,true);assert.equal(body.job_id,'old');const j=completed(legacyState,{model:'Anterior'});return response(200,{machine:j.machine,auto_apply:j.auto_apply});}throw Error(url);},{job:{id:'old',status:'completed'},query:'?paso=5'});legacyState=legacy.state;await pause(70);assert.equal(legacyCalls.filter(u=>u.endsWith('aplicar/')).length,1);assert.equal(legacyCalls.filter(u=>u.endsWith('analizar/')).length,0);assert.equal(legacy.doc.querySelector('#model').value,'Anterior');assert.equal(legacy.w.location.search,'?paso=2');legacy.close();pass('legacy completed job reused without paid analysis; old step 5 maps to step 2');

 let readonlyCalls=[],readState;
 const readonly=setup(async(url)=>{readonlyCalls.push(url);return response(200,{id:'old',status:'completed',result:{data:{}},machine:readState,auto_apply:{requested:false,status:'disabled'}});},{readonly:true,job:{id:'old',status:'completed'}});readState=readonly.state;await pause(30);click(readonly,'analyze-button');click(readonly,'submit-machine');assert.equal(readonlyCalls.length,1);assert.equal(readonly.doc.querySelector('#brand').disabled,true);readonly.close();pass('read-only records inspect results without applying or writing');

 let submitBody,submitRelease,submitCount=0;
 const submit=setup(async(url,o)=>{if(url.endsWith('enviar/')){submitCount++;submitBody=JSON.parse(o.body);await new Promise(resolve=>submitRelease=resolve);return response(500,{error:'Prueba de respuesta recuperable'});}throw Error(url);});submit.doc.querySelector('[data-asset-action]').disabled=true;click(submit,'submit-machine');click(submit,'submit-machine');await pause(10);assert.equal(submitCount,1);assert.equal(submit.doc.querySelector('#brand').disabled,true);assert.equal(submit.doc.querySelector('[data-file-open]').disabled,true);assert.deepEqual(submitBody,{advertise_consent:true,contact_consent:false});submitRelease();await pause(30);assert.equal(submit.doc.querySelector('#submit-machine').disabled,false);assert.equal(submit.doc.querySelector('#brand').disabled,false);assert.equal(submit.doc.querySelector('#brand').value,'Original');assert.equal(submit.doc.querySelector('[data-asset-action]').disabled,false,'completed asset action unlocks after send failure');submit.close();pass('final action authorizes review once; public contact stays false; failed submit retains inputs');

 let optionalRequests=0;
 const optional=setup(async(url)=>{assert.ok(url.endsWith('enviar/'));optionalRequests++;return response(500,{error:'Respuesta de prueba'});},{state:{title:'Mi maquinaria'},data:{location:'',price:null}});click(optional,'submit-machine');await pause(25);assert.equal(optionalRequests,1);assert.equal(optional.doc.querySelector('#commercial-details').open,false);assert.equal(optional.doc.querySelector('#edit-information').open,false);optional.close();pass('title, location and price do not force manual entry before submission');

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

 const sourceMeta={status:'completed',basis:'exact_serial',match:'model',fields:[
   {key:'power',value:'125 kW',scope:'model',source_url:'https://manufacturer.example/specification.pdf',source_title:'<img src=x onerror=alert(1)> Manual del fabricante'},
   {key:'weight',value:'<script>alert(1)</script>',scope:'exact_serial',source_url:'javascript:alert(1)',source_title:'Unsafe'},
   {key:'capacity',value:'2 m³',scope:'model',source_url:'data:text/html,unsafe',source_title:'Unsafe data'}],
   sources:[{url:'https://manufacturer.example/specification.pdf',title:'Ficha técnica'},{url:'https://manufacturer.example/specification.pdf',title:'Duplicado'},{url:'javascript:alert(1)',title:'JS'},{url:'//evil.example/file',title:'Relative'},{url:'https://name:password@example.invalid/file',title:'Credentials'},{url:'data:text/html,unsafe',title:'Data'}],warnings:['La configuración del modelo puede variar.'],proof:{secret:'not displayed'},usage:{tokens:999999}};
 let researched;
 researched=setup(async()=>{await pause(1);const job=completed(researched.state,{description:'Descripción preparada con datos disponibles.'});job.result.research=sourceMeta;return response(200,job);},{job:{id:'job',status:'completed'}});
 await pause(40);const details=researched.doc.querySelector('#analysis-results');assert.equal(details.open,false);assert.equal(details.hidden,false);assert.match(researched.doc.querySelector('#research-brief').textContent,/referencias del modelo/);assert.match(details.textContent,/Referencia del modelo; confirmar en este equipo/);assert.match(details.textContent,/Referencia de la unidad; pendiente de revisión/);
 assert.equal(details.querySelectorAll('img,script,iframe').length,0);assert.equal(details.querySelectorAll('a').length,2);for(const link of details.querySelectorAll('a')){assert.equal(link.href,'https://manufacturer.example/specification.pdf');assert.equal(link.rel,'noopener noreferrer');assert.equal(link.target,'_blank');}
 assert.match(details.textContent,/<script>alert\(1\)<\/script>/);assert.doesNotMatch(details.textContent,/999999|not displayed/);assert.equal(researched.doc.querySelector('#preview-description').textContent,'Descripción preparada con datos disponibles.');researched.close();pass('web sources render safely as text, block unsafe URLs, deduplicate and distinguish model from unit');

 for(const status of ['no_results','insufficient_identifiers','degraded']){
   let noResults;noResults=setup(async()=>{await pause(1);const job=completed(noResults.state,{});job.result.research={status,basis:'none',match:'none',fields:[],sources:[],warnings:[]};return response(200,job);},{job:{id:'job',status:'completed'},data:{description:''}});
   await pause(35);assert.equal(noResults.doc.querySelector('#submit-machine').disabled,false);assert.equal(noResults.doc.querySelector('#research-brief').hidden,false);assert.doesNotMatch(noResults.doc.querySelector('#preview-description').textContent,/manualmente|añadirla|Editar información/i);assert.match(noResults.doc.querySelector('#preview-description').textContent,/No se encontró/);assert.equal(noResults.doc.querySelector('#commercial-details').open,false);noResults.close();
 }
 pass('missing identifiers or unsuccessful research stays nonblocking without requesting manual description');

 let quotaSubmissions=0;
 const quota=setup(async(url)=>{if(url.endsWith('analizar/'))return response(400,{error:'Límite de preparación alcanzado'});if(url.endsWith('enviar/')){quotaSubmissions++;return response(500,{error:'Respuesta de prueba'});}throw Error(url);},{state:{title:'Mi maquinaria'},data:{location:'',description:''}});
 click(quota,'analyze-button');await pause(30);assert.match(quota.doc.querySelector('#preview-description').textContent,/No se encontró/);assert.doesNotMatch(quota.doc.querySelector('#preview-description').textContent,/manualmente|añadirla/);click(quota,'manual-continue');click(quota,'submit-machine');await pause(30);assert.equal(quotaSubmissions,1);assert.equal(quota.doc.querySelector('#edit-information').open,false);quota.close();pass('quota rejection offers existing-photo submission without title, location or manual description');

 let serialSaves=[],serialAnalysis=[],serialRelease;
 const serial=setup(async(url,o)=>{const body=o.body?JSON.parse(o.body):null;if(url.endsWith('guardar/')){serialSaves.push(body);if(serialSaves.length===1)await new Promise(resolve=>serialRelease=resolve);return response(200,{revision:body.revision+1});}if(url.endsWith('analizar/')){serialAnalysis.push(body);return response(200,{id:'serial-job',status:'running'});}if(url.includes('/api/analisis/'))return response(200,{id:'serial-job',status:'failed',error:'Lectura de prueba'});throw Error(url);},{before(w){w.document.querySelectorAll('.asset-card:not([data-kind="image"][data-purpose="general"])').forEach(e=>e.remove());}});
 assert.equal(serial.doc.querySelectorAll('#serial,[data-field="serial"]').length,1);assert.equal(serial.doc.querySelector('#serial').closest('[data-step-panel]').dataset.stepPanel,'1');assert.equal(serial.doc.querySelector('#serial').closest('details'),null);assert.equal(serial.doc.querySelector('#serial').required,false);
 serial.doc.querySelector('[data-step-to="1"]').click();input(serial,'serial','SERIE-SINTETICA-001');click(serial,'analyze-button');await pause(15);assert.equal(serialSaves.length,1);assert.equal(serialAnalysis.length,0,'analysis must wait for the serial save');input(serial,'serial','SERIE-SINTETICA-002');serialRelease();await pause(60);
 assert.equal(serialSaves.length,2);assert.deepEqual(serialSaves[0].data,{serial:'SERIE-SINTETICA-001'});assert.deepEqual(serialSaves[1].data,{serial:'SERIE-SINTETICA-002'});assert.equal(serialSaves[1].revision,2);assert.equal(serialAnalysis.length,1);assert.equal(serialAnalysis[0].revision,3);assert.deepEqual(serialAnalysis[0].asset_ids,['1']);assert.equal(serialAnalysis[0].research,true);assert.equal(serial.doc.querySelector('#serial').value,'SERIE-SINTETICA-002');serial.close();pass('single optional serial input appears in photos step; latest typed serial saves before analysis without a plate photo');

 let photosOnlyAnalysis=0;
 const photosOnly=setup(async(url,o)=>{if(url.endsWith('analizar/')){photosOnlyAnalysis++;const body=JSON.parse(o.body);assert.deepEqual(body.asset_ids,['1']);assert.equal(body.revision,1);return response(200,{id:'photos-job',status:'running'});}if(url.includes('/api/analisis/'))return response(200,{id:'photos-job',status:'failed',error:'Lectura de prueba'});throw Error('Unexpected save or requirement: '+url);},{before(w){w.document.querySelectorAll('.asset-card:not([data-kind="image"][data-purpose="general"])').forEach(e=>e.remove());}});
 assert.equal(photosOnly.doc.querySelector('#serial').value,'');click(photosOnly,'analyze-button');await pause(40);assert.equal(photosOnlyAnalysis,1);assert.equal(photosOnly.doc.querySelector('#wizard-errors').hidden,true);photosOnly.close();pass('a general photo can prepare the sheet with no serial or plate and no extra confirmation');

 let categoryContext;
 categoryContext=setup(async()=>{await pause(1);const job=completed(categoryContext.state,{description:'Se observa maquinaria en la fotografía.'});job.result.research={status:'general_context',basis:'category',match:'category',fields:[],context:{category:'Excavadora',label:'Referencias generales; no identifican esta unidad'},sources:[{url:'https://manufacturer.example/equipment/excavators',title:'Información general de excavadoras'}],warnings:[]};return response(200,job);},{job:{id:'job',status:'completed'}});
 await pause(40);assert.match(categoryContext.doc.querySelector('#research-brief').textContent,/Referencias generales.*no identifican esta unidad/);assert.match(categoryContext.doc.querySelector('#analysis-results').textContent,/Tipo consultado: Excavadora/);assert.equal(categoryContext.doc.querySelectorAll('#analysis-results .research-field-list').length,0);assert.equal(categoryContext.doc.querySelectorAll('#analysis-results .research-source-list a').length,1);assert.equal(categoryContext.doc.querySelector('#submit-machine').disabled,false);categoryContext.close();pass('category research is labeled general context with sources, never unit specifications');


 let pdfSaves=[],pdfRelease;const pdfDownloads=[];
 const pdf=setup(async(url,o)=>{assert.ok(url.endsWith('guardar/'));const body=JSON.parse(o.body);pdfSaves.push(body);if(pdfSaves.length===1)await new Promise(resolve=>pdfRelease=resolve);return response(200,{revision:body.revision+1});},{before(w){captureDownloads(w,pdfDownloads);}});
 const pdfLink=pdf.doc.querySelector('#download-draft-pdf');assert.equal(pdfLink.closest('[data-step-panel]').dataset.stepPanel,'2');assert.equal(pdfLink.closest('details'),null);assert.equal(pdfLink.textContent,'Descargar ficha PDF ↓');assert.match(pdf.doc.querySelector('#draft-pdf-note').textContent,/PDF interno.*datos privados/);
 input(pdf,'model','Primer modelo');click(pdf,'download-draft-pdf');click(pdf,'download-draft-pdf');await pause(15);assert.equal(pdfSaves.length,1);assert.equal(pdfDownloads.length,0);assert.equal(pdfLink.getAttribute('aria-busy'),'true');assert.equal(pdf.doc.querySelector('#submit-machine').disabled,true);
 input(pdf,'model','Último modelo');pdfRelease();await pause(45);assert.equal(pdfSaves.length,2);assert.deepEqual(pdfSaves[1].data,{model:'Último modelo'});assert.equal(pdfSaves[1].revision,2);assert.equal(pdfDownloads.length,1);assert.match(pdfDownloads[0].url,/\/panel\/maquinarias\/[^/]+\/pdf\/$/);assert.equal(pdfDownloads[0].filename,'');assert.equal(pdfLink.getAttribute('aria-busy'),'false');assert.equal(pdf.doc.querySelector('#model').value,'Último modelo');assert.equal(pdf.doc.querySelector('#submit-machine').disabled,false);assert.equal(pdf.doc.querySelectorAll('[data-step-panel]').length,2);
 const pdfLeave=new pdf.w.Event('beforeunload',{cancelable:true});pdf.w.dispatchEvent(pdfLeave);assert.equal(pdfLeave.defaultPrevented,false);pdf.close();pass('PDF action beside preview flushes latest in-flight edits, deduplicates downloads and keeps two-step draft open');

 for(const rejectedStatus of [400,409]){
   const rejectedDownloads=[];let rejectedCalls=0;
   const rejectedPdf=setup(async()=>{rejectedCalls++;return response(rejectedStatus,{error:'No se pudo guardar la revisión',revision:7});},{before(w){captureDownloads(w,rejectedDownloads);}});
   input(rejectedPdf,'serial','SERIE-PRIVADA-SIN-PERDER');click(rejectedPdf,'download-draft-pdf');await pause(30);assert.equal(rejectedDownloads.length,0);assert.equal(rejectedPdf.doc.querySelector('#serial').value,'SERIE-PRIVADA-SIN-PERDER');assert.match(rejectedPdf.doc.querySelector('#draft-pdf-status').textContent,/No se descargó.*Conservamos/);assert.equal(rejectedPdf.doc.querySelector('#download-draft-pdf').getAttribute('aria-busy'),'false');assert.equal(rejectedPdf.doc.querySelector('#wizard-errors').hidden,false);
   const unsaved=new rejectedPdf.w.Event('beforeunload',{cancelable:true});rejectedPdf.w.dispatchEvent(unsaved);assert.equal(unsaved.defaultPrevented,true);
   if(rejectedStatus===409){click(rejectedPdf,'download-draft-pdf');await pause(15);assert.equal(rejectedCalls,1);assert.equal(rejectedDownloads.length,0);}
   rejectedPdf.close();
 }
 pass('rejected or conflicting save never downloads a stale PDF and retains dirty private fields');

 let pdfUploadFinish;const uploadDownloads=[];
 const pdfUpload=setup(async()=>{throw Error('Unexpected request');},{before(w){captureDownloads(w,uploadDownloads);w.XMLHttpRequest=class extends w.EventTarget{constructor(){super();this.upload=new w.EventTarget();}open(){}setRequestHeader(){}send(){pdfUploadFinish=()=>{this.status=200;this.responseText=JSON.stringify({id:'pdf-photo',kind:'image',purpose:'general',revision:2});this.dispatchEvent(new w.Event('load'));};}};}});
 const pdfGallery=pdfUpload.doc.querySelector('#gallery-input');Object.defineProperty(pdfGallery,'files',{value:[new pdfUpload.w.File(['photo'],'pdf.jpg',{type:'image/jpeg'})]});pdfGallery.dispatchEvent(new pdfUpload.w.Event('change'));click(pdfUpload,'download-draft-pdf');await pause(20);assert.equal(uploadDownloads.length,0);assert.equal(typeof pdfUploadFinish,'function');
 const lateDrop=new pdfUpload.w.Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(lateDrop,'dataTransfer',{value:{files:[new pdfUpload.w.File(['late'],'late.jpg',{type:'image/jpeg'})]}});pdfUpload.doc.querySelector('#drop-zone').dispatchEvent(lateDrop);assert.equal(pdfUpload.doc.querySelector('#upload-queue').children.length,1);
 pdfUploadFinish();await pause(40);assert.equal(uploadDownloads.length,1);assert.ok(pdfUpload.doc.querySelector('[data-asset-id="pdf-photo"]'));pdfUpload.close();pass('PDF waits for queued uploads and blocks additional drops until the download is requested');

 let assetSaveRelease,assetChangeRelease,assetPdfCalls=[];const assetDownloads=[];
 const assetPdf=setup(async(url,o)=>{assetPdfCalls.push(url);if(url.endsWith('guardar/')){await new Promise(resolve=>assetSaveRelease=resolve);return response(200,{revision:2});}if(url.includes('/api/archivos/')){await new Promise(resolve=>assetChangeRelease=resolve);return response(200,{revision:3});}throw Error(url);},{before(w){captureDownloads(w,assetDownloads);}});
 input(assetPdf,'brand','Marca guardada');assetPdf.doc.querySelector('[data-asset-action="cover"]').click();click(assetPdf,'download-draft-pdf');await pause(20);assert.equal(assetDownloads.length,0);assetSaveRelease();await pause(20);assert.equal(assetPdfCalls.length,2);assert.equal(assetDownloads.length,0);assetChangeRelease();await pause(35);assert.equal(assetDownloads.length,1);assetPdf.close();pass('PDF waits for a file mutation that was still waiting for a field save');

 const readonlyDownloads=[];
 const readonlyPdf=setup(async()=>{throw Error('Read-only PDF should not save');},{readonly:true,before(w){captureDownloads(w,readonlyDownloads);}});click(readonlyPdf,'download-draft-pdf');await pause(20);assert.equal(readonlyDownloads.length,1);assert.equal(readonlyPdf.doc.querySelector('#brand').disabled,true);readonlyPdf.close();pass('read-only owner sheet can download its saved PDF without any mutation');

 console.log(JSON.stringify({suite:'quick-intake-dom',checks,passed:checks,uncaughtErrors:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
