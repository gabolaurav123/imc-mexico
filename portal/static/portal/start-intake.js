'use strict';
(() => {
  const root=document.querySelector('[data-intake-start]'), form=document.getElementById('start-machine-form');
  if (!root || !form) return;
  const $=id=>document.getElementById(id), category=$('start-category'), model=$('catalogue-model');
  const sections={category:$('type-question'),brand:$('brand-question'),model:$('model-question'),identify:$('identify-question')};
  let categories=[]; try { categories=JSON.parse($('category-data').textContent); } catch { /* Photo entry remains available. */ }
  let stage='category', selectedCategory=null, selectedBrand=null, selectedModel=null, allCategories=false, submitting=false;
  const cache=new Map(), requests={brand:0,model:0}, controllers={}, timers={}, pages={brand:1,model:1};
  const error=message=>{ $('intake-error').textContent=message||''; $('intake-error').hidden=!message; };
  function show(next,focus=false) {
    stage=next; Object.entries(sections).forEach(([name,node])=>{node.hidden=name!==next;});
    $('catalogue-fallback').hidden=next==='identify'; $('catalogue-continue').hidden=next!=='model';
    document.querySelectorAll('[data-browse-back]').forEach(button=>{
      const name=button.dataset.browseBack; button.disabled=name==='brand'?!selectedCategory:name==='model'?!selectedBrand:false;
      if(name===next)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');
    });
    if(focus) sections[next].querySelector('h2')?.focus({preventScroll:true});
  }
  function resetModel() {
    selectedModel=null; model.value=''; $('known-model').value=''; $('path-model').textContent='Modelo';
    $('catalogue-selection').hidden=true; $('catalogue-generate').disabled=true; $('selection-summary').textContent='Selecciona el modelo para preparar tu ficha.';
  }
  function chooseCategory(item) {
    for(const kind of ['brand','model']){++requests[kind];controllers[kind]?.abort();clearTimeout(timers[kind]);}
    selectedCategory=item; selectedBrand=null; resetModel(); category.value=String(item.id); $('known-brand').value='';
    $('start-category-search').value=item.name; $('path-category').textContent=item.name; $('path-brand').textContent='Marca';
    $('catalogue-brand-search').value=''; $('catalogue-model-search').value=''; $('brand-title').textContent=`Marcas de ${item.name.toLocaleLowerCase('es')}`;
    $('fallback-title').textContent='¿No encuentras la marca?'; error(''); show('brand',true); load('brand');
  }
  function chooseBrand(item) {
    selectedBrand=item; resetModel(); $('known-brand').value=item.label; $('path-brand').textContent=item.label;
    $('catalogue-model-search').value=''; $('model-title').textContent=`Elige el modelo ${item.label}`;
    $('fallback-title').textContent='¿No encuentras el modelo?'; error(''); show('model',true); load('model');
  }
  function chooseModel(item,button) {
    selectedModel=item; model.value=String(item.id); $('known-model').value=item.label; $('path-model').textContent=item.label;
    $('catalogue-selected-name').textContent=`${selectedBrand.label} ${item.label}`;
    $('catalogue-selection-help').textContent=item.has_specs?'Incorporaremos las características documentadas de este modelo y buscaremos las referencias que falten.':'Ya identificamos el modelo. Consultaremos sus características y referencias de año y valor para preparar la ficha.';
    $('catalogue-selection').hidden=false; $('catalogue-generate').disabled=false;
    $('selection-summary').textContent=`${selectedCategory.name} · ${selectedBrand.label} · ${item.label}`;
    $('catalogue-model-results').querySelectorAll('button[data-model-id]').forEach(node=>node.setAttribute('aria-pressed',String(node===button)));
    error('');
  }
  function renderCategories() {
    const priority=['excavadoras','retroexcavadoras','compactadores','cargadores','minicargadores','gruas','montacargas','plataformas-elevadoras'];
    const sorted=[...categories].sort((a,b)=>{const x=priority.indexOf(a.slug),y=priority.indexOf(b.slug);return (x<0?99:x)-(y<0?99:y)||a.name.localeCompare(b.name,'es');});
    $('popular-categories').replaceChildren();
    for(const item of allCategories?sorted:sorted.slice(0,8)){
      const button=document.createElement('button'); button.type='button'; button.className='catalogue-option'; button.textContent=item.name;
      button.dataset.categoryId=String(item.id); button.addEventListener('click',()=>chooseCategory(item)); $('popular-categories').append(button);
    }
    $('show-all-categories').hidden=sorted.length<=8; $('show-all-categories').textContent=allCategories?'Ver tipos principales ↑':`Ver los ${sorted.length} tipos ↓`;
  }
  async function load(kind,append=false) {
    const input=$(`catalogue-${kind}-search`), list=$(`catalogue-${kind}-results`), status=$(`${kind}-status`), more=$(kind==='brand'?'more-brands':'more-models');
    const ticket=++requests[kind]; controllers[kind]?.abort(); controllers[kind]=new AbortController();
    if(!append){pages[kind]=1;list.replaceChildren();}
    more.hidden=true; list.setAttribute('aria-busy','true'); status.textContent=kind==='brand'?'Buscando marcas…':'Buscando modelos…';
    const query=new URLSearchParams({stage:kind==='brand'?'brands':'models',category:category.value,q:input.value.trim(),page:String(pages[kind])});
    if(kind==='model')query.set('brand',String(selectedBrand.id));
    const key=query.toString();
    try {
      let data=cache.get(key);
      if(!data){
        const response=await fetch(`${root.dataset.catalogueUrl}?${key}`,{credentials:'same-origin',signal:controllers[kind].signal,headers:{Accept:'application/json'}});
        if(!response.ok || !response.headers.get('content-type')?.includes('application/json'))throw new Error('No pudimos cargar el catálogo. Intenta de nuevo o continúa con fotografías.');
        data=await response.json(); if(!Array.isArray(data.items))throw new Error('El catálogo no respondió correctamente. Vuelve a intentarlo.');
        if(cache.size>=30)cache.delete(cache.keys().next().value);cache.set(key,data);
      }
      if(ticket!==requests[kind])return;
      for(const item of data.items){
        if(!item || !item.id || typeof item.label!=='string')continue;
        const button=document.createElement('button');button.type='button';button.className='catalogue-option';
        const label=document.createElement('strong');label.textContent=item.label;button.append(label);
        if(kind==='model'){
          button.dataset.modelId=String(item.id);button.setAttribute('aria-pressed',String(String(item.id)===model.value));
          const hint=document.createElement('span');hint.textContent=item.has_specs?'Características disponibles':'Identificación en catálogo';button.append(hint);
          button.addEventListener('click',()=>chooseModel(item,button));
        }else button.addEventListener('click',()=>chooseBrand(item));
        list.append(button);
      }
      const count=list.querySelectorAll('button').length;
      status.textContent=count?`${data.total||count} ${kind==='brand'?'marcas':'modelos'}${input.value.trim()?' encontrados':''}. ${kind==='brand'?'Selecciona una marca.':'Elige el modelo que coincide con tu equipo.'}`:'No encontramos coincidencias. Prueba otro nombre o usa fotografías.';
      more.hidden=!data.has_more;
    } catch(exc) {
      if(ticket!==requests[kind]||exc.name==='AbortError')return;
      status.textContent=exc.message;const retry=document.createElement('button');retry.type='button';retry.className='link-button';retry.textContent='Reintentar';retry.addEventListener('click',()=>load(kind));list.append(retry);
    } finally {if(ticket===requests[kind])list.setAttribute('aria-busy','false');}
  }
  root.addEventListener('categoryselected',event=>{if(event.detail?.category)chooseCategory(event.detail.category);});
  $('start-category-search').addEventListener('input',()=>{
    if(!category.value){
      selectedCategory=null;selectedBrand=null;resetModel();$('known-brand').value='';
      $('path-category').textContent='Tipo de máquina';$('path-brand').textContent='Marca';
      for(const kind of ['brand','model']){++requests[kind];controllers[kind]?.abort();clearTimeout(timers[kind]);}
      show('category');
    }
  });
  $('show-all-categories').addEventListener('click',()=>{allCategories=!allCategories;renderCategories();});
  for(const kind of ['brand','model']){
    $(`catalogue-${kind}-search`).addEventListener('input',()=>{clearTimeout(timers[kind]);++requests[kind];controllers[kind]?.abort();timers[kind]=setTimeout(()=>load(kind),180);});
    $(`catalogue-${kind}-search`).addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();clearTimeout(timers[kind]);load(kind);}if(event.key==='ArrowDown'){event.preventDefault();$(`catalogue-${kind}-results`).querySelector('button')?.focus();}});
    $(kind==='brand'?'more-brands':'more-models').addEventListener('click',()=>{pages[kind]++;load(kind,true);});
  }
  document.querySelectorAll('[data-browse-back]').forEach(button=>button.addEventListener('click',()=>show(button.dataset.browseBack,true)));
  $('identify-with-photos').addEventListener('click',()=>{error('');show('identify',true);});
  $('return-catalogue').addEventListener('click',()=>{error('');show(selectedBrand?'model':selectedCategory?'brand':'category',true);});
  $('typed-serial').addEventListener('input',()=>{$('typed-serial').setCustomValidity('');error('');});
  form.addEventListener('submit',event=>{
    const route=event.submitter?.dataset.entryRoute;
    if(submitting||!route){event.preventDefault();return;}
    if(route==='catalogue'&&(!selectedCategory||!selectedBrand||!selectedModel||!model.value||stage!=='model')){event.preventDefault();error('Selecciona el tipo, la marca y el modelo.');return;}
    if(route!=='catalogue'&&stage!=='identify'){event.preventDefault();return;}
    const serial=route==='serial'?$('typed-serial').value.trim():'';
    if(route==='serial'&&serial.replace(/[^a-z0-9]/gi,'').length<3){event.preventDefault();error('Escribe el número de serie o continúa con fotografías.');$('typed-serial').focus();return;}
    $('start-entry-mode').value=route;$('start-serial').value=serial;
    if(route!=='catalogue')model.value='';
    submitting=true;form.setAttribute('aria-busy','true');event.submitter.textContent=route==='catalogue'?'Preparando tu ficha…':'Abriendo tu ficha…';
  });
  addEventListener('pageshow',event=>{if(event.persisted){submitting=false;form.removeAttribute('aria-busy');$('catalogue-generate').textContent='Generar ficha de maquinaria →';}});
  renderCategories();show('category');
})();
