'use strict';
(() => {
  const modal=document.getElementById('share-modal');
  if (!modal) return;
  const urlInput=modal.querySelector('#share-modal-url');
  const urlLabel=modal.querySelector('label[for="share-modal-url"]');
  const feedback=modal.querySelector('#share-modal-feedback');
  const description=modal.querySelector('#share-modal-description');
  const editorLink=modal.querySelector('[data-return-share-editor]');
  const buttons=[...modal.querySelectorAll('[data-copy-share-link], [data-share-native]')];
  const links=[...modal.querySelectorAll('[data-share-whatsapp], [data-share-facebook]')];
  const close=()=>{if(typeof modal.close==='function')modal.close();else modal.removeAttribute('open');};
  const csrf=()=>document.querySelector('input[name=csrfmiddlewaretoken]')?.value||document.cookie.split('; ').find(value=>value.startsWith('csrftoken='))?.split('=')[1]||'';
  const defaultTitle=()=>document.title.replace(/\s*·\s*IMC México\s*$/,'').trim()||'Ficha de maquinaria';
  let sharedUrl='';
  let sharedTitle=defaultTitle();

  const validUrl=url=>{
    let parsed;
    try { if(typeof url!=='string'||!url.trim())throw new Error();parsed=new URL(url,location.origin); }
    catch { throw new Error('El enlace preparado no es válido. Vuelve a intentarlo.'); }
    // The backend may return its canonical PUBLIC_URL when opened via an alias.
    if(!['https:','http:'].includes(parsed.protocol)||parsed.username||parsed.password||parsed.search||parsed.hash||!/^\/(?:s|ficha)\/[A-Za-z0-9_-]+\/?$/.test(parsed.pathname))throw new Error('El enlace preparado no es válido. Vuelve a intentarlo.');
    return parsed.href;
  };
  const show=()=>{if(modal.open)return;if(typeof modal.showModal==='function')modal.showModal();else modal.setAttribute('open','');};
  const setState=(state,message='')=>{
    const ready=state==='ready'&&Boolean(sharedUrl);
    modal.dataset.state=state;modal.setAttribute('aria-busy',String(state==='loading'));
    urlLabel.hidden=urlInput.hidden=!ready;
    buttons.forEach(button=>{button.disabled=!ready;});
    links.forEach(link=>{link.setAttribute('aria-disabled',String(!ready));if(ready)link.removeAttribute('tabindex');else link.tabIndex=-1;});
    description.textContent=ready?'Elige dónde compartir el enlace de esta ficha.':state==='loading'?'Estamos preparando el enlace de tu ficha.':'No se creó un enlace para compartir.';
    feedback.setAttribute('role',state==='error'?'alert':'status');feedback.textContent=message;
    editorLink.hidden=state!=='error'||!editorLink.hasAttribute('href');
  };

  const clear=()=>{
    sharedUrl=''; urlInput.value=''; feedback.textContent='';
    modal.querySelector('[data-share-whatsapp]').removeAttribute('href');
    modal.querySelector('[data-share-facebook]').removeAttribute('href');
    modal.querySelector('#revoke-sheet-link').hidden=true;
  };

  const loading=(title,editorUrl='')=>{
    clear();sharedTitle=String(title||defaultTitle());
    if(editorUrl)editorLink.setAttribute('href',editorUrl);else editorLink.removeAttribute('href');
    setState('loading','Comprobando que la ficha esté lista para compartir…');show();
  };
  const fail=message=>{clear();setState('error',message||'No se pudo preparar el enlace. Vuelve a intentarlo.');show();};

  const copy=async()=>{
    if(!sharedUrl||modal.dataset.state!=='ready')return;
    try { await navigator.clipboard.writeText(sharedUrl); feedback.textContent='Enlace copiado. Puedes pegarlo en un mensaje o una publicación.'; }
    catch { urlInput.focus(); urlInput.select(); feedback.textContent='Selecciona y copia el enlace.'; }
  };
  const open=(url,title)=>{
    clear();setState('loading');sharedUrl=validUrl(url);
    sharedTitle=String(title||defaultTitle());
    urlInput.value=sharedUrl; feedback.textContent='';
    modal.querySelector('[data-share-whatsapp]').href=`https://wa.me/?text=${encodeURIComponent(`${sharedTitle}\n${sharedUrl}`)}`;
    modal.querySelector('[data-share-facebook]').href=`https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(sharedUrl)}`;
    setState('ready');show();return sharedUrl;
  };
  const api=async(button)=>{
    const response=await fetch(`/api/maquinarias/${button.dataset.shareMachineId}/compartir/`,{
      method:'POST',credentials:'same-origin',headers:{'Accept':'application/json','Content-Type':'application/json','X-CSRFToken':csrf()},
      body:JSON.stringify({revision:Number(button.dataset.shareRevision),action:'enable',include_serial:button.dataset.shareIncludeSerial==='true',include_contact:button.dataset.shareIncludeContact==='true'})
    });
    const contentType=response.headers.get('content-type')||'';
    const result=contentType.includes('application/json')?await response.json():{};
    if (!response.ok) throw new Error(result.error||'No se pudo preparar el enlace. Vuelve a intentarlo.');
    validUrl(result.url);
    button.dataset.shareSheet=result.url;
    button.dataset.shareRevision=String(result.revision);
    return result.url;
  };

  modal.querySelector('[data-close-share-modal]').addEventListener('click',close);
  modal.addEventListener('click',event=>{if(event.target===modal)close();});
  modal.querySelector('[data-copy-share-link]').addEventListener('click',copy);
  links.forEach(link=>link.addEventListener('click',event=>{if(!sharedUrl||modal.dataset.state!=='ready')event.preventDefault();}));
  editorLink.addEventListener('click',event=>{
    if(editorLink.getAttribute('href')?.startsWith('#')){
      event.preventDefault();close();
      const target=document.querySelector(editorLink.getAttribute('href'));
      if(target){target.setAttribute('tabindex','-1');target.focus();target.scrollIntoView({behavior:'smooth',block:'nearest'});}
    }
  });
  modal.querySelector('[data-share-native]').addEventListener('click',async()=>{
    if(!sharedUrl||modal.dataset.state!=='ready')return;
    if (navigator.share) { try { await navigator.share({title:sharedTitle,url:sharedUrl}); } catch (error) { if (error.name!=='AbortError') await copy(); } }
    else await copy();
  });
  document.querySelectorAll('[data-share-sheet], [data-share-machine-id]').forEach(button=>button.addEventListener('click',async()=>{
    if (button.disabled||modal.dataset.state==='loading') return;
    const label=button.textContent; button.disabled=true;
    const existing=button.dataset.shareSheet;
    loading(defaultTitle(),button.dataset.shareMachineId?`/panel/maquinarias/${encodeURIComponent(button.dataset.shareMachineId)}/?paso=2`:'');
    try { open(existing||await api(button)); }
    catch (error) { fail(error.message); }
    finally { button.disabled=false; button.textContent=label; }
  }));
  setState('idle');
  window.imcShareModal={open,close,loading,fail};
})();
