const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'mistake-review.js'), 'utf8');

class FakeElement {
  constructor({dataset = {}, checked = false} = {}) {
    this.dataset = dataset;
    this.checked = checked;
    this.listeners = new Map();
    this.children = {};
    this.textContent = '';
    this.disabled = false;
    this.style = {};
    this.attributes = {};
  }
  addEventListener(type, listener) {
    const list = this.listeners.get(type) || [];
    list.push(listener);
    this.listeners.set(type, list);
  }
  emit(type, event = {}) {
    for (const listener of this.listeners.get(type) || []) listener(event);
  }
  querySelector(selector) { return this.children[selector] || null; }
  querySelectorAll(selector) { return selector === 'input[type="radio"]:checked' && this.children.checked ? [this.children.checked] : []; }
  matches(selector) { return selector === 'input[type="radio"]' && this.isRadio; }
  setAttribute(key, value) { this.attributes[key] = value; }
}

function setup({confirmResult = true, autosave = false, initiallySelected = 0} = {}) {
  const form = new FakeElement({dataset: {total: '2'}});
  if (autosave) form.dataset.practiceDraft = '';
  const questions = [new FakeElement(), new FakeElement()];
  const radios = [new FakeElement(), new FakeElement()];
  radios.forEach((radio) => { radio.isRadio = true; });
  questions.forEach((question, index) => {
    question.children['input[type="radio"]:checked'] = null;
    question.children.checked = null;
    question.select = () => {
      question.children.checked = radios[index];
      question.children['input[type="radio"]:checked'] = radios[index];
    };
  });
  const count = new FakeElement();
  const status = new FakeElement();
  const draftStatus = new FakeElement();
  draftStatus.textContent = 'Đã khôi phục bản nháp';
  const progressbar = new FakeElement();
  const progressFill = new FakeElement();
  const submitButton = new FakeElement();
  submitButton.textContent = 'Nộp lượt ôn';
  const submitStatus = new FakeElement();
  const abandon = new FakeElement();
  form.querySelectorAll = (selector) => selector === '[data-question]' ? questions : [];
  form.querySelector = (selector) => ({
    '[data-answered-count]': count,
    '[data-review-status]': status,
    '[data-draft-status]': draftStatus,
    '[data-progressbar]': progressbar,
    '[data-progress-fill]': progressFill,
    '[data-review-submit]': submitButton,
    '[data-submit-status]': submitStatus,
  })[selector] || null;
  const listeners = new Map();
  let confirmCalls = 0;
  const window = {
    addEventListener: (type, listener) => listeners.set(type, listener),
    confirm: () => { confirmCalls += 1; return confirmResult; },
  };
  const document = {
    querySelector: (selector) => ({'[data-mistake-review]': form, '[data-mistake-abandon]': abandon})[selector] || null,
  };
  questions.slice(0, initiallySelected).forEach((question) => question.select());
  vm.runInContext(script, vm.createContext({document, window, queueMicrotask}), {filename: 'mistake-review.js'});
  return {form, questions, radios, count, status, draftStatus, progressbar, progressFill, submitButton, submitStatus, abandon, listeners, getConfirmCalls: () => confirmCalls};
}

const flushMicrotasks = () => new Promise((resolve) => queueMicrotask(resolve));

test('counts selected answers and warns only after a choice changes', () => {
  const ui = setup();
  assert.equal(ui.count.textContent, '0');
  assert.match(ui.status.textContent, /Còn 2 câu/);
  const initial = {prevented: false, preventDefault() { this.prevented = true; }};
  ui.listeners.get('beforeunload')(initial);
  assert.equal(initial.prevented, false);

  ui.questions[0].select();
  ui.form.emit('change', {target: ui.radios[0]});
  assert.equal(ui.count.textContent, '1');
  assert.equal(ui.progressbar.attributes['aria-valuenow'], '1');
  assert.equal(ui.progressFill.style.width, '50%');
  const changed = {prevented: false, preventDefault() { this.prevented = true; }};
  ui.listeners.get('beforeunload')(changed);
  assert.equal(changed.prevented, true);
  assert.equal(changed.returnValue, '');
});

test('prevents duplicate submit and resets controls on pageshow', async () => {
  const ui = setup();
  const first = {prevented: false, defaultPrevented: false, preventDefault() { this.prevented = true; this.defaultPrevented = true; }};
  ui.form.emit('submit', first);
  await flushMicrotasks();
  assert.equal(ui.submitButton.disabled, true);
  const second = {prevented: false, defaultPrevented: false, preventDefault() { this.prevented = true; this.defaultPrevented = true; }};
  ui.form.emit('submit', second);
  assert.equal(second.prevented, true);
  ui.listeners.get('pageshow')({persisted: false});
  assert.equal(ui.submitButton.disabled, false);
  assert.equal(ui.submitButton.textContent, 'Nộp lượt ôn');
});

test('cancelled submit from another listener preserves answers and leave warning', async () => {
  const ui = setup();
  ui.questions[0].select();
  ui.form.emit('change', {target: ui.radios[0]});
  const submit = {defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }};
  ui.form.emit('submit', submit);
  // Simulate a later document-level handler cancelling the same event.
  submit.preventDefault();
  await flushMicrotasks();
  assert.equal(ui.submitButton.disabled, false);
  assert.equal(ui.submitStatus.textContent, '');
  const warning = {prevented: false, preventDefault() { this.prevented = true; }};
  ui.listeners.get('beforeunload')(warning);
  assert.equal(warning.prevented, true);

  const retry = {defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }};
  ui.form.emit('submit', retry);
  await flushMicrotasks();
  assert.equal(ui.submitButton.disabled, true);
});

test('cancelled abandon keeps leave warning; confirmed abandon clears it', () => {
  const ui = setup({confirmResult: false});
  ui.questions[0].select();
  ui.form.emit('change', {target: ui.radios[0]});
  const cancel = {prevented: false, preventDefault() { this.prevented = true; }};
  ui.abandon.emit('submit', cancel);
  assert.equal(cancel.prevented, true);
  const stillDirty = {prevented: false, preventDefault() { this.prevented = true; }};
  ui.listeners.get('beforeunload')(stillDirty);
  assert.equal(stillDirty.prevented, true);

  const accepted = setup({confirmResult: true});
  accepted.questions[0].select();
  accepted.form.emit('change', {target: accepted.radios[0]});
  accepted.abandon.emit('submit', {preventDefault() {}});
  const noExtraPrompt = {prevented: false, preventDefault() { this.prevented = true; }};
  accepted.listeners.get('beforeunload')(noExtraPrompt);
  assert.equal(noExtraPrompt.prevented, false);
});

test('autosave mode lets shared persistence own leave warnings and the single abandon prompt', () => {
  const ui = setup({autosave: true});
  ui.questions[0].select();
  ui.form.emit('change', {target: ui.radios[0]});
  assert.equal(ui.count.textContent, '1');
  assert.match(ui.status.textContent, /Còn 1 câu/);
  assert.doesNotMatch(ui.status.textContent, /chỉ được lưu khi/);
  assert.equal(ui.draftStatus.textContent, 'Đã khôi phục bản nháp');
  assert.equal(ui.listeners.has('beforeunload'), false);
  assert.equal(ui.abandon.listeners.has('submit'), false);
  ui.abandon.emit('submit', {preventDefault() { throw new Error('review script must not intercept'); }});
  assert.equal(ui.getConfirmCalls(), 0);
});

test('autosave mode initializes restored counts and leaves submit/BFCache lock to shared persistence', async () => {
  const ui = setup({autosave: true, initiallySelected: 1});
  assert.equal(ui.count.textContent, '1');
  assert.equal(ui.progressbar.attributes['aria-valuenow'], '1');
  assert.equal(ui.progressFill.style.width, '50%');
  assert.equal(ui.form.listeners.has('submit'), false, 'shared controller owns submit serialization');
  ui.submitButton.disabled = true;
  ui.listeners.get('pageshow')({persisted: true});
  assert.equal(ui.submitButton.disabled, true, 'must not undo a shared conflict or BFCache lock');
  assert.equal(ui.draftStatus.textContent, 'Đã khôi phục bản nháp');
  assert.equal(ui.count.textContent, '1');
});

test('autosave mode cancelled submit does not announce grading or disable the form', async () => {
  const ui = setup({autosave: true, initiallySelected: 1});
  const cancelled = {defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }};
  ui.form.emit('submit', cancelled);
  cancelled.preventDefault();
  await flushMicrotasks();
  assert.equal(ui.submitButton.disabled, false);
  assert.equal(ui.submitStatus.textContent, '');
  assert.equal(ui.draftStatus.textContent, 'Đã khôi phục bản nháp');
  assert.equal(ui.count.textContent, '1');
});
