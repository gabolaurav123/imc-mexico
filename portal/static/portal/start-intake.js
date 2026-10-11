'use strict';
(() => {
  const root=document.querySelector('[data-intake-start]'), form=document.getElementById('start-machine-form');
  if (!root || !form) return;
  const $=id=>document.getElementById(id), category=$('start-category');
  let categories=[];
  try { const data=JSON.parse($('category-data').textContent); if(Array.isArray(data))categories=data; } catch { /* Keep the form available. */ }
  let allCategories=false, submitting=false;
  function error(message) { $('intake-error').textContent=message; $('intake-error').hidden=!message; }
  function chooseCategory(item) {
    if(submitting || !categories.some(value=>String(value.id)===String(item?.id)))return;
    category.value=String(item.id); $('start-category-search').value=item.name;
    $('start-category-selection').textContent=`Seleccionaste: ${item.name}.`;
    error(''); form.requestSubmit($('start-continue'));
  }
  function renderCategories() {
    const priority=['excavadoras','retroexcavadoras','compactadores','cargadores','minicargadores','gruas','montacargas','plataformas-elevadoras'];
    const sorted=[...categories].sort((a,b)=>{const x=priority.indexOf(a.slug),y=priority.indexOf(b.slug);return (x<0?99:x)-(y<0?99:y)||a.name.localeCompare(b.name,'es');});
    $('popular-categories').replaceChildren();
    for(const item of allCategories?sorted:sorted.slice(0,8)){
      const button=document.createElement('button'); button.type='button'; button.className='catalogue-option'; button.textContent=item.name;
      if(root.dataset.iconsUrl){
        const icons={'excavadoras':'excavator','retroexcavadoras':'backhoe','compactadores':'compactor','cargadores':'loader','minicargadores':'skidsteer','gruas':'crane','montacargas':'forklift','plataformas-elevadoras':'platform'};
        const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),use=document.createElementNS('http://www.w3.org/2000/svg','use');
        svg.setAttribute('viewBox','0 0 64 48');svg.setAttribute('aria-hidden','true');svg.setAttribute('class','category-option-icon');
        use.setAttribute('href',root.dataset.iconsUrl+'#'+(icons[item.slug]||'generic'));svg.append(use);button.prepend(svg);
      }
      button.dataset.categoryId=String(item.id); button.addEventListener('click',()=>chooseCategory(item)); $('popular-categories').append(button);
    }
    $('show-all-categories').hidden=sorted.length<=8; $('show-all-categories').textContent=allCategories?'Ver tipos principales ↑':`Ver los ${sorted.length} tipos ↓`;
  }
  root.addEventListener('categoryselected',event=>chooseCategory(event.detail?.category));
  $('show-all-categories').addEventListener('click',()=>{if(!submitting){allCategories=!allCategories;renderCategories();}});
  form.addEventListener('submit',event=>{
    if(submitting){event.preventDefault();return;}
    if(!categories.some(item=>String(item.id)===category.value)){
      event.preventDefault();error('Selecciona el tipo de máquina para continuar.');$('start-category-search').focus();return;
    }
    $('start-entry-mode').value='photos';
    submitting=true;form.setAttribute('aria-busy','true');$('intake-progress').hidden=false;
  });
  addEventListener('pageshow',event=>{
    if(!event.persisted)return;
    submitting=false;form.removeAttribute('aria-busy');$('intake-progress').hidden=true;
    // Back returns to the selector; it must never create another draft by itself.
    $('start-continue').hidden=!categories.some(item=>String(item.id)===category.value);
  });
  renderCategories();
  const initial=categories.find(item=>item.slug===root.dataset.initialCategory);
  if(initial){
    const navigation=performance.getEntriesByType?.('navigation')?.[0]?.type;
    const initialError=form.querySelector('.notice.error:not([hidden])')?.textContent.trim();
    if(navigation==='back_forward' || navigation==='reload' || initialError){
      category.value=String(initial.id);$('start-category-search').value=initial.name;
      $('start-category-selection').textContent=`Seleccionaste: ${initial.name}.`;
      $('start-continue').hidden=false;
    }else chooseCategory(initial);
  }
})();
