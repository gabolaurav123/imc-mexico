'use strict';
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const csrf = () => $('input[name=csrfmiddlewaretoken]')?.value || document.cookie.split('; ').find(v => v.startsWith('csrftoken='))?.split('=')[1] || '';
  let toastTimer;
  function toast(message, error = false) {
    const box = $('#toast');
    if (!box) return;
    clearTimeout(toastTimer);
    box.textContent = message; box.classList.toggle('error', error); box.hidden = false;
    toastTimer = setTimeout(() => { box.hidden = true; }, error ? 10000 : 5000);
  }
  async function api(url, payload, options = {}) {
    const response = await fetch(url, {
      method: payload === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: { 'Accept': 'application/json', ...(payload === undefined ? {} : { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }) },
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }), ...options,
    });
    let result;
    if ((response.headers.get('content-type') || '').includes('application/json')) result = await response.json();
    else {
      const error = new Error(response.status === 403 ? 'Tu sesión necesita renovarse. Abre el acceso en otra pestaña y vuelve a intentar.' : 'No recibimos una respuesta válida. Comprueba tu conexión y vuelve a intentar.');
      error.status = response.status; throw error;
    }
    if (!response.ok) {
      const details = result.fields ? Object.entries(result.fields).map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(' ') : value}`).join(' · ') : '';
      const error = new Error([result.error || 'No se pudo completar la acción.', details].filter(Boolean).join(' '));
      error.status = response.status; throw error;
    }
    return result;
  }
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function networkStatus() { const banner = $('#offline-banner'); if (banner) banner.hidden = navigator.onLine; }
  addEventListener('online', networkStatus); addEventListener('offline', networkStatus); networkStatus();
  $('[data-menu]')?.addEventListener('click', event => {
    const button = event.currentTarget, nav = $('#primary-nav');
    const open = button.getAttribute('aria-expanded') !== 'true';
    button.setAttribute('aria-expanded', String(open)); nav?.classList.toggle('open', open);
  });
  let creating = false;
  $$('[data-create]').forEach(button => button.addEventListener('click', async () => {
    if (creating) return;
    creating = true; const label = button.textContent; button.disabled = true; button.textContent = 'Preparando tu borrador…';
    try { const result = await api('/api/maquinarias/', {}); location.assign(result.url || `/panel/maquinarias/${result.id}/`); }
    catch (error) { toast(error.message, true); creating = false; button.disabled = false; button.textContent = label; }
  }));
  const deleteDraftConfirmation = '¿Eliminar este borrador? Podrás recuperarlo desde la papelera.';
  $$('[data-machine-action]').forEach(button => button.addEventListener('click', async () => {
    if (button.disabled) return;
    const action = button.dataset.machineAction;
    const payload = { action };
    if (action === 'delete_draft' && !confirm(deleteDraftConfirmation)) return;
    if (action === 'delete_draft' || action === 'restore_draft') payload.revision = Number(button.dataset.machineRevision);
    if (action === 'availability') payload.value = $('#availability')?.value;
    const label = button.textContent, message = button.closest('.machine-card')?.querySelector('[data-action-error]');
    if (message) message.hidden = true;
    button.disabled = true;
    if (action === 'delete_draft' || action === 'restore_draft') button.textContent = action === 'delete_draft' ? 'Moviendo a la papelera…' : 'Restaurando borrador…';
    try {
      const result = await api(`/api/maquinarias/${button.dataset.machineId}/accion/`, payload);
      if (action === 'duplicate') location.assign(result.url || `/panel/maquinarias/${result.id}/`);
      else if (action === 'delete_draft' || action === 'restore_draft') location.assign(result.url || '/panel/maquinarias/');
      else location.reload();
    } catch (error) { toast(error.message, true); if (message) { message.textContent = error.message; message.hidden = false; } button.disabled = false; button.textContent = label; }
  }));

  let beforePreferencesReload = null;
  $$('[data-analytics-consent]').forEach(button => button.addEventListener('click', async () => {
    const buttons = $$('[data-analytics-consent]'); buttons.forEach(item => { item.disabled = true; });
    try {
      const result = await api('/preferencias/analitica/', { consent: button.dataset.analyticsConsent === 'true' });
      $('#analytics-preferences').dataset.consent = result.consent;
      $('#analytics-consent-status').textContent = result.enabled === false ? 'La analítica está desactivada en la plataforma.' : result.consent === 'granted' ? 'Has permitido la analítica opcional. Puedes cambiar tu elección aquí.' : 'Has desactivado la analítica opcional. Puedes cambiar tu elección aquí.';
      if (beforePreferencesReload && !(await beforePreferencesReload())) toast('Preferencia guardada. Conservamos esta página hasta que termines de guardar y cargar tus archivos.');
      else location.reload();
    } catch (error) { toast(error.message, true); }
    finally { buttons.forEach(item => { item.disabled = false; }); }
  }));
  const compare = $('#version-compare');
  if (compare) {
    let versions = [];
    try { versions = JSON.parse($('#versions-data').textContent); } catch { /* No comparison without validated source data. */ }
    const before = $('#compare-before'), after = $('#compare-after'), body = $('#version-differences');
    if (versions.length > 1) before.selectedIndex = 1;
    const labels = { title:'Título', category:'Categoría', brand:'Marca', model:'Modelo', year:'Año', serial:'Serie privada', hours:'Horas', location:'Ubicación', description:'Descripción', price:'Precio', currency:'Moneda', condition:'Condición', notes:'Comentarios', contact_public:'Contacto para difusión', no_plate:'Sin placa', plate_kind:'Componente de la placa', plate_transcription:'Transcripción privada', files:'Archivos asociados' };
    function showDiff() {
      body.replaceChildren();
      const left = versions.find(v => String(v.id) === before.value), right = versions.find(v => String(v.id) === after.value);
      if (!left || !right) return;
      const fields = v => ({ title:v.data.title, category:v.data.category_name, ...v.data.data, files:(v.data.asset_ids || []).join(', ') });
      const a = fields(left), b = fields(right); let count = 0;
      const show = value => value === undefined || value === null || value === '' ? 'Sin indicar' : typeof value === 'boolean' ? (value ? 'Sí' : 'No') : String(value);
      for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
        if (show(a[key]) === show(b[key])) continue;
        count++; const row = el('tr'); row.append(el('td', '', labels[key] || key), el('td', '', key === 'files' ? `${left.data.asset_ids?.length || 0} archivo(s)` : show(a[key])), el('td', '', key === 'files' ? `${right.data.asset_ids?.length || 0} archivo(s) · selección u orden diferente` : show(b[key]))); body.append(row);
      }
      $('#version-compare-status').textContent = count ? `${count} campo(s) diferente(s) entre la versión ${left.number} y la ${right.number}.` : 'No hay diferencias en los datos o archivos de estas versiones.';
    }
    before.addEventListener('change', showDiff); after.addEventListener('change', showDiff); showDiff();
  }
  const wizard = $('#wizard');
  if (!wizard) return;
  let state;
  try { state = JSON.parse($('#machine-state').textContent); if (typeof state === 'string') state = JSON.parse(state); }
  catch { $('#wizard-errors').textContent = 'No pudimos cargar el borrador. Recarga antes de editar.'; $('#wizard-errors').hidden = false; return; }
  state.data ||= {}; state.provenance ||= {};
  const base = `/api/maquinarias/${wizard.dataset.machine}/`;
  let editable = wizard.dataset.editable === 'true';
  const pending = new Map(), legacyAttempts = new Set(), uploadFailures = new Set(), assetTasks = new Set();
  let sequence = 0, saveTimer, saving = null, conflict = false, assetMutation = null;
  let uploadCount = 0, fileChain = Promise.resolve(), preparing = false, submitting = false, downloading = false, deleting = false, deleteComplete = false;
  let analysisOutcome = null, valuationFeedback = null;
  let valuationIdentity = valuationIdentityOf(state);
  let researchHypotheses = [], researchHypothesisIdentity = valuationIdentityOf(state);
  const previewImageKinds = new Map();
  let activeJob = null, pollTimer, pollTask = null, polling = false, jobPending = false, analysisStartedAt = 0, currentStep = 1;
  const saveStatus = $('#save-status'), saveRetry = $('#save-retry'), errorBox = $('#wizard-errors');
    const keyLabels = { title:'Título',description:'Descripción',brand:'Marca',model:'Modelo',year:'Año',serial:'Serie privada',hours:'Horas',category:'Categoría',location:'Ubicación actual',condition:'Condición',plate_kind:'Componente de la placa',plate_transcription:'Texto de la placa',price:'Precio',currency:'Moneda',notes:'Comentarios',contact_public:'Contacto público',power:'Potencia',weight:'Peso',capacity:'Capacidad',dimensions:'Dimensiones',fuel:'Combustible',kilometers:'Kilometraje',attachments:'Accesorios',engine:'Motor',transmission:'Transmisión',vibration_frequency:'Frecuencia de vibración',centrifugal_force:'Fuerza centrífuga',compaction_depth:'Profundidad de compactación',digging_depth:'Profundidad máxima de excavación',hydraulic_system:'Sistema hidráulico',country_of_origin:'País de fabricación' };
    const additionalPlateLabels = { digging_depth:'Profundidad máxima de excavación',hydraulic_system:'Sistema hidráulico',front_tire_size:'Llantas delanteras',rear_tire_size:'Llantas traseras',mast_tilt:'Inclinación mástil (placa)',load_tire_tread:'Entrecentros de llantas de carga',manufacturer:'Fabricante',manufacturer_address:'Dirección del fabricante',voltage:'Voltaje',lift_height:'Altura de elevación',load_center:'Centro de carga',battery_weight:'Peso de batería',battery_capacity:'Capacidad de batería',fork_length:'Longitud de horquillas' };
  const conditionLabels = { usage_condition:'Uso aparente',preservation_condition:'Conservación aparente',preservation_notes:'Observaciones de conservación',operating_status:'Funcionamiento',visible_defects:'Defectos visibles',visible_components:'Componentes visibles',applications:'Aplicaciones y usos' };
  const estimateLabels = { estimate_min:'Mínimo estimado',estimate_max:'Máximo estimado',estimate_currency:'Moneda de la estimación',estimate_market:'Mercado de referencia',estimate_basis:'Base de la estimación',estimate_missing_info:'Información que falta para afinar el precio' };
  const ageLabels = { estimated_year_from:'Año aproximado desde',estimated_year_to:'Año aproximado hasta',estimated_year_basis:'Indicios para el año aproximado' };
  Object.assign(keyLabels,additionalPlateLabels,conditionLabels,estimateLabels,ageLabels);
  const sourceLabels = { image:'Imagen',plate:'Placa',user:'Declarado por ti',visual:'Lectura visual',visual_proposal:'Lectura visual',user_declared:'Declarado por ti',unknown:'Por identificar',web_model:'Especificación del modelo',web_serial:'Coincidencia de serie en fuente web',web:'Fuente web',system:'Texto preparado',valuation:'Estimación orientativa' };
  const purposeLabels = { general:'Vista general',detail:'Detalle',plate:'Placa · privada',document:'Documento · privado' };
  const missing = value => value === undefined || value === null || value === '';
  const fieldValue = (snapshot,key) => key === 'title' || key === 'category' ? snapshot[key] : snapshot.data?.[key];
  function problem(message) { errorBox.textContent = message; errorBox.hidden = false; errorBox.scrollIntoView({behavior:'smooth',block:'nearest'}); }
  function clearProblem() { errorBox.hidden = true; errorBox.textContent = ''; }
  function markSave(message,status='saved') { saveStatus.textContent = message; saveStatus.dataset.state = status; saveRetry.hidden = status !== 'error' || conflict; }
  function readInput(input) { if (input.type === 'checkbox') return input.checked; const value = input.value.trim(); return value === '' ? null : value; }
  function collect() {
    const value = { revision:state.revision,title:state.title,category:state.category,data:{...state.data},provenance:{...state.provenance} };
    $$('[data-field]',wizard).forEach(input => { value.data[input.dataset.field] = readInput(input); });
    $$('[data-top-field]',wizard).forEach(input => { value[input.dataset.topField] = readInput(input); });
    for (const [key,entry] of pending) {
      if (key === 'title' || key === 'category') value[key] = entry.value; else value.data[key] = entry.value;
      value.provenance[key] = {source:'user',review:'confirmed'};
    }
    return value;
  }
  function changed(event) {
    if (!editable || submitting || deleting) return;
    const input = event.target, key = input.dataset.field || input.dataset.topField;
    if (!key) return;
    pending.set(key,{value:readInput(input),sequence:++sequence});
    renderPreview();
    if (conflict) return;
    markSave('Cambios pendientes','pending'); clearTimeout(saveTimer);
    saveTimer = setTimeout(() => save().catch(() => {}),850);
  }
  function bindInput(input) {
    input.addEventListener('input',changed);
    if (input.tagName === 'SELECT' || input.type === 'checkbox') input.addEventListener('change',changed);
  }
  function isOwnAutoAdvance(snapshot,metadata,revision=state.revision) {
    return metadata?.status === 'applied' && Number(metadata.revision_before) === Number(revision) && Number(metadata.revision_after) === Number(snapshot?.revision) && Number(snapshot.revision) > Number(revision);
  }
  function hydrate(snapshot) {
    if (!snapshot || Number(snapshot.revision) < Number(state.revision)) return false;
    if (Object.hasOwn(snapshot,'valuation')) valuationIdentity = valuationIdentityOf(snapshot);
    state = {...state,...snapshot,data:{...(snapshot.data || {})},provenance:{...(snapshot.provenance || {})}};
    $$('[data-top-field]',wizard).forEach(input => { if (!pending.has(input.dataset.topField)) input.value = state[input.dataset.topField] ?? ''; });
    categoryFields();
    $$('[data-field]',wizard).forEach(input => {
      const key = input.dataset.field, value = pending.has(key) ? pending.get(key).value : state.data[key];
      if (input.type === 'checkbox') input.checked = Boolean(value); else input.value = value ?? (key === 'currency' ? 'MXN' : '');
    });
    // Catalog listens to this event; text-input change is not a user edit here.
    $('#brand')?.dispatchEvent(new Event('change'));
    if (snapshot.editable === false) { editable = false; lockEditing(); }
    renderPreview(); return true;
  }
  async function rebaseOwnAnalysis(revision) {
    if (!activeJob) return false;
    try {
      const job = await api(`/api/analisis/${activeJob}/`);
      if (!isOwnAutoAdvance(job.machine,job.auto_apply,revision)) return false;
      return hydrate(job.machine);
    } catch { return false; }
  }
  async function save() {
    clearTimeout(saveTimer);
    if (!editable || deleting || !pending.size) return;
    if (conflict) throw new Error('El borrador cambió en otra sesión. Conservamos tus cambios en esta pestaña.');
    if (assetMutation) await assetMutation;
    if (deleting) return;
    if (saving) { await saving; if (pending.size) return save(); return; }
    saving = (async () => {
      let recovered = false;
      while (pending.size && !deleting) {
        const sent = new Map(pending), payload = {revision:state.revision,data:{},provenance:{}};
        for (const [key,entry] of sent) {
          if (key === 'title' || key === 'category') payload[key] = entry.value; else payload.data[key] = entry.value;
          payload.provenance[key] = {source:'user',review:'confirmed'};
        }
        markSave('Guardando…','pending');
        try {
          const result = await api(`${base}guardar/`,payload);
          for (const [key,entry] of sent) {
            const unchanged = String(fieldValue(state,key) ?? '') === String(entry.value ?? '');
            const previous = state.provenance[key];
            if (key === 'title' || key === 'category') state[key] = entry.value; else state.data[key] = entry.value;
            state.provenance[key] = unchanged && previous ? {...previous,review:'confirmed'} : {source:'user',review:'confirmed'};
            if (pending.get(key)?.sequence === entry.sequence) pending.delete(key);
          }
          state.revision = result.revision;
          // The server may invalidate automatic suggestions after an identity edit.
          // hydrate keeps newer pending values, including explicit blanks and zero.
          if (result.machine) hydrate(result.machine);
          markSave(pending.size ? 'Cambios pendientes' : 'Guardado',pending.size ? 'pending' : 'saved');
        } catch (error) {
          if (error.status === 409 && !recovered && await rebaseOwnAnalysis(payload.revision)) { recovered = true; continue; }
          if (error.status === 409) {
            conflict = true;
            problem('Este borrador cambió en otra pestaña. Tus correcciones siguen aquí y no se sobrescribieron. Copia lo que quieras conservar y recarga para consultar la versión actual.');
          } else problem(error.message);
          markSave(navigator.onLine ? 'No se guardó. Reintenta.' : 'Sin conexión · pendiente','error');
          throw error;
        }
      }
    })();
    try { await saving; } finally { saving = null; }
  }
  $$('[data-field],[data-top-field]',wizard).forEach(bindInput);
  saveRetry.addEventListener('click',() => { if (deleting) return; clearProblem(); save().catch(() => {}); });
  addEventListener('online',() => { if (pending.size && !conflict && !deleting) save().catch(() => {}); });
  addEventListener('beforeunload',event => { if (!deleteComplete && (pending.size || saving || uploadCount || uploadFailures.size || submitting || deleting || assetTasks.size)) { event.preventDefault(); event.returnValue = ''; } });
  $('#save-exit').addEventListener('click',async event => {
    event.preventDefault();
    if (submitting || downloading || deleting) return problem('Espera a que termine la operación en curso.');
    if (uploadCount || uploadFailures.size) return problem('Termina la carga o descarta los archivos que no pudieron subir antes de salir.');
    try { await save(); location.assign('/panel/maquinarias/'); } catch { /* Keep local corrections visible. */ }
  });
  beforePreferencesReload = async () => {
    if (submitting || downloading || deleting || uploadCount || uploadFailures.size) return false;
    try { await save(); return true; } catch { return false; }
  };
  function displayStep(step,scroll=true) {
    currentStep = Number(step) > 1 ? 2 : 1;
    $$('[data-step-panel]',wizard).forEach(panel => { panel.hidden = Number(panel.dataset.stepPanel) !== currentStep; });
    $$('.wizard-progress [data-step-to]',wizard).forEach(button => { if (Number(button.dataset.stepTo) === currentStep) button.setAttribute('aria-current','step'); else button.removeAttribute('aria-current'); });
    $('#step-prev').hidden = currentStep === 1;
    const url = new URL(location.href); url.searchParams.set('paso',currentStep); url.searchParams.delete('step'); history.replaceState(null,'',url);
    if (currentStep === 2) renderPreview();
    if (scroll) $('.wizard-progress').scrollIntoView({behavior:'smooth',block:'start'});
  }
  $$('[data-step-to]',wizard).forEach(button => button.addEventListener('click',() => displayStep(button.dataset.stepTo)));
  $('#step-prev').addEventListener('click',() => displayStep(1));
  function updateRevision(result) { if (result.revision !== undefined) state.revision = Math.max(Number(state.revision),Number(result.revision)); }
  function mutateAsset(action) {
    const task = performAssetMutation(action);
    assetTasks.add(task);
    task.then(() => assetTasks.delete(task),() => assetTasks.delete(task));
    return task;
  }
  async function performAssetMutation(action) {
    while (assetMutation) await assetMutation;
    await save();
    while (assetMutation) await assetMutation;
    let release;
    assetMutation = new Promise(resolve => { release = resolve; });
    try { const result = await action(); updateRevision(result); return result; }
    finally { assetMutation = null; release(); if (pending.size && !conflict && !deleting) saveTimer = setTimeout(() => save().catch(() => {}),0); }
  }
  function assetSummary(card) {
    const summary = $('.asset-info>summary',card); summary.replaceChildren(el('span','',purposeLabels[card.dataset.purpose] || 'Archivo'),el('span','optional',' · opciones'));
  }
  function assetActionButtons(card) {
    $$('[data-asset-action]',card).forEach(button => { button.disabled = !editable || submitting || deleting; button.addEventListener('click',async () => {
      if (!editable || preparing || submitting || downloading || deleting || button.disabled) return;
      const action = button.dataset.assetAction;
      if (action === 'delete' && !confirm('¿Eliminar este archivo del borrador?')) return;
      button.disabled = true;
      try {
        await mutateAsset(() => api(`/api/archivos/${card.dataset.assetId}/accion/`,{action}));
        if (action === 'delete') card.remove();
        if (action === 'cover') { $$('.asset-cover',wizard).forEach(badge => { badge.hidden = true; }); $('.asset-cover',card).hidden = false; }
        if (action === 'up' && card.previousElementSibling) card.parentNode.insertBefore(card,card.previousElementSibling);
        if (action === 'down' && card.nextElementSibling) card.parentNode.insertBefore(card.nextElementSibling,card);
        renderPreview(); toast(action === 'delete' ? 'Archivo eliminado del borrador.' : 'Cambio guardado.');
      } catch (error) { problem(error.message); }
      finally { button.disabled = !editable || submitting || deleting; }
    }); });
    const select = el('select','asset-purpose'); select.setAttribute('aria-label','Tipo de archivo'); select.disabled = !editable || submitting || deleting;
    for (const [value,label] of Object.entries(purposeLabels)) { const option = el('option','',label); option.value = value; option.selected = value === card.dataset.purpose; select.append(option); }
    select.addEventListener('change',async () => {
      const previous = card.dataset.purpose; if (preparing || submitting || downloading || deleting) { select.value = previous; return; } select.disabled = true;
      try { await mutateAsset(() => api(`/api/archivos/${card.dataset.assetId}/accion/`,{action:'purpose',purpose:select.value})); card.dataset.purpose = select.value; assetSummary(card); renderPreview(); }
      catch (error) { select.value = previous; problem(error.message); }
      finally { select.disabled = !editable || submitting || deleting; }
    });
    $('.asset-info',card).append(select);
  }
  $$('.asset-card',wizard).forEach(assetActionButtons);
  function appendAsset(result) {
    if ($$('.asset-card',wizard).some(card => card.dataset.assetId === String(result.id))) return;
    const card = el('article','asset-card'); card.dataset.assetId = result.id; card.dataset.kind = result.kind; card.dataset.purpose = result.purpose;
    const preview = el('div','asset-preview'), url = result.url || `/archivos/${result.id}/`;
    if (result.kind === 'video') { const video = el('video'); video.src = url; video.controls = true; video.preload = 'metadata'; preview.append(video); }
    else { const link = el('a'); link.href = `/archivos/${result.id}/?original=1`; link.target = '_blank'; link.rel = 'noopener'; const image = el('img'); image.src = url; image.alt = 'Fotografía de tu maquinaria'; image.loading = 'lazy'; link.append(image); preview.append(link); }
    const cover = el('span','tag asset-cover','PORTADA'); cover.hidden = !result.is_cover; preview.append(cover);
    const info = el('details','asset-info'), summary = el('summary'), actions = el('div','asset-actions');
    for (const [action,label,symbol] of [['cover','Usar como portada','☆'],['up','Mover antes','←'],['down','Mover después','→'],['delete','Eliminar archivo','×']]) { const button = el('button','',symbol); button.type = 'button'; button.dataset.assetAction = action; button.setAttribute('aria-label',label); button.title = label; actions.append(button); }
    info.append(summary,actions); card.append(preview,info); $('#asset-grid').append(card); assetSummary(card); assetActionButtons(card); renderPreview();
  }
  function sendFile(file,purpose,row) {
    return new Promise((resolve,reject) => {
      const progress = $('progress',row), label = $('.upload-message',row);
      const xhr = new XMLHttpRequest(); xhr.open('POST',`${base}archivos/`); xhr.withCredentials = true; xhr.timeout = 300000;
      xhr.setRequestHeader('X-CSRFToken',csrf()); xhr.setRequestHeader('Accept','application/json');
      xhr.upload.addEventListener('progress',event => { if (event.lengthComputable) { progress.max = event.total; progress.value = event.loaded; label.textContent = event.loaded === event.total ? 'Validando el archivo…' : `${Math.round(event.loaded / event.total * 100)}% transferido`; } });
      xhr.addEventListener('load',() => { let result; try { result = JSON.parse(xhr.responseText); } catch { reject(new Error('Respuesta no válida. Conservamos el archivo para reintentar.')); return; } if (xhr.status < 200 || xhr.status >= 300) reject(new Error(result.error || 'No se pudo recibir este archivo.')); else resolve(result); });
      xhr.addEventListener('error',() => reject(new Error('Se interrumpió la carga. Puedes reintentar este archivo.')));
      xhr.addEventListener('timeout',() => reject(new Error('La conexión tardó demasiado. Puedes reintentar este archivo.')));
      const form = new FormData(); form.append('file',file); form.append('purpose',purpose); xhr.send(form);
    });
  }
  function queueFiles(files) {
    if (!editable) return;
    if (preparing || submitting || downloading || deleting) return problem('Espera a que termine la operación en curso antes de agregar más archivos.');
    for (const file of files) {
      const purpose = $('#upload-purpose').value;
      const row = el('div','upload-item'), top = el('div','upload-item-top'), message = el('span','upload-message','En espera de carga…'), progress = el('progress');
      progress.max = 100; progress.value = 0; progress.setAttribute('aria-label',`Carga de ${file.name}`);
      const controls = el('div','button-row'), retry = el('button','link-button small','Reintentar'), omit = el('button','link-button small','Descartar'); retry.type = omit.type = 'button'; retry.hidden = omit.hidden = true;
      controls.append(retry,omit); top.append(el('strong','',file.name),controls); row.append(top,progress,message); $('#upload-queue').append(row);
      const isVideo = file.type.startsWith('video/') || /\.(mov|mp4)$/i.test(file.name), maxMb = Number(isVideo ? wizard.dataset.maxVideoMb : wizard.dataset.maxImageMb);
      omit.addEventListener('click',() => { if (deleting) return; uploadFailures.delete(row); row.remove(); });
      if (file.size > maxMb * 1024 * 1024) { uploadFailures.add(row); message.textContent = `Supera ${maxMb} MB. Elige un archivo más pequeño o descártalo.`; row.classList.add('error-text'); progress.hidden = true; omit.hidden = false; continue; }
      async function attempt() {
        uploadFailures.delete(row); retry.hidden = omit.hidden = true; progress.hidden = false; row.classList.remove('error-text'); message.textContent = 'Preparando carga…'; progress.value = 0;
        try { const result = await mutateAsset(() => sendFile(file,purpose,row)); appendAsset(result); message.textContent = 'Archivo recibido y verificado.'; progress.hidden = true; }
        catch (error) { uploadFailures.add(row); message.textContent = error.message; row.classList.add('error-text'); retry.hidden = omit.hidden = false; progress.hidden = true; }
        finally { uploadCount--; }
      }
      function enqueue() { if (deleting) return; uploadCount++; retry.hidden = omit.hidden = true; fileChain = fileChain.then(attempt); }
      retry.addEventListener('click',enqueue); enqueue();
    }
  }
  $$('[data-file-open]',wizard).forEach(button => button.addEventListener('click',() => { if (editable && !preparing && !submitting && !downloading && !deleting) $(`#${button.dataset.fileOpen}`).click(); }));
  for (const input of [$('#gallery-input'),$('#camera-input')]) input.addEventListener('change',() => { queueFiles([...input.files]); input.value = ''; });
  const drop = $('#drop-zone');
  for (const name of ['dragenter','dragover']) drop.addEventListener(name,event => { event.preventDefault(); drop.classList.add('drag-over'); });
  for (const name of ['dragleave','drop']) drop.addEventListener(name,event => { event.preventDefault(); drop.classList.remove('drag-over'); });
  drop.addEventListener('drop',event => queueFiles([...event.dataTransfer.files]));
  async function uploadsReady() {
    while (uploadCount || assetTasks.size) {
      await fileChain;
      if (assetTasks.size) await Promise.all([...assetTasks]);
    }
    if (uploadFailures.size) throw new Error('Hay archivos que no pudieron subir. Reinténtalos o descártalos para continuar.');
  }

  const pdfDownload = $('#download-draft-pdf'), pdfStatus = $('#draft-pdf-status'), sheetLinks = $$('[data-open-sheet]',wizard);
  let documentMode = 'pdf';
  function pdfLabel() {
    const busy = downloading || submitting || preparing || jobPending || polling || deleting;
    pdfDownload.setAttribute('aria-disabled',String(busy));
    pdfDownload.setAttribute('aria-busy',String(downloading && documentMode === 'pdf'));
    pdfDownload.textContent = downloading && documentMode === 'pdf' ? 'Preparando PDF…' : 'Descargar ficha PDF ↓';
    sheetLinks.forEach(link => { link.setAttribute('aria-disabled',String(busy)); link.setAttribute('aria-busy',String(downloading && documentMode === 'screen')); });
    $('#view-draft-sheet').textContent = downloading && documentMode === 'screen' ? 'Abriendo tu ficha…' : 'Ver ficha en pantalla →';
  }
  async function openDocument(event,mode) {
    event.preventDefault();
    if (downloading) return;
    if (submitting || preparing || jobPending || polling || deleting) return problem('Espera a que termine la operación en curso para consultar la ficha.');
    const destination = event.currentTarget.href;
    documentMode = mode; downloading = true; clearProblem(); prepareLabel();
    pdfStatus.hidden = false; pdfStatus.textContent = 'Terminando cargas y guardando tus cambios…';
    try {
      await uploadsReady(); await save();
      if (conflict) throw new Error('El borrador cambió en otra sesión. Conservamos tus cambios; recarga la versión actual antes de consultar la ficha.');
      // Navigation happens only after uploads, asset mutations and every dirty edit settle.
      const link = el('a'); link.href = destination; link.hidden = true;
      if (mode === 'pdf') link.download = ''; else link.dataset.sheetNavigation = 'true';
      document.body.append(link); link.click(); link.remove();
      pdfStatus.textContent = mode === 'pdf' ? 'Descarga solicitada. Tus cambios están guardados.' : 'Abriendo la ficha guardada en pantalla…';
    } catch (error) {
      problem(error.message); pdfStatus.textContent = mode === 'pdf' ? 'No se descargó el PDF. Conservamos tus cambios para que puedas reintentar.' : 'No se abrió la ficha. Conservamos tus cambios para que puedas reintentar.';
    } finally { downloading = false; prepareLabel(); }
  }
  pdfDownload.addEventListener('click',event => openDocument(event,'pdf'));
  sheetLinks.forEach(link => link.addEventListener('click',event => openDocument(event,'screen')));
  function analysisStatus(message,status='') { $('#analysis-feedback').hidden = false; const box = $('#analysis-status'); box.textContent = message; box.dataset.state = status; }
  function relevanceOf(job) {
    const relevance = job.result?.relevance;
    return relevance && typeof relevance === 'object' && ['relevant','mixed','unrelated','uncertain','unassessed'].includes(relevance.status) ? relevance : null;
  }
  function relevanceAssetIds(value) {
    return new Set((Array.isArray(value) ? value : []).filter(id => typeof id === 'string' || typeof id === 'number').map(String));
  }
  function incompleteReadingsOf(job) {
    const readings = new Map();
    for (const item of Array.isArray(job.result?.image_readings) ? job.result.image_readings : []) {
      if (item && ['failed','not_run','budget_unavailable'].includes(item.status) && ['string','number'].includes(typeof item.asset_id)) readings.set(String(item.asset_id),item.status);
    }
    return readings;
  }
  function hasIncompleteReadings(job,readings) {
    return readings.size > 0 || job.result?.image_analysis_status === 'partial' || job.result?.image_analysis_complete === false;
  }
  function incompleteReadingMessage(readings) {
    const count = readings.size;
    return `Lectura incompleta: no terminamos de analizar ${count ? `${count} foto${count === 1 ? '' : 's'}` : 'todas las fotos'}. Conservamos la información disponible, tus correcciones y tus archivos. Puedes continuar con lo disponible o agregar otras fotos.`;
  }
  function renderRelevance(relevance,readings=new Map()) {
    const excluded = relevanceAssetIds(relevance?.excluded_asset_ids), uncertain = relevanceAssetIds(relevance?.uncertain_asset_ids);
    $$('.asset-card',wizard).forEach(card => {
      $('.asset-relevance',card)?.remove(); delete card.dataset.relevance;
      const reading = readings.get(card.dataset.assetId);
      if (!reading && (!relevance || relevance.status === 'unassessed')) return;
      const status = reading || (excluded.has(card.dataset.assetId) ? 'excluded' : uncertain.has(card.dataset.assetId) ? 'uncertain' : null);
      if (!status) return;
      card.dataset.relevance = status;
      const text = status === 'failed' ? 'Análisis interrumpido · lectura pendiente'
        : ['not_run','budget_unavailable'].includes(status) ? 'Lectura pendiente · no se completó el análisis'
        : status === 'excluded' ? 'Foto ajena a maquinaria · omitida en esta lectura' : 'No se pudo identificar el equipo en esta foto';
      const label = el('p','small muted asset-relevance',text);
      label.setAttribute('role','note');
      $('.asset-preview',card).insertAdjacentElement('afterend',label);
    });
  }
  function blockedRelevance(job) {
    const relevance = relevanceOf(job);
    if (!relevance || !['unrelated','uncertain'].includes(relevance.status)) return false;
    const readings = incompleteReadingsOf(job), incomplete = hasIncompleteReadings(job,readings);
    renderRelevance(relevance,readings); analysisOutcome = incomplete ? 'partial' : relevance.status;
    const message = incomplete ? incompleteReadingMessage(readings) : relevance.status === 'unrelated'
      ? 'Estas fotos no corresponden a maquinaria ni a una placa de equipo. Agrega una foto de la máquina o de su placa para preparar la ficha. Tus archivos y datos se conservan.'
      : 'No pudimos identificar maquinaria o una placa con claridad en estas fotos. Agrega una foto del equipo o una placa más legible. Tus archivos y datos se conservan.';
    analysisStatus(message,analysisOutcome);
    $('#ready-heading').textContent = 'Tu ficha conserva la información disponible.';
    $('.wizard-progress [data-step-to="2"] b',wizard).textContent = 'Ficha';
    $('#analysis-results').hidden = true; $('#research-brief').hidden = true;
    renderPreview();
    if (!deleting) displayStep(1);
    return true;
  }
  function prepareLabel() { $$('[data-file-open]',wizard).forEach(button => { button.disabled = !editable || preparing || submitting || downloading || deleting; }); $('#analyze-button').disabled = !editable || preparing || jobPending || polling || submitting || downloading || deleting; $('#analyze-button').textContent = preparing && uploadCount ? 'Esperando tus archivos…' : preparing || jobPending || polling ? 'Preparando tu ficha…' : 'Preparar mi ficha ✧'; $('#submit-machine').disabled = !editable || submitting || downloading || deleting; const remove = $('#delete-draft'); if (remove) remove.disabled = !editable || preparing || submitting || downloading || deleting; pdfLabel(); }
  async function syncSnapshot(job) {
    if (saving) { try { await saving; } catch { return job; } }
    if (assetMutation) await assetMutation;
    if (job.machine && Number(job.machine.revision) < Number(state.revision)) job = await api(`/api/analisis/${job.id}/`);
    if (!conflict && job.machine && (!pending.size || Number(job.machine.revision) === Number(state.revision) || isOwnAutoAdvance(job.machine,job.auto_apply))) hydrate(job.machine);
    return job;
  }
  async function completedJob(job) {
    // Rejected/uncertain photos must never trigger legacy autofill or replace
    // the existing draft, even when an older client result contains fields.
    if (blockedRelevance(job)) return;
    job = await syncSnapshot(job);
    if (blockedRelevance(job)) return;
    const readings = incompleteReadingsOf(job), incomplete = hasIncompleteReadings(job,readings);
    if (incomplete) {
      analysisOutcome = 'partial';
      $('#ready-heading').textContent = 'Tu ficha conserva la información disponible.';
      $('.wizard-progress [data-step-to="2"] b',wizard).textContent = 'Ficha';
      renderRelevance(relevanceOf(job),readings);
    }
    // A previous, already consented analysis can fill blanks without a second AI call.
    if (editable && !conflict && !deleting && (!job.auto_apply?.requested || job.auto_apply.reason === 'application_failed') && !legacyAttempts.has(job.id)) {
      legacyAttempts.add(job.id);
      try { await save(); if (deleting) return; const applied = await api(`${base}aplicar/`,{automatic:true,job_id:job.id,revision:state.revision}); job = await syncSnapshot({...job,auto_apply:applied.auto_apply,machine:applied.machine}); }
      catch (error) { analysisStatus(`${error.message} Conservamos tu ficha con la información disponible.`,'failed'); renderResults(job); return; }
    }
    analysisOutcome = incomplete ? 'partial' : 'completed';
    renderResults(job);
    const relevance = relevanceOf(job); renderRelevance(relevance,readings);
    const metadata = job.auto_apply || {}, count = metadata.applied_fields?.length || 0;
    const message = metadata.status === 'skipped' ? 'Conservamos tus datos. Las fotos o la ficha cambiaron durante la lectura; puedes editar la información o volver a prepararla con las fotos actuales.' : count ? `Ficha preparada. Completamos ${count} dato${count === 1 ? '' : 's'} disponible${count === 1 ? '' : 's'} y conservamos tus correcciones.` : 'Tu ficha está lista para revisar. Los datos que no se encontraron quedan sin indicar.';
    let relevanceMessage = '';
    if (relevance?.status === 'mixed') {
      const excluded = [...relevanceAssetIds(relevance.excluded_asset_ids)].filter(id => !readings.has(id)).length, uncertain = [...relevanceAssetIds(relevance.uncertain_asset_ids)].filter(id => !readings.has(id)).length;
      relevanceMessage = excluded ? `Se ${excluded === 1 ? 'omitió 1 foto ajena' : `omitieron ${excluded} fotos ajenas`} a maquinaria en esta lectura. ` : incomplete ? '' : 'La ficha se preparó con las fotos que se pudieron identificar. ';
      if (uncertain) relevanceMessage += `No se pudo identificar el equipo en ${uncertain} foto${uncertain === 1 ? '' : 's'} adicional${uncertain === 1 ? '' : 'es'}. `;
    }
    analysisStatus(relevanceMessage + (incomplete ? incompleteReadingMessage(readings) : message),analysisOutcome);
    $('#ready-heading').textContent = incomplete ? 'Tu ficha conserva la información disponible.' : 'Tu ficha está preparada.';
    $('.wizard-progress [data-step-to="2"] b',wizard).textContent = incomplete ? 'Ficha' : 'Ficha lista';
    if (currentStep === 1 && !conflict && !deleting) displayStep(2);
  }
  function pollJob(id) {
    if (polling || deleting) return Promise.resolve();
    const task = runPollJob(id); pollTask = task;
    task.finally(() => { if (pollTask === task) pollTask = null; });
    return task;
  }
  async function runPollJob(id) {
    clearTimeout(pollTimer); activeJob = id; polling = true; prepareLabel(); $('#analysis-resume').hidden = true;
    try {
      const job = await api(`/api/analisis/${id}/`);
      analysisOutcome = job.status;
      if (job.status === 'completed') { jobPending = false; await completedJob(job); }
      else if (job.status === 'failed') { jobPending = false; await syncSnapshot(job); analysisStatus(job.error || 'No pudimos completar la lectura. Tus fotos están guardadas y puedes enviar la ficha para revisión.','failed'); $('#ready-heading').textContent = 'Tu ficha conserva la información disponible.'; renderPreview(); }
      else {
        jobPending = true;
        analysisStatus(job.status === 'running' ? 'Estamos identificando el equipo, buscando sus especificaciones y preparando la descripción. Tus correcciones se conservarán.' : 'Tus fotos están guardadas. La ficha espera su turno de preparación.',job.status);
        if (Date.now() - analysisStartedAt > 10 * 60 * 1000) { $('#analysis-resume').hidden = false; jobPending = false; analysisStatus('El análisis sigue en el servidor. Puedes consultar su estado después; tus datos se conservan.','queued'); }
        else if (!deleting) pollTimer = setTimeout(() => pollJob(id),2500);
      }
    } catch (error) { jobPending = false; analysisStatus(`${error.message} Tus datos siguen aquí y puedes enviar la ficha disponible para revisión.`,'failed'); $('#analysis-resume').hidden = false; }
    finally { polling = false; prepareLabel(); }
  }
  $('#analysis-resume').addEventListener('click',() => { if (activeJob) { analysisStartedAt = Date.now(); pollJob(activeJob); } });
  $('#analyze-button').addEventListener('click',async () => {
    if (!editable || preparing || jobPending || polling || submitting || downloading || deleting) return;
    preparing = true; clearProblem(); prepareLabel();
    try {
      await uploadsReady(); await save();
      const assetIds = $$('.asset-card[data-kind=image]',wizard).filter(card => card.dataset.purpose !== 'document').map(card => card.dataset.assetId);
      if (!assetIds.length) throw new Error('Agrega al menos una fotografía para preparar la ficha.');
      const job = await api(`${base}analizar/`,{consent:true,auto_apply:true,research:true,revision:state.revision,asset_ids:assetIds,mode:'analysis'});
      activeJob = job.id; analysisStartedAt = Date.now(); jobPending = ['queued','running'].includes(job.status);
      renderRelevance(null);
      displayStep(2); analysisStatus('Preparando tu ficha con las fotos guardadas…','running'); await pollJob(job.id);
    } catch (error) { analysisOutcome = 'failed'; renderPreview(); problem(error.message); analysisStatus('No se pudo preparar toda la información. Tus datos y fotos recibidas siguen guardados; puedes enviar la ficha para revisión.','failed'); }
    finally { preparing = false; prepareLabel(); }
  });
  function researchHypothesesOf(research) {
    return Array.isArray(research?.hypotheses) ? research.hypotheses.filter(item => item && typeof item === 'object') : [];
  }
  function renderResearchHypotheses(value) {
    const target = $('#preview-research-hypotheses');
    if (!target) return;
    target.replaceChildren(); target.hidden = true;
    const identity = valuationIdentityOf(value);
    if (identity !== researchHypothesisIdentity) {
      researchHypotheses = [];
      researchHypothesisIdentity = identity;
    }
    if (!researchHypotheses.length || !missing(value.data?.model)) return;
    const items = [];
    for (const hypothesis of researchHypotheses) {
      const model = typeof hypothesis.model === 'string' ? hypothesis.model.trim() : '';
      if (!model) continue;
      const item = el('li'), title = el('strong','',model);
      item.append(title);
      const evidence = typeof hypothesis.evidence === 'string' ? hypothesis.evidence.trim() : '';
      const period = hypothesis.production_period && typeof hypothesis.production_period === 'object' ? hypothesis.production_period : {};
      const from = period.from, to = period.to;
      const periodText = from !== undefined && from !== null && from !== '' && to !== undefined && to !== null && to !== ''
        ? `Periodo documentado: ${from}–${to}. No indica la edad de esta unidad.`
        : from !== undefined && from !== null && from !== ''
          ? `Periodo documentado: desde ${from}. No indica la edad de esta unidad.`
          : to !== undefined && to !== null && to !== ''
            ? `Periodo documentado: hasta ${to}. No indica la edad de esta unidad.` : '';
      const details = [];
      if (evidence) details.push(evidence);
      if (periodText) details.push(periodText);
      if (details.length) item.append(el('p','',details.join('\n')));
      items.push(item);
    }
    if (!items.length) return;
    const list = el('ul','research-hypothesis-list'); items.forEach(item => list.append(item));
    target.append(el('h3','', 'Modelos de referencia encontrados · por identificar'),el('p','', 'Estos modelos no confirman la unidad fotografiada ni su configuración. El periodo de producción indicado tampoco determina la edad de esta unidad.'),list);
    target.hidden = false;
  }
  function renderResearch(research,target) {
    if (!research || typeof research !== 'object') return;
    const fields = Array.isArray(research.fields) ? research.fields : [];
    const summaries = {
      general_context:'Referencias generales del tipo de maquinaria; no identifican esta unidad ni confirman sus especificaciones.',
      no_results:'No se encontraron especificaciones verificables en la búsqueda. Conservamos la información de tus fotos.',
      insufficient_identifiers:'No se identificaron datos suficientemente claros para buscar especificaciones. Conservamos la información de tus fotos.',
      degraded:'No se pudo completar la búsqueda web. Conservamos la información disponible.',
      disabled:'Este análisis no incluye una búsqueda web.'
    };
    const scopeLabels = {model:'Referencia del modelo; confirmar en este equipo',exact_serial:'Referencia de la unidad; pendiente de revisión'};
    const summary = summaries[research.status] || (research.match === 'exact_serial'
      ? 'Se encontró una referencia que coincide con la serie. La información de la unidad queda pendiente de revisión.'
      : research.match === 'model'
        ? 'Se encontraron referencias del modelo. No confirman la configuración ni el estado de esta unidad.'
        : 'La búsqueda no confirmó especificaciones para esta maquinaria.');
    const brief = $('#research-brief');
    if (brief) { brief.textContent = summary; brief.hidden = research.status === 'disabled'; }
    target.append(el('p','research-summary',summary));
    if (research.status === 'general_context' && typeof research.context?.category === 'string') target.append(el('p','small',`Tipo consultado: ${research.context.category}`));
    const list = el('dl','research-field-list');
    for (const field of fields) {
      if (!field || typeof field !== 'object' || missing(field.value)) continue;
      const row = el('div'), value = typeof field.value === 'object' ? JSON.stringify(field.value) : String(field.value), definition = el('dd');
      definition.append(el('strong','',value),el('span','research-scope',scopeLabels[field.scope] || 'Referencia por revisar'));
      row.append(el('dt','',keyLabels[field.key] || field.key || 'Especificación'),definition); list.append(row);
    }
    if (list.children.length) target.append(list);
  }
  function valuationIdentityOf(snapshot) {
    return JSON.stringify([snapshot.category,...['brand','model','serial'].map(key => snapshot.data?.[key])].map(value => String(value ?? '').trim()));
  }
  function renderValuation(value) {
    const data = value.data, feedback = $('#valuation-status'), disclaimer = $('#valuation-disclaimer'), target = $('#valuation-comparables');
    const identityMatches = valuationIdentityOf(value) === valuationIdentity;
    const hasEstimate = ['estimate_min','estimate_max'].some(key => !missing(data[key]));
    const activePrice = !missing(data.price) && value.provenance.price?.source === 'valuation';
    const activeEstimate = Object.keys(estimateLabels).some(key => !missing(data[key]) && value.provenance[key]?.source === 'valuation');
    const valuation = identityMatches && (activeEstimate || activePrice) && state.valuation && typeof state.valuation === 'object' ? state.valuation : null;
    const status = valuation?.status || (identityMatches && state.valuation?.status === 'insufficient' ? 'insufficient' : valuationFeedback);
    if (disclaimer) disclaimer.textContent = status === 'conditional_reference'
      ? 'Referencia de mercado condicional, editable y sujeta a confirmación.'
      : 'Estimación orientativa, editable y sujeta a confirmación';
    if (!identityMatches) feedback.textContent = 'La identificación cambió. Las referencias anteriores quedan ocultas hasta una nueva estimación; conserva o corrige los importes que quieras.';
    else if (status === 'insufficient') feedback.textContent = 'No se encontraron referencias de precio suficientes para una estimación fiable. Puedes continuar sin precio o indicar el tuyo.';
    else if (status === 'conditional_reference') feedback.textContent = 'Rango de mercado de comparables con una condición documentada; no confirma la condición de esta unidad. No se completó un precio de anuncio sugerido.';
    else if (hasEstimate || activePrice) feedback.textContent = 'Estos importes son orientativos. Puedes modificar o borrar cada propuesta; los anuncios no acreditan precios de venta.';
    else feedback.textContent = 'No hay una estimación activa. Puedes continuar sin precio o indicar el tuyo.';
    if (!missing(data.estimate_missing_info)) feedback.textContent += ` ${hasEstimate ? 'Para afinarla' : 'Para obtenerla'}: ${String(data.estimate_missing_info)}`;
    target.replaceChildren();
  }
  function renderResults(job) {
    const target = $('#analysis-results'), result = job.result || {}, metadata = job.auto_apply || {};
    researchHypotheses = researchHypothesesOf(result.research);
    researchHypothesisIdentity = valuationIdentityOf(job.machine || state);
    valuationFeedback = result.valuation?.status === 'insufficient' ? 'insufficient' : null;
    previewImageKinds.clear();
    for (const image of Array.isArray(result.image_observations) ? result.image_observations : []) if (image && ['machine','plate','document','other','unknown'].includes(image.kind)) previewImageKinds.set(String(image.asset_id),image.kind);
    // Legacy jobs identify close-up plates without the newer main-object classification.
    for (const plate of Array.isArray(result.plates) ? result.plates : []) if (plate?.asset_id && !previewImageKinds.has(String(plate.asset_id))) previewImageKinds.set(String(plate.asset_id),'plate');
    const wasOpen = target.open; target.replaceChildren(); target.hidden = false; target.open = wasOpen;
    const observations = [...new Set([...(Array.isArray(result.warnings) ? result.warnings : []),...(Array.isArray(result.questions) ? result.questions : []),...(Array.isArray(result.research?.warnings) ? result.research.warnings : [])].map(item => typeof item === 'string' ? item : JSON.stringify(item)))];
    target.append(el('summary','',observations.length ? `Detalles · ${observations.length} ${observations.length === 1 ? 'observación' : 'observaciones'}` : 'Detalles de la preparación'),el('p','small muted','Los datos quedan pendientes de revisión y no certifican la condición del equipo.'));
    renderResearch(result.research,target);
    if (metadata.skipped_fields?.length) target.append(el('p','small','Se conservaron tus datos en: '+metadata.skipped_fields.map(key => keyLabels[key] || key).join(', ')+'.'));
    if (observations.length) { const list = el('ul'); observations.forEach(item => list.append(el('li','',typeof item === 'string' ? item : JSON.stringify(item)))); target.append(list); }
    const data = result.data || {};
    const provenance = el('dl','analysis-provenance');
    for (const [key,value] of Object.entries(data)) if (!missing(value)) { const row = el('div'); const origin = result.provenance?.[key]; row.append(el('dt','',keyLabels[key] || key),el('dd','',`${typeof value === 'object' ? JSON.stringify(value) : value} · ${sourceLabels[origin?.source] || 'Lectura de IA'}`)); provenance.append(row); }
    if (provenance.children.length) target.append(provenance);
    for (const plate of Array.isArray(result.plates) ? result.plates : []) { target.append(el('p','small',`Placa: ${plate.component || 'componente por identificar'}`),el('pre','plate-text',plate.transcription || 'No identificable')); if ($$('.asset-card',wizard).some(card => card.dataset.assetId === String(plate.asset_id))) { const link = el('a','text-link small','Ver placa original ↗'); link.href = `/archivos/${plate.asset_id}/?original=1`; link.target = '_blank'; link.rel = 'noopener'; target.append(link); } }
    renderPreview();
  }
  function previewSource(meta) {
    if (!meta || !meta.source || meta.source === 'unknown') return '';
    if (meta.source === 'web' || meta.source === 'web_model' || meta.source === 'web_serial') return (meta.scope === 'model' || meta.source === 'web_model' ? 'Referencia del modelo' : meta.scope === 'exact_serial' || meta.source === 'web_serial' ? 'Referencia de la unidad' : 'Fuente web') + (meta.review === 'confirmed' ? ' · confirmado por ti' : ' · por confirmar');
    if (meta.source === 'plate') return 'Lectura de placa' + (meta.review === 'needs_review' ? ' · por revisar' : '');
    if (['visual','visual_proposal'].includes(meta.source)) return 'Observación visual · por revisar';
    return sourceLabels[meta.source] || '';
  }
  function renderPreview() {
    const value = collect(), data = value.data;
    $('#preview-title').textContent = value.title && value.title !== 'Mi maquinaria' ? value.title : 'Maquinaria · ficha en preparación';
    $('#preview-description').textContent = data.description || (analysisOutcome === 'partial' ? 'La lectura quedó incompleta. Se conserva la información disponible.' : ['unrelated','uncertain'].includes(analysisOutcome) ? 'Agrega una foto del equipo o de su placa para preparar la descripción.' : ['completed','failed'].includes(analysisOutcome) ? 'No se encontró una descripción con la información disponible.' : 'La descripción se preparará con tus fotos y los datos encontrados.');
    const selectedCategory = $('#category')?.selectedOptions[0];
    const categoryLabel = value.category && selectedCategory?.value ? selectedCategory.textContent.trim() : 'Maquinaria';
    $('#preview-category').textContent = categoryLabel;
    const allImages = $$('.asset-card[data-kind=image]',wizard).filter(card => card.dataset.purpose !== 'document');
    const isPlate = card => previewImageKinds.get(card.dataset.assetId) === 'plate' || card.dataset.purpose === 'plate';
    const machineImages = allImages.filter(card => !isPlate(card));
    const images = machineImages.length ? machineImages : allImages;
    const cover = images.find(card => !$('.asset-cover',card).hidden) || images[0], coverBox = $('#preview-cover');
    if (cover) {
      if ($('img',coverBox)?.dataset.assetId !== cover.dataset.assetId) {
        const link = el('a'), image = el('img');
        link.href = `/archivos/${encodeURIComponent(cover.dataset.assetId)}/?original=1`; link.target = '_blank'; link.rel = 'noopener';
        image.src = `/archivos/${encodeURIComponent(cover.dataset.assetId)}/`; image.dataset.assetId = cover.dataset.assetId;
        link.append(image); coverBox.replaceChildren(link);
      }
      $('img',coverBox).alt = isPlate(cover) ? 'Placa de identificación de esta ficha' : 'Fotografía aportada de la maquinaria';
      $('#preview-image-caption').textContent = isPlate(cover) ? 'Placa de identificación · privada. No sustituye una vista general del equipo.' : 'Fotografía aportada · pulsa para ampliar el original.';
    } else {
      coverBox.replaceChildren(el('span','preview-photo-placeholder','Sin fotografía general de la maquinaria'));
      $('#preview-image-caption').textContent = 'Los archivos originales se conservan en esta ficha interna.';
    }
    function addField(target,key,text,label=keyLabels[key] || key) {
      if (missing(text)) return;
      const row = el('div'), definition = el('dd',key === 'serial' ? 'preview-private-value' : '',String(text));
      row.dataset.previewField = key;
      const source = previewSource(value.provenance[key]);
      if (source) definition.append(el('small','preview-field-source',source));
      row.append(el('dt','',label),definition); target.append(row);
    }
    const specs = $('#preview-specs'); specs.replaceChildren();
    for (const key of ['brand','model','year','serial','hours','condition']) addField(specs,key,data[key]);
    if (!specs.children.length) addField(specs,'category',value.category ? categoryLabel : 'Por identificar','Tipo de equipo');
    renderResearchHypotheses(value);
    const ageFrom = data.estimated_year_from, ageTo = data.estimated_year_to;
    const hasAgeRange = !missing(ageFrom) || !missing(ageTo);
    $('#preview-age-range').textContent = !missing(ageFrom) && !missing(ageTo) ? `${ageFrom}–${ageTo}` : !missing(ageFrom) ? `Desde ${ageFrom}` : !missing(ageTo) ? `Hasta ${ageTo}` : '';
    $('#preview-age-range').hidden = !hasAgeRange;
    $('#preview-age-basis').textContent = data.estimated_year_basis || '';
    $('#preview-age-basis').hidden = !hasAgeRange || missing(data.estimated_year_basis);
    const technical = $('#preview-technical-specs'); technical.replaceChildren();
    for (const key of ['power','weight','capacity','vibration_frequency','centrifugal_force','compaction_depth','dimensions','fuel','kilometers','engine','transmission','attachments',...Object.keys(additionalPlateLabels)]) addField(technical,key,data[key]);
    $('#preview-technical-section').hidden = !technical.children.length;
    const condition = $('#preview-condition-specs'); condition.replaceChildren();
    for (const key of ['preservation_notes','visible_defects','visible_components','attachments','applications']) addField(condition,key,data[key]);
    const estimate = $('#preview-valuation-specs'); estimate.replaceChildren();
    const hasEstimateRange = !missing(data.estimate_min) || !missing(data.estimate_max);
    for (const key of ['estimate_market','estimate_basis','estimate_missing_info']) {
      if (key === 'estimate_basis' && !hasEstimateRange) continue;
      addField(estimate,key,data[key]);
    }
    renderValuation(value);
    const commercial = $('#preview-commercial-specs'); commercial.replaceChildren();
    addField(commercial,'location',data.location || 'No indicada','Ubicación actual');
    addField(commercial,'country_of_origin',data.country_of_origin || 'No identificado','País de fabricación');
  }
  $('#submit-machine').addEventListener('click',async () => {
    if (!editable || submitting || downloading || deleting) return;
    submitting = true; clearProblem(); pdfLabel(); const frozenControls = $$('input,textarea,select,[data-asset-action],[data-file-open],#analyze-button',wizard).map(control => [control,control.disabled]);
    frozenControls.forEach(([control]) => { control.disabled = true; });
    const button = $('#submit-machine'); button.disabled = true; button.textContent = 'Enviando tu solicitud…';
    try {
      await uploadsReady(); await save();
      if (!$('.asset-card[data-kind=image][data-purpose=general],.asset-card[data-kind=image][data-purpose=detail]',wizard)) { displayStep(1); throw new Error('Agrega al menos una fotografía general o de detalle antes de enviar.'); }
      const result = await api(`${base}enviar/`,{advertise_consent:true,contact_consent:$('#contact-consent').checked});
      pending.clear(); submitting = false; location.assign(result.url || '/panel/solicitudes/');
    } catch (error) { problem(error.message); submitting = false; frozenControls.forEach(([control,wasDisabled]) => { control.disabled = !editable || wasDisabled; }); $$('[data-asset-action],.asset-purpose,[data-field],[data-top-field]',wizard).forEach(control => { if (control.matches('[data-asset-action],.asset-purpose') || !frozenControls.some(([original]) => original === control)) control.disabled = !editable; }); prepareLabel(); button.disabled = !editable; button.textContent = 'Enviar a IMC México ↗'; }
  });
  $('#delete-draft')?.addEventListener('click',async () => {
    if (!editable || deleting || preparing || submitting || downloading) return;
    if (conflict) return problem('El borrador cambió en otra sesión. Conservamos tus correcciones; recarga la versión actual antes de eliminar.');
    if (!confirm(deleteDraftConfirmation)) return;
    deleting = true; clearTimeout(saveTimer); clearTimeout(pollTimer); clearProblem();
    const button = $('#delete-draft'), frozen = $$('input,textarea,select,button',wizard).map(control => [control,control.disabled]);
    frozen.forEach(([control]) => { control.disabled = true; });
    button.textContent = 'Moviendo a la papelera…'; prepareLabel();
    try {
      // Finish only work already started. Unsaved corrections need not be saved to delete a draft.
      while (saving || pollTask || uploadCount || assetTasks.size) {
        const results = await Promise.allSettled([saving,pollTask,fileChain,...assetTasks].filter(Boolean));
        const failed = results.find(result => result.status === 'rejected');
        if (failed) throw failed.reason;
      }
      if (conflict) throw new Error('El borrador cambió en otra sesión. Tus correcciones siguen aquí; no se eliminó.');
      const result = await api(`${base}accion/`,{action:'delete_draft',revision:state.revision});
      deleteComplete = true; pending.clear(); uploadFailures.clear();
      clearTimeout(saveTimer); clearTimeout(pollTimer);
      location.assign(result.url || '/panel/maquinarias/');
    } catch (error) {
      deleting = false;
      if (error.status === 409) { conflict = true; markSave('Conflicto de versión · cambios conservados','error'); }
      problem(error.status === 409 ? 'El borrador cambió en otra sesión y no se eliminó. Tus correcciones siguen aquí; recarga la versión actual antes de reintentar.' : `${error.message} No se eliminó el borrador. Conservamos tus correcciones.`);
      frozen.forEach(([control,wasDisabled]) => { control.disabled = !editable || wasDisabled; });
      $$('input,textarea,select,button',wizard).forEach(control => { if (!frozen.some(([original]) => original === control) || control.matches('[data-asset-action],.asset-purpose')) control.disabled = !editable; });
      button.textContent = 'Eliminar borrador'; prepareLabel();
      if (pending.size && !conflict) saveTimer = setTimeout(() => save().catch(() => {}),850);
      if (activeJob && !conflict) pollTimer = setTimeout(() => pollJob(activeJob),2500);
    }
  });
  function categoryFields() {
    const target = $('#category-fields'), source = $('#category-data'); if (!target || !source) return;
    let categories; try { categories = JSON.parse(source.textContent); } catch { return; }
    const category = categories.find(item => String(item.id) === $('#category').value); target.replaceChildren();
    const technical = ['power','weight','capacity','dimensions','fuel','kilometers','attachments','engine','transmission','vibration_frequency','centrifugal_force','compaction_depth','country_of_origin',...Object.keys(additionalPlateLabels)];
    const fields = [...(category?.fields || [])];
    for (const key of technical) if (!missing(pending.has(key) ? pending.get(key).value : state.data[key]) && !fields.some(item => (typeof item === 'string' ? item : item.key || item.name) === key)) fields.push(key);
    for (const item of fields) {
      const field = typeof item === 'string' ? {key:item,label:keyLabels[item] || item} : item, key = field.key || field.name;
      if (!key || !/^[a-zA-Z0-9_]+$/.test(key) || $$('[data-field]',wizard).some(input => input.dataset.field === key)) continue;
      const group = el('div','form-field'), label = el('label','',`${field.label || keyLabels[key] || key}${field.unit ? ` (${field.unit})` : ''} · opcional`), input = el('input');
      label.htmlFor = `extra-${key}`; input.id = label.htmlFor; input.dataset.field = key; input.type = field.type === 'number' ? 'number' : 'text'; input.value = (pending.has(key) ? pending.get(key).value : state.data[key]) ?? ''; input.disabled = !editable || submitting || deleting; input.maxLength = 500; if (input.type === 'number') input.step = 'any'; bindInput(input); group.append(label,input); target.append(group);
    }
  }
  function lockEditing() { $$('input,textarea,select,[data-asset-action],[data-file-open],#analyze-button,#submit-machine',wizard).forEach(control => { control.disabled = true; }); }
  $('#category')?.addEventListener('change',categoryFields); categoryFields();
  if (!editable) lockEditing();
  let initialJob = null;
  try { if ($('#current-job')) initialJob = JSON.parse($('#current-job').textContent); } catch { /* Manual editing remains available. */ }
  const params = new URL(location.href).searchParams, explicitStep = params.get('paso') || params.get('step');
  displayStep(explicitStep || (initialJob || (state.title && state.title !== 'Mi maquinaria') ? 2 : wizard.dataset.step),false);
  if (initialJob) { activeJob = initialJob.id; jobPending = ['queued','running'].includes(initialJob.status); analysisStartedAt = Date.now(); pollJob(initialJob.id); }
  prepareLabel(); renderPreview();
})();
