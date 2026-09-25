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
  document.querySelectorAll('[data-share-sheet]').forEach(button=>button.addEventListener('click',()=> {
    const url=new URL(button.dataset.shareSheet,location.origin).href;
    const panel=document.getElementById('sheet-share-status');
    panel.replaceChildren(); panel.hidden=false;
    const title=document.createElement('h3'); title.textContent='Compartir ficha';
    const input=document.createElement('input'); input.readOnly=true; input.value=url; input.setAttribute('aria-label','Enlace corto de la ficha');
    const actions=document.createElement('div'); actions.className='button-row';
    const message=document.createElement('p'); message.setAttribute('role','status');
    const copy=async()=>{try{await navigator.clipboard.writeText(url);message.textContent='Enlace copiado. Puedes pegarlo en tu conversación o publicación.';}catch{input.focus();input.select();message.textContent='Selecciona y copia el enlace.';}};
    const copyButton=document.createElement('button'); copyButton.type='button';copyButton.className='button button-navy';copyButton.textContent='Copiar enlace';copyButton.addEventListener('click',copy);
    actions.append(copyButton);
    for(const [label,href] of [['WhatsApp','https://wa.me/?text='+encodeURIComponent(document.title+' '+url)],['Facebook','https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(url)]]){
      const link=document.createElement('a');link.className='button button-outline';link.textContent=label;link.href=href;link.target='_blank';link.rel='noopener noreferrer';actions.append(link);
    }
    const other=document.createElement('button');other.type='button';other.className='button button-outline';other.textContent='Instagram y otras apps';
    other.addEventListener('click',async()=>{if(navigator.share){try{await navigator.share({title:document.title,url});}catch(error){if(error.name!=='AbortError')await copy();}}else await copy();});actions.append(other);
    panel.append(title,input,actions,message);panel.scrollIntoView({behavior:'smooth',block:'center'});
  }));
})();
