const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'navigation.js'), 'utf8');

class FakeElement {
  constructor() { this.listeners = new Map(); this.open = false; this.focused = false; }
  addEventListener(type, listener) {
    const list = this.listeners.get(type) || [];
    list.push(listener);
    this.listeners.set(type, list);
  }
  emit(type, event = {}) {
    for (const listener of this.listeners.get(type) || []) listener(event);
  }
  querySelector() { return this.summary || null; }
  querySelectorAll() { return this.links || []; }
  focus() { this.focused = true; }
}

function setup() {
  const details = new FakeElement();
  details.summary = new FakeElement();
  const link = new FakeElement();
  details.links = [link];
  const document = {querySelectorAll: () => [details]};
  vm.runInContext(script, vm.createContext({document}), {filename: 'navigation.js'});
  return {details, link};
}

test('mobile menu closes when a destination is selected', () => {
  const {details, link} = setup();
  details.open = true;
  link.emit('click');
  assert.equal(details.open, false);
});

test('Escape closes the native details menu and returns focus to its summary', () => {
  const {details} = setup();
  details.open = true;
  let prevented = false;
  details.emit('keydown', {key: 'Escape', preventDefault() { prevented = true; }});
  assert.equal(details.open, false);
  assert.equal(details.summary.focused, true);
  assert.equal(prevented, true);
});
