'use strict';
(() => {
  const root=document.querySelector('[data-intake-start]'), form=document.getElementById('start-machine-form');
  if (!root || !form) return;
  const category=document.getElementById('start-category'), next=document.getElementById('start-category-next');
  const type=document.getElementById('type-question'), question=document.getElementById('identifier-question'), yes=document.getElementById('identifier-yes');
  const photosQuestion=document.getElementById('photos-question'), photosYes=document.getElementById('photos-yes'), catalogue=document.getElementById('catalogue-question');
  const typedWrap=document.getElementById('typed-serial-wrap'), typed=document.getElementById('typed-serial'), serial=document.getElementById('start-serial'), mode=document.getElementById('start-entry-mode');
  const catalogueModel=document.getElementById('catalogue-model'), brandSelect=document.getElementById('catalogue-brand-select'), modelSelect=document.getElementById('catalogue-model-select');
  const manualToggle=document.getElementById('catalogue-manual-toggle'), manualFields=document.getElementById('catalogue-manual-fields'), manualBrand=document.getElementById('catalogue-manual-brand'), manualModel=document.getElementById('catalogue-manual-model'), catalogueHelp=document.getElementById('catalogue-selection-help');
  let catalogueModels=[]; try { catalogueModels=JSON.parse(document.getElementById('catalogue-intake-data')?.textContent || '[]'); } catch { catalogueModels=[]; }
  let stage='category', manual=false;
  const stages=[type,question,yes,photosQuestion,photosYes,catalogue].filter(Boolean);
  const show=node => { stages.forEach(item => { item.hidden=item!==node; }); node.hidden=false; node.scrollIntoView({behavior:'smooth',block:'nearest'}); };
  const addOption=(select,value,label) => { const option=document.createElement('option'); option.value=String(value); option.textContent=label; select.append(option); };
  const resetSelect=(select,label) => { select.textContent=''; addOption(select,'',label); };
  function populateBrands(){
    resetSelect(brandSelect,'Seleccionar marca'); resetSelect(modelSelect,'Seleccionar modelo'); modelSelect.disabled=true; catalogueModel.value='';
    const selected=String(category.value), brands=[...new Set(catalogueModels.filter(item=>String(item.category)===selected).map(item=>item.brand))].sort((a,b)=>a.localeCompare(b,'es'));
    brands.forEach(brand=>addOption(brandSelect,brand,brand));
    catalogueHelp.textContent=brands.length?'Selecciona la marca y el modelo documentado.':'No hay modelos técnicos aprobados para este tipo todavía.';
  }
  function populateModels(){
    resetSelect(modelSelect,'Seleccionar modelo'); catalogueModel.value='';
    const models=catalogueModels.filter(item=>String(item.category)===String(category.value) && item.brand===brandSelect.value);
    models.forEach(item=>addOption(modelSelect,item.id,item.name)); modelSelect.disabled=!models.length;
  }
  next.addEventListener('click', () => {
    if (!category.value) { document.getElementById('start-category-selection').textContent='Escribe el tipo de máquina y elige una de las sugerencias.'; document.getElementById('start-category-search').focus(); return; }
    stage='question'; show(question);
  });
  root.querySelectorAll('[data-identifier-answer]').forEach(button => button.addEventListener('click', () => {
    stage=button.dataset.identifierAnswer==='yes'?'yes':'photos-question'; typedWrap.hidden=true; serial.value=''; if(mode)mode.value='photos'; show(stage==='yes'?yes:photosQuestion);
  }));
  root.querySelectorAll('[data-identifier-choice]').forEach(button => button.addEventListener('click', () => {
    const isTyped=button.dataset.identifierChoice==='typed'; typedWrap.hidden=!isTyped; yes.querySelector('.intake-finish').hidden=false;
    stage=isTyped?'typed':'plate'; if(mode)mode.value=isTyped?'serial':'plate'; if(isTyped)typed.focus(); else serial.value='';
  }));
  root.querySelectorAll('[data-photo-answer]').forEach(button => button.addEventListener('click', () => {
    const hasPhotos=button.dataset.photoAnswer==='yes'; stage=hasPhotos?'photos':'catalogue'; if(mode)mode.value=hasPhotos?'photos':'catalogue';
    if (hasPhotos) show(photosYes); else { manual=false; manualFields.hidden=true; populateBrands(); show(catalogue); }
  }));
  brandSelect.addEventListener('change',populateModels);
  modelSelect.addEventListener('change',()=>{ catalogueModel.value=modelSelect.value; manual=false; manualFields.hidden=true; catalogueHelp.textContent=modelSelect.value?'Prepararemos una ficha editable con referencias del modelo, no datos de esta unidad.':''; });
  manualToggle.addEventListener('click',()=>{ manual=!manual; manualFields.hidden=!manual; if(manual){catalogueModel.value='';modelSelect.value='';catalogueHelp.textContent='Escribe la marca y el modelo que conoces.';manualBrand.focus();} });
  root.querySelectorAll('[data-identifier-back]').forEach(button => button.addEventListener('click', () => { stage='question'; typedWrap.hidden=true; typed.value=''; serial.value=''; show(question); }));
  root.querySelectorAll('[data-photo-back]').forEach(button => button.addEventListener('click', () => { stage='photos-question'; show(photosQuestion); }));
  root.querySelectorAll('[data-type-back]').forEach(button => button.addEventListener('click', () => { stage='category'; show(type); }));
  form.addEventListener('submit', event => {
    const button=event.submitter, section=button?.closest('.intake-question');
    if (!category.value || !button?.matches('.intake-finish') || button.hidden || !section || section.hidden) { event.preventDefault(); if(stage==='category')next.click(); return; }
    if(stage==='typed'){ serial.value=!typedWrap.hidden?typed.value.trim():''; if(!serial.value){event.preventDefault();typed.setCustomValidity('Escribe la serie o elige continuar con fotografías.');typed.reportValidity();typed.focus();} return; }
    if(stage==='plate'){serial.value='';return;}
    if(stage==='photos'){serial.value='';if(mode)mode.value='photos';return;}
    if(stage==='catalogue'){
      serial.value='';
      if(catalogueModel.value){if(mode)mode.value='catalogue';return;}
      if(manual && manualBrand.value.trim() && manualModel.value.trim()){if(mode)mode.value='manual_identity';return;}
      event.preventDefault(); catalogueHelp.textContent='Selecciona un modelo del catálogo o escribe la marca y el modelo que conoces.';
    } else { event.preventDefault(); }
  });
  typed.addEventListener('input',()=>typed.setCustomValidity(''));
})();
