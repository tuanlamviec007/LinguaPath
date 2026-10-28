const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/motion.js', 'utf8');

function setup({ reduced = false, stored = 'false', blocked = false } = {}) {
  const listeners = {}, windowListeners = {}, classes = new Set(), nodes = [], timers = new Map();
  const button = () => ({hidden:true, disabled:false, attrs:{}, setAttribute(k,v){this.attrs[k]=v;}, addEventListener(k,fn){this[k]=fn;}});
  const toggle = button(), celebrate = button();
  celebrate.getBoundingClientRect = () => ({left:100, top:100, width:100, height:40, bottom:140});
  const preference = {matches:reduced, addEventListener(_, fn){this.change=fn;}};
  let clock = 10000, saved, nextTimer = 0;
  const document = {hidden:false, documentElement:{classList:{toggle(k,on){if(on)classes.add(k);else classes.delete(k);}}},
    querySelectorAll(s){return s === '[data-motion-toggle]' ? [toggle] : [celebrate];},
    addEventListener(k,fn){listeners[k]=fn;},
    createElement(){return {style:{setProperty(){}},setAttribute(){},remove(){this.removed=true;}};},
    body:{appendChild(node){nodes.push(node);}}};
  const window = {innerWidth:400, innerHeight:800, matchMedia:()=>preference,
    addEventListener(k,fn){windowListeners[k]=fn;},
    setTimeout(fn){timers.set(++nextTimer,fn);return nextTimer;},clearTimeout(id){timers.delete(id);},
    localStorage:{getItem(){if(blocked)throw Error('blocked');return stored;},setItem(_,v){if(blocked)throw Error('blocked');saved=v;}}};
  vm.runInNewContext(source,{window,document,Date:{now:()=>clock}});
  return {toggle,celebrate,preference,classes,nodes,timers,listeners,windowListeners,document,
    get saved(){return saved;},advance(){clock+=2000;},cleanup(){[...timers.values()].forEach(fn=>fn());}};
}
test('saved opt-out suppresses celebrations and can be reversed', () => {
  const s=setup({stored:'true'});assert.ok(s.classes.has('motion-paused'));
  s.celebrate.click();assert.equal(s.nodes.length,0);s.toggle.click();assert.ok(!s.classes.has('motion-paused'));
  s.celebrate.click();assert.equal(s.nodes.length,16);
});
test('blocked storage still permits a session opt-out', () => {
  const s=setup({blocked:true});s.toggle.click();assert.ok(s.classes.has('motion-paused'));
  s.celebrate.click();assert.equal(s.nodes.length,0);s.toggle.click();s.celebrate.click();assert.equal(s.nodes.length,16);
});
test('system reduced motion overrides opt-in and clears active particles immediately', () => {
  const s=setup();s.celebrate.click();assert.equal(s.nodes.length,16);
  s.preference.matches=true;s.preference.change();assert.ok(s.nodes.every(n=>n.removed));
  assert.equal(s.toggle.disabled,true);assert.equal(s.celebrate.hidden,true);
  s.advance();s.celebrate.click();assert.equal(s.nodes.length,16);
  s.preference.matches=false;s.preference.change();assert.equal(s.toggle.disabled,false);
});
test('repeated celebrations are bounded and temporary, and backgrounding removes them', () => {
  const s=setup();s.celebrate.click();s.celebrate.click();assert.equal(s.nodes.length,16);
  s.cleanup();assert.ok(s.nodes.every(n=>n.removed));s.advance();s.celebrate.click();
  assert.equal(s.nodes.filter(n=>!n.removed).length,16);
  s.document.hidden=true;s.listeners.visibilitychange();assert.equal(s.nodes.filter(n=>!n.removed).length,0);
  s.advance();s.celebrate.click();assert.equal(s.nodes.length,32);
});
test('pausing synchronizes across tabs and cleans up when leaving the page', () => {
  const s=setup();s.toggle.click();assert.equal(s.saved,'true');assert.equal(s.toggle.attrs['aria-pressed'],'true');
  s.windowListeners.storage({key:'linguapath.motion.paused',newValue:'false'});
  assert.ok(!s.classes.has('motion-paused'));s.celebrate.click();s.windowListeners.pagehide();assert.ok(s.nodes.every(n=>n.removed));
});
