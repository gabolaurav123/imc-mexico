'use strict';
(() => {
  const brand = document.getElementById('brand');
  const model = document.getElementById('model');
  const category = document.getElementById('category');
  const source = document.getElementById('catalog-model-data');
  const target = document.getElementById('catalog-models');
  if (!brand || !model || !category || !source || !target) return;
  let entries;
  try { entries = JSON.parse(source.textContent); } catch { return; }
  if (!Array.isArray(entries)) return;
  const normalized = value => String(value || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase('es-MX');
  function updateSuggestions() {
    const selectedBrand = normalized(brand.value);
    const selectedCategory = category.value;
    target.replaceChildren();
    const seen = new Set();
    for (const item of entries) {
      if (!item || typeof item.name !== 'string' || typeof item.brand !== 'string') continue;
      if (selectedBrand && normalized(item.brand) !== selectedBrand) continue;
      if (selectedCategory && item.category != null && String(item.category) !== selectedCategory) continue;
      const key = normalized(item.name);
      if (seen.has(key)) continue;
      seen.add(key);
      const option = document.createElement('option');
      option.value = item.name;
      option.label = item.brand;
      target.append(option);
    }
    // Suggestions never replace a declared model, even when the brand or category changes.
  }
  brand.addEventListener('input', updateSuggestions);
  brand.addEventListener('change', updateSuggestions);
  category.addEventListener('change', updateSuggestions);
  updateSuggestions();
})();
