'use strict';
(() => {
  const snapshot = document.getElementById('sheet-completion-data');
  let resolvePending = null, trigger = null;
  function values() {
    const form = document.querySelector('#wizard, #machine-wizard, [data-api-base]');
    if (form) return Object.fromEntries([...form.querySelectorAll('[data-field]')].map(input => [input.dataset.field, input.value]));
    try { return snapshot ? JSON.parse(snapshot.textContent) : null; } catch { return null; }
  }
  const populated = value => value !== null && value !== undefined && String(value).trim() !== '';
  function missing(data) {
    if (!data) return [];
    const items = [];
    if (!populated(data.location) && !populated(data.location_country)) items.push({id:'location_country',label:'País donde está la máquina',why:'Ayuda a valorar transporte y mercado.'});
    if (!populated(data.location) && !populated(data.location_city)) items.push({id:'location_city',label:'Ciudad o municipio',why:'Facilita coordinar una visita.'});
    if (!populated(data.hours)) items.push({id:'hours',label:'Horas de uso',why:'Ayudan al comprador a comparar equipos.'});
    return items;
  }
  const dialog = document.createElement('dialog');
  dialog.id='sheet-completeness'; dialog.className='sheet-completeness';
  dialog.setAttribute('aria-labelledby','sheet-completeness-title');
  dialog.setAttribute('aria-describedby','sheet-completeness-description');
  dialog.innerHTML='<div class="completion-dialog-heading"><span class="eyebrow">Antes de continuar</span><button type="button" data-completion-close aria-label="Cerrar sugerencias">×</button></div><h2 id="sheet-completeness-title">Tu ficha puede ser más útil</h2><p id="sheet-completeness-description">Si conoces estos datos, te recomendamos añadirlos. Puedes continuar ahora y completarlos después.</p><ul data-completion-list></ul><div class="completion-dialog-actions"><button type="button" class="button button-navy" data-completion-edit>Rellenar estos datos</button><button type="button" class="button button-outline" data-completion-continue>Continuar sin rellenar</button></div>';
  document.body.append(dialog);
  function finish(continueAction) {
    const resolve=resolvePending; resolvePending=null;
    if (typeof dialog.close==='function') dialog.close(); else dialog.removeAttribute('open');
    trigger?.focus();
    resolve?.(continueAction);
  }
  dialog.querySelector('[data-completion-close]').addEventListener('click',()=>finish(false));
  dialog.querySelector('[data-completion-continue]').addEventListener('click',()=>finish(true));
  dialog.addEventListener('cancel',event=>{event.preventDefault();finish(false);});
  dialog.addEventListener('close',()=>{if(resolvePending)finish(false);});
  dialog.querySelector('[data-completion-edit]').addEventListener('click',()=>{
    const first=missing(values())[0]; finish(false);
    if (!first) return;
    const field=document.getElementById(first.id);
    if (field) {
      for (let parent=field.parentElement;parent;parent=parent.parentElement) if(parent.tagName==='DETAILS')parent.open=true;
      field.scrollIntoView({behavior:'smooth',block:'center'});field.focus({preventScroll:true});
    } else { const url=document.getElementById('sheet-completion-context')?.dataset.editorUrl; if(url)location.assign(url+'#'+first.id); }
  });
  window.imcSheetCompleteness={
    missing,
    confirm() {
      const items=missing(values());
      if (!items.length) return Promise.resolve(true);
      if (resolvePending) return Promise.resolve(false);
      trigger=document.activeElement;
      const list=dialog.querySelector('[data-completion-list]'); list.replaceChildren();
      for(const item of items){const li=document.createElement('li'),title=document.createElement('strong'),detail=document.createElement('span');title.textContent=item.label;detail.textContent=item.why;li.append(title,detail);list.append(li);}
      const result=new Promise(resolve=>{resolvePending=resolve;});
      if(typeof dialog.showModal==='function')dialog.showModal();else dialog.setAttribute('open','');
      dialog.querySelector('[data-completion-edit]').focus();
      return result;
    }
  };
})();
