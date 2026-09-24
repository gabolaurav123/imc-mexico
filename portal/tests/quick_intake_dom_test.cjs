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
 if(options.readonly){state.editable=false;doc.querySelector('#wizard').dataset.editable='false';doc.querySelector('#delete-draft')?.remove();}
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
function captureSheetNavigation(w,navigations){
 const original=w.HTMLAnchorElement.prototype.click;
 w.HTMLAnchorElement.prototype.click=function(){if(this.dataset.sheetNavigation==='true'){navigations.push(this.href);return;}return original.call(this);};
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

 let readingConflicts;
 readingConflicts=setup(async()=>{await pause(1);const job=completed(readingConflicts.state,{});job.result.warnings=['Hay varias lecturas para Potencia; revisa las fuentes.'];job.result.conflicts={power:[{value:'10 kW',asset_id:'1',source:'plate',evidence:'Placa A'},{value:'20 kW',asset_id:'2',source:'image',evidence:'Etiqueta B'},{value:'10 kW',asset_id:'1',source:'plate',evidence:'Duplicado'}]};return response(200,job);},{job:{id:'reading-conflicts',status:'completed'}});
 await pause(40);const readingsBox=readingConflicts.doc.querySelector('.analysis-reading-conflicts');assert.ok(readingsBox);assert.match(readingsBox.textContent,/10 kW.*20 kW/s);assert.equal(readingsBox.querySelectorAll('li').length,2);assert.equal(readingsBox.querySelectorAll('a').length,2);assert.equal(readingsBox.querySelectorAll('input,button').length,0);assert.match(readingConflicts.doc.querySelector('#analysis-results').textContent,/Hay varias lecturas para Potencia/);readingConflicts.close();pass('conflicting readings display each value and available photo once without an automatic action');

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
 assert.equal(details.querySelectorAll('img,script,iframe').length,0);assert.equal(details.querySelectorAll('a').length,0);assert.doesNotMatch(details.textContent,/Fuentes consultadas|Manual del fabricante|Ficha técnica/);
 assert.match(details.textContent,/<script>alert\(1\)<\/script>/);assert.doesNotMatch(details.textContent,/999999|not displayed/);assert.equal(researched.doc.querySelector('#preview-description').textContent,'Descripción preparada con datos disponibles.');researched.close();pass('research details retain values and review scope without rendering sources or links');

 let hypothesisLead;
 hypothesisLead=setup(async()=>{await pause(1);const job=completed(hypothesisLead.state,{});job.result.research={status:'completed',match:'none',fields:[],sources:[],warnings:[],hypotheses:[
   {model:'MODELO <img src=x onerror=alert(1)>',source_url:'javascript:alert(1)',source_title:'<script>unsafe</script>',evidence:'Evidencia <svg onload=alert(1)>',support_count:2,production_period:{from:2008,to:2014}},
   {model:'Modelo documentado seguro',source_url:'https://catalog.example/modelo',source_title:'Catálogo seguro',evidence:'Ficha de referencia',support_count:1}
 ]};return response(200,job);},{job:{id:'job',status:'completed'},data:{model:''}});
 await pause(40);const hypotheses=hypothesisLead.doc.querySelector('#preview-research-hypotheses');assert.equal(hypotheses.hidden,false);assert.match(hypotheses.textContent,/Modelos de referencia encontrados · por identificar/);assert.match(hypotheses.textContent,/no confirman la unidad fotografiada/);assert.match(hypotheses.textContent,/No indica la edad de esta unidad/);assert.ok(hypotheses.textContent.includes('Evidencia <svg onload=alert(1)>'));assert.equal(hypotheses.querySelectorAll('img,script,iframe,svg').length,0);assert.equal(hypotheses.querySelectorAll('a').length,0);assert.doesNotMatch(hypotheses.textContent,/Fuentes que lo respaldan|Catálogo seguro/);assert.equal(hypothesisLead.doc.querySelector('#model').value,'');assert.equal(hypothesisLead.doc.querySelector('#price').value,'');
 input(hypothesisLead,'model','MODELO ACTUAL');assert.equal(hypothesisLead.doc.querySelector('#preview-research-hypotheses').hidden,true);assert.equal(hypothesisLead.doc.querySelector('#preview-research-hypotheses').textContent,'');hypothesisLead.close();pass('model hypotheses render as safe non-authoritative leads and clear when a human model is entered');

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
 await pause(40);assert.match(categoryContext.doc.querySelector('#research-brief').textContent,/Referencias generales.*no identifican esta unidad/);assert.match(categoryContext.doc.querySelector('#analysis-results').textContent,/Tipo consultado: Excavadora/);assert.equal(categoryContext.doc.querySelectorAll('#analysis-results .research-field-list').length,0);assert.equal(categoryContext.doc.querySelectorAll('#analysis-results .research-source-list a').length,0);assert.equal(categoryContext.doc.querySelector('#submit-machine').disabled,false);categoryContext.close();pass('category research retains general context without sources or unit specifications');


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

 let screenRelease;const screenSaves=[],screenNav=[];
 const screen=setup(async(url,o)=>{assert.ok(url.endsWith('guardar/'));const body=JSON.parse(o.body);screenSaves.push(body);if(screenSaves.length===1)await new Promise(resolve=>screenRelease=resolve);return response(200,{revision:body.revision+1});},{before(w){captureSheetNavigation(w,screenNav);}});
 const screenLink=screen.doc.querySelector('#view-draft-sheet');assert.equal(screenLink.closest('[data-step-panel]').dataset.stepPanel,'2');assert.equal(screenLink.closest('details'),null);assert.equal(screenLink.hasAttribute('download'),false);assert.equal(screenLink.target,'');
 input(screen,'model','Primero');click(screen,'view-draft-sheet');click(screen,'view-draft-sheet');await pause(15);assert.equal(screenNav.length,0);assert.equal(screen.doc.querySelector('#submit-machine').disabled,true);input(screen,'model','Último');screenRelease();await pause(40);assert.equal(screenSaves.length,2);assert.deepEqual(screenSaves[1].data,{model:'Último'});assert.equal(screenNav.length,1);assert.match(screenNav[0],/\/panel\/maquinarias\/[^/]+\/ficha\/$/);const screenLeave=new screen.w.Event('beforeunload',{cancelable:true});screen.w.dispatchEvent(screenLeave);assert.equal(screenLeave.defaultPrevented,false);screen.close();pass('virtual sheet waits for all in-flight edits, navigates once in same app and preserves two-step intake');
 for(const status of [400,409]){const blockedNav=[];const blockedScreen=setup(async()=>response(status,{error:'Guardado rechazado',revision:8}),{before(w){captureSheetNavigation(w,blockedNav);}});input(blockedScreen,'serial','SERIE-PENDIENTE');click(blockedScreen,'view-draft-sheet');await pause(25);assert.equal(blockedNav.length,0);assert.equal(blockedScreen.doc.querySelector('#serial').value,'SERIE-PENDIENTE');assert.match(blockedScreen.doc.querySelector('#draft-pdf-status').textContent,/No se abrió.*Conservamos/);blockedScreen.close();}pass('virtual sheet never opens stale data after rejected save or conflict');
 let screenUploadDone;const uploadedScreenNav=[];const screenUpload=setup(async()=>{throw Error('Unexpected write');},{before(w){captureSheetNavigation(w,uploadedScreenNav);w.XMLHttpRequest=class extends w.EventTarget{constructor(){super();this.upload=new w.EventTarget();}open(){}setRequestHeader(){}send(){screenUploadDone=()=>{this.status=200;this.responseText=JSON.stringify({id:'screen-photo',kind:'image',purpose:'general',revision:2});this.dispatchEvent(new w.Event('load'));};}};}});const screenGallery=screenUpload.doc.querySelector('#gallery-input');Object.defineProperty(screenGallery,'files',{value:[new screenUpload.w.File(['photo'],'screen.jpg',{type:'image/jpeg'})]});screenGallery.dispatchEvent(new screenUpload.w.Event('change'));click(screenUpload,'view-draft-sheet');await pause(20);assert.equal(uploadedScreenNav.length,0);screenUploadDone();await pause(30);assert.equal(uploadedScreenNav.length,1);screenUpload.close();pass('virtual sheet also waits for queued images');
 const readonlyScreenNav=[];const readonlyScreen=setup(async()=>{throw Error('Readonly screen must not save');},{readonly:true,before(w){captureSheetNavigation(w,readonlyScreenNav);}});readonlyScreen.doc.querySelector('[data-open-sheet]').click();await pause(20);assert.equal(readonlyScreenNav.length,1);assert.equal(readonlyScreen.doc.querySelector('#brand').disabled,true);readonlyScreen.close();pass('header sheet link uses the same safe route; readonly navigation makes no writes');


 let cancelledCalls=0,cancelledPrompts=[];
 const cancelDelete=setup(async()=>{cancelledCalls++;throw Error('Cancel must not write');},{before(w){w.confirm=message=>{cancelledPrompts.push(message);return false;};}});
 input(cancelDelete,'model','Corrección que conservo');click(cancelDelete,'delete-draft');await pause(20);assert.equal(cancelledCalls,0);assert.deepEqual(cancelledPrompts,['¿Eliminar este borrador? Podrás recuperarlo desde la papelera.']);assert.equal(cancelDelete.doc.querySelector('#model').value,'Corrección que conservo');assert.equal(cancelDelete.doc.querySelector('#model').disabled,false);assert.equal(cancelDelete.doc.querySelector('#delete-draft').disabled,false);cancelDelete.close();pass('canceling reversible deletion makes no request and preserves editable corrections');

 let deletingRelease,deleteBodies=[],deletePrompts=0;const noDeleteDownloads=[];
 const deleteDirty=setup(async(url,o)=>{assert.ok(url.endsWith('accion/'),'deletion must not flush unsaved edits');deleteBodies.push(JSON.parse(o.body));await new Promise(resolve=>deletingRelease=resolve);return response(200,{ok:true,url:'/panel/maquinarias/'});},{before(w){captureDownloads(w,noDeleteDownloads);w.confirm=()=>{deletePrompts++;return true;};}});
 input(deleteDirty,'serial','CAMBIO-LOCAL-NO-GUARDADO');click(deleteDirty,'delete-draft');click(deleteDirty,'delete-draft');await pause(15);assert.equal(deleteBodies.length,1);assert.equal(deletePrompts,1);assert.deepEqual(deleteBodies[0],{action:'delete_draft',revision:1});assert.equal(deleteDirty.doc.querySelector('#serial').disabled,true);assert.equal(deleteDirty.doc.querySelector('#submit-machine').disabled,true);
 click(deleteDirty,'download-draft-pdf');click(deleteDirty,'analyze-button');click(deleteDirty,'submit-machine');deleteDirty.w.dispatchEvent(new deleteDirty.w.Event('online'));click(deleteDirty,'save-retry');
 const deleteDrop=new deleteDirty.w.Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(deleteDrop,'dataTransfer',{value:{files:[new deleteDirty.w.File(['ignored'],'late.jpg',{type:'image/jpeg'})]}});deleteDirty.doc.querySelector('#drop-zone').dispatchEvent(deleteDrop);
 assert.equal(deleteDirty.doc.querySelector('#upload-queue').children.length,0);assert.equal(noDeleteDownloads.length,0);assert.equal(deleteBodies.length,1);
 const deletingLeave=new deleteDirty.w.Event('beforeunload',{cancelable:true});deleteDirty.w.dispatchEvent(deletingLeave);assert.equal(deletingLeave.defaultPrevented,true);deletingRelease();await pause(25);const deletedLeave=new deleteDirty.w.Event('beforeunload',{cancelable:true});deleteDirty.w.dispatchEvent(deletedLeave);assert.equal(deletedLeave.defaultPrevented,false);deleteDirty.close();pass('delete freezes mutations, skips irrelevant dirty saves, deduplicates and clears unload protection only after success');

 for(const status of [400,409]){
   let failedDeleteCalls=0;
   const failedDelete=setup(async(url)=>{failedDeleteCalls++;assert.ok(url.endsWith('accion/'));return response(status,{error:'Rechazo de prueba'});});input(failedDelete,'description','Mi descripción sigue aquí');click(failedDelete,'delete-draft');await pause(20);assert.equal(failedDeleteCalls,1);assert.equal(failedDelete.doc.querySelector('#description').value,'Mi descripción sigue aquí');assert.equal(failedDelete.doc.querySelector('#description').disabled,false);assert.equal(failedDelete.doc.querySelector('#delete-draft').disabled,false);assert.match(failedDelete.doc.querySelector('#wizard-errors').textContent,/no se eliminó|No se eliminó/);const kept=new failedDelete.w.Event('beforeunload',{cancelable:true});failedDelete.w.dispatchEvent(kept);assert.equal(kept.defaultPrevented,true);if(status===409){click(failedDelete,'delete-draft');await pause(15);assert.equal(failedDeleteCalls,1);}failedDelete.close();
 }
 pass('delete rejection restores controls; revision conflict never retries or discards local corrections');

 let deleteSaveRelease,deleteAfterSave=[],inflightDeleteCalls=[];
 const inflightDelete=setup(async(url,o)=>{const body=JSON.parse(o.body);inflightDeleteCalls.push(url);if(url.endsWith('guardar/')){await new Promise(resolve=>deleteSaveRelease=resolve);return response(200,{revision:2});}if(url.endsWith('accion/')){deleteAfterSave.push(body);return response(400,{error:'Conservar para revisión'});}throw Error(url);});input(inflightDelete,'brand','Edición en vuelo');await pause(900);input(inflightDelete,'brand','Última corrección sin guardar');click(inflightDelete,'delete-draft');await pause(15);assert.equal(deleteAfterSave.length,0);deleteSaveRelease();await pause(35);assert.equal(inflightDeleteCalls.filter(url=>url.endsWith('guardar/')).length,1);assert.deepEqual(deleteAfterSave,[{action:'delete_draft',revision:2}]);assert.equal(inflightDelete.doc.querySelector('#brand').value,'Última corrección sin guardar');inflightDelete.close();pass('delete waits an existing save, uses its returned revision and never flushes later dirty edits');

 let deleteUploadFinish,deleteUploadBodies=[];
 const deleteUpload=setup(async(url,o)=>{assert.ok(url.endsWith('accion/'));deleteUploadBodies.push(JSON.parse(o.body));return response(200,{ok:true,url:'/panel/maquinarias/'});},{before(w){w.XMLHttpRequest=class extends w.EventTarget{constructor(){super();this.upload=new w.EventTarget();}open(){}setRequestHeader(){}send(){deleteUploadFinish=()=>{this.status=200;this.responseText=JSON.stringify({id:'trash-photo',kind:'image',purpose:'general',revision:2});this.dispatchEvent(new w.Event('load'));};}};}});
 const trashGallery=deleteUpload.doc.querySelector('#gallery-input');Object.defineProperty(trashGallery,'files',{value:[new deleteUpload.w.File(['photo'],'trash.jpg',{type:'image/jpeg'})]});trashGallery.dispatchEvent(new deleteUpload.w.Event('change'));click(deleteUpload,'delete-draft');await pause(15);assert.equal(deleteUploadBodies.length,0);deleteUploadFinish();await pause(35);assert.deepEqual(deleteUploadBodies,[{action:'delete_draft',revision:2}]);assert.equal(deleteUpload.doc.querySelector('#asset-grid [data-asset-id="trash-photo"] [data-asset-action]').disabled,true);deleteUpload.close();pass('delete finishes existing file upload and uses its new revision while keeping appended controls frozen');

 let deletePollRelease,deletePollState,deletePollCalls=[];
 const deletePoll=setup(async(url,o)=>{deletePollCalls.push(url);if(url.includes('/api/analisis/')){await new Promise(resolve=>deletePollRelease=resolve);return response(200,{id:'legacy-trash',status:'completed',result:{data:{model:'No aplicar'}},machine:deletePollState,auto_apply:{requested:false,status:'disabled'}});}if(url.endsWith('accion/'))return response(200,{ok:true,url:'/panel/maquinarias/'});throw Error('New work during deletion: '+url);},{job:{id:'legacy-trash',status:'completed'}});deletePollState=deletePoll.state;input(deletePoll,'model','Corrección local');click(deletePoll,'delete-draft');await pause(15);assert.equal(deletePollCalls.length,1);deletePollRelease();await pause(35);assert.equal(deletePollCalls.filter(url=>url.endsWith('aplicar/')).length,0);assert.equal(deletePollCalls.filter(url=>url.endsWith('guardar/')).length,0);assert.equal(deletePollCalls.filter(url=>url.endsWith('accion/')).length,1);deletePoll.close();pass('delete waits an in-flight analysis read without starting legacy application or saving local corrections');

 for(const action of ['delete_draft','restore_draft']){
   let cardBodies=[],cardPrompts=0,cardRelease;
   const card=setup(async(url,o)=>{assert.ok(url.endsWith('/card-fixture/accion/'));cardBodies.push(JSON.parse(o.body));await new Promise(resolve=>cardRelease=resolve);return response(409,{error:'La versión cambió'});},{before(w){w.confirm=message=>{assert.equal(message,'¿Eliminar este borrador? Podrás recuperarlo desde la papelera.');cardPrompts++;return true;};const article=w.document.createElement('article');article.className='machine-card';article.innerHTML='<button id="card-action" data-machine-id="card-fixture" data-machine-revision="8" data-machine-action="'+action+'">'+(action==='delete_draft'?'Eliminar borrador':'Restaurar borrador')+'</button><p data-action-error hidden></p>';w.document.body.append(article);}});
   click(card,'card-action');click(card,'card-action');await pause(15);assert.deepEqual(cardBodies,[{action,revision:8}]);assert.equal(cardPrompts,action==='delete_draft'?1:0);cardRelease();await pause(20);assert.equal(card.doc.querySelector('#card-action').disabled,false);assert.equal(card.doc.querySelector('[data-action-error]').hidden,false);assert.match(card.doc.querySelector('[data-action-error]').textContent,/versión cambió/);card.close();
 }
 pass('list delete and restore send displayed revision once; only deletion confirms and errors remain visible in card');

const professional=setup(async()=>{throw Error('Preview must not make requests');},{query:'?paso=2',state:{title:'Compactadora de prueba',provenance:{power:{source:'plate',review:'clear'},weight:{source:'web',scope:'model',review:'needs_review'},country_of_origin:{source:'plate',review:'clear'}}},data:{model:'MODELO-SINTETICO',serial:'SERIE-PRIVADA-DE-PRUEBA',description:'Descripción completa de la maquinaria.\nSe conserva el segundo párrafo. <img src=x onerror=alert(1)>',location:'',country_of_origin:'País de prueba',price:0,power:'4.5 kW',weight:'90 kg',vibration_frequency:'4200 VPM',centrifugal_force:'13 kN',compaction_depth:'30 cm'}});
 const technicalPreview=professional.doc.querySelector('#preview-technical-specs');
 assert.equal(professional.doc.querySelector('#preview-technical-section').hidden,false);
 for(const key of ['power','weight','vibration_frequency','centrifugal_force','compaction_depth']){const row=technicalPreview.querySelector('[data-preview-field="'+key+'"]');assert.ok(row,key+' must be visible in the document');assert.equal(row.closest('details'),null);}
 assert.match(technicalPreview.textContent,/Lectura de placa/);assert.match(technicalPreview.textContent,/Referencia del modelo · por confirmar/);
 assert.match(professional.doc.querySelector('#preview-specs').textContent,/Serie privadaSERIE-PRIVADA-DE-PRUEBA/);assert.match(professional.doc.querySelector('#preview-specs').textContent,/Horas0/);
 assert.match(professional.doc.querySelector('#preview-commercial-specs').textContent,/Ubicación actualNo indicada/);assert.match(professional.doc.querySelector('#preview-commercial-specs').textContent,/País de fabricaciónPaís de prueba/);assert.doesNotMatch(professional.doc.querySelector('#preview-commercial-specs').textContent,/Precio/);assert.equal(professional.doc.querySelector('#auto-valuation-section #price').value,'0');
 assert.equal(professional.doc.querySelector('#preview-description img'),null);assert.match(professional.doc.querySelector('#preview-description').textContent,/segundo párrafo/);
 assert.equal(professional.doc.querySelector('#extra-country_of_origin').value,'País de prueba');
 assert.ok(professional.doc.querySelector('#submit-machine').compareDocumentPosition(professional.doc.querySelector('#commercial-details')) & professional.w.Node.DOCUMENT_POSITION_FOLLOWING,'send precedes optional editing controls');
 input(professional,'extra-compaction_depth','35 cm');assert.match(technicalPreview.textContent,/35 cm/);assert.equal(professional.doc.querySelector('#location').value,'');professional.close();pass('professional preview exposes technical data, private serial, zero and full safe description; manufacturing origin never becomes current location');

 for(const explicitKind of ['plate','machine',null]){
   let photoPreview;
   photoPreview=setup(async()=>{await pause(1);const result=completed(photoPreview.state,{});result.result.plates=[{asset_id:'1',component:'machine',transcription:'PLACA SINTETICA'}];if(explicitKind)result.result.image_observations=[{asset_id:'1',kind:explicitKind}];return response(200,result);},{job:{id:'job',status:'completed'},before(w){w.document.querySelectorAll('.asset-card:not([data-asset-id="1"])').forEach(node=>node.remove());}});
   await pause(35);const caption=photoPreview.doc.querySelector('#preview-image-caption').textContent;
   if(explicitKind==='machine')assert.doesNotMatch(caption,/Placa de identificación/);else assert.match(caption,/Placa de identificación · privada/);
   assert.equal(photoPreview.doc.querySelector('.asset-card').dataset.purpose,'general','display label never changes classification or publication permissions');
   assert.match(photoPreview.doc.querySelector('#preview-cover a').href,/\/archivos\/1\/\?original=1$/);
   photoPreview.close();
 }
 pass('main-object classification labels plate close-ups, prioritizes machine evidence, and supports legacy jobs without mutating asset permissions');
 const forkliftData={front_tire_size:'21x7x15',rear_tire_size:'16x6x10.5',mast_tilt:'Rearward 6 deg',load_tire_tread:'34.5 in',manufacturer:'Fabricante de prueba',manufacturer_address:'Houston, USA',voltage:'48 V',lift_height:'188 in',load_center:'24 in',battery_weight:'MIN 1800 lb / MAX 2200 lb',battery_capacity:'600 Ah',fork_length:'42 in'};
 let forkliftSave;
 const forklift=setup(async(url,o)=>{assert.ok(url.endsWith('guardar/'));forkliftSave=JSON.parse(o.body);return response(200,{revision:forkliftSave.revision+1});},{data:{...forkliftData,location:'',country_of_origin:''}});
 for(const [key,value] of Object.entries(forkliftData)){
   assert.equal(forklift.doc.querySelector(`[data-preview-field="${key}"] dd`).textContent,value);
   assert.equal(forklift.doc.querySelector(`[data-field="${key}"]`).value,value,'present plate field stays editable without category schema');
 }
 assert.match(forklift.doc.querySelector('#preview-commercial-specs').textContent,/Ubicación actualNo indicada/);
 assert.match(forklift.doc.querySelector('#preview-commercial-specs').textContent,/País de fabricaciónNo identificado/);
 input(forklift,'extra-mast_tilt','Rearward 5 deg');await pause(900);
 assert.deepEqual(forkliftSave.data,{mast_tilt:'Rearward 5 deg'});
 assert.equal(forklift.doc.querySelectorAll('[data-step-panel]').length,2);
 forklift.close();pass('forklift plate fields render and remain editable with literal qualifiers; manufacturer address never becomes location or origin');
 for(const relevanceStatus of ['unrelated','uncertain']){
   let rejected,releaseRelevance;const rejectedCalls=[];
   rejected=setup(async(url,o)=>{
     rejectedCalls.push(url);
     if(url.includes('/api/analisis/')){
       await new Promise(resolve=>releaseRelevance=resolve);
       const job=completed(rejected.state,{brand:'NO DEBE APLICARSE',model:'NO DEBE HIDRATARSE'});
       job.auto_apply={requested:false,status:'disabled'};
       job.result.relevance={status:relevanceStatus,message:'<img src=x onerror=alert(1)>',accepted_asset_ids:[],excluded_asset_ids:relevanceStatus==='unrelated'?['1','2']:[],uncertain_asset_ids:relevanceStatus==='uncertain'?['1','2']:[]};return response(200,job);
     }
     if(url.endsWith('guardar/')){assert.equal(JSON.parse(o.body).revision,1);return response(200,{revision:2});}
     if(url.endsWith('enviar/'))return response(200,{url:'/panel/solicitudes/'});
     throw Error('Unexpected relevance request '+url);
   },{job:{id:'rejected-job',status:'completed'}});
   const retainedIds=[...rejected.doc.querySelectorAll('.asset-card')].map(card=>card.dataset.assetId);
   input(rejected,'brand','Corrección conservada');releaseRelevance();await pause(40);
   assert.equal(rejected.doc.querySelector('[data-step-panel="1"]').hidden,false);
   assert.equal(rejected.doc.querySelector('[data-step-panel="2"]').hidden,true);
   assert.equal(rejected.doc.querySelector('#brand').value,'Corrección conservada');
   assert.equal(rejected.doc.querySelector('#model').value,rejected.state.data.model ?? '');
   assert.deepEqual([...rejected.doc.querySelectorAll('.asset-card')].map(card=>card.dataset.assetId),retainedIds);
   assert.equal(rejected.doc.querySelectorAll('.asset-relevance[role="note"]').length,2);
   assert.equal(rejected.doc.querySelector('#analysis-status').dataset.state,relevanceStatus);
   assert.match(rejected.doc.querySelector('#analysis-status').textContent,/Agrega una foto/);
   assert.doesNotMatch(rejected.doc.querySelector('#ready-heading').textContent,/preparada|lista/);
   assert.equal(rejected.doc.querySelector('#analysis-feedback img'),null);
   assert.equal(rejected.doc.querySelector('#analyze-button').disabled,false);
   assert.equal(rejected.doc.querySelector('[data-file-open]').disabled,false);
   assert.equal(rejectedCalls.some(url=>url.endsWith('aplicar/')),false);
   click(rejected,'manual-continue');click(rejected,'submit-machine');await pause(40);
   assert.equal(rejectedCalls.filter(url=>url.endsWith('enviar/')).length,1,'manual submission remains available');
   rejected.close();
 }
 pass('unrelated and uncertain photos stay in step 1, never hydrate or request autofill, retain edits/files, and permit manual submission');

 let mixed;
 mixed=setup(async(url)=>{assert.ok(url.includes('/api/analisis/'));await pause(1);const job=completed(mixed.state,{model:'Equipo leído'});job.result.relevance={status:'mixed',accepted_asset_ids:['1'],excluded_asset_ids:['2'],uncertain_asset_ids:[]};return response(200,job);},{job:{id:'mixed',status:'completed'}});
 await pause(35);assert.equal(mixed.doc.querySelector('#model').value,'Equipo leído');assert.equal(mixed.doc.querySelector('[data-step-panel="2"]').hidden,false);
 assert.match(mixed.doc.querySelector('#analysis-status').textContent,/Se omitió 1 foto ajena a maquinaria/);
 assert.equal(mixed.doc.querySelector('[data-asset-id="2"]').dataset.relevance,'excluded');
 assert.equal(mixed.doc.querySelector('[data-asset-id="2"]').dataset.purpose,'plate','relevance never changes original file classification');
 assert.equal(mixed.doc.querySelector('[data-asset-id="1"] .asset-relevance'),null);mixed.close();
 pass('mixed photos complete normally with a visible omission count and an accessible per-photo note');

 for(const relevance of [undefined,{status:'unassessed',excluded_asset_ids:['1']},{status:'invalid'}]){
   let compatible;let applies=0;
   compatible=setup(async(url)=>{await pause(1);if(url.includes('/api/analisis/')){const job=completed(compatible.state,{});job.result.relevance=relevance;job.auto_apply={requested:false,status:'disabled'};return response(200,job);}if(url.endsWith('aplicar/')){applies++;const job=completed(compatible.state,{model:'Legacy conservado'});return response(200,{machine:job.machine,auto_apply:job.auto_apply});}throw Error(url);},{job:{id:'legacy-relevance',status:'completed'}});
   await pause(45);assert.equal(applies,1);assert.equal(compatible.doc.querySelector('#model').value,'Legacy conservado');assert.equal(compatible.doc.querySelector('[data-step-panel="2"]').hidden,false);assert.equal(compatible.doc.querySelector('.asset-relevance'),null);compatible.close();
 }
 pass('legacy missing, unassessed or invalid relevance retains the existing completion flow');

 let retryPhotos,finishReplacement;const retryBodies=[];
 retryPhotos=setup(async(url,o)=>{
   await pause(1);
   if(url.includes('/api/analisis/rejected/'))return response(200,{id:'rejected',status:'completed',result:{relevance:{status:'unrelated',excluded_asset_ids:['1','2']}},machine:retryPhotos.state,auto_apply:{requested:true,status:'skipped'}});
   if(url==='/api/archivos/2/accion/'){assert.equal(JSON.parse(o.body).action,'delete');return response(200,{revision:2});}
   if(url.endsWith('analizar/')){const body=JSON.parse(o.body);retryBodies.push(body);assert.deepEqual(body.asset_ids,['1','replacement']);assert.equal(body.revision,3);assert.equal(body.consent,true);return response(200,{id:'replacement-job',status:'running'});}
   if(url.includes('/api/analisis/replacement-job/')){const job=completed({...retryPhotos.state,revision:3},{model:'Equipo de nueva foto'});job.result.relevance={status:'relevant',accepted_asset_ids:['1','replacement'],excluded_asset_ids:[],uncertain_asset_ids:[]};return response(200,job);}
   throw Error('Unexpected retry request '+url);
 },{job:{id:'rejected',status:'completed'},before(w){w.XMLHttpRequest=class extends w.EventTarget{constructor(){super();this.upload=new w.EventTarget();}open(){}setRequestHeader(){}send(){finishReplacement=()=>{this.status=200;this.responseText=JSON.stringify({id:'replacement',kind:'image',purpose:'general',revision:3});this.dispatchEvent(new w.Event('load'));};}};}});
 await pause(30);retryPhotos.doc.querySelector('[data-asset-id="2"] [data-asset-action="delete"]').click();await pause(25);
 const replacementInput=retryPhotos.doc.querySelector('#gallery-input');Object.defineProperty(replacementInput,'files',{value:[new retryPhotos.w.File(['photo'],'replacement.jpg',{type:'image/jpeg'})]});replacementInput.dispatchEvent(new retryPhotos.w.Event('change'));await pause(10);finishReplacement();await pause(25);
 click(retryPhotos,'analyze-button');await pause(50);assert.equal(retryBodies.length,1);assert.equal(retryPhotos.doc.querySelector('#model').value,'Equipo de nueva foto');assert.equal(retryPhotos.doc.querySelector('[data-step-panel="2"]').hidden,false);assert.equal(retryPhotos.doc.querySelector('.asset-relevance'),null);assert.equal(retryPhotos.doc.querySelectorAll('input[type="checkbox"]').length,1);retryPhotos.close();
 pass('rejected photos can be removed/replaced and reanalyzed without another consent control; success clears old photo notices');
 for(const readingStatus of ['failed','not_run','budget_unavailable']){
   let interrupted,finishRead;const calls=[];
   interrupted=setup(async(url)=>{
     calls.push(url);assert.ok(url.includes('/api/analisis/'),'uncertain interrupted job must never request legacy application');
     await new Promise(resolve=>finishRead=resolve);
     const job=completed(interrupted.state,{model:'No hidratar lectura incompleta'});
     job.auto_apply={requested:false,status:'disabled'};
     job.result.relevance={status:'uncertain',accepted_asset_ids:[],excluded_asset_ids:[],uncertain_asset_ids:['1','2']};
     job.result.image_analysis_status='partial';job.result.image_analysis_complete=false;
     job.result.image_readings=[{asset_id:'1',status:'completed',relevance:'uncertain'},{asset_id:'2',status:readingStatus,relevance:'uncertain',error:'<img src=x onerror=alert(1)>'}];
     return response(200,job);
   },{job:{id:'interrupted',status:'completed'},data:{description:''}});
   input(interrupted,'brand','Mi corrección');finishRead();await pause(40);
   assert.equal(calls.length,1);assert.equal(interrupted.doc.querySelector('#brand').value,'Mi corrección');
   assert.equal(interrupted.doc.querySelector('#model').value,interrupted.state.data.model??'');
   assert.equal(interrupted.doc.querySelector('[data-step-panel="1"]').hidden,false);
   assert.equal(interrupted.doc.querySelector('#analysis-status').dataset.state,'partial');
   assert.match(interrupted.doc.querySelector('#analysis-status').textContent,/Lectura incompleta.*1 foto.*Conservamos.*continuar.*otras fotos/);
   assert.doesNotMatch(interrupted.doc.querySelector('#analysis-status').textContent,/legible|claridad|ajena|no corresponden|identificar maquinaria|reintentar|volver a preparar/);
   const card=interrupted.doc.querySelector('[data-asset-id="2"]');
   assert.equal(card.dataset.relevance,readingStatus);assert.match(card.querySelector('.asset-relevance').textContent,readingStatus==='failed'?/Análisis interrumpido/:/Lectura pendiente/);
   assert.doesNotMatch(card.textContent,/No se pudo identificar|Foto ajena/);assert.equal(card.querySelector('.asset-relevance img'),null);
   assert.match(interrupted.doc.querySelector('#preview-description').textContent,/lectura quedó incompleta/);
   assert.doesNotMatch(interrupted.doc.querySelector('#ready-heading').textContent,/preparada|lista/);
   assert.equal(interrupted.doc.querySelector('.wizard-progress [data-step-to="2"] b').textContent,'Ficha');
   assert.equal(interrupted.doc.querySelector('#analyze-button').disabled,false);assert.equal(interrupted.doc.querySelector('#submit-machine').disabled,false);
   interrupted.close();
 }
 pass('interrupted uncertain reads preserve continuation without mislabeling unfinished photos, promising duplicate retries or hydrating an unaccepted result');

 for(const readingStatus of ['failed','not_run','budget_unavailable']){
   let partial,finishRead;const calls=[];
   partial=setup(async(url)=>{
     calls.push(url);assert.ok(url.includes('/api/analisis/'));await new Promise(resolve=>finishRead=resolve);
     const job=completed(partial.state,{model:'Modelo recuperado',weight:'2500 kg'});
     job.result.relevance={status:'mixed',accepted_asset_ids:['1'],excluded_asset_ids:[],uncertain_asset_ids:['2']};
     // Old clients can use the per-image records without requiring the aggregate flag.
     job.result.image_readings=[{asset_id:'1',status:'completed',relevance:'relevant'},{asset_id:'2',status:readingStatus,relevance:'uncertain'}];
     return response(200,job);
   },{job:{id:'partial-useful',status:'completed'},data:{description:''}});
   input(partial,'brand','Corrección humana conservada');finishRead();await pause(40);
   assert.equal(calls.length,1);assert.equal(partial.doc.querySelector('#model').value,'Modelo recuperado');
   assert.equal(partial.doc.querySelector('#brand').value,'Corrección humana conservada');
   assert.match(partial.doc.querySelector('#preview-technical-specs').textContent,/2500 kg/);
   assert.equal(partial.doc.querySelector('[data-step-panel="2"]').hidden,false);
   assert.equal(partial.doc.querySelector('#analysis-status').dataset.state,'partial');
   assert.match(partial.doc.querySelector('#analysis-status').textContent,/Lectura incompleta.*Conservamos/);
   assert.doesNotMatch(partial.doc.querySelector('#analysis-status').textContent,/foto ajena|fotos ajenas|No se pudo identificar|Ficha preparada|lista para revisar/);
   assert.doesNotMatch(partial.doc.querySelector('#ready-heading').textContent,/preparada|lista/);
   assert.equal(partial.doc.querySelector('.wizard-progress [data-step-to="2"] b').textContent,'Ficha');
   assert.equal(partial.doc.querySelector('[data-asset-id="1"] .asset-relevance'),null);
   assert.equal(partial.doc.querySelector('[data-asset-id="2"]').dataset.relevance,readingStatus);
   assert.equal(partial.doc.querySelector('#submit-machine').disabled,false);assert.equal(partial.doc.querySelector('#analyze-button').disabled,false);
   partial.close();
 }
 pass('partial mixed reads preserve useful values and concurrent edits, label only unfinished photos and never announce a ready sheet');
 const conditionData={usage_condition:'Usada',preservation_condition:'Bueno',preservation_notes:'Desgaste visible en pintura',operating_status:'Pendiente de confirmar',visible_defects:'Rayón visible <img src=x onerror=alert(1)>',visible_components:'Mástil y ruedas',attachments:'Horquillas',applications:'Movimiento de cargas'};
 const valuationData={estimate_min:'1000.25',estimate_max:'1500.75',estimate_currency:'USD',estimate_market:'Mercado de prueba',estimate_basis:'Dos anuncios comparables; precio solicitado',estimate_missing_info:'Horas y funcionamiento',price:'1200.50',currency:'USD'};
 const valuationMeta={status:'estimated',suggested_price:'999999',proof:'PRIVATE-PROOF-NOT-FOR-UI',comparables:[
   {url:'https://source.example/listing',title:'Anuncio <img src=x onerror=alert(1)>',price:'1400',currency:'USD',market:'Mercado A',price_type:'asking',evidence:'Referencia <script>bad()</script>'},
   {url:'https://source.example/sold',title:'Registro de venta',price:'1000',currency:'USD',market:'Mercado B',price_type:'sold'},
   {url:'https://source.example/unknown',title:'Otra referencia',price:0,currency:'USD',price_type:'unknown'},
   {url:'javascript:alert(1)',title:'Inseguro',price:1,currency:'USD',price_type:'sold'},
   {url:'https://user:password@source.example/',title:'Credenciales no permitidas',price:1,currency:'USD',price_type:'asking'}]};
 const editableProposal=setup(async()=>{throw Error('Initial proposals need no request or copy action');},{query:'?paso=2',state:{valuation:valuationMeta,provenance:{price:{source:'valuation',review:'needs_review'},preservation_notes:{source:'visual_proposal',review:'needs_review'}}},data:{...conditionData,...valuationData}});
 for(const [key,value] of Object.entries({...conditionData,...valuationData})){
   const nodes=editableProposal.doc.querySelectorAll(`[data-field="${key}"]`);assert.equal(nodes.length,1,key+' has a single editable control');assert.equal(nodes[0].value,value);
 }
 assert.equal(editableProposal.doc.querySelector('#usage_condition').closest('details'),null);
 assert.equal(editableProposal.doc.querySelector('#price').closest('details'),null);
 assert.equal(editableProposal.doc.querySelector('#estimate_min').closest('details'),null);
 assert.equal(editableProposal.doc.querySelector('#valuation-details').open,false);
 assert.match(editableProposal.doc.querySelector('.valuation-disclaimer').textContent,/^Estimación orientativa, editable y sujeta a confirmación$/);
 assert.match(editableProposal.doc.querySelector('#preview-condition-specs').textContent,/Desgaste visible|Horquillas/);
 assert.equal(editableProposal.doc.querySelector('#preview-condition-specs img'),null);
 const refs=editableProposal.doc.querySelector('#valuation-comparables');
 assert.equal(refs.children.length,0);assert.equal(refs.querySelector('img,script'),null);
 assert.equal(refs.textContent,'');
 assert.doesNotMatch(editableProposal.doc.querySelector('#auto-valuation-section').textContent,/PRIVATE-PROOF-NOT-FOR-UI/);
 for(const a of refs.querySelectorAll('a')){assert.equal(a.target,'_blank');assert.equal(a.rel,'noopener noreferrer');}
 assert.equal(editableProposal.doc.querySelector('#price').value,'1200.50','valuation suggested_price never replaces saved asking price');
 input(editableProposal,'model','Otra identificación');assert.equal(refs.children.length,0);assert.match(editableProposal.doc.querySelector('#valuation-status').textContent,/identificación cambió/);
 editableProposal.close();pass('visual and price proposals stay editable while comparable sources stay out of the sheet');

 let evolving,releaseInitial,server,evolvingSaves=[];
 evolving=setup(async(url,o)=>{
   if(url.includes('/api/analisis/evolving-initial/')){
     await new Promise(resolve=>releaseInitial=resolve);
     const job=completed(evolving.state,{...conditionData,...valuationData});job.machine.valuation=valuationMeta;job.result.valuation={...valuationMeta,fields:{price:'777777',currency:'EUR'}};server=JSON.parse(JSON.stringify(job.machine));return response(200,job);
   }
   if(url.endsWith('guardar/')){
     const payload=JSON.parse(o.body);evolvingSaves.push(payload);assert.equal(payload.revision,server.revision);
     Object.assign(server.data,payload.data);Object.assign(server.provenance,payload.provenance);server.revision++;
     return response(200,{revision:server.revision});
   }
   if(url.endsWith('analizar/')){assert.equal(JSON.parse(o.body).revision,server.revision);return response(200,{id:'evolving-again',status:'running'});}
   if(url.includes('/api/analisis/evolving-again/')){
     const job=completed(server,{applications:'Uso actualizado sin reemplazar la estimación corregida'});job.machine.valuation=valuationMeta;job.result.valuation={...valuationMeta,suggested_price:'999999'};server=JSON.parse(JSON.stringify(job.machine));return response(200,job);
   }
   throw Error(url);
 },{job:{id:'evolving-initial',status:'completed'}});
 input(evolving,'price','0');input(evolving,'currency','EUR');input(evolving,'preservation_condition','Aceptable');
 releaseInitial();await pause(40);
 assert.equal(evolving.doc.querySelector('#price').value,'0');assert.equal(evolving.doc.querySelector('#currency').value,'EUR');assert.equal(evolving.doc.querySelector('#preservation_condition').value,'Aceptable');assert.equal(evolving.doc.querySelector('#estimate_min').value,'1000.25');
 await pause(900);assert.equal(evolvingSaves.length,1);assert.deepEqual(evolvingSaves[0].data,{price:'0',currency:'EUR',preservation_condition:'Aceptable'});assert.equal(evolvingSaves[0].revision,2);
 input(evolving,'estimate_min','');input(evolving,'visible_defects','');input(evolving,'operating_status','');
 click(evolving,'analyze-button');await pause(90);
 assert.deepEqual(evolvingSaves[1].data,{estimate_min:null,visible_defects:null,operating_status:null});
 assert.deepEqual(evolvingSaves[1].provenance.visible_defects,{source:'user',review:'confirmed'});
 assert.equal(evolving.doc.querySelector('#estimate_min').value,'');assert.equal(evolving.doc.querySelector('#visible_defects').value,'');assert.equal(evolving.doc.querySelector('#operating_status').value,'');
 assert.equal(evolving.doc.querySelector('#estimate_max').value,'1500.75');assert.equal(evolving.doc.querySelector('#applications').value,'Uso actualizado sin reemplazar la estimación corregida');assert.equal(evolving.doc.querySelector('#price').value,'0');assert.equal(evolving.doc.querySelector('#currency').value,'EUR');assert.equal(evolving.doc.querySelector('#preservation_condition').value,'Aceptable');
 assert.equal(evolving.doc.querySelector('#preview-condition-specs [data-preview-field="visible_defects"]'),null);
 assert.doesNotMatch(evolving.doc.querySelector('#preview-commercial-specs').textContent,/Precio/);assert.equal(evolving.doc.querySelector('#auto-valuation-section #price').value,'0');assert.equal(evolving.doc.querySelector('#auto-valuation-section #currency').value,'EUR');
 evolving.close();pass('valuation hydration preserves in-flight edits, zero and asking currency; deliberate clears flush before reanalysis and remain cleared afterward');

 let insufficient;
 insufficient=setup(async(url)=>{assert.ok(url.includes('/api/analisis/'));await pause(1);const job=completed(insufficient.state,{estimate_missing_info:'Faltan comparables de la misma configuración y mercado'});job.machine.valuation={};job.result.valuation={status:'insufficient',fields:{estimate_min:'99999',price:'99999'},suggested_price:'99999',comparables:valuationMeta.comparables};return response(200,job);},{job:{id:'insufficient',status:'completed'}});
 await pause(40);assert.match(insufficient.doc.querySelector('#valuation-status').textContent,/referencias de precio suficientes.*misma configuración y mercado/);assert.equal(insufficient.doc.querySelector('#estimate_min').value,'');assert.equal(insufficient.doc.querySelector('#price').value,'');assert.doesNotMatch(insufficient.doc.querySelector('#preview-valuation-specs').textContent,/Base de la estimación/);assert.equal(insufficient.doc.querySelector('#valuation-comparables').children.length,0);assert.equal(insufficient.doc.querySelector('#submit-machine').disabled,false);assert.equal(insufficient.doc.querySelectorAll('input[type="checkbox"]').length,1);insufficient.close();
 const clearedEstimate=setup(async()=>{throw Error('No request expected');},{state:{valuation:valuationMeta},data:{...valuationData}});
 for(const key of ['estimate_min','estimate_max','estimate_currency','estimate_market','estimate_basis','estimate_missing_info','price'])input(clearedEstimate,key,'');
 assert.equal(clearedEstimate.doc.querySelector('#valuation-comparables').children.length,0);assert.match(clearedEstimate.doc.querySelector('#valuation-status').textContent,/No hay una estimación activa/);clearedEstimate.close();
 pass('insufficient valuation gives concrete missing information without inventing a price or blocking submission, and clearing proposals hides their references');
 const onlyReason=setup(async()=>{throw Error('No request expected');},{data:{estimate_basis:'Estimación orientativa',estimate_missing_info:'Falta identificar modelo'}});
 assert.match(onlyReason.doc.querySelector('#valuation-status').textContent,/No hay una estimación activa.*Falta identificar modelo/);
 assert.doesNotMatch(onlyReason.doc.querySelector('#valuation-status').textContent,/Estos importes/);
 const conditionalReference=setup(async()=>{throw Error('Conditional reference preview must not make requests');},{state:{valuation:{status:'conditional_reference',suggested_price:null,comparables:[]},provenance:{estimate_min:{source:'valuation',review:'needs_review'},estimate_max:{source:'valuation',review:'needs_review'},estimate_basis:{source:'valuation',review:'needs_review'}}},data:{estimate_min:'1000',estimate_max:'1500',estimate_currency:'USD',estimate_basis:'Comparables con condición documentada',estimate_missing_info:'Confirmar condición de esta unidad',price:null}});
 assert.match(conditionalReference.doc.querySelector('#valuation-disclaimer').textContent,/Referencia de mercado condicional/);assert.match(conditionalReference.doc.querySelector('#valuation-status').textContent,/no confirma la condición de esta unidad.*No se completó un precio de anuncio sugerido/);assert.equal(conditionalReference.doc.querySelector('#price').value,'');conditionalReference.close();pass('conditional market reference is explicit, keeps asking price blank and remains editable');
 onlyReason.close();pass('a missing-data explanation alone is never displayed as an existing monetary estimate');
 let invalidatedSave,invalidatedCalls=[];
 invalidatedSave=setup(async(url,o)=>{
   assert.ok(url.endsWith('guardar/'));const body=JSON.parse(o.body);invalidatedCalls.push(body);
   assert.deepEqual(body.data,{model:'NUEVA IDENTIDAD'});
   const clean={...invalidatedSave.state.data,model:'NUEVA IDENTIDAD'};
   for(const key of [...Object.keys(valuationData),'price','currency'])delete clean[key];
   return response(200,{revision:2,machine:{...invalidatedSave.state,revision:2,data:clean,provenance:{model:{source:'user',review:'confirmed'}},valuation:{}}});
 },{data:{...valuationData,model:'ANTERIOR',preservation_notes:'Nota manual conservada'},state:{valuation:valuationMeta,provenance:{price:{source:'valuation',review:'needs_review'},estimate_min:{source:'valuation',review:'needs_review'}}}});
 input(invalidatedSave,'model','NUEVA IDENTIDAD');await pause(950);
 assert.equal(invalidatedCalls.length,1);assert.equal(invalidatedSave.doc.querySelector('#save-status').textContent,'Guardado');
 for(const key of ['price','estimate_min','estimate_max','estimate_currency','estimate_basis'])assert.equal(invalidatedSave.doc.querySelector(`[data-field="${key}"]`).value,'',key+' server invalidation must be reflected immediately');
 assert.equal(invalidatedSave.doc.querySelector('#valuation-comparables').children.length,0);
 assert.doesNotMatch(invalidatedSave.doc.querySelector('#preview-commercial-specs').textContent,/Precio|Consultar precio/);assert.equal(invalidatedSave.doc.querySelector('#auto-valuation-section #price').value,'');
 assert.equal(invalidatedSave.doc.querySelector('#preservation_notes').value,'Nota manual conservada');invalidatedSave.close();
 pass('successful identity save rehydrates server-invalidated automatic price and range instead of leaving stale values marked saved');

 for(const manualPrice of ['0','']){
   let duringSave,finishFirst,finishSecond,serverSaved;const bodies=[];
   duringSave=setup(async(url,o)=>{
     assert.ok(url.endsWith('guardar/'));const body=JSON.parse(o.body);bodies.push(body);
     if(bodies.length===1){
       await new Promise(resolve=>finishFirst=resolve);
       serverSaved={...duringSave.state,revision:2,data:{brand:'Original',model:'NUEVO',preservation_notes:'Nota aún pendiente de corregir'},provenance:{model:{source:'user',review:'confirmed'}},valuation:{}};
       return response(200,{revision:2,machine:JSON.parse(JSON.stringify(serverSaved))});
     }
     assert.equal(body.revision,2);assert.deepEqual(body.data,{price:manualPrice===''?null:'0',currency:'EUR',preservation_notes:null});
     await new Promise(resolve=>finishSecond=resolve);
     serverSaved={...serverSaved,revision:3,data:{...serverSaved.data,...body.data},provenance:{...serverSaved.provenance,...body.provenance}};
     return response(200,{revision:3,machine:serverSaved});
   },{data:{...valuationData,preservation_notes:'Nota aún pendiente de corregir'},state:{valuation:valuationMeta,provenance:{price:{source:'valuation',review:'needs_review'}}}});
   input(duringSave,'model','NUEVO');await pause(900);
   input(duringSave,'price',manualPrice);input(duringSave,'currency','EUR');input(duringSave,'preservation_notes','');finishFirst();await pause(35);
   assert.equal(bodies.length,2);assert.equal(duringSave.doc.querySelector('#price').value,manualPrice);assert.equal(duringSave.doc.querySelector('#currency').value,'EUR');assert.equal(duringSave.doc.querySelector('#preservation_notes').value,'');assert.equal(duringSave.doc.querySelector('#estimate_min').value,'');
   finishSecond();await pause(35);
   assert.equal(duringSave.doc.querySelector('#price').value,manualPrice);assert.equal(duringSave.doc.querySelector('#currency').value,'EUR');assert.equal(duringSave.doc.querySelector('#preservation_notes').value,'');assert.equal(duringSave.doc.querySelector('#save-status').textContent,'Guardado');
   assert.equal(duringSave.doc.querySelector('#valuation-comparables').children.length,0);
   const unload=new duringSave.w.Event('beforeunload',{cancelable:true});duringSave.w.dispatchEvent(unload);assert.equal(unload.defaultPrevented,false);duringSave.close();
 }
 pass('save response hydration preserves newer pending manual zero, EUR and explicit blanks, then saves them against the returned revision');
 const age = setup(async()=>{throw Error('No request expected');},{data:{year:2007,estimated_year_from:2004,estimated_year_to:2009,estimated_year_basis:'<img src=x onerror=alert(1)> Indicio, no año exacto'}});
 for(const key of ['estimated_year_from','estimated_year_to']){const field=age.doc.getElementById(key);assert.equal(field.min,'1900');assert.equal(field.max,String(new Date().getFullYear()));assert.equal(field.step,'1');assert.equal(field.required,false);assert.equal(age.doc.querySelectorAll(`[data-field="${key}"]`).length,1);}
 assert.equal(age.doc.querySelector('#age-details').open,false);assert.equal(age.doc.querySelector('#estimated_year_basis').maxLength,2000);assert.equal(age.doc.querySelector('#year').value,'2007');assert.equal(age.doc.querySelector('#preview-age-range').textContent,'2004–2009');
 assert.equal(age.doc.querySelector('#preview-age-basis img'),null);assert.match(age.doc.querySelector('#preview-age-basis').textContent,/<img/);assert.match(age.doc.querySelector('#auto-age-heading').textContent,/Año aproximado · por confirmar/);
 input(age,'estimated_year_from','');assert.equal(age.doc.querySelector('#preview-age-range').textContent,'Hasta 2009');input(age,'estimated_year_to','');assert.equal(age.doc.querySelector('#preview-age-range').hidden,true);assert.equal(age.doc.querySelector('#preview-age-basis').hidden,true);assert.equal(age.doc.querySelector('#year').value,'2007');assert.equal(age.doc.querySelector('#submit-machine').disabled,false);age.close();
 pass('optional approximate age is bounded, separate from the exact year, safely rendered and hidden when both endpoints are cleared');
 let ageInflight,ageRelease,ageServer;const ageSaves=[];
 ageInflight=setup(async(url,o)=>{
   if(url.includes('/api/analisis/age-initial/')){await new Promise(resolve=>ageRelease=resolve);const job=completed(ageInflight.state,{estimated_year_from:2000,estimated_year_to:2010,estimated_year_basis:'Indicios automáticos'});ageServer=JSON.parse(JSON.stringify(job.machine));return response(200,job);}
   if(url.endsWith('guardar/')){const body=JSON.parse(o.body);ageSaves.push(body);assert.equal(body.revision,ageServer.revision);Object.assign(ageServer.data,body.data);Object.assign(ageServer.provenance,body.provenance);ageServer.revision++;return response(200,{revision:ageServer.revision,machine:JSON.parse(JSON.stringify(ageServer))});}
   if(url.endsWith('analizar/')){assert.equal(JSON.parse(o.body).revision,ageServer.revision);return response(200,{id:'age-again',status:'running'});}
   if(url.includes('/api/analisis/age-again/')){const job=completed(ageServer,{applications:'Aplicación actualizada'});job.result.data={...job.result.data,estimated_year_from:1999,estimated_year_to:2012,estimated_year_basis:'No copiar este resultado sobre la ficha'};ageServer=JSON.parse(JSON.stringify(job.machine));return response(200,job);}
   throw Error(url);
 },{data:{year:2007},job:{id:'age-initial',status:'completed'}});
 input(ageInflight,'estimated_year_from','2005');input(ageInflight,'estimated_year_to','');input(ageInflight,'estimated_year_basis','');input(ageInflight,'price','0');input(ageInflight,'currency','EUR');ageRelease();await pause(40);
 assert.equal(ageInflight.doc.querySelector('#estimated_year_from').value,'2005');assert.equal(ageInflight.doc.querySelector('#estimated_year_to').value,'');assert.equal(ageInflight.doc.querySelector('#estimated_year_basis').value,'');assert.equal(ageInflight.doc.querySelector('#year').value,'2007');assert.equal(ageInflight.doc.querySelector('#preview-age-range').textContent,'Desde 2005');
 await pause(900);assert.equal(ageSaves.length,1);assert.deepEqual(ageSaves[0].data,{estimated_year_from:'2005',estimated_year_to:null,estimated_year_basis:null,price:'0',currency:'EUR'});assert.equal(ageSaves[0].revision,2);
 input(ageInflight,'estimated_year_from','');click(ageInflight,'analyze-button');await pause(90);
 assert.deepEqual(ageSaves[1].data,{estimated_year_from:null});assert.deepEqual(ageSaves[1].provenance.estimated_year_from,{source:'user',review:'confirmed'});
 for(const key of ['estimated_year_from','estimated_year_to','estimated_year_basis'])assert.equal(ageInflight.doc.getElementById(key).value,'');assert.equal(ageInflight.doc.querySelector('#preview-age-range').hidden,true);assert.equal(ageInflight.doc.querySelector('#year').value,'2007');assert.equal(ageInflight.doc.querySelector('#price').value,'0');assert.equal(ageInflight.doc.querySelector('#currency').value,'EUR');assert.equal(ageInflight.doc.querySelector('#applications').value,'Aplicación actualizada');ageInflight.close();
 pass('approximate age hydration keeps in-flight edits, explicit clears and zero price; reanalysis consumes the saved machine instead of raw suggested years');
 console.log(JSON.stringify({suite:'quick-intake-dom',checks,passed:checks,uncaughtErrors:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
