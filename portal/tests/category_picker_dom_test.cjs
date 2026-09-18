const {JSDOM}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict'),path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../static/portal/category-picker.js'),'utf8');
const catalogue=[
  {id:1,name:'Excavadoras',slug:'excavadoras',aliases:['excavadora','excavadora hidráulica'],fields:[],profile:{}},
  {id:2,name:'Retroexcavadoras cargadoras',slug:'retroexcavadoras',aliases:['retroexcavadora','backhoe'],fields:[],profile:{}},
  {id:3,name:'Grúas',slug:'gruas',aliases:['grúa','crane'],fields:[],profile:{}},
  {id:4,name:'Dragalinas',slug:'dragalinas',aliases:['dragalina','dragline'],fields:[],profile:{}},
];
const dom=new JSDOM(`<!doctype html><form><div data-category-picker><input id="start-category-search"><input id="start-category" name="category" type="hidden"><span id="start-category-help"></span><div id="start-category-results" hidden></div><p id="start-category-selection"></p><button type="button" data-category-unsure>Seguro no</button></div></form><script id="category-data" type="application/json">${JSON.stringify(catalogue)}</script>`,{runScripts:'outside-only'});
const {window}=dom,{document}=window;window.eval(script);
const search=document.getElementById('start-category-search'),results=document.getElementById('start-category-results'),value=document.getElementById('start-category');
function query(text){search.value=text;search.dispatchEvent(new window.Event('input',{bubbles:true}));return [...results.querySelectorAll('button')].map(node=>node.textContent);}
assert.deepEqual(query('excavadora'),['Excavadoras'],'exact excavator alias selects its own category');
assert.deepEqual(query('backhoe'),['Retroexcavadoras cargadoras'],'backhoe never becomes an excavator');
assert.deepEqual(query('crane'),['Grúas'],'crane never becomes an excavator');
assert.deepEqual(query('dragline'),['Dragalinas'],'dragline never becomes an excavator');
query('excavadora');results.querySelector('button').click();assert.equal(value.value,'1');assert.match(document.getElementById('start-category-selection').textContent,/Excavadoras/);
document.querySelector('[data-category-unsure]').click();assert.equal(value.value,'');assert.match(document.getElementById('start-category-selection').textContent,/No seleccionaste/);
dom.window.close();console.log('Category picker DOM PASS: local aliases, category boundaries and no-selection route.');
