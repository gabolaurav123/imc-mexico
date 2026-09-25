'use strict';
(() => {
  const root=document.querySelector('[data-intake-start]'), form=document.getElementById('start-machine-form');
  if (!root || !form) return;
  const category=document.getElementById('start-category'), next=document.getElementById('start-category-next');
  const type=document.getElementById('type-question'), question=document.getElementById('identifier-question'), yes=document.getElementById('identifier-yes'), no=document.getElementById('identifier-no');
  const typedWrap=document.getElementById('typed-serial-wrap'), typed=document.getElementById('typed-serial'), serial=document.getElementById('start-serial'), mode=document.getElementById('start-entry-mode');
  let stage='category';
  const show=node => { [type,question,yes,no].filter(Boolean).forEach(item => { item.hidden=item!==node; }); node.hidden=false; node.scrollIntoView({behavior:'smooth',block:'nearest'}); };
  next.addEventListener('click', () => {
    if (!category.value) { document.getElementById('start-category-selection').textContent='Escribe el tipo de máquina y elige una de las sugerencias.'; document.getElementById('start-category-search').focus(); return; }
    stage='question'; show(question);
  });
  root.querySelectorAll('[data-identifier-answer]').forEach(button => button.addEventListener('click', () => { stage=button.dataset.identifierAnswer==='yes'?'yes':'no'; typedWrap.hidden=true; serial.value=''; if(mode)mode.value='photos'; show(stage==='yes'?yes:no); }));
  root.querySelectorAll('[data-identifier-choice]').forEach(button => button.addEventListener('click', () => {
    const isTyped=button.dataset.identifierChoice==='typed'; typedWrap.hidden=!isTyped; yes.querySelector('.intake-finish').hidden=false;
    stage=isTyped?'typed':'plate'; if(mode)mode.value=isTyped?'serial':'plate'; if(isTyped)typed.focus(); else serial.value='';
  }));
  root.querySelectorAll('[data-identifier-back]').forEach(button => button.addEventListener('click', () => { stage='question'; typedWrap.hidden=true; typed.value=''; serial.value=''; show(question); }));
  root.querySelectorAll('[data-type-back]').forEach(button => button.addEventListener('click', () => { stage='category'; show(type); }));
  form.addEventListener('submit', event => {
    const button=event.submitter, section=button?.closest('.intake-question');
    if (!category.value || !['no','typed','plate'].includes(stage) || !button?.matches('.intake-finish') || button.hidden || !section || section.hidden) { event.preventDefault(); if(stage==='category')next.click(); return; }
    serial.value=stage==='typed'&&!typedWrap.hidden?typed.value.trim():'';
    if(stage==='typed'&&!serial.value){event.preventDefault();typed.setCustomValidity('Escribe la serie o elige continuar con fotografías.');typed.reportValidity();typed.focus();}
  });
  typed.addEventListener('input',()=>typed.setCustomValidity(''));
})();
