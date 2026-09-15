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
  $$('[data-machine-action]').forEach(button => button.addEventListener('click', async () => {
    const action = button.dataset.machineAction;
    const payload = { action };
    if (action === 'availability') payload.value = $('#availability')?.value;
    button.disabled = true;
    try {
      const result = await api(`/api/maquinarias/${button.dataset.machineId}/accion/`, payload);
      if (action === 'duplicate') location.assign(result.url || `/panel/maquinarias/${result.id}/`);
      else location.reload();
    } catch (error) { toast(error.message, true); button.disabled = false; }
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
  catch { $('#wizard-errors').textContent = 'No pudimos cargar los datos del borrador. Recarga esta página antes de editar.'; $('#wizard-errors').hidden = false; return; }
  state.data ||= {}; state.provenance ||= {};
  const base = `/api/maquinarias/${wizard.dataset.machine}/`;
  const editable = wizard.dataset.editable === 'true';
  let dirty = false, editSequence = 0, savedSequence = 0, saveTimer, saving = null, conflict = false;
  let uploadCount = 0, activeJob = null, pollTimer, pendingMode = 'analysis', currentStep = 1;
  const saveStatus = $('#save-status'), saveRetry = $('#save-retry'), errorBox = $('#wizard-errors');
  const keyLabels = { title: 'Título', description: 'Descripción', brand: 'Marca', model: 'Modelo', year: 'Año', serial: 'Número de serie', hours: 'Horas de uso', category: 'Categoría', location: 'Ubicación', condition: 'Condición', plate_kind: 'La placa corresponde a', plate_transcription: 'Texto de la placa', price: 'Precio', currency: 'Moneda', notes: 'Comentarios', contact_public: 'Contacto autorizado', power: 'Potencia declarada', weight: 'Peso declarado', capacity: 'Capacidad declarada', dimensions: 'Dimensiones', fuel: 'Combustible', kilometers: 'Kilometraje', attachments: 'Accesorios', engine: 'Motor', transmission: 'Transmisión' };
  const sourceLabels = { image: 'Imagen', plate: 'Placa', user: 'Declaración del usuario', external: 'Fuente externa', visual: 'Propuesta visual', visual_proposal: 'Propuesta visual', user_declared: 'Declaración del usuario', unknown: 'Sin identificar' };
  const reviewLabels = { clear: 'Lectura clara', pending: 'Necesita revisión', needs_review: 'Necesita revisión', confirmed: 'Confirmado por el usuario', unreadable: 'No identificable', needs_confirmation: 'Necesita confirmación' };
  function problem(message) { errorBox.textContent = message; errorBox.hidden = false; errorBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
  function clearProblem() { errorBox.hidden = true; errorBox.textContent = ''; }
  function markSave(message, status = 'saved') { saveStatus.textContent = message; saveStatus.dataset.state = status; saveRetry.hidden = status !== 'error' || conflict; }
  function readInput(input) { if (input.type === 'checkbox') return input.checked; const value = input.value.trim(); return value === '' ? null : value; }
  function collect() {
    const payload = { revision: state.revision, title: state.title, category: state.category, data: { ...state.data }, provenance: { ...state.provenance } };
    $$('[data-field]', wizard).forEach(input => { payload.data[input.dataset.field] = readInput(input); });
    $$('[data-top-field]', wizard).forEach(input => { payload[input.dataset.topField] = readInput(input); });
    return payload;
  }
  function changed(event) {
    if (!editable || conflict) return;
    dirty = true; editSequence++;
    const input = event.target, key = input.dataset.field || input.dataset.topField;
    if (key) state.provenance[key] = { source: 'user', review: 'confirmed' };
    markSave('Cambios pendientes', 'pending'); clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { save().catch(() => {}); }, 850);
  }
  async function save() {
    clearTimeout(saveTimer);
    if (!editable || !dirty) return;
    if (conflict) throw new Error('Este borrador cambió en otra sesión. Recarga antes de seguir.');
    if (saving) { await saving; if (dirty) return save(); return; }
    const sequence = editSequence, payload = collect();
    // Submit visible category fields and shared fields; historical category-specific
    // data remains on the server and must not make a category change invalid.
    const sharedFields = ['brand','model','year','serial','hours','description','location','price','currency','condition','notes','contact_public','plate_transcription','plate_type','plate_kind','no_plate','kilometers','power','capacity','weight','dimensions','fuel','attachments','engine','transmission'];
    const dataKeys = new Set([...sharedFields, ...$$('[data-field]', wizard).map(input => input.dataset.field)]);
    payload.data = Object.fromEntries(Object.entries(payload.data).filter(([key]) => dataKeys.has(key)));
    payload.provenance = Object.fromEntries(Object.entries(payload.provenance).filter(([key]) => dataKeys.has(key) || key === 'title' || key === 'category'));
    markSave('Guardando…', 'pending');
    saving = (async () => {
      try {
        const result = await api(`${base}guardar/`, payload);
        state.revision = result.revision; state.title = payload.title; state.category = payload.category;
        state.data = { ...state.data, ...payload.data };
        savedSequence = sequence; dirty = editSequence !== sequence;
        if (!dirty) markSave('Guardado'); else markSave('Cambios pendientes', 'pending');
      } catch (error) {
        dirty = true;
        if (error.status === 409) {
          conflict = true; problem('Este borrador cambió en otra pestaña o durante un proceso. Copia los cambios que quieras conservar y recarga la página para consultar la versión actual. No se han sobrescrito tus datos.');
        }
        markSave(navigator.onLine ? 'No se guardó. Reintenta.' : 'Sin conexión · pendiente', 'error');
        if (error.status !== 409) problem(error.message);
        throw error;
      } finally { saving = null; }
    })();
    await saving;
    if (dirty && !conflict) return save();
  }
  $$('[data-field],[data-top-field]', wizard).forEach(input => {
    input.addEventListener('input', changed);
    if (input.tagName === 'SELECT' || input.type === 'checkbox') input.addEventListener('change', changed);
  });
  saveRetry.addEventListener('click', () => { clearProblem(); save().catch(() => {}); });
  addEventListener('online', () => { if (dirty && !conflict) save().catch(() => {}); });
  addEventListener('beforeunload', event => { if (dirty || saving || uploadCount) { event.preventDefault(); event.returnValue = ''; } });
  $('#save-exit').addEventListener('click', async event => {
    event.preventDefault();
    if (uploadCount) return problem('Espera a que termine la carga de tus archivos antes de salir.');
    try { await save(); location.assign('/panel/maquinarias/'); } catch { /* Keep the unsaved form visible. */ }
  });
  beforePreferencesReload = async () => {
    if (uploadCount) return false;
    try { await save(); return true; } catch { return false; }
  };
  function displayStep(step, scroll = true) {
    currentStep = Math.min(5, Math.max(1, Number(step) || 1));
    $$('[data-step-panel]', wizard).forEach(panel => { panel.hidden = Number(panel.dataset.stepPanel) !== currentStep; });
    $$('[data-step-to]', $('.wizard-progress')).forEach(button => {
      if (Number(button.dataset.stepTo) === currentStep) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
    $('#step-prev').hidden = currentStep === 1; $('#step-next').hidden = currentStep === 5;
    const url = new URL(location.href); url.searchParams.set('paso', currentStep); history.replaceState(null, '', url);
    if (currentStep === 2) renderAnalysisAssets();
    if (currentStep === 5) renderPreview();
    if (scroll) $('.wizard-progress').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  $$('[data-step-to]', wizard).forEach(button => button.addEventListener('click', () => displayStep(button.dataset.stepTo)));
  $('#step-prev').addEventListener('click', () => displayStep(currentStep - 1));
  $('#step-next').addEventListener('click', () => displayStep(currentStep + 1));
  const initialStep = new URL(location.href).searchParams.get('paso') || wizard.dataset.step;
  displayStep(initialStep, false);

  function updateRevision(result) { if (result.revision !== undefined) state.revision = result.revision; }
  const purposeLabels = { general: 'Vista general', detail: 'Detalle', plate: 'Placa · privada', document: 'Documento · privado' };
  function assetActionButtons(card) {
    $$('[data-asset-action]', card).forEach(button => button.addEventListener('click', async () => {
      if (!editable || button.disabled) return;
      const action = button.dataset.assetAction;
      if (action === 'delete' && !confirm('¿Eliminar este archivo del borrador?')) return;
      button.disabled = true;
      try {
        await save();
        const result = await api(`/api/archivos/${card.dataset.assetId}/accion/`, { action }); updateRevision(result);
        if (action === 'delete') card.remove();
        if (action === 'cover') { $$('.asset-cover', wizard).forEach(badge => { badge.hidden = true; }); $('.asset-cover', card).hidden = false; }
        if (action === 'up' && card.previousElementSibling) card.parentNode.insertBefore(card, card.previousElementSibling);
        if (action === 'down' && card.nextElementSibling) card.parentNode.insertBefore(card.nextElementSibling, card);
        renderAnalysisAssets(); toast(action === 'delete' ? 'Archivo eliminado del borrador.' : 'Cambio guardado.');
      } catch (error) { problem(error.message); }
      finally { button.disabled = false; }
    }));
    const purposeSelect = el('select', 'asset-purpose'); purposeSelect.setAttribute('aria-label', 'Tipo de archivo'); purposeSelect.disabled = !editable;
    for (const [value, label] of Object.entries(purposeLabels)) { const option = el('option', '', label); option.value = value; option.selected = value === card.dataset.purpose; purposeSelect.append(option); }
    purposeSelect.addEventListener('change', async () => {
      const previous = card.dataset.purpose; purposeSelect.disabled = true;
      try {
        await save(); const result = await api(`/api/archivos/${card.dataset.assetId}/accion/`, { action: 'purpose', purpose: purposeSelect.value }); updateRevision(result);
        card.dataset.purpose = purposeSelect.value;
        $('.asset-info>.small', card).textContent = purposeLabels[purposeSelect.value];
        renderAnalysisAssets(); toast('Tipo de archivo guardado. Se revisará su privacidad antes de difundirlo.');
      } catch (error) { purposeSelect.value = previous; problem(error.message); }
      finally { purposeSelect.disabled = !editable; }
    });
    $('.asset-info', card).append(purposeSelect);
  }
  $$('.asset-card', wizard).forEach(assetActionButtons);
  function appendAsset(result) {
    if ($$('.asset-card', wizard).some(card => card.dataset.assetId === String(result.id))) return;
    const card = el('article', 'asset-card'); card.dataset.assetId = result.id; card.dataset.kind = result.kind; card.dataset.purpose = result.purpose;
    const preview = el('div', 'asset-preview');
    const url = result.url || `/archivos/${result.id}/`;
    if (result.kind === 'video') { const video = el('video'); video.src = url; video.controls = true; video.preload = 'metadata'; preview.append(video); }
    else { const link = el('a'); link.href = `/archivos/${result.id}/?original=1`; link.target = '_blank'; link.rel = 'noopener'; const img = el('img'); img.src = url; img.alt = 'Fotografía de tu maquinaria'; img.loading = 'lazy'; link.append(img); preview.append(link); }
    const cover = el('span', 'tag asset-cover', 'PORTADA'); cover.hidden = !result.is_cover; preview.append(cover);
    const info = el('div', 'asset-info'); info.append(el('span', 'small', purposeLabels[result.purpose] || 'Archivo'));
    const actions = el('div', 'asset-actions');
    for (const [action, label, symbol] of [['cover', 'Usar como portada', '☆'], ['up', 'Mover antes', '←'], ['down', 'Mover después', '→'], ['delete', 'Eliminar archivo', '×']]) {
      const button = el('button', '', symbol); button.type = 'button'; button.dataset.assetAction = action; button.setAttribute('aria-label', label); button.title = label; actions.append(button);
    }
    info.append(actions); card.append(preview, info); $('#asset-grid').append(card); assetActionButtons(card);
  }
  function sendFile(file, purpose, row) {
    return new Promise((resolve, reject) => {
      const progress = $('progress', row), label = $('.upload-message', row);
      const xhr = new XMLHttpRequest(); xhr.open('POST', `${base}archivos/`); xhr.withCredentials = true;
      xhr.setRequestHeader('X-CSRFToken', csrf()); xhr.setRequestHeader('Accept', 'application/json'); xhr.timeout = 300000;
      xhr.upload.addEventListener('progress', event => {
        if (event.lengthComputable) { progress.max = event.total; progress.value = event.loaded; label.textContent = event.loaded === event.total ? 'Transferencia completa. Esperando validación del servidor…' : `${Math.round(event.loaded / event.total * 100)}% transferido`; }
      });
      xhr.addEventListener('load', () => {
        let result; try { result = JSON.parse(xhr.responseText); } catch { reject(new Error('No recibimos una respuesta válida. Tu sesión puede haber expirado.')); return; }
        if (xhr.status < 200 || xhr.status >= 300) reject(new Error(result.error || 'No se pudo recibir este archivo.'));
        else resolve(result);
      });
      xhr.addEventListener('error', () => reject(new Error('La carga se interrumpió. Conservamos el archivo en esta pestaña para que puedas reintentar.')));
      xhr.addEventListener('timeout', () => reject(new Error('La conexión tardó demasiado. Puedes reintentar este archivo.')));
      const form = new FormData(); form.append('file', file); form.append('purpose', purpose); xhr.send(form);
    });
  }
  let fileChain = Promise.resolve();
  function queueFiles(files) {
    if (!editable) return;
    for (const file of files) {
      const purpose = $('#upload-purpose').value;
      const row = el('div', 'upload-item'), top = el('div', 'upload-item-top'), name = el('strong', '', file.name), message = el('span', 'upload-message', 'En espera de carga…');
      const progress = el('progress'); progress.max = 100; progress.value = 0; progress.setAttribute('aria-label', `Carga de ${file.name}`);
      const retry = el('button', 'link-button small', 'Reintentar'); retry.type = 'button'; retry.hidden = true;
      top.append(name, retry); row.append(top, progress, message); $('#upload-queue').append(row);
      const isVideo = file.type.startsWith('video/') || /\.(mov|mp4)$/i.test(file.name);
      const maxMb = Number(isVideo ? wizard.dataset.maxVideoMb : wizard.dataset.maxImageMb);
      if (file.size > maxMb * 1024 * 1024) { message.textContent = `El archivo supera el límite de ${maxMb} MB. Elige una versión más pequeña.`; row.classList.add('error-text'); progress.hidden = true; continue; }
      async function attempt() {
        uploadCount++; retry.hidden = true; row.classList.remove('error-text'); message.textContent = 'Preparando carga…'; progress.value = 0;
        try {
          await save(); const result = await sendFile(file, purpose, row); updateRevision(result);
          appendAsset(result); message.textContent = result.processing_status === 'pending' ? 'Recibido. El servidor está preparando el archivo.' : 'Archivo recibido y verificado.';
          progress.hidden = true; renderAnalysisAssets();
        } catch (error) { message.textContent = error.message; row.classList.add('error-text'); retry.hidden = false; progress.hidden = true; }
        finally { uploadCount--; }
      }
      retry.addEventListener('click', () => { progress.hidden = false; fileChain = fileChain.then(attempt); });
      fileChain = fileChain.then(attempt);
    }
  }
  $$('[data-file-open]', wizard).forEach(button => button.addEventListener('click', () => $(`#${button.dataset.fileOpen}`).click()));
  for (const input of [$('#gallery-input'), $('#camera-input')]) input.addEventListener('change', () => { queueFiles([...input.files]); input.value = ''; });
  const drop = $('#drop-zone');
  for (const name of ['dragenter', 'dragover']) drop.addEventListener(name, event => { event.preventDefault(); drop.classList.add('drag-over'); });
  for (const name of ['dragleave', 'drop']) drop.addEventListener(name, event => { event.preventDefault(); drop.classList.remove('drag-over'); });
  drop.addEventListener('drop', event => queueFiles([...event.dataTransfer.files]));

  function renderAnalysisAssets() {
    const target = $('#analysis-assets'); const previous = new Map($$('input', target).map(input => [input.value, input.checked])); target.replaceChildren();
    for (const card of $$('.asset-card[data-kind=image]', wizard)) {
      const label = el('label', 'analysis-choice'), input = el('input'); input.type = 'checkbox'; input.value = card.dataset.assetId; input.checked = previous.has(input.value) ? previous.get(input.value) : card.dataset.purpose !== 'document'; input.disabled = !editable;
      const img = el('img'); img.src = `/archivos/${card.dataset.assetId}/`; img.alt = purposeLabels[card.dataset.purpose] || 'Fotografía';
      label.append(img, input, el('span', '', purposeLabels[card.dataset.purpose] || 'Fotografía')); target.append(label);
    }
    if (!target.children.length) target.append(el('p', 'small muted', 'Agrega al menos una imagen en el paso Fotografías o continúa con la edición manual.'));
  }
  function analysisStatus(message, status) { const box = $('#analysis-status'); box.textContent = message; box.dataset.state = status || ''; }
  let analysisStartedAt = 0;
  async function pollJob(id) {
    clearTimeout(pollTimer); activeJob = id; $('#analysis-resume').hidden = true;
    try {
      const job = await api(`/api/analisis/${id}/`);
      if (job.status === 'completed') {
        analysisStatus('Borrador preparado. Revisa las propuestas antes de incorporarlas.', 'completed'); renderResults(job.result || {}, id); $('#analyze-button').disabled = !editable; return;
      }
      if (job.status === 'failed') {
        analysisStatus(job.error || 'No se pudo completar el análisis. Tus archivos siguen guardados. Puedes editar manualmente o reintentar.', 'failed');
        $('#analyze-button').disabled = !editable; return;
      }
      analysisStatus(job.status === 'running' ? 'Análisis en curso. Puedes continuar completando tu ficha.' : 'Archivos recibidos. El análisis está en espera de procesamiento.', 'running');
      if (Date.now() - analysisStartedAt > 10 * 60 * 1000) { $('#analysis-resume').hidden = false; analysisStatus('El análisis sigue pendiente en el servidor. Puedes cerrar esta página y consultar su estado después.', 'queued'); return; }
      pollTimer = setTimeout(() => pollJob(id), 3500);
    } catch (error) {
      analysisStatus(`${error.message} Tus archivos siguen guardados.`, 'failed'); $('#analysis-resume').hidden = false; $('#analyze-button').disabled = !editable;
    }
  }
  $('#analysis-resume').addEventListener('click', () => { if (activeJob) { analysisStartedAt = Date.now(); pollJob(activeJob); } });
  $('#analyze-button').addEventListener('click', async () => {
    if (!editable) return;
    clearProblem();
    if (!$('#ai-consent').checked) return problem('Antes del análisis, confirma que autorizas el procesamiento de las imágenes seleccionadas mediante OpenAI.');
    const assetIds = $$('input:checked', $('#analysis-assets')).map(input => input.value);
    if (!assetIds.length && pendingMode === 'analysis') return problem('Selecciona al menos una fotografía para analizar. También puedes continuar con los datos manualmente.');
    if (uploadCount) return problem('Espera a que termine la carga de los archivos seleccionados.');
    $('#analyze-button').disabled = true;
    try { await save(); const result = await api(`${base}analizar/`, { consent: true, asset_ids: assetIds, mode: pendingMode }); analysisStartedAt = Date.now(); await pollJob(result.id); }
    catch (error) { analysisStatus(error.message, 'failed'); $('#analyze-button').disabled = false; }
  });
  $('#regenerate-description').addEventListener('click', () => {
    pendingMode = 'description'; $('#analyze-button').textContent = 'Preparar una nueva descripción ✧'; displayStep(2);
    analysisStatus('Revisa el consentimiento y solicita una nueva descripción. Tu texto actual se conservará hasta que aceptes la propuesta.', '');
  });
  function renderResults(result, jobId) {
    const target = $('#analysis-results'); target.replaceChildren(); target.hidden = false;
    target.append(el('p', 'eyebrow', 'PROPUESTAS PARA TU REVISIÓN'), el('h3', '', 'Elige qué incorporar.'), el('p', 'small muted', 'Ningún dato se incorpora automáticamente. Las correcciones que ya escribiste se conservarán salvo que elijas reemplazarlas.'));
    for (const [key, title] of [['warnings', 'Observaciones'], ['questions', 'Por confirmar']]) if (Array.isArray(result[key]) && result[key].length) {
      target.append(el('h4', '', title)); const list = el('ul'); result[key].forEach(item => list.append(el('li', '', typeof item === 'string' ? item : JSON.stringify(item)))); target.append(list);
    }
    const proposed = result.data || { ...(result.title ? { title: result.title } : {}), ...(result.description ? { description: result.description } : {}) };
    const current = collect();
    for (const [key, value] of Object.entries(proposed)) {
      if (value === null || value === undefined || value === '') continue;
      const row = el('div', 'suggestion-row'), checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.value = key; checkbox.id = `suggestion-${key.replace(/[^a-zA-Z0-9_-]/g, '')}`; checkbox.disabled = !editable;
      const label = el('label'); label.htmlFor = checkbox.id; label.append(el('strong', '', keyLabels[key] || key), el('p', '', typeof value === 'object' ? JSON.stringify(value) : String(value)));
      const provenance = result.provenance?.[key] || {}, old = key === 'title' ? current.title : current.data[key];
      label.append(el('small', '', `Origen: ${sourceLabels[provenance.source] || provenance.source || 'Propuesta de IA'} · ${reviewLabels[provenance.review] || 'Necesita revisión'}`));
      if (old && String(old) !== String(value)) label.append(el('small', 'error-text', `Valor que tienes: ${old}. Al seleccionar esta propuesta, lo reemplazarás.`));
      row.append(checkbox, label); target.append(row);
    }
    if (Array.isArray(result.plates) && result.plates.length) {
      const details = el('details', 'more-details'); details.append(el('summary', '', 'Comparar la transcripción de las placas'));
      result.plates.forEach(plate => {
        details.append(el('p', 'small', `Componente: ${plate.component || 'Por confirmar'} · ${reviewLabels[plate.readability] || plate.readability || 'Necesita revisión'}`), el('pre', 'plate-text', plate.transcription || 'No identificable'));
        if ($$('.asset-card', wizard).some(card => card.dataset.assetId === String(plate.asset_id))) { const link = el('a', 'text-link small', 'Ampliar la placa original ↗'); link.href = `/archivos/${plate.asset_id}/?original=1`; link.target = '_blank'; link.rel = 'noopener'; details.append(link); }
      }); target.append(details);
    }
    const apply = el('button', 'button button-navy', 'Incorporar los datos seleccionados →'); apply.type = 'button'; apply.disabled = !editable;
    apply.addEventListener('click', async () => {
      const fields = $$('.suggestion-row input:checked', target).map(input => input.value);
      if (!fields.length) return toast('Selecciona al menos una propuesta para incorporarla.', true);
      apply.disabled = true;
      try { await save(); await api(`${base}aplicar/`, { job_id: jobId, fields, revision: state.revision }); dirty = false; const url = new URL(location.href); url.searchParams.set('paso', '3'); location.assign(url); }
      catch (error) { problem(error.message); apply.disabled = false; }
    }); target.append(apply);
  }
  function renderPreview() {
    const value = collect(); $('#preview-title').textContent = value.title || 'Título por completar';
    $('#preview-description').textContent = value.data.description || 'Descripción pendiente de completar.';
    const cover = $$('.asset-card', wizard).find(card => card.dataset.kind === 'image' && card.dataset.purpose !== 'plate' && card.dataset.purpose !== 'document' && !$('.asset-cover', card).hidden) || $$('.asset-card', wizard).find(card => card.dataset.kind === 'image' && card.dataset.purpose !== 'plate' && card.dataset.purpose !== 'document');
    $('#preview-cover').replaceChildren();
    if (cover) { const image = el('img'); image.src = `/archivos/${cover.dataset.assetId}/`; image.alt = 'Vista previa de tu maquinaria'; $('#preview-cover').append(image); }
    const specs = $('#preview-specs'); specs.replaceChildren();
    for (const [label, text] of [['Marca', value.data.brand || 'No indicada'], ['Modelo', value.data.model || 'No indicado'], ['Año', value.data.year || 'No indicado'], ['Horas', value.data.hours || 'No indicadas'], ['Ubicación', value.data.location || 'Por completar'], ['Precio', value.data.price ? `${value.data.price} ${value.data.currency || 'MXN'}` : 'Consultar precio'], ['Condición declarada', value.data.condition || 'Por confirmar']]) { const row = el('div'); row.append(el('dt', '', label), el('dd', '', String(text))); specs.append(row); }
  }
  $('#submit-machine').addEventListener('click', async () => {
    if (!editable) return;
    clearProblem();
    if (!$('#advertise-consent').checked) return problem('Para enviar la solicitud debes autorizar a IMC México a revisar la maquinaria y confirmar que puedes ofrecerla.');
    const value = collect();
    if (!value.data.location) { problem('Completa la ubicación general en el paso Información antes de enviar.'); return; }
    if (!value.title || value.title === 'Mi maquinaria') { problem('Añade un título que identifique tu maquinaria en el paso Revisar datos.'); return; }
    if (!$('.asset-card[data-kind=image]', wizard)) { problem('Agrega al menos una fotografía útil antes de enviar.'); return; }
    if (uploadCount) return problem('Espera a que termine la carga de todos tus archivos.');
    const button = $('#submit-machine'); button.disabled = true; button.textContent = 'Enviando tu solicitud…';
    try { await save(); const result = await api(`${base}enviar/`, { advertise_consent: true, contact_consent: $('#contact-consent').checked }); dirty = false; location.assign(result.url || '/panel/solicitudes/'); }
    catch (error) { problem(error.message); button.disabled = false; button.textContent = 'Enviar a revisión de IMC México ↗'; }
  });

  function categoryFields() {
    const target = $('#category-fields'), source = $('#category-data');
    if (!target || !source) return;
    let categories; try { categories = JSON.parse(source.textContent); } catch { return; }
    const category = categories.find(item => String(item.id) === $('#category').value);
    target.replaceChildren();
    const fields = category?.fields || [];
    for (const item of fields) {
      const field = typeof item === 'string' ? { key: item, label: keyLabels[item] || item } : item;
      const key = field.key || field.name;
      if (!key || !/^[a-zA-Z0-9_]+$/.test(key) || $$('[data-field]', wizard).some(input => input.dataset.field === key)) continue;
      const group = el('div', 'form-field'), label = el('label', '', `${field.label || keyLabels[key] || key}${field.unit ? ` (${field.unit})` : ''} · opcional`); label.htmlFor = `extra-${key}`;
      const input = el('input'); input.id = label.htmlFor; input.dataset.field = key; input.type = field.type === 'number' ? 'number' : 'text'; input.value = state.data[key] ?? ''; input.disabled = !editable; input.maxLength = 500;
      if (input.type === 'number') input.step = 'any'; input.addEventListener('input', changed); group.append(label, input); target.append(group);
    }
  }
  $('#category')?.addEventListener('change', categoryFields); categoryFields();
  if (!editable) $$('input,textarea,select,[data-asset-action],[data-file-open],#analyze-button,#submit-machine,#regenerate-description', wizard).forEach(control => { control.disabled = true; });
  const jobSource = $('#current-job');
  if (jobSource) {
    try { const job = JSON.parse(jobSource.textContent); activeJob = job.id; analysisStartedAt = Date.now(); if (job.status !== 'failed') pollJob(job.id); }
    catch { /* An absent job does not block manual editing. */ }
  }
})();
