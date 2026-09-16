// Run with: node portal/tests/catalog_dom_test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Field {
  constructor(value = '') { this.value = value; this.children = []; this.listeners = {}; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  dispatch(name) { for (const callback of this.listeners[name] || []) callback(); }
  replaceChildren() { this.children = []; }
  append(child) { this.children.push(child); }
}
const fields = {
  brand: new Field('  CATERPILLAR '), model: new Field('Modelo declarado independiente'),
  category: new Field('1'), 'catalog-models': new Field(), 'catalog-model-data': new Field(),
};
fields['catalog-model-data'].textContent = JSON.stringify([
  { name: '320DL', brand: 'Caterpillar', category: 1 },
  { name: 'E450AJ', brand: 'JLG', category: 2 },
  { name: 'A77TE93', brand: 'Altec', category: 3 },
]);
const document = { getElementById: id => fields[id], createElement: () => new Field() };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/portal/catalog.js'), 'utf8'), { document });
const options = () => fields['catalog-models'].children.map(item => item.value);
assert.deepEqual(options(), ['320DL']);
assert.equal(fields.model.value, 'Modelo declarado independiente');
fields.brand.value = 'JLG'; fields.brand.dispatch('input');
assert.deepEqual(options(), []); // Category remains the selected excavator category.
fields.category.value = '2'; fields.category.dispatch('change');
assert.deepEqual(options(), ['E450AJ']);
assert.equal(fields.model.value, 'Modelo declarado independiente');
fields.brand.value = 'Marca escrita libremente'; fields.brand.dispatch('change');
assert.deepEqual(options(), []);
assert.equal(fields.model.value, 'Modelo declarado independiente');
assert.equal(fields.brand.value, 'Marca escrita libremente');
fields.brand.value = ''; fields.category.value = ''; fields.category.dispatch('change');
assert.deepEqual(options(), ['320DL', 'E450AJ', 'A77TE93']);
assert.equal(fields.model.value, 'Modelo declarado independiente');
console.log('Catalog DOM PASS: brand/category filters, free text and model preserved; no technical autofill.');
