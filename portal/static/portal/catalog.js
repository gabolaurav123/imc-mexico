'use strict';
(() => {
  const brand = document.getElementById('brand');
  const model = document.getElementById('model');
  const category = document.getElementById('category');
  const source = document.getElementById('catalog-model-data');
  const target = document.getElementById('catalog-models');
  const brandList = document.getElementById('catalog-brands');
  if (!brand || !model || !category || !source || !target) return;

  let initialEntries = [];
  try {
    const parsed = JSON.parse(source.textContent || '[]');
    if (Array.isArray(parsed)) initialEntries = parsed;
  } catch { /* Editable free-text fields still work without suggestions. */ }

  const discoveryUrl = target.dataset?.discoveryUrl || source.dataset?.discoveryUrl
    || target.getAttribute?.('data-discovery-url') || source.getAttribute?.('data-discovery-url') || '';
  const normalized = value => String(value || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase('es-MX');
  const cache = new Map();
  let controller = null;
  let requestNumber = 0;
  let timer = null;

  function setSuggestions(entries) {
    target.replaceChildren();
    const seen = new Set();
    for (const item of entries) {
      const name = item?.model_name || item?.name;
      if (typeof name !== 'string' || !name.trim()) continue;
      const key = normalized(name);
      if (seen.has(key)) continue;
      seen.add(key);
      const option = document.createElement('option');
      option.value = name;
      option.label = item.brand_name || item.brand || brand.value || '';
      target.append(option);
    }
  }

  function initialSuggestions() {
    const selectedBrand = normalized(brand.value);
    const selectedCategory = String(category.value || '');
    return initialEntries.filter(item => item && typeof item.name === 'string'
      && (!selectedBrand || normalized(item.brand) === selectedBrand)
      && (!selectedCategory || item.category == null || String(item.category) === selectedCategory));
  }

  function selectedBrandId() {
    const value = normalized(brand.value);
    if (!value || !brandList?.children) return '';
    for (const option of brandList.children) {
      if (normalized(option.value) === value && option.dataset?.brandId) return option.dataset.brandId;
    }
    return '';
  }

  function discovery(stage, params) {
    if (!discoveryUrl) return Promise.resolve(null);
    const query = new URLSearchParams({ stage, ...params });
    const url = `${discoveryUrl}${discoveryUrl.includes('?') ? '&' : '?'}${query}`;
    if (cache.has(url)) return Promise.resolve(cache.get(url));
    controller?.abort();
    controller = new AbortController();
    return fetch(url, { credentials: 'same-origin', signal: controller.signal, headers: { Accept: 'application/json' } })
      .then(response => response.ok ? response.json() : null)
      .then(result => {
        if (result) cache.set(url, result);
        return result;
      })
      .catch(error => error?.name === 'AbortError' ? null : null);
  }

  async function resolveBrand(categoryId, expectedRequest) {
    const typed = brand.value.trim();
    if (!typed || !categoryId) return '';
    const known = selectedBrandId();
    if (known) return known;
    const response = await discovery('brands', { category: categoryId, q: typed });
    if (expectedRequest !== requestNumber || !response?.items) return '';
    const exact = response.items.find(item => normalized(item.label || item.brand_name) === normalized(typed));
    return exact ? String(exact.brand_id || exact.id || '') : '';
  }

  async function updateSuggestions() {
    const currentRequest = ++requestNumber;
    const categoryId = String(category.value || '');
    setSuggestions(initialSuggestions());
    if (!discoveryUrl || !categoryId || !brand.value.trim()) return;
    const brandId = await resolveBrand(categoryId, currentRequest);
    if (!brandId || currentRequest !== requestNumber) return;
    const response = await discovery('models', { category: categoryId, brand: brandId, q: model.value.trim() });
    if (currentRequest !== requestNumber || !response?.items) return;
    // Suggestions guide a choice only. Never replace a free-text identity or
    // apply a catalogue technical profile from this field listener.
    setSuggestions(response.items);
  }

  function scheduleSuggestions() {
    clearTimeout(timer);
    controller?.abort();
    timer = setTimeout(updateSuggestions, 160);
  }

  brand.addEventListener('input', scheduleSuggestions);
  brand.addEventListener('change', scheduleSuggestions);
  model.addEventListener('input', scheduleSuggestions);
  category.addEventListener('change', scheduleSuggestions);
  updateSuggestions();
})();
