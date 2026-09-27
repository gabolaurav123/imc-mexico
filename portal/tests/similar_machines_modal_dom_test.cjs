const {JSDOM,VirtualConsole}=require('jsdom');
const fs=require('fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..');
const sheet=fs.readFileSync(path.join(root,'templates/portal/sheet.html'),'utf8');
const markup=sheet.match(/<dialog id="similar-machines-modal"[\s\S]*?<\/dialog>/)[0];
const footer=sheet.match(/<div class="similar-machines-cta">[\s\S]*?<\/div>/)[0];
const shareMarkup=fs.readFileSync(path.join(root,'templates/portal/includes/share_modal.html'),'utf8');
const script=fs.readFileSync(path.join(root,'static/portal/similar-machines-modal.js'),'utf8');
const shareScript=fs.readFileSync(path.join(root,'static/portal/share-modal.js'),'utf8');
let checks=0;
function setup({native=true,previous=true,includeModal=true,shareOpen=false}={}){
  const errors=[],virtualConsole=new VirtualConsole();
  virtualConsole.on('jsdomError',error=>errors.push(error.message));
  const dom=new JSDOM(`<button id="previous">Anterior</button><div id="already-inert"></div><main><h1 id="sheet-title" tabindex="-1">Ficha</h1><button id="share-button" data-share-sheet="/s/example/">Compartir ficha</button>${includeModal?markup:''}${footer}${shareMarkup}</main>`,{url:'https://example.invalid/s/example/',runScripts:'outside-only',virtualConsole});
  const w=dom.window,doc=w.document;
  Object.defineProperty(doc,'readyState',{value:'complete'});
  for(const key of ['localStorage','sessionStorage'])Object.defineProperty(w,key,{get(){throw Error('This invitation must not persist browser state');}});
  w.fetch=()=>{throw Error('This invitation must not send requests');};
  if(native){
    w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
    w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');this.dispatchEvent(new w.Event('close'));};
  }else{
    w.HTMLDialogElement.prototype.showModal=undefined;
    w.HTMLDialogElement.prototype.close=undefined;
  }
  doc.getElementById('already-inert').inert=true;
  if(previous)doc.getElementById('previous').focus();
  if(shareOpen)doc.getElementById('share-modal').setAttribute('open','');
  w.eval(shareScript);w.eval(script);
  return {w,doc,modal:doc.getElementById('similar-machines-modal'),close(){assert.deepEqual(errors,[]);dom.window.close();}};
}
function key(ctx,name,shiftKey=false){const event=new ctx.w.KeyboardEvent('keydown',{key:name,shiftKey,bubbles:true,cancelable:true});ctx.modal.dispatchEvent(event);return event;}
const main=setup();
assert.equal(main.modal.open,true);
assert.equal(main.doc.activeElement,main.modal.querySelector('[data-close-similar-machines]'));
assert.equal(main.modal.getAttribute('aria-labelledby'),'similar-machines-modal-title');
assert.equal(main.modal.getAttribute('aria-describedby'),'similar-machines-modal-description');
assert.equal(main.modal.getAttribute('aria-modal'),'true');
const link=main.modal.querySelector('a'),footerLink=main.doc.querySelector('.similar-machines-cta a');
assert.equal(link.href,'https://www.imcmexico.com.mx/catalogo-de-maquinaria');
assert.equal(link.href,footerLink.href);assert.equal(link.textContent,footerLink.textContent);
assert.equal(link.target,'_blank');assert.match(link.rel,/noopener/);assert.match(link.rel,/noreferrer/);
assert.equal(main.doc.querySelectorAll('.similar-machines-cta').length,1);
const first=main.modal.querySelector('button'),last=main.modal.querySelector('.similar-machines-modal__actions button');
last.focus();assert.equal(key(main,'Tab').defaultPrevented,true);assert.equal(main.doc.activeElement,first);
first.focus();assert.equal(key(main,'Tab',true).defaultPrevented,true);assert.equal(main.doc.activeElement,last);
main.doc.getElementById('previous').focus();assert.equal(main.doc.activeElement,first,'focus remains in the invitation');
main.modal.querySelector('p').click();assert.equal(main.modal.open,true,'clicking content does not dismiss');
first.click();assert.equal(main.modal.open,false);assert.equal(main.doc.activeElement,main.doc.getElementById('previous'));
main.w.eval(script);assert.equal(main.modal.open,false,'duplicate initialization does not reopen a dismissed invitation');
main.close();checks++;

for(const method of ['continue','escape','cancel','backdrop']){
  const ctx=setup();
  if(method==='continue')ctx.modal.querySelector('.similar-machines-modal__actions button').click();
  if(method==='escape')key(ctx,'Escape');
  if(method==='cancel')ctx.modal.dispatchEvent(new ctx.w.Event('cancel',{cancelable:true}));
  if(method==='backdrop')ctx.modal.dispatchEvent(new ctx.w.MouseEvent('click',{bubbles:true}));
  assert.equal(ctx.modal.open,false,method+' closes the invitation');
  assert.equal(ctx.doc.activeElement,ctx.doc.getElementById('previous'));
  ctx.close();checks++;
}
const fresh=setup({previous:false});assert.equal(fresh.modal.open,true,'every fresh page load shows the invitation');
fresh.modal.querySelector('button').click();assert.equal(fresh.doc.activeElement,fresh.doc.getElementById('sheet-title'),'automatic entry restores focus to the sheet title');fresh.close();checks++;

const fallback=setup({native:false});
assert.equal(fallback.modal.open,true);assert.ok(fallback.doc.querySelector('.similar-machines-modal-backdrop'));
assert.equal(fallback.doc.getElementById('previous').inert,true);assert.equal(fallback.doc.getElementById('already-inert').inert,true);
fallback.doc.querySelector('.similar-machines-modal-backdrop').click();
assert.equal(fallback.modal.open,false);assert.equal(fallback.doc.querySelector('.similar-machines-modal-backdrop'),null);
assert.equal(fallback.doc.getElementById('previous').inert,false);assert.equal(fallback.doc.getElementById('already-inert').inert,true);
assert.equal(fallback.doc.activeElement,fallback.doc.getElementById('previous'));fallback.close();checks++;

const sharing=setup();sharing.doc.getElementById('share-button').click();
assert.equal(sharing.modal.open,false);assert.equal(sharing.doc.getElementById('share-modal').open,true);
assert.equal(sharing.doc.getElementById('share-modal-url').value,'https://example.invalid/s/example/');sharing.close();checks++;
const other=setup({shareOpen:true});assert.equal(other.modal.open,false,'never stacks on an already open sharing dialog');other.close();checks++;
const privatePage=setup({includeModal:false});assert.equal(privatePage.modal,null);assert.equal(privatePage.doc.querySelector('.similar-machines-modal-backdrop'),null);privatePage.close();checks++;
console.log(JSON.stringify({suite:'similar-machines-modal',checks,passed:checks,uncaughtErrors:0}));
