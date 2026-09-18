'use strict';
(() => {
  const root = document.querySelector('[data-category-picker]');
  const source = document.getElementById('category-data');
  if (!root || !source) return;
  const input = document.getElementById('start-category-search');
  const value = document.getElementById('start-category');
  const results = document.getElementById('start-category-results');
  const selection = document.getElementById('start-category-selection');
  const unsure = root.querySelector('[data-category-unsure]');
  let categories;
  try { categories = JSON.parse(source.textContent); } catch { return; }
  if (!Array.isArray(categories)) return;
  const normalize = text => String(text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es-MX').replace(/[^a-z0-9]+/g, ' ').trim();
  const terms = item => [item.name, item.slug, ...(Array.isArray(item.aliases) ? item.aliases : [])].map(normalize).filter(Boolean);
  const score = (item, query) => {
    if (!query) return 0;
    const words = query.split(' ').filter(Boolean);
    return Math.max(...terms(item).map(term => {
      if (term === query) return 100;
      if (term.startsWith(query)) return 80;
      if (term.includes(query)) return 60;
      return words.every(word => term.includes(word)) ? 40 : 0;
    }), 0);
  };
  function setSelected(item, message) {
    value.value = item ? String(item.id) : '';
    input.value = item ? item.name : '';
    selection.textContent = message || (item ? `Seleccionaste: ${item.name}.` : 'No seleccionaste un tipo; podremos sugerirlo con las fotografías.');
    results.replaceChildren(); results.hidden = true; input.setAttribute('aria-expanded', 'false');
  }
  function show() {
    const query = normalize(input.value);
    value.value = '';
    selection.textContent = '';
    if (!query) { results.replaceChildren(); results.hidden = true; input.setAttribute('aria-expanded', 'false'); return; }
    let matches = categories.map(item => ({item, score:score(item, query)})).filter(item => item.score);
    // An exact catalogue term is decisive. This keeps "excavadora" from
    // presenting a backhoe merely because its longer name contains the word.
    if (matches.some(match => match.score === 100)) matches = matches.filter(match => match.score === 100);
    matches = matches.sort((a,b) => b.score - a.score || String(a.item.name).localeCompare(String(b.item.name),'es-MX')).slice(0,7);
    results.replaceChildren();
    for (const {item} of matches) {
      const option = document.createElement('button'); option.type = 'button'; option.className = 'category-result'; option.setAttribute('role','option'); option.textContent = item.name;
      option.addEventListener('click', () => setSelected(item)); results.append(option);
    }
    if (!matches.length) results.append(Object.assign(document.createElement('p'), {className:'small muted category-no-results', textContent:'No vemos una coincidencia exacta. Puedes continuar y la identificaremos con fotos.'}));
    results.hidden = false; input.setAttribute('aria-expanded', 'true');
  }
  input.addEventListener('input', show);
  input.addEventListener('focus', () => { if (input.value.trim()) show(); });
  input.addEventListener('keydown', event => { if (event.key === 'Escape') { results.hidden = true; input.setAttribute('aria-expanded','false'); } });
  document.addEventListener('click', event => { if (!root.contains(event.target)) { results.hidden = true; input.setAttribute('aria-expanded','false'); } });
  unsure?.addEventListener('click', () => setSelected(null));
})();
