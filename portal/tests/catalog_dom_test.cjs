// Run with: node portal/tests/catalog_dom_test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Field {
  constructor(value = '') { this.value = value; this.children = []; this.listeners = {}; this.dataset = {}; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  dispatch(name) { for (const callback of this.listeners[name] || []) callback(); }
  replaceChildren() { this.children = []; }
  append(child) { this.children.push(child); }
}
const script = fs.readFileSync(path.join(__dirname, '../static/portal/catalog.js'), 'utf8');
const options = fields => fields['catalog-models'].children.map(item => item.value);
const immediateTimer = callback => { callback(); return 1; };

function fieldsFor(entries, { url = '' } = {}) {
  const fields = {
    brand: new Field('  CATERPILLAR '), model: new Field('Modelo declarado independiente'),
    category: new Field('1'), 'catalog-brands': new Field(), 'catalog-models': new Field(), 'catalog-model-data': new Field(),
  };
  fields['catalog-model-data'].textContent = JSON.stringify(entries);
  fields['catalog-models'].dataset.discoveryUrl = url;
  return fields;
}

function load(fields, extras = {}) {
  const document = { getElementById: id => fields[id], createElement: () => new Field() };
  vm.runInNewContext(script, { document, clearTimeout() {}, setTimeout: immediateTimer, ...extras });
}

// The bounded server-rendered list remains a graceful fallback for a failed or
// unavailable discovery request. It also keeps manually written values intact.
const fallback = fieldsFor([
  { name: '320DL', brand: 'Caterpillar', category: 1 },
  { name: 'E450AJ', brand: 'JLG', category: 2 },
  { name: 'A77TE93', brand: 'Altec', category: 3 },
]);
load(fallback);
assert.deepEqual(options(fallback), ['320DL']);
assert.equal(fallback.model.value, 'Modelo declarado independiente');
fallback.brand.value = 'JLG'; fallback.brand.dispatch('input');
assert.deepEqual(options(fallback), []); // Category remains the selected excavator category.
fallback.category.value = '2'; fallback.category.dispatch('change');
assert.deepEqual(options(fallback), ['E450AJ']);
assert.equal(fallback.model.value, 'Modelo declarado independiente');
fallback.brand.value = 'Marca escrita libremente'; fallback.brand.dispatch('change');
assert.deepEqual(options(fallback), []);
assert.equal(fallback.model.value, 'Modelo declarado independiente');
fallback.brand.value = ''; fallback.category.value = ''; fallback.category.dispatch('change');
assert.deepEqual(options(fallback), ['320DL', 'E450AJ', 'A77TE93']);

async function asyncDiscoveryTest() {
  const asyncFields = fieldsFor([], { url: '/api/maquinarias/catalogo/descubrir/' });
  asyncFields.brand.value = 'Caterpillar';
  asyncFields.model.value = '320';
  const cat = new Field('Caterpillar'); cat.dataset.brandId = '12'; asyncFields['catalog-brands'].append(cat);
  const requested = [];
  const fetch = async (url, options) => {
    requested.push({ url, options });
    return { ok: true, json: async () => ({ items: [{ model_name: '320DL', brand_name: 'Caterpillar' }] }) };
  };
  load(asyncFields, { fetch, URLSearchParams, AbortController });
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(options(asyncFields), ['320DL']);
  assert.match(requested[0].url, /stage=models/);
  assert.match(requested[0].url, /category=1/);
  assert.match(requested[0].url, /brand=12/);
  assert.match(requested[0].url, /q=320/);
  assert.equal(asyncFields.brand.value, 'Caterpillar');
  assert.equal(asyncFields.model.value, '320');

  // A repeated lookup for the same identity consumes the cached response.
  asyncFields.model.dispatch('input');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requested.length, 1);
}

asyncDiscoveryTest().then(() => {
  console.log('Catalog DOM PASS: lazy lookup, bounded fallback, cache, and free text are preserved.');
}).catch(error => { console.error(error); process.exitCode = 1; });
