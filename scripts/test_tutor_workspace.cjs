const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'tutor-workspace.js'), 'utf8');

class FakeElement {
  constructor(dataset = {}) {
    this.dataset = dataset;
    this.listeners = new Map();
    this.value = '';
    this.textContent = '';
    this.focused = false;
    this.selection = null;
  }
  addEventListener(type, listener) {
    const list = this.listeners.get(type) || [];
    list.push(listener);
    this.listeners.set(type, list);
  }
  emit(type, event = {}) {
    for (const listener of this.listeners.get(type) || []) listener(event);
  }
  focus() { this.focused = true; }
  setSelectionRange(start, end) { this.selection = [start, end]; }
  checkValidity() { return true; }
}

test('suggested prompt replaces question and clears submitted-question context without submitting', () => {
  const form = new FakeElement();
  const textarea = new FakeElement();
  const contextQuestion = new FakeElement();
  contextQuestion.value = 'question-72';
  const counter = new FakeElement();
  const submitButton = new FakeElement();
  const submitStatus = new FakeElement();
  const suggestion = new FakeElement({prompt: 'Giải thích từ deadline trong ngữ cảnh công việc.'});
  let submits = 0;

  form.querySelector = (selector) => ({
    'textarea[name="question"]': textarea,
    'input[name="question_id"]': contextQuestion,
    '[data-char-count]': counter,
    '[data-submit-question]': submitButton,
    '[data-submit-status]': submitStatus,
  })[selector] || null;
  const document = {
    querySelector: (selector) => selector === '[data-tutor-form]' ? form : null,
    querySelectorAll: (selector) => selector === '[data-prompt]' ? [suggestion] : [],
  };
  const windowListeners = new Map();
  const window = {addEventListener: (type, listener) => windowListeners.set(type, listener)};
  const context = vm.createContext({document, window});
  vm.runInContext(script, context, {filename: 'tutor-workspace.js'});
  form.addEventListener('submit', () => { submits += 1; });

  suggestion.emit('click');

  assert.equal(textarea.value, suggestion.dataset.prompt);
  assert.equal(contextQuestion.value, '');
  assert.equal(counter.textContent, String(suggestion.dataset.prompt.length));
  assert.equal(textarea.focused, true);
  assert.deepEqual(textarea.selection, [textarea.value.length, textarea.value.length]);
  assert.equal(submits, 0);
});

test('submit guard prevents duplicate POST and pageshow restores the form', () => {
  const form = new FakeElement();
  form.dataset = {};
  const textarea = new FakeElement();
  const submitButton = new FakeElement();
  submitButton.innerHTML = 'Gửi câu hỏi';
  const submitStatus = new FakeElement();
  form.querySelector = (selector) => ({
    'textarea[name="question"]': textarea,
    'input[name="question_id"]': new FakeElement(),
    '[data-char-count]': new FakeElement(),
    '[data-submit-question]': submitButton,
    '[data-submit-status]': submitStatus,
  })[selector] || null;
  const document = {
    querySelector: (selector) => selector === '[data-tutor-form]' ? form : null,
    querySelectorAll: () => [],
  };
  const windowListeners = new Map();
  const window = {addEventListener: (type, listener) => windowListeners.set(type, listener)};
  vm.runInContext(script, vm.createContext({document, window}), {filename: 'tutor-workspace.js'});

  const firstSubmit = {prevented: false, preventDefault() { this.prevented = true; }};
  form.emit('submit', firstSubmit);
  assert.equal(form.dataset.submitting, 'true');
  assert.equal(submitButton.disabled, true);

  const secondSubmit = {prevented: false, preventDefault() { this.prevented = true; }};
  form.emit('submit', secondSubmit);
  assert.equal(secondSubmit.prevented, true);

  windowListeners.get('pageshow')();
  assert.equal(form.dataset.submitting, 'false');
  assert.equal(submitButton.disabled, false);
  assert.equal(submitButton.innerHTML, 'Gửi câu hỏi');
  assert.equal(submitStatus.textContent, '');
});

function descriptionSetup({initialDescription = false} = {}) {
  const form = new FakeElement();
  const textarea = new FakeElement(); textarea.value = 'Câu hỏi vẫn được giữ';
  const contextQuestion = new FakeElement(); contextQuestion.value = '72';
  const automatic = new FakeElement(); automatic.checked = !initialDescription;
  const description = new FakeElement(); description.checked = initialDescription;
  const lookup = new FakeElement(); lookup.checked = false;
  const ai = new FakeElement(); ai.checked = true;
  const submitButton = new FakeElement(); submitButton.innerHTML = initialDescription ? 'Tìm từ gợi ý →' : 'Gửi câu hỏi';
  const submitStatus = new FakeElement();
  const suggestion = new FakeElement({prompt:'Giải thích từ “classmate” trong ngữ cảnh: bạn cùng lớp.'});
  form.querySelector = (selector) => ({
    'textarea[name="question"]':textarea, 'input[name="question_id"]':contextQuestion,
    'input[name="query_mode"][value="auto"]':automatic, 'input[name="query_mode"][value="description"]':description,
    'input[name="response_mode"][value="lookup"]':lookup, 'input[name="response_mode"][value="ai"]':ai,
    '[data-char-count]':new FakeElement(), '[data-submit-question]':submitButton, '[data-submit-status]':submitStatus,
  })[selector] || null;
  const document={querySelector:()=>form,querySelectorAll:()=>[suggestion]};
  const windowListeners=new Map();
  const window={addEventListener:(type,listener)=>windowListeners.set(type,listener)};
  vm.runInContext(script,vm.createContext({document,window}),{filename:'tutor-workspace.js'});
  return {form,textarea,contextQuestion,automatic,description,lookup,ai,submitButton,submitStatus,suggestion,windowListeners};
}

test('description selection clears question context, disables AI and keeps the typed description', () => {
  const ui=descriptionSetup();
  ui.automatic.checked=false;ui.description.checked=true;ui.description.emit('change');
  assert.equal(ui.contextQuestion.value,'');
  assert.equal(ui.lookup.checked,true);assert.equal(ui.ai.checked,false);assert.equal(ui.ai.disabled,true);
  assert.equal(ui.textarea.value,'Câu hỏi vẫn được giữ');
  assert.match(ui.textarea.placeholder,/Một người học cùng lớp/);
  assert.equal(ui.submitButton.textContent,'Tìm từ gợi ý →');
});

test('choosing a suggested concrete word resets description and AI without submitting', () => {
  const ui=descriptionSetup({initialDescription:true});
  let submits=0;ui.form.addEventListener('submit',()=>submits++);
  ui.suggestion.emit('click');
  assert.equal(ui.automatic.checked,true);assert.equal(ui.description.checked,false);
  assert.equal(ui.lookup.checked,true);assert.equal(ui.ai.checked,false);assert.equal(ui.ai.disabled,false);
  assert.equal(ui.contextQuestion.value,'');assert.equal(ui.textarea.value,ui.suggestion.dataset.prompt);
  assert.match(ui.submitButton.innerHTML,/Gửi câu hỏi/);
  assert.equal(submits,0);
});

test('returning to automatic mode enables AI choice but never restores an earlier paid selection', () => {
  const ui=descriptionSetup({initialDescription:true});
  ui.description.checked=false;ui.automatic.checked=true;ui.automatic.emit('change');
  assert.equal(ui.ai.disabled,false);assert.equal(ui.ai.checked,false);assert.equal(ui.lookup.checked,true);
  assert.match(ui.submitButton.innerHTML,/Gửi câu hỏi/);
});

test('description submit and BFCache restoration keep free lookup and recover the correct action label', () => {
  const ui=descriptionSetup({initialDescription:true});
  ui.form.emit('submit');
  assert.equal(ui.submitButton.disabled,true);assert.equal(ui.submitButton.textContent,'Đang tìm từ gợi ý…');
  assert.equal(ui.submitStatus.textContent,'Đang đối chiếu mô tả với học liệu.');
  ui.ai.checked=true;ui.lookup.checked=false;ui.contextQuestion.value='accidental-old-context';
  ui.windowListeners.get('pageshow')();
  assert.equal(ui.submitButton.disabled,false);assert.equal(ui.submitButton.textContent,'Tìm từ gợi ý →');
  assert.equal(ui.lookup.checked,true);assert.equal(ui.ai.checked,false);assert.equal(ui.ai.disabled,true);
  assert.equal(ui.contextQuestion.value,'');
});
