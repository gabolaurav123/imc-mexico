const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const script=fs.readFileSync(path.join(__dirname,'../static/portal/sheet-completeness.js'),'utf8');
function fixture(html){
  const dom=new JSDOM(html,{runScripts:'outside-only',url:'https://imc.example/'});
  dom.window.HTMLElement.prototype.scrollIntoView=function(){};
  dom.window.eval(script);return dom;
}
(async()=>{
  const dom=fixture('<div id="wizard"><input id="location_country" data-field="location_country"><input id="location_city" data-field="location_city"><input id="hours" data-field="hours"></div><button id="share">Compartir</button>');
  const w=dom.window,d=w.document,api=w.imcSheetCompleteness;
  d.querySelector('#share').focus();
  let proceed=api.confirm();
  assert.equal(d.querySelectorAll('[data-completion-list] li').length,3);
  assert.equal(d.querySelector('#sheet-completeness').open,true);
  assert.equal(await api.confirm(),false,'second action cannot open a second prompt or share twice');
  d.querySelector('[data-completion-continue]').click();
  assert.equal(await proceed,true,'missing optional fields never block a conscious continue');
  assert.equal(d.activeElement.id,'share');
  proceed=api.confirm();d.querySelector('[data-completion-edit]').click();
  assert.equal(await proceed,false);assert.equal(d.activeElement.id,'location_country');
  d.querySelector('#location_country').value='México';d.querySelector('#location_city').value='Puebla';d.querySelector('#hours').value='0';
  assert.equal(await api.confirm(),true,'zero hours is valid and complete, not missing');
  d.querySelector('#hours').value='';proceed=api.confirm();
  d.querySelector('#sheet-completeness').dispatchEvent(new w.Event('cancel',{cancelable:true}));
  assert.equal(await proceed,false,'Escape cancels the pending action');dom.window.close();
  const publicDom=fixture('<article>Public sheet</article>');
  assert.equal(await publicDom.window.imcSheetCompleteness.confirm(),true,'public recipients never receive an owner edit reminder');publicDom.window.close();
  const privateDom=fixture('<script id="sheet-completion-data" type="application/json">{"location":"Monterrey","hours":200}</script>');
  assert.equal(await privateDom.window.imcSheetCompleteness.confirm(),true,'legacy location counts without asking the owner to enter it twice');privateDom.window.close();
  console.log('Sheet completeness DOM PASS: advisory, continue, edit, cancellation, zero hours, private/public separation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
