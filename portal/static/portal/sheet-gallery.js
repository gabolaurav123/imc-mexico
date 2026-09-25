'use strict';
(() => {
  document.querySelectorAll('[data-sheet-carousel]').forEach(gallery => {
    const photos=[...gallery.querySelectorAll('.virtual-photo')];
    if (!photos.length) return;
    const controls=document.createElement('div'); controls.className='sheet-gallery-controls';
    const previous=document.createElement('button'), next=document.createElement('button'), count=document.createElement('span');
    previous.type=next.type='button'; previous.className=next.className='button button-outline button-small';
    previous.textContent='← Anterior'; next.textContent='Siguiente →'; count.setAttribute('aria-live','polite');
    let index=0;
    const update=() => { count.textContent=`${index+1} / ${photos.length}`; previous.disabled=index===0; next.disabled=index===photos.length-1; };
    const go=delta => { index=Math.max(0,Math.min(photos.length-1,index+delta)); gallery.scrollTo({left:photos[index].offsetLeft-gallery.offsetLeft,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}); update(); };
    previous.addEventListener('click',()=>go(-1)); next.addEventListener('click',()=>go(1));
    gallery.addEventListener('scroll',()=> { const center=gallery.getBoundingClientRect().left; let distance=Infinity; photos.forEach((photo,i)=> { const d=Math.abs(photo.getBoundingClientRect().left-center); if(d<distance){index=i;distance=d;} }); update(); },{passive:true});
    gallery.addEventListener('keydown',event=> { if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();go(event.key==='ArrowLeft'?-1:1);} });
    gallery.tabIndex=0; gallery.setAttribute('aria-label','Galería de fotografías. Usa las flechas para avanzar.');
    controls.append(previous,count,next); gallery.after(controls); update();
  });
  document.querySelectorAll('[data-share-sheet]').forEach(button=>button.addEventListener('click',async()=> {
    const url=new URL(button.dataset.shareSheet,location.origin).href;
    const status=document.getElementById('sheet-share-status');
    try { await navigator.clipboard.writeText(url); status.textContent='Enlace web copiado. Puedes compartirlo.'; }
    catch { status.replaceChildren(); const link=document.createElement('a');link.href=url;link.textContent=url;status.append('Copia este enlace: ',link); }
  }));
})();
