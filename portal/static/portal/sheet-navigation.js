'use strict';
(() => {
  document.querySelectorAll('[data-sheet-back]').forEach(link => {
    link.addEventListener('click', event => {
      if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      // Direct links and unrelated browser history keep the local fallback.
      const previous = document.referrer && new URL(document.referrer);
      if (window.history.length <= 1 || !previous || previous.origin !== window.location.origin || previous.href === window.location.href) return;
      event.preventDefault();
      window.history.back();
    });
  });
})();
