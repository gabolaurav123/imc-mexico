'use strict';
(() => {
  const modal=document.getElementById('share-modal');
  if (!modal) return;
  const urlInput=modal.querySelector('#share-modal-url');
  const feedback=modal.querySelector('#share-modal-feedback');
  const close=()=>{if(typeof modal.close==='function')modal.close();else modal.removeAttribute('open');};
  const csrf=()=>document.querySelector('input[name=csrfmiddlewaretoken]')?.value||document.cookie.split('; ').find(value=>value.startsWith('csrftoken='))?.split('=')[1]||'';
  const defaultTitle=()=>document.title.replace(/\s*·\s*IMC México\s*$/,'').trim()||'Ficha de maquinaria';
  let sharedUrl='';
  let sharedTitle=defaultTitle();

  const clear=()=>{
    sharedUrl=''; urlInput.value=''; feedback.textContent='';
    modal.querySelector('[data-share-whatsapp]').removeAttribute('href');
    modal.querySelector('[data-share-facebook]').removeAttribute('href');
  };

  const copy=async()=>{
    try { await navigator.clipboard.writeText(sharedUrl); feedback.textContent='Enlace copiado. Puedes pegarlo en un mensaje o una publicación.'; }
    catch { urlInput.focus(); urlInput.select(); feedback.textContent='Selecciona y copia el enlace.'; }
  };
  const open=(url,title)=>{
    sharedUrl=new URL(url,location.origin).href;
    sharedTitle=String(title||defaultTitle());
    urlInput.value=sharedUrl; feedback.textContent='';
    modal.querySelector('[data-share-whatsapp]').href=`https://wa.me/?text=${encodeURIComponent(`${sharedTitle}\n${sharedUrl}`)}`;
    modal.querySelector('[data-share-facebook]').href=`https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(sharedUrl)}`;
    if (typeof modal.showModal==='function') modal.showModal();
    else { modal.setAttribute('open',''); }
  };
  const api=async(button)=>{
    const response=await fetch(`/api/maquinarias/${button.dataset.shareMachineId}/compartir/`,{
      method:'POST',credentials:'same-origin',headers:{'Accept':'application/json','Content-Type':'application/json','X-CSRFToken':csrf()},
      body:JSON.stringify({revision:Number(button.dataset.shareRevision),action:'enable',include_serial:button.dataset.shareIncludeSerial==='true',include_contact:button.dataset.shareIncludeContact==='true'})
    });
    const contentType=response.headers.get('content-type')||'';
    const result=contentType.includes('application/json')?await response.json():{};
    if (!response.ok) throw new Error(result.error||'No se pudo preparar el enlace. Vuelve a intentarlo.');
    if (!result.url) throw new Error('El enlace preparado no es válido. Vuelve a intentarlo.');
    button.dataset.shareSheet=result.url;
    button.dataset.shareRevision=String(result.revision);
    return result.url;
  };

  modal.querySelector('[data-close-share-modal]').addEventListener('click',close);
  modal.addEventListener('click',event=>{if(event.target===modal)close();});
  modal.querySelector('[data-copy-share-link]').addEventListener('click',copy);
  modal.querySelector('[data-share-native]').addEventListener('click',async()=>{
    if (navigator.share) { try { await navigator.share({title:sharedTitle,url:sharedUrl}); } catch (error) { if (error.name!=='AbortError') await copy(); } }
    else await copy();
  });
  document.querySelectorAll('[data-share-sheet], [data-share-machine-id]').forEach(button=>button.addEventListener('click',async()=>{
    if (button.disabled) return;
    const label=button.textContent; button.disabled=true;
    const existing=button.dataset.shareSheet;
    if (!existing) clear();
    try { open(existing||await api(button)); }
    catch (error) { feedback.textContent=error.message; if (typeof modal.showModal==='function'&&!modal.open) modal.showModal(); }
    finally { button.disabled=false; button.textContent=label; }
  }));
  window.imcShareModal={open,close};
})();
