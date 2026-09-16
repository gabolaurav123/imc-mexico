/* Private, tab-local notification state. Opening an alert never marks it read. */
(() => {
  'use strict';
  const bell = document.getElementById('notification-bell');
  if (!bell || bell.dataset.initialized) return;
  bell.dataset.initialized = 'true';
  const badge = document.getElementById('notification-badge');
  const banner = document.getElementById('notification-pending-banner');
  const title = document.getElementById('notification-pending-title');
  const subject = document.getElementById('notification-pending-subject');
  const pendingLink = document.getElementById('notification-pending-link');
  const arrival = document.getElementById('notification-arrival');
  const arrivalSubject = document.getElementById('notification-arrival-subject');
  const arrivalLink = document.getElementById('notification-arrival-link');
  const seen = new Set(bell.dataset.latestId ? [bell.dataset.latestId] : []);
  let highestId = /^\d+$/.test(bell.dataset.latestId || '') ? bell.dataset.latestId : '0';
  const newerId = id => id.length > highestId.length || (id.length === highestId.length && id > highestId);
  const viewer = String(bell.dataset.viewer || '');
  let timer, arrivalTimer, controller, stopped = false, inFlight = false, readBusy = false, failures = 0;
  let dismissedLatest = null, currentLatest = String(bell.dataset.latestId || '');
  let mutationVersion = 0;
  const countLabel = count => count === 1 ? 'Tienes 1 aviso sin leer' : `Tienes ${count} avisos sin leer`;

  function safeDetail(value) {
    try {
      const url = new URL(value, location.origin);
      return url.origin === location.origin && /^\/panel\/notificaciones\/\d+\/$/.test(url.pathname)
        && !url.search && !url.hash && !url.username && !url.password ? url.pathname : '/panel/notificaciones/';
    } catch (_) { return '/panel/notificaciones/'; }
  }
  function clearArrival() { clearTimeout(arrivalTimer); arrival.hidden = true; }
  function stop(clear = false) {
    stopped = true; clearTimeout(timer); controller?.abort(); clearArrival();
    if (clear) { badge.hidden = true; badge.textContent = ''; banner.hidden = true; subject.textContent = ''; arrivalSubject.textContent = ''; bell.setAttribute('aria-label', 'Notificaciones'); }
  }
  function accept(result, announce) {
    if (!result || String(result.viewer_id) !== viewer) { stop(true); return false; }
    const count = Number(result.unread_count);
    if (!Number.isSafeInteger(count) || count < 0) return false;
    badge.textContent = count > 99 ? '99+' : String(count); badge.hidden = count === 0;
    bell.dataset.unreadCount = String(count); bell.setAttribute('aria-label', `Notificaciones: ${count} sin leer`);
    title.textContent = countLabel(count);
    const latest = result.latest && typeof result.latest === 'object' ? result.latest : null;
    const id = latest && /^\d+$/.test(String(latest.id)) ? String(latest.id) : '';
    const text = latest && typeof latest.subject === 'string' ? latest.subject : '';
    const url = id ? safeDetail(latest.url) : '/panel/notificaciones/';
    currentLatest = id; subject.textContent = text; pendingLink.href = url;
    banner.hidden = count === 0 || dismissedLatest === id;
    if (!count) clearArrival();
    if (id && newerId(id) && !seen.has(id) && announce && !document.hidden) {
      highestId = id; seen.add(id);
      // Bounded in-memory deduplication; no account data is persisted in storage.
      if (seen.size > 100) seen.delete(seen.values().next().value);
      arrivalSubject.textContent = text; arrivalLink.href = url; arrival.hidden = false;
      clearTimeout(arrivalTimer); arrivalTimer = setTimeout(clearArrival, 12000);
    } else if (id && !announce) { seen.add(id); if (newerId(id)) highestId = id; }
    return true;
  }
  function schedule(delay = 30000) {
    clearTimeout(timer);
    if (!stopped && !document.hidden) timer = setTimeout(poll, delay);
  }
  async function poll() {
    if (stopped || inFlight || readBusy || document.hidden) return;
    inFlight = true; controller = new AbortController(); const version = mutationVersion;
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller?.abort(); }, 15000);
    try {
      const response = await fetch(bell.dataset.summaryUrl, {credentials:'same-origin',cache:'no-store',
        headers:{Accept:'application/json'},signal:controller.signal});
      if ([401,403].includes(response.status) || response.redirected) { stop(true); return; }
      if (!response.ok) throw new Error('Summary unavailable');
      if (!(response.headers.get('content-type') || '').includes('application/json')) { stop(true); return; }
      const result = await response.json();
      // A summary started before a read action cannot restore a stale badge.
      if (version === mutationVersion && !accept(result, true) && !stopped) throw new Error('Invalid summary');
      failures = 0;
    } catch (error) { if (timedOut || error.name !== 'AbortError') failures = Math.min(failures + 1, 4); }
    finally { clearTimeout(timeout); inFlight = false; controller = null; schedule(Math.min(30000 * 2 ** failures, 300000)); }
  }
  document.addEventListener('visibilitychange', () => {
    clearTimeout(timer);
    if (document.hidden) { controller?.abort(); clearArrival(); }
    else schedule(0);
  });
  window.addEventListener('pagehide', () => { clearTimeout(timer); controller?.abort(); clearArrival(); });
  window.addEventListener('pageshow', () => schedule());
  document.querySelectorAll('[data-dismiss-notification]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.dismissNotification === 'banner') { dismissedLatest = currentLatest; banner.hidden = true; }
    else clearArrival();
  }));
  document.querySelectorAll('form[data-notification-read]').forEach(form => {
    let busy = false;
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (busy || readBusy || stopped) return;
      const button = form.querySelector('button[type=submit]'), status = form.querySelector('.notification-read-status');
      busy = readBusy = true; button.disabled = true; status.hidden = true; mutationVersion++; controller?.abort();
      try {
        const csrf = form.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
        const response = await fetch(form.action, {method:'POST',credentials:'same-origin',cache:'no-store',
          headers:{Accept:'application/json','X-CSRFToken':csrf},body:new FormData(form)});
        if ([401,403].includes(response.status) || response.redirected) { stop(true); throw new Error('Tu sesión necesita renovarse. Vuelve a iniciar sesión para marcar el aviso.'); }
        if (!response.ok || !(response.headers.get('content-type') || '').includes('application/json')) throw new Error('No se pudo marcar como leído. Puedes reintentar.');
        const result = await response.json(); mutationVersion++;
        if (!accept(result, true)) throw new Error('Tu sesión cambió. Recarga para consultar tus avisos.');
        const cards = form.hasAttribute('data-mark-all') ? document.querySelectorAll('[data-notification-item]') : [form.closest('[data-notification-item]')];
        cards.forEach(card => { if (!card) return; card.classList.remove('is-unread'); card.querySelector('.notification-read-state').textContent = 'Leída'; card.querySelectorAll('[data-notification-read]').forEach(item => { item.hidden = true; }); });
        if (form.hasAttribute('data-mark-all')) form.hidden = true;
        if (!result.unread_count) clearArrival();
      } catch (error) { status.textContent = error.message; status.dataset.error = 'true'; status.hidden = false; }
      finally { busy = readBusy = false; button.disabled = false; schedule(); }
    });
  });
  schedule();
})();
