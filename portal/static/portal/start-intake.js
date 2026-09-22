'use strict';
(() => {
  const root=document.querySelector('[data-intake-start]'), form=document.getElementById('start-machine-form');
  if (!root || !form) return;
  const category=document.getElementById('start-category'), next=document.getElementById('start-category-next');
  const question=document.getElementById('identifier-question'), yes=document.getElementById('identifier-yes'), no=document.getElementById('identifier-no');
  const typedWrap=document.getElementById('typed-serial-wrap'), typed=document.getElementById('typed-serial'), serial=document.getElementById('start-serial');
  let stage='category';
  const show=node => { [question,yes,no].forEach(item => { item.hidden=item!==node; }); node.hidden=false; node.scrollIntoView({behavior:'smooth',block:'start'}); };
  next.addEventListener('click', () => {
    if (!category.value && document.getElementById('start-category-search').value.trim()) {
      document.getElementById('start-category-selection').textContent='Elige una sugerencia o selecciona «No estoy seguro» para continuar.'; return;
    }
    stage='question'; show(question);
  });
  root.addEventListener('categoryselected', () => { next.disabled=false; });
  root.querySelectorAll('[data-identifier-answer]').forEach(button => button.addEventListener('click', () => { stage=button.dataset.identifierAnswer==='yes'?'yes':'no'; typedWrap.hidden=true; serial.value=''; show(stage==='yes' ? yes : no); }));
  root.querySelectorAll('[data-identifier-choice]').forEach(button => button.addEventListener('click', () => {
    const isTyped=button.dataset.identifierChoice==='typed'; typedWrap.hidden=!isTyped;
    yes.querySelector('.intake-finish').hidden=false;
    if (isTyped) { stage='typed'; typed.focus(); } else { stage='plate'; serial.value=''; }
  }));
  root.querySelectorAll('[data-identifier-back]').forEach(button => button.addEventListener('click', () => { stage='question'; typedWrap.hidden=true; typed.value=''; serial.value=''; show(question); }));
  form.addEventListener('submit', event => {
    const button=event.submitter, section=button?.closest('.intake-question');
    const permitted=['no','typed','plate'].includes(stage) && button?.matches('.intake-finish') && !button.hidden && section && !section.hidden;
    if (!permitted) { event.preventDefault(); if (stage==='category') next.click(); return; }
    serial.value=stage==='typed' && !typedWrap.hidden ? typed.value.trim() : '';
  });
})();
