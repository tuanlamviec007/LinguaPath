const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync('static/js/quiz-hub.js', 'utf8');
class Element {
  constructor(dataset = {}) { this.dataset = dataset; this.listeners = {}; this.attrs = {}; this.value = ''; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  emit(type) { for (const fn of this.listeners[type] || []) fn(); }
  setAttribute(key, value) { this.attrs[key] = value; }
}
function setup({path = '/learning/quiz/', sourceValues = ['all', 'saved', 'weak'], missingForm = false} = {}) {
  const form = new Element({quizHubUrl: path});
  const links = sourceValues.map((source) => new Element({quizSource: source}));
  links.forEach((link) => { link.attrs.href = '?source=fallback'; });
  const mode = new Element(), count = new Element(), level = new Element(), topic = new Element();
  mode.value = 'meaning'; count.value = '10';
  form.querySelectorAll = () => links;
  form.querySelector = (selector) => ({
    'input[name="mode"]:checked': mode, 'input[name="count"]:checked': count,
    '[name="level"]': level, '[name="topic"]': topic,
  })[selector] || null;
  const win = new Element(); win.location = {origin: 'https://linguapath.test'};
  vm.runInNewContext(script, {document: {querySelector: () => missingForm ? null : form}, window: win, URL, URLSearchParams});
  return {form, links, mode, count, level, topic, win};
}
function query(link) { return new URL(link.attrs.href, 'https://linguapath.test').searchParams; }

test('initial source links retain mode, count and construct local GET destinations', () => {
  const ui = setup();
  for (const [index, source] of ['all', 'saved', 'weak'].entries()) {
    assert.equal(ui.links[index].attrs.href.startsWith('/learning/quiz/?'), true);
    assert.deepEqual([...query(ui.links[index])], [['source', source], ['mode', 'meaning'], ['count', '10']]);
  }
});

test('mode, level, Unicode topic and count remain selected across every source link', () => {
  const ui = setup();
  ui.mode.value = 'recall'; ui.level.value = 'B2'; ui.topic.value = 'Office & lịch họp / #1'; ui.count.value = '15';
  ui.form.emit('change');
  for (const link of ui.links) {
    assert.equal(query(link).get('mode'), 'recall'); assert.equal(query(link).get('level'), 'B2');
    assert.equal(query(link).get('topic'), 'Office & lịch họp / #1'); assert.equal(query(link).get('count'), '15');
    assert.equal(query(link).get('source'), link.dataset.quizSource);
  }
});

test('meaning and all supported lengths replace earlier selections without stale values', () => {
  const ui = setup(); ui.mode.value = 'recall'; ui.level.value = 'A2'; ui.topic.value = 'Travel'; ui.form.emit('input');
  ui.mode.value = 'meaning'; ui.level.value = ''; ui.topic.value = '';
  for (const size of ['5', '10', '15']) {
    ui.count.value = size; ui.form.emit('change');
    const state = query(ui.links[1]); assert.equal(state.get('count'), size); assert.equal(state.get('mode'), 'meaning');
    assert.equal(state.has('level'), false); assert.equal(state.has('topic'), false);
  }
});

test('browser restoration refreshes source destinations from restored controls', () => {
  const ui = setup(); ui.mode.value = 'recall'; ui.count.value = '5'; ui.win.emit('pageshow');
  assert.equal(query(ui.links[2]).get('mode'), 'recall'); assert.equal(query(ui.links[2]).get('count'), '5');
});

test('unknown mode/count cannot create a new quiz mode or length', () => {
  const ui = setup(); ui.mode.value = 'javascript:bad'; ui.count.value = '500'; ui.form.emit('change');
  assert.equal(query(ui.links[0]).get('mode'), 'meaning'); assert.equal(query(ui.links[0]).get('count'), '10');
});

test('topic and level values are query data and cannot inject sources, fragments or destinations', () => {
  const ui = setup(); ui.topic.value = 'x&source=evil#https://evil.test/?mode=other'; ui.level.value = '" onmouseover="bad';
  ui.links[0].attrs.href = 'javascript:alert(1)'; ui.form.emit('change');
  const destination = new URL(ui.links[0].attrs.href, ui.win.location.origin);
  assert.equal(destination.origin, ui.win.location.origin); assert.equal(destination.pathname, '/learning/quiz/');
  assert.equal(destination.hash, ''); assert.equal(destination.searchParams.getAll('source').length, 1);
  assert.equal(destination.searchParams.get('source'), 'all'); assert.equal(destination.searchParams.get('topic'), ui.topic.value);
  assert.equal(destination.searchParams.get('level'), ui.level.value);
});

test('unsafe or cross-origin base paths never replace the server-rendered fallback links', () => {
  for (const path of ['javascript:alert(1)', 'https://evil.test/', '//evil.test/', '/\\evil.test/', 'data:text/html,bad']) {
    const ui = setup({path}); ui.form.emit('change');
    assert.deepEqual(ui.links.map((link) => link.attrs.href), ['?source=fallback', '?source=fallback', '?source=fallback']);
  }
});

test('unknown source targets and unrelated pages remain unchanged', () => {
  const ui = setup({sourceValues: ['all', 'arbitrary']}); assert.equal(ui.links[1].attrs.href, '?source=fallback');
  assert.doesNotThrow(() => setup({missingForm: true}));
});


test('due source selects recall without changing other source modes and keeps filters', () => {
  const ui = setup({sourceValues: ['all', 'saved', 'weak', 'due']});
  ui.level.value = 'B1'; ui.topic.value = 'Office'; ui.count.value = '5'; ui.form.emit('change');
  assert.equal(query(ui.links[3]).get('mode'), 'recall');
  assert.equal(query(ui.links[0]).get('mode'), 'meaning');
  assert.equal(query(ui.links[3]).get('source'), 'due');
  assert.equal(query(ui.links[3]).get('level'), 'B1');
  assert.equal(query(ui.links[3]).get('topic'), 'Office');
  assert.equal(query(ui.links[3]).get('count'), '5');
});
