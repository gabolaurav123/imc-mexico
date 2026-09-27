'use strict';
(() => {
  const modal = document.getElementById('similar-machines-modal');
  if (!modal || modal.dataset.initialized) return;
  modal.dataset.initialized = 'true';
  const closeButton = modal.querySelector('[data-close-similar-machines]');
  let active = false, previousFocus = null, backdrop = null;
  let inertElements = [];
  const focusable = () => [...modal.querySelectorAll('button, a[href], [tabindex]:not([tabindex="-1"])')]
    .filter(node => !node.disabled && !node.closest('[hidden]'));

  const restore = () => {
    if (!active) return;
    active = false;
    backdrop?.remove();
    backdrop = null;
    inertElements.forEach(([element, wasInert]) => { element.inert = wasInert; });
    inertElements = [];
    const target = previousFocus?.isConnected && previousFocus !== document.body
      ? previousFocus : document.getElementById('sheet-title');
    target?.focus({preventScroll: true});
  };
  const dismiss = () => {
    if (!active) return;
    if (typeof modal.close === 'function') modal.close();
    else modal.removeAttribute('open');
    restore();
  };
  const open = () => {
    if (active || document.querySelector('dialog[open]')) return;
    previousFocus = document.activeElement;
    active = true;
    if (typeof modal.showModal === 'function') modal.showModal();
    else {
      // Keep older browsers usable without changing or hiding the sheet data.
      modal.classList.add('similar-machines-modal--fallback');
      backdrop = document.createElement('div');
      backdrop.className = 'similar-machines-modal-backdrop';
      backdrop.setAttribute('aria-hidden', 'true');
      backdrop.addEventListener('click', dismiss);
      document.body.append(backdrop);
      for (let child = modal, parent = child.parentElement; parent; child = parent, parent = parent.parentElement) {
        [...parent.children].filter(element => element !== child && element !== backdrop).forEach(element => {
          inertElements.push([element, Boolean(element.inert)]);
          element.inert = true;
        });
        if (parent === document.body) break;
      }
      modal.setAttribute('open', '');
    }
    closeButton.focus({preventScroll: true});
  };

  modal.querySelectorAll('[data-close-similar-machines]').forEach(button => button.addEventListener('click', dismiss));
  modal.addEventListener('click', event => { if (event.target === modal) dismiss(); });
  modal.addEventListener('cancel', event => { event.preventDefault(); dismiss(); });
  modal.addEventListener('close', restore);
  modal.addEventListener('keydown', event => {
    if (!active) return;
    if (event.key === 'Escape') { event.preventDefault(); dismiss(); return; }
    if (event.key !== 'Tab') return;
    const controls = focusable(), first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  document.addEventListener('focusin', event => {
    if (active && !modal.contains(event.target)) closeButton.focus({preventScroll: true});
  });
  // The sharing dialog owns its own lifecycle and remains available after this invitation.
  document.addEventListener('click', event => {
    if (event.target.closest?.('[data-share-sheet], [data-share-machine-id]')) dismiss();
  }, true);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', open, {once: true});
  else open();
})();
