/* A local visibility control; never copy, persist, or transmit field values. */
(() => {
  'use strict';
  if (window.imcPasswordVisibilityInitialized) return;
  window.imcPasswordVisibilityInitialized = true;
  const enhanced = new WeakMap();
  let nextId = 0;

  function enhance(input) {
    if (!(input instanceof HTMLInputElement) || !input.parentElement) return;
    if (enhanced.has(input)) {
      enhanced.get(input).button.disabled = input.disabled;
      return;
    }
    if (input.type !== 'password' && !(input.type === 'text'
        && input.parentElement.matches('.password-field.password-field-enhanced'))) return;
    if (!input.id) {
      do { nextId += 1; input.id = `imc-password-${nextId}`; }
      while (document.getElementById(input.id) !== input);
    }
    let wrapper = input.parentElement;
    if (!wrapper.classList.contains('password-field')) {
      wrapper = document.createElement('span');
      wrapper.className = 'password-field';
      input.before(wrapper);
      wrapper.append(input);
    }
    // A formset can clone enhanced markup; DOM listeners are not cloned.
    wrapper.querySelectorAll('.password-visibility-toggle').forEach(button => button.remove());
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'password-visibility-toggle';
    button.setAttribute('aria-controls', input.id);
    button.disabled = input.disabled;
    button.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/><path class="password-eye-slash" d="m3 3 18 18"/></svg>';
    const caption = document.createElement('span');
    caption.className = 'password-visibility-caption';
    caption.setAttribute('aria-hidden', 'true');
    button.append(caption);

    function setVisible(visible) {
      let start = null, end = null, direction = 'none';
      try { start = input.selectionStart; end = input.selectionEnd; direction = input.selectionDirection; }
      catch (_) { /* A restricted selection API must not prevent the visibility control. */ }
      input.type = visible ? 'text' : 'password';
      if (start !== null && end !== null) {
        try { input.setSelectionRange(start, end, direction || 'none'); }
        catch (_) { /* Some password managers temporarily restrict selection. */ }
      }
      const label = visible ? 'Ocultar contraseña' : 'Mostrar contraseña';
      button.setAttribute('aria-pressed', String(visible));
      button.setAttribute('aria-label', label);
      button.title = label;
      caption.textContent = visible ? 'Ocultar' : 'Mostrar';
    }

    button.addEventListener('pointerdown', event => {
      // A pointer click keeps the insertion point when the user was typing.
      // Keyboard users retain the normal focusable button behavior.
      if (document.activeElement === input) event.preventDefault();
    });
    button.addEventListener('click', () => setVisible(input.type === 'password'));
    enhanced.set(input, { button });
    setVisible(false);
    wrapper.append(button);
    wrapper.classList.add('password-field-enhanced');
    if (input.form) {
      input.form.addEventListener('reset', () => setVisible(false));
      input.form.addEventListener('submit', () => setVisible(false));
    }
  }

  function scan(node) {
    if (!(node instanceof Element) && node !== document) return;
    if (node instanceof HTMLInputElement) enhance(node);
    node.querySelectorAll('input[type="password"], .password-field.password-field-enhanced>input[type="text"]').forEach(enhance);
  }

  function start() {
    scan(document);
    new MutationObserver(records => {
      for (const record of records) {
        if (record.type === 'attributes') enhance(record.target);
        else record.addedNodes.forEach(scan);
      }
    }).observe(document.body, { childList: true, subtree: true, attributes: true,
                                attributeFilter: ['type', 'disabled'] });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
