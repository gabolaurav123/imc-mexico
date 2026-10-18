const {JSDOM, VirtualConsole}=require('jsdom');
const fs=require('fs'), path=require('path'), assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const script=fs.readFileSync(path.join(__dirname,'../static/portal/app.js'),'utf8');
const render=guest=>execFileSync(process.env.PYTHON||'python',[path.join(__dirname,'render_quick_fixture.py'),...(guest?['--guest']:[])],{
  cwd:path.resolve(__dirname,'../..'),encoding:'utf8',maxBuffer:4*1024*1024,env:{...process.env,PYTHONIOENCODING:'utf-8'}
});
const html=render(false), guestHtml=render(true), pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const response=(status,body)=>({ok:status>=200&&status<300,status,headers:{get:()=> 'application/json'},json:async()=>body});
async function until(check){const end=Date.now()+4000;while(!check()){assert.ok(Date.now()<end,'Expected state not reached');await pause(10);}}
function setup(handler,{guest=false,result={}}={}){
  const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>{if(!e.message.includes('navigation'))errors.push(e.message);});
  const dom=new JSDOM(guest?guestHtml:html,{url:'https://test.invalid/panel/maquinarias/fixture/?paso=2',runScripts:'outside-only',virtualConsole:vc});
  const w=dom.window,doc=w.document;w.HTMLElement.prototype.scrollIntoView=function(){};w.confirm=()=>true;
  let server=JSON.parse(doc.querySelector('#machine-state').textContent), starts=0;
  const calls=[];
  const initial=doc.createElement('script');initial.id='current-job';initial.textContent=JSON.stringify({id:'original',status:'completed'});doc.body.append(initial);
  const job=(id,changes={})=>({id,status:'completed',input_category:701,input_assets:[{id:'1',purpose:'general'},{id:'2',purpose:'plate'}],
    result:{relevance:{status:'relevant',accepted_asset_ids:['1','2']},data:{},...result},machine:{...server,data:{...server.data,...changes}},
    guest_draft:{analysis_used:true,serial_enrichment_available:false},auto_apply:{requested:true,status:'applied',applied_fields:[],skipped_fields:[]}});
  w.fetch=async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
    if(url.endsWith('/original/'))return response(200,job('original'));
    if(url.endsWith('/guardar/')){
      server={...server,...(body.category!==undefined?{category:body.category}:{}),revision:server.revision+1,data:{...server.data,...body.data},provenance:{...server.provenance,...body.provenance}};
      const custom=await handler?.({kind:'save',url,body,server,job,w,doc});
      return custom||response(200,{revision:server.revision,machine:server});
    }
    if(url.endsWith('/analizar/')){starts++;return response(200,{id:'refresh-'+starts,status:'queued'});}
    const custom=await handler?.({kind:'other',url,body,server,job,w,doc});
    if(custom)return custom;
    throw Error('Unexpected request '+url);
  };
  w.eval(script);
  return {w,doc,calls,starts:()=>starts,input(id,value){const el=doc.getElementById(id);el.value=value;el.dispatchEvent(new w.Event('input',{bubbles:true}));},
    commit(){const el=doc.getElementById('serial');el.dispatchEvent(new w.Event('change',{bubbles:true}));el.dispatchEvent(new w.Event('blur'));},
    close(){assert.deepEqual(errors,[]);dom.window.close();}};
}
(async()=>{
  let release;
  const c=setup(async({kind,url,job})=>{
    if(kind==='other'&&url.endsWith('/refresh-1/')){await new Promise(resolve=>release=resolve);return response(200,job('refresh-1',{model:'AP655',description:'Descripción sugerida'}));}
  });
  await until(()=>c.doc.querySelector('#ready-heading').textContent==='Tu ficha está preparada.');
  for(const value of ['S','SE','SER','SER-2026'])c.input('serial',value);
  await pause(450);assert.equal(c.starts(),0,'typing never starts a paid job');
  c.commit();await until(()=>c.starts()===1&&release);
  const save=c.calls.find(x=>x.url.endsWith('/guardar/'));
  assert.equal(save.body.data.serial,'SER-2026');
  const analyze=c.calls.find(x=>x.url.endsWith('/analizar/'));
  assert.equal(analyze.body.revision,2);assert.equal(analyze.body.auto_apply,true);assert.equal(analyze.body.research,true);
  assert.deepEqual(analyze.body.asset_ids,['1','2'],'updated serial uses the existing photos for consistency');
  c.input('description','Mi descripción corregida se conserva.');release();await pause(60);
  assert.equal(c.doc.querySelector('#model').value,'AP655');assert.equal(c.doc.querySelector('#description').value,'Mi descripción corregida se conserva.');
  c.commit();await pause(420);assert.equal(c.starts(),1,'change plus blur and repeated focus do not duplicate jobs');
  c.input('serial','sin serie');c.commit();await pause(420);assert.equal(c.starts(),1,'placeholder is never researched automatically');
  c.close();console.log('PASS serial completion saves once, enriches with existing photos and preserves concurrent corrections without per-keystroke calls');

  let releaseFirst;
  const queued=setup(async({url,job})=>{
    if(url.endsWith('/refresh-1/')){await new Promise(resolve=>releaseFirst=resolve);return response(200,job('refresh-1',{model:'Modelo previo'}));}
    if(url.endsWith('/refresh-2/'))return response(200,job('refresh-2',{model:'Modelo de serie corregida'}));
  });
  await until(()=>queued.doc.querySelector('#ready-heading').textContent==='Tu ficha está preparada.');
  queued.input('serial','PRIMERA-SERIE');queued.commit();await until(()=>releaseFirst);
  queued.input('serial','SERIE-CORREGIDA');queued.commit();await pause(400);
  assert.equal(queued.starts(),1,'a committed correction waits for the running analysis');
  releaseFirst();await until(()=>queued.starts()===2&&queued.doc.querySelector('#model').value==='Modelo de serie corregida');
  assert.equal(queued.doc.querySelector('#serial').value,'SERIE-CORREGIDA');
  assert.equal(queued.calls.filter(call=>call.url.endsWith('/guardar/')).at(-1).body.data.serial,'SERIE-CORREGIDA');
  queued.close();console.log('PASS a serial corrected during analysis queues one refresh after the first job, preserving the latest serial');

  for(const available of [true,false]){
    const g=setup(async({kind,url,server,job})=>{
      if(kind==='save')return response(200,{revision:server.revision,machine:{...server,serial_enrichment_available:available}});
      if(url.endsWith('/refresh-1/'))return response(200,job('refresh-1',{model:'AP655'}));
    },{guest:true});
    await until(()=>g.doc.querySelector('#ready-heading').textContent==='Tu ficha está preparada.');
    g.input('serial','GUEST-NEW-SERIAL');g.commit();await pause(450);
    assert.equal(g.starts(),Number(available),'guest supplement follows server entitlement after saving');
    if(!available)assert.match(g.doc.querySelector('#serial-refresh-status').textContent,/Crea tu cuenta/);
    assert.ok(g.calls.every(call=>call.url.startsWith('/api/invitados/')));
    g.close();
  }
  console.log('PASS guest serial enrichment uses saved server entitlement and never bypasses the single-use limit');

  for(const result of [
    {category_conflict:{selected:'Excavadoras',detected:'Montacargas',message:'El tipo no coincide con las fotos.'}},
    {integrity:{category_conflict:{selected:'Excavadoras',detected:'Montacargas',message:'El tipo no coincide con las fotos.'}}},
    {processing_integrity:{multiple_machines:{message:'Hay dos máquinas diferentes.'}}}
  ]){
    const c=setup(null,{result});await pause(50);
    assert.equal(c.doc.querySelector('[data-step-panel="1"]').hidden,false);
    assert.equal(c.doc.querySelector('[data-share-machine]').disabled,true);
    assert.equal(c.doc.querySelector('#submit-machine').disabled,true);
    assert.equal(c.doc.querySelector('#analyze-button').disabled,true);
    assert.doesNotMatch(c.doc.querySelector('#ready-heading').textContent,/lista|preparada/);
    c.doc.querySelector('[data-step-to="2"]').click();
    assert.equal(c.doc.querySelector('[data-step-panel="1"]').hidden,false,'step navigation cannot bypass evidence rejection');
    assert.equal(c.calls.length,1,'rejected photos trigger no legacy application or sharing');
    if(result.category_conflict || result.integrity?.category_conflict){
      c.doc.querySelector('#photo-correction-actions button').click();await pause(30);
      assert.equal(c.doc.querySelector('#category').value,'702');
      assert.equal(c.doc.querySelector('#analyze-button').disabled,false,'fixing the category permits re-analysis');
      assert.equal(c.doc.querySelector('[data-share-machine]').disabled,true,'changing the category alone does not certify the photos');
      assert.equal(c.starts(),0,'category correction does not silently incur another analysis');
    }
    c.close();
  }
  console.log('PASS category conflicts and multiple machines block ready/share/submit even without a legacy blocking_reason');

  const alias=setup(null,{result:{category_conflict:{selected:'Montacargas',detected:'Excavadora',message:'El tipo no coincide.'}}});
  await pause(50);
  assert.match(alias.doc.querySelector('#photo-correction-actions').textContent,/Cambiar tipo a Excavadoras/,'singular category alias resolves to the real selectable category');
  alias.close();
  console.log('PASS detected singular category maps to a clear correction button');

  const historicalConflict={blocking_reason:'multiple_machines',multiple_machines:{detected:true,message:'Se detectaron tres máquinas.'}};
  for(const accepted of [true,false]){
    let finishRecheck;
    const c=setup(async({url,job})=>{
      if(url.endsWith('/refresh-1/')){
        await new Promise(resolve=>finishRecheck=resolve);
        const fresh=job('refresh-1',{model:'AP655'});
        fresh.result={relevance:{status:'relevant',accepted_asset_ids:['1','2']},...(accepted?{}:historicalConflict)};
        return response(200,fresh);
      }
    },{result:historicalConflict});
    await pause(50);
    const button=c.doc.querySelector('[data-recheck-photos]');assert.ok(button,'historical conflict has an explicit recheck route');
    assert.equal(c.doc.querySelector('#model').value,'');
    button.click();button.click();await until(()=>finishRecheck);
    assert.equal(c.starts(),1,'double-click starts only one recheck');
    assert.equal(c.doc.querySelector('[data-share-machine]').disabled,true,'recheck never itself authorizes sharing');
    assert.equal(c.doc.querySelector('#submit-machine').disabled,true,'recheck never itself authorizes submitting');
    assert.equal(c.doc.querySelector('#model').value,'','the original rejected result was never hydrated');
    finishRecheck();await pause(50);
    assert.equal(c.doc.querySelector('#model').value,accepted?'AP655':'');
    assert.equal(c.doc.querySelector('[data-share-machine]').disabled,!accepted);
    assert.equal(c.doc.querySelector('#submit-machine').disabled,!accepted);
    assert.equal(c.doc.querySelector('#analyze-button').disabled,!accepted);
    if(!accepted)assert.ok(c.doc.querySelector('[data-recheck-photos]'),'a fresh rejection remains blocked with a deliberate retry route');
    c.close();
  }
  const guestConflict=setup(null,{guest:true,result:historicalConflict});await pause(50);
  assert.equal(guestConflict.doc.querySelector('[data-recheck-photos]'),null,'guest historical rejection cannot bypass the trial quota');
  assert.equal(guestConflict.starts(),0);guestConflict.close();
  console.log('PASS explicit historical-photo recheck preserves share/submit gates until acceptance, reblocks rejection and keeps guest limits');
})().catch(error=>{console.error(error);process.exitCode=1;});
