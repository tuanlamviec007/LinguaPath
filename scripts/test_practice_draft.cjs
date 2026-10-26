const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'practice-draft.js'), 'utf8');
const pause = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitFor(predicate, message, timeout = 1500) {
  const start = Date.now();
  while (!predicate()) {
    if (Date.now() - start > timeout) throw Error(message);
    await pause(5);
  }
}
class Element {
  constructor(dataset = {}) {
    this.dataset = dataset; this.listeners = new Map(); this.attributes = {}; this.style = {};
    this.textContent = ''; this.value = ''; this.disabled = false; this.checked = false; this.hidden = false;
  }
  addEventListener(type, fn) { this.listeners.set(type, [...(this.listeners.get(type) || []), fn]); }
  emit(type, event = {}) { for (const fn of this.listeners.get(type) || []) fn(event); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
}
function event(extra = {}) { return {defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extra}; }
function response({ok = true, redirected = false, status = 200, result = {saved_count: 1, last_saved_at: '2026-10-19T12:30:00Z', draft_revision: 1}, jsonError} = {}) {
  return {ok, redirected, status, async json() { if (jsonError) throw jsonError; return result; }};
}
function setup(fetchImpl, {confirmResult = true, revision = '0', conflict = false, shortTimeout = false, cancelNative = false, total = '1', practice = true} = {}) {
  const status = new Element(), count = new Element(), progress = new Element(), fill = new Element();
  const save = new Element(), reload = new Element(), hiddenRevision = new Element(), csrf = new Element(), submit = new Element();
  hiddenRevision.value = revision; csrf.value = 'csrf'; reload.hidden = true;
  const abandon = new Element();
  const radios = ['101', '102'].map((value) => Object.assign(new Element(), {
    value, name: 'question_41', matches: (selector) => selector === 'input[type="radio"]',
  }));
  const form = new Element({draftRevision: revision, draftConflict: String(conflict), draftUrl: '/draft/', total});
  form.matches = (selector) => practice && selector === '.practice-form';
  form.querySelector = (selector) => ({
    '[data-draft-status]': status, '[data-answered-count]': count, '[data-progressbar]': progress,
    '[data-progress-fill]': fill, '[data-save-draft]': save, '[data-reload-draft]': reload,
    '[data-draft-revision]': hiddenRevision, 'input[name="csrfmiddlewaretoken"]': csrf,
  })[selector] || null;
  form.querySelectorAll = (selector) => selector === 'input[type="radio"]:checked' ? radios.filter((r) => r.checked)
    : selector === '[type="submit"]' ? [submit] : [];
  let nativeSubmits = 0, reloads = 0, confirms = 0;
  const nativePayloads = [];
  form.requestSubmit = (submitter) => {
    const evt = event({submitter});
    form.emit('submit', evt);
    if (cancelNative) evt.preventDefault();
    if (!evt.defaultPrevented) {
      nativeSubmits += 1;
      nativePayloads.push({revision: hiddenRevision.value, answer: radios.find((r) => r.checked)?.value});
    }
    return evt;
  };
  const listeners = new Map();
  const window = {
    setTimeout: (fn, ms) => setTimeout(fn, shortTimeout && ms === 15000 ? 25 : ms), clearTimeout,
    addEventListener: (type, fn) => listeners.set(type, fn), removeEventListener: (type) => listeners.delete(type),
    confirm: () => { confirms += 1; return confirmResult; }, location: {reload: () => { reloads += 1; }},
  };
  const document = {querySelector: (selector) => selector === '[data-practice-draft]' ? form : selector === '[data-abandon-attempt]' ? abandon : null};
  vm.runInContext(script, vm.createContext({window, document, fetch: fetchImpl, AbortController, Intl, Date, Number, Object, Promise, JSON}), {filename: 'practice-draft.js'});
  const choose = (n) => { radios.forEach((r, i) => { r.checked = i === n; }); form.emit('change', {target: radios[n]}); };
  const saveNow = () => save.emit('click');
  return {form, status, count, progress, fill, save, reload, hiddenRevision, submit, radios, abandon, listeners, choose, saveNow,
    get nativeSubmits() { return nativeSubmits; }, nativePayloads, get reloads() { return reloads; }, get confirms() { return confirms; }};
}

test('successful save sends revision, updates hidden revision and clears warning', async () => {
  let body;
  const ui = setup(async (_, opts) => { body = JSON.parse(opts.body); return response(); });
  ui.choose(0); ui.saveNow();
  await waitFor(() => ui.status.dataset.state === 'saved', 'save not acknowledged');
  assert.deepEqual(body, {answers: {'41': '101'}, draft_revision: 0});
  assert.equal(ui.hiddenRevision.value, '1'); assert.equal(ui.form.dataset.draftRevision, '1');
  assert.equal(ui.count.textContent, '1'); assert.equal(ui.progress.attributes['aria-valuenow'], '1');
  assert.equal(ui.listeners.has('beforeunload'), false);
});

test('slow request queues newest edits with acknowledged revision, never overlaps', async () => {
  const requests = [];
  const ui = setup((_, opts) => new Promise((resolve) => requests.push({opts, resolve})));
  ui.choose(0); ui.saveNow(); ui.choose(1); ui.saveNow();
  assert.equal(requests.length, 1);
  requests[0].resolve(response());
  await waitFor(() => requests.length === 2, 'newest edit not saved');
  assert.deepEqual(JSON.parse(requests[1].opts.body), {answers: {'41': '102'}, draft_revision: 1});
  requests[1].resolve(response({result: {saved_count: 1, last_saved_at: '2026-10-19T12:31:00Z', draft_revision: 2}}));
  await waitFor(() => ui.status.dataset.state === 'saved', 'second ack missing');
  assert.equal(ui.hiddenRevision.value, '2');
});

test('409 conflict locks both saves and submit while preserving local inputs', async () => {
  let calls = 0;
  const ui = setup(async () => { calls += 1; return response({ok: false, status: 409, result: {status: 'conflict', error: 'Bản nháp mới hơn.', draft_revision: 3}}); });
  ui.choose(0); ui.saveNow();
  await waitFor(() => ui.status.dataset.state === 'conflict', 'no conflict');
  assert.equal(ui.reload.hidden, false); assert.equal(ui.save.disabled, true); assert.equal(ui.submit.disabled, true);
  assert.equal(ui.radios[0].checked, true); assert.equal(ui.hiddenRevision.value, '0');
  ui.choose(1); ui.saveNow(); ui.form.requestSubmit(ui.submit);
  await pause(550); assert.equal(calls, 1); assert.equal(ui.nativeSubmits, 0);
});

test('closed and unavailable 409 responses require explicit reload', async () => {
  for (const state of ['submitted', 'unavailable']) {
    const ui = setup(async () => response({ok: false, status: 409, result: {status: state, error: 'Lượt làm đã đóng.'}}));
    ui.choose(0); ui.saveNow();
    await waitFor(() => ui.status.dataset.state === 'conflict', 'no closed lock');
    assert.equal(ui.submit.disabled, true); assert.match(ui.status.textContent, /đã đóng/);
  }
});

test('server-rendered conflict starts locked and leaves posted choices intact', () => {
  const ui = setup(async () => { throw Error('must not save'); }, {conflict: true, revision: '4'});
  assert.equal(ui.status.dataset.state, 'conflict'); assert.equal(ui.submit.disabled, true);
  ui.choose(1); ui.saveNow(); assert.equal(ui.radios[1].checked, true); assert.equal(ui.hiddenRevision.value, '4');
});

test('invalid initial revision requires reload', () => {
  for (const revision of ['bad', '-1', '1.5']) {
    const ui = setup(async () => response(), {revision}); assert.equal(ui.submit.disabled, true);
  }
});

test('login redirect and malformed ACK retain unsaved warning and allow retry', async () => {
  for (const result of [response({redirected: true, jsonError: Error('HTML')}), response({result: {saved_count: 1, last_saved_at: 'now'}}), response({result: {saved_count: 1, last_saved_at: 'now', draft_revision: 8}})]) {
    const ui = setup(async () => result); ui.choose(0); ui.saveNow();
    await waitFor(() => ui.status.dataset.state === 'error', 'invalid response accepted');
    assert.equal(ui.hiddenRevision.value, '0'); assert.equal(ui.save.disabled, false); assert.equal(ui.listeners.has('beforeunload'), true);
  }
});

test('timeout ends request even if fetch ignores abort; late ACK cannot advance revision', async () => {
  let resolve, signal;
  const ui = setup((_, opts) => { signal = opts.signal; return new Promise((r) => { resolve = r; }); }, {shortTimeout: true});
  ui.choose(0); ui.saveNow();
  await waitFor(() => ui.status.dataset.state === 'error', 'timeout failed');
  assert.equal(signal.aborted, true); assert.equal(ui.save.disabled, false); assert.equal(ui.listeners.has('beforeunload'), true);
  resolve(response()); await pause();
  assert.equal(ui.hiddenRevision.value, '0'); assert.equal(ui.status.dataset.state, 'error');
});

test('submit waits active ACK and posts current revision with newest visible answer', async () => {
  let resolve; const ui = setup(() => new Promise((r) => { resolve = r; }));
  ui.choose(0); ui.saveNow(); ui.choose(1);
  const first = ui.form.requestSubmit(ui.submit); assert.equal(first.defaultPrevented, true); assert.equal(ui.nativeSubmits, 0);
  ui.form.requestSubmit(ui.submit); // duplicate click during wait
  resolve(response());
  await waitFor(() => ui.nativeSubmits === 1, 'submit not resumed'); await pause();
  assert.deepEqual(ui.nativePayloads, [{revision: '1', answer: '102'}]);
  assert.equal(ui.listeners.has('beforeunload'), false); assert.equal(ui.submit.disabled, true);
});

test('conflict or failure during submit wait prevents automatic submit', async () => {
  for (const reply of [response({ok: false, status: 409, result: {error: 'Conflict'}}), response({ok: false, status: 500})]) {
    let resolve; const ui = setup(() => new Promise((r) => { resolve = r; }));
    ui.choose(0); ui.saveNow(); ui.form.requestSubmit(ui.submit); resolve(reply);
    await waitFor(() => ['conflict', 'error'].includes(ui.status.dataset.state), 'failure missing');
    await pause(); assert.equal(ui.nativeSubmits, 0); assert.equal(ui.listeners.has('beforeunload'), true);
  }
});

test('cancelled real submit resumes autosave and keeps choices', async () => {
  let calls = 0;
  const ui = setup(async () => { calls += 1; return response(); }, {cancelNative: true});
  ui.choose(0); ui.form.requestSubmit(ui.submit); await pause();
  assert.equal(ui.submit.disabled, false); assert.equal(ui.listeners.has('beforeunload'), true);
  await waitFor(() => calls === 1, 'autosave did not resume');
  await waitFor(() => ui.status.dataset.state === 'saved', 'ack missing');
});

test('two immediate final submits generate one native request', async () => {
  const ui = setup(async () => response());
  ui.choose(0); ui.form.requestSubmit(ui.submit); ui.form.requestSubmit(ui.submit);
  await pause(); assert.equal(ui.nativeSubmits, 1); assert.equal(ui.submit.disabled, true);
  assert.equal(ui.listeners.has('beforeunload'), false);
});

test('BFCache restoration locks without saving and ignores an old in-flight ACK', async () => {
  let resolve, calls = 0;
  const ui = setup(() => { calls += 1; return new Promise((r) => { resolve = r; }); });
  ui.choose(0); ui.saveNow(); ui.listeners.get('pageshow')({persisted: true});
  resolve(response()); await pause(); ui.choose(1); ui.saveNow(); ui.form.requestSubmit(ui.submit);
  assert.equal(ui.status.dataset.state, 'conflict'); assert.equal(ui.hiddenRevision.value, '0');
  assert.equal(ui.radios[1].checked, true); assert.equal(ui.nativeSubmits, 0); assert.equal(calls, 1);
});

test('BFCache restoration after final submit also requires explicit reload', async () => {
  let calls = 0; const ui = setup(async () => { calls += 1; return response(); });
  ui.form.requestSubmit(ui.submit); await pause(); ui.listeners.get('pageshow')({persisted: true});
  await pause(550); assert.equal(calls, 0); assert.equal(ui.submit.disabled, true); assert.equal(ui.reload.hidden, false);
});

test('reload action confirms replacement of local choices; cancellation preserves them', () => {
  for (const confirmResult of [true, false]) {
    const ui = setup(async () => response(), {confirmResult, conflict: true});
    ui.choose(1); ui.reload.emit('click'); assert.equal(ui.reloads, confirmResult ? 1 : 0);
    assert.equal(ui.radios[1].checked, true);
  }
});

test('confirmed abandon cancels pending/inflight saves and ignores late ACK', async () => {
  let resolve; const ui = setup(() => new Promise((r) => { resolve = r; }));
  ui.choose(0); ui.saveNow(); const evt = event(); ui.abandon.emit('submit', evt); resolve(response()); await pause();
  assert.equal(evt.defaultPrevented, false); assert.equal(ui.listeners.has('beforeunload'), false); assert.equal(ui.hiddenRevision.value, '0');
});

test('cancelled abandon leaves pending autosave operational', async () => {
  let calls = 0; const ui = setup(async () => { calls += 1; return response(); }, {confirmResult: false});
  ui.choose(0); const evt = event(); ui.abandon.emit('submit', evt); assert.equal(evt.defaultPrevented, true);
  ui.saveNow(); await waitFor(() => ui.status.dataset.state === 'saved', 'autosave disabled after cancel'); assert.equal(calls, 1);
});


test('shared owner confirms incomplete practice once after ACK and cancellation stays usable', async () => {
  let resolve; const ui = setup(() => new Promise((r) => { resolve = r; }), {total: '2', confirmResult: false});
  ui.choose(0); ui.saveNow(); ui.form.requestSubmit(ui.submit);
  assert.equal(ui.confirms, 0, 'do not confirm a submit while it only waits for an ACK');
  resolve(response()); await pause(); await pause();
  assert.equal(ui.confirms, 1); assert.equal(ui.nativeSubmits, 0); assert.equal(ui.submit.disabled, false);
  ui.choose(1); assert.equal(ui.listeners.has('beforeunload'), true);
  ui.form.requestSubmit(ui.submit); assert.equal(ui.confirms, 2); assert.equal(ui.submit.disabled, false);
  ui.abandon.emit('submit', event()); // cancelled: keeps choices; manually save to clear timer
  ui.saveNow(); resolve(response({result: {saved_count: 1, last_saved_at: '2026-10-19T12:30:00Z', draft_revision: 2}})); await pause();
});

test('another listener cancelling after a native microtask checkpoint restores controls and warning', async () => {
  const ui = setup(async () => response()); ui.choose(0);
  const evt = event(); ui.form.emit('submit', evt);
  await Promise.resolve(); // simulate checkpoint before a later bubbling handler
  evt.preventDefault(); await pause();
  assert.equal(ui.submit.disabled, false); assert.equal(ui.listeners.has('beforeunload'), true);
  ui.saveNow(); await waitFor(() => ui.status.dataset.state === 'saved', 'cancelled submit cannot save');
});

test('mistake review uses shared lifecycle without introducing practice confirmation', async () => {
  const ui = setup(async () => response(), {practice: false, total: '2', confirmResult: false});
  ui.form.requestSubmit(ui.submit); await pause();
  assert.equal(ui.nativeSubmits, 1); assert.equal(ui.confirms, 0);
});
