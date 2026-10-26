const test = require('node:test');
const assert = require('node:assert/strict');
const editor = require('../static/js/content-review-editor.js');
const fs = require('node:fs');
function packet() {
  const review = () => ({reviewer_name: '', qualifications: '', reviewed_at: null, conclusion: null, notes: ''});
  const checklist = () => Object.fromEntries(Object.keys(editor.CHECKS).map(key => [key, {result: null, notes: ''}]));
  const item = (id, extra) => ({id, content_id: 5, version_hash: `item-${id}`, human_review: review(), checklist: checklist(), ...extra});
  return {schema_version: 'linguapath-content-review-v1', fingerprint: 'original-fingerprint', generated_at: '2026-10-25T10:00:00Z', approval_allowed: false,
    human_review: review(), checklist_template: checklist(), selection: {content_ids: [5]},
    contents: [{content: {id: 5, title: '<img src=x onerror=alert(1)>', source_name: 'Original', source_url: 'javascript:alert(1)', rights_note: 'Check this'},
      content_hash: 'whole-parent-original', coverage: {flashcards: {exported: 1, total: 15}, questions: {exported: 1, total: 1}},
      flashcards: [item(9, {term: '<script>injected()</script>', meaning_vi: 'nghĩa gốc'})],
      questions: [item(10, {prompt: 'Which?', passage: 'Friday.', explanation: 'Friday.', options: [
        {id: 1, label: 'A', text: '<b>Friday</b>', is_correct: true, explanation_vi: 'Đúng theo bài.'},
        {id: 2, label: 'B', text: 'Monday', is_correct: false, explanation_vi: 'Không có trong bài.'},
      ]})]}]};
}
function fill(state, index = 0) {
  [['reviewer_name', 'Teacher A'], ['qualifications', 'English reviewer'], ['reviewed_at', '2026-10-25'], ['conclusion', 'pass']].forEach(([key, value]) => editor.updateReview(state, index, key, value));
  Object.keys(editor.CHECKS).forEach(key => editor.updateChecklist(state, index, key, 'result', 'pass'));
}
function withoutAnnotations(value) {
  const copy = structuredClone(value);
  delete copy.human_review;
  copy.contents.forEach(content => ['flashcards', 'questions'].forEach(kind => content[kind].forEach(item => { delete item.human_review; delete item.checklist; })));
  return copy;
}
test('v2 availability stays source evidence when annotations change', () => {
  const source = packet(); source.schema_version = 'linguapath-content-review-v2';
  source.contents[0].flashcards[0].is_available = false;
  source.contents[0].flashcards[0].availability_note = 'Awaiting review';
  const state = editor.createState(source); fill(state);
  assert.equal(state.packet.contents[0].flashcards[0].is_available, false);
  assert.equal(state.packet.contents[0].flashcards[0].availability_note, 'Awaiting review');
  assert.deepEqual(withoutAnnotations(state.packet), withoutAnnotations(source));
});
test('annotation helpers preserve original packet, every source field and hashes', () => {
  const source = packet(); const untouched = structuredClone(source); const state = editor.createState(source);
  fill(state); editor.updateChecklist(state, 0, 'source_and_rights', 'notes', 'Reviewed rights evidence');
  assert.deepEqual(source, untouched);
  assert.deepEqual(withoutAnnotations(state.packet), withoutAnnotations(untouched));
  assert.equal(state.packet.approval_allowed, false);
  assert.equal(state.packet.fingerprint, 'original-fingerprint');
  assert.equal(state.packet.contents[0].content_hash, 'whole-parent-original');
  assert.equal(state.dirty, true);
});
test('arbitrary source paths, prototype fields, invalid enums and dates are rejected', () => {
  const state = editor.createState(packet());
  for (const key of ['prompt', 'is_correct', '__proto__', 'constructor', 'content_hash']) assert.throws(() => editor.updateReview(state, 0, key, 'bad'));
  assert.throws(() => editor.updateReview(state, -1, 'notes', 'bad'));
  assert.throws(() => editor.updateReview(state, 0, 'conclusion', 'teacher_approved'));
  assert.throws(() => editor.updateChecklist(state, 0, '__proto__', 'result', 'pass'));
  assert.throws(() => editor.updateChecklist(state, 0, 'answer_key', 'result', 'yes'));
  assert.throws(() => editor.updateChecklist(state, 0, 'answer_key', 'source', 'bad'));
  for (const date of ['2026-02-30', '25/10/2026', '2026-1-2', 'not-a-date']) assert.throws(() => editor.updateReview(state, 0, 'reviewed_at', date));
  assert.throws(() => editor.updateReview(state, 0, 'notes', 'x'.repeat(4001)));
  assert.throws(() => editor.updateChecklist(state, 0, 'answer_key', 'notes', {}));
  assert.equal({}.polluted, undefined);
});
test('loaded reviewer annotations survive navigation and download preparation', () => {
  const source = packet(); fill(editor.createState(source));
  source.contents[0].flashcards[0].human_review = {reviewer_name: 'Existing reviewer', qualifications: 'Original expertise', reviewed_at: '2026-10-24', conclusion: 'needs_changes', notes: 'Rewrite example'};
  source.contents[0].flashcards[0].checklist.answer_key = {result: 'not_applicable', notes: 'Vocabulary card'};
  const state = editor.createState(source);
  editor.updateReview(state, null, 'reviewer_name', 'Another person');
  assert.deepEqual(state.packet.contents[0].flashcards[0].human_review, source.contents[0].flashcards[0].human_review);
  assert.deepEqual(state.packet.contents[0].flashcards[0].checklist, source.contents[0].flashcards[0].checklist);
});
test('explicit reviewer copy updates identity only and assessed scope leaves untouched items blank', () => {
  const state = editor.createState(packet());
  [['reviewer_name', 'Teacher B'], ['qualifications', 'TOEIC editor'], ['reviewed_at', '2026-10-25']].forEach(([key, value]) => editor.updateReview(state, null, key, value));
  editor.updateReview(state, 0, 'conclusion', 'needs_changes'); editor.updateReview(state, 0, 'notes', 'Fix sense');
  assert.equal(editor.copyReviewer(state, 'assessed'), 1);
  const card = editor.itemAt(state, 0); const question = editor.itemAt(state, 1);
  assert.equal(card.human_review.reviewer_name, 'Teacher B'); assert.equal(card.human_review.conclusion, 'needs_changes'); assert.equal(card.human_review.notes, 'Fix sense');
  assert.equal(question.human_review.reviewer_name, '');
  assert.equal(editor.copyReviewer(state, 1), 1); assert.equal(question.human_review.reviewer_name, 'Teacher B');
});
test('completion counts require named dated reviewers, every check and rationale for exceptions', () => {
  const state = editor.createState(packet());
  assert.deepEqual(editor.summary(state), {total: 2, complete: 0, pending: 2, pass: 0, needs_changes: 0, insufficient_info: 0});
  fill(state); assert.equal(editor.summary(state).complete, 1);
  editor.updateChecklist(state, 0, 'audio_and_accessibility', 'result', 'not_applicable');
  assert.equal(editor.summary(state).complete, 0);
  editor.updateChecklist(state, 0, 'audio_and_accessibility', 'notes', 'No audio task on this vocabulary card');
  assert.equal(editor.summary(state).complete, 1);
  editor.updateReview(state, 0, 'conclusion', 'insufficient_info'); assert.equal(editor.summary(state).complete, 0);
  editor.updateReview(state, 0, 'notes', 'Need license confirmation'); assert.equal(editor.summary(state).complete, 1);
  editor.updateReview(state, 0, 'qualifications', '  '); assert.equal(editor.summary(state).complete, 0);
});
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.listeners = {}; this.attrs = {}; this.value = ''; this.textContent = ''; }
  set innerHTML(_) { throw new Error('HTML interpolation forbidden'); }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  replaceChildren(...children) { this.children = []; children.forEach(child => this.appendChild(child)); }
  get firstChild() { return this.children[0]; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(key, fn) { this.listeners[key] = fn; }
  click() { if (this.listeners.click) this.listeners.click(); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
}
function setup() {
  const root = new Element('div'), body = new Element('body'), nodes = [];
  const doc = {body, createElement: tag => { const node = new Element(tag); nodes.push(node); return node; }};
  const hooks = {}, revoked = [], timers = [], blobs = [];
  const win = {addEventListener: (key, fn) => { hooks[key] = fn; }, setTimeout: (fn, delay) => timers.push({fn, delay}),
    Blob: class { constructor(parts, options) { blobs.push({parts, options}); } }, URL: {createObjectURL: () => 'blob:test', revokeObjectURL: value => revoked.push(value)}};
  const attached = editor.attach(root, packet(), doc, win);
  return {root, body, nodes, hooks, revoked, timers, blobs, ...attached};
}
test('DOM rendering treats source HTML as text and never makes unsafe source URLs navigable', () => {
  const x = setup();
  assert.ok(x.nodes.some(node => node.textContent === '<script>injected()</script>'));
  assert.ok(x.nodes.some(node => node.textContent === '<img src=x onerror=alert(1)>'));
  assert.ok(x.nodes.some(node => node.textContent === 'javascript:alert(1)'));
  assert.equal(x.nodes.some(node => node.tagName === 'script' || node.tagName === 'img' || node.href === 'javascript:alert(1)'), false);
  x.navigate(1); assert.ok(x.nodes.some(node => node.textContent.includes('<b>Friday</b>')));
  const inputIds = x.nodes.filter(node => ['input', 'select', 'textarea'].includes(node.tagName)).map(node => node.id);
  assert.ok(inputIds.every(id => x.nodes.some(node => node.tagName === 'label' && node.htmlFor === id)));
});
test('dirty unload guard and local download preserve annotations with delayed URL revocation', () => {
  const x = setup(); let prevented = false;
  x.hooks.beforeunload({preventDefault() { prevented = true; }}); assert.equal(prevented, false);
  editor.updateReview(x.state, 0, 'notes', 'Human note');
  const event = {preventDefault() { prevented = true; }}; x.hooks.beforeunload(event);
  assert.equal(prevented, true); assert.equal(event.returnValue, '');
  x.nodes.find(node => node.tagName === 'button' && node.textContent === 'Tải phiếu đã điền · JSON').click();
  const exported = JSON.parse(x.blobs[0].parts[0]);
  assert.equal(exported.contents[0].flashcards[0].human_review.notes, 'Human note');
  assert.equal(exported.fingerprint, 'original-fingerprint'); assert.equal(x.state.dirty, false);
  assert.equal(x.revoked.length, 0); assert.equal(x.timers[0].delay, 30000);
  x.timers[0].fn(); assert.deepEqual(x.revoked, ['blob:test']);
});
test('passed conclusion with failed checks remains incomplete; loaded timezone dates are retained', () => {
  const state = editor.createState(packet()); fill(state);
  editor.itemAt(state, 0).human_review.reviewed_at = '2026-10-25T10:00:00+07:00';
  assert.equal(editor.summary(state).complete, 1);
  editor.updateChecklist(state, 0, 'answer_key', 'result', 'fail');
  editor.updateChecklist(state, 0, 'answer_key', 'notes', 'Key needs correction');
  assert.equal(editor.summary(state).complete, 0);
  editor.updateReview(state, 0, 'conclusion', 'needs_changes');
  editor.updateReview(state, 0, 'notes', 'Resolve key');
  assert.equal(editor.summary(state).complete, 1);
  assert.throws(() => editor.updateReview(state, 0, 'reviewer_name', 'x'.repeat(201)));
  assert.throws(() => editor.updateReview(state, 0, 'qualifications', 'x'.repeat(2001)));
});
test('unsafe numeric source IDs cannot silently round trip through browser JSON', () => {
  const source = packet(); source.contents[0].flashcards[0].id = 9007199254740992;
  assert.throws(() => editor.createState(source), /unsafe-source-number/);
});
test('assessed reviewer copy includes a draft with only a human note', () => {
  const state = editor.createState(packet()); editor.updateReview(state, null, 'reviewer_name', 'Reviewer');
  editor.updateReview(state, 1, 'notes', 'Still reviewing');
  assert.equal(editor.copyReviewer(state, 'assessed'), 1);
  assert.equal(editor.itemAt(state, 1).human_review.reviewer_name, 'Reviewer');
  assert.equal(editor.itemAt(state, 0).human_review.reviewer_name, '');
});
test('conflicts explain contradictory conclusions without blocking draft export', () => {
  const x = setup(); fill(x.state);
  editor.updateChecklist(x.state, 0, 'answer_key', 'result', 'fail');
  editor.updateReview(x.state, 1, 'conclusion', 'needs_changes');
  editor.updateReview(x.state, null, 'conclusion', 'pass');
  assert.deepEqual(editor.conflicts(x.state), {items: 1, overall: true});
  x.navigate(1);
  const warning = x.nodes.find(node => node.className === 'review-editor-conflict');
  assert.equal(warning.hidden, false); assert.match(warning.textContent, /mâu thuẫn/);
  x.nodes.find(node => node.tagName === 'button' && node.textContent === 'Tải phiếu đã điền · JSON').click();
  assert.equal(x.blobs.length, 1);
});
test('editor contains no persistence or request channel for reviewer notes', () => {
  const source = fs.readFileSync('static/js/content-review-editor.js', 'utf8');
  assert.doesNotMatch(source, /\b(?:localStorage|sessionStorage|indexedDB|fetch|XMLHttpRequest|sendBeacon)\b/);
});
