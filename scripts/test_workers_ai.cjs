const {test} = require('node:test');
const assert = require('node:assert/strict');
const gateway = import('../deploy/cloudflare/ai-gateway.js');
const router = import('../deploy/cloudflare/router.js');
const secret = 'test-only-internal-key-'.repeat(3);
function request(payload = {query: 'despite và although?', context: 'Despite + noun; although + clause.'}, headers = {}) {
  return new Request('https://learn.example/internal/tutor/infer', {
    method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + secret, ...headers},
    body: JSON.stringify(payload),
  });
}
function storage() {
  const state = new Map();
  let tail = Promise.resolve();
  return {
    state,
    transaction(callback) {
      const next = tail.then(() => callback({
        get: async key => structuredClone(state.get(key)),
        put: async (key, value) => state.set(key, structuredClone(value)),
      }));
      tail = next.catch(() => {});
      return next;
    },
  };
}
function environment() {
  return {AI_TUTOR_ENABLED: 'true', AI_BRIDGE_SECRET: secret,
    AI: {run: async () => ({response: 'Giải thích từ nguồn.'})},
    AI_TUTOR_GLOBAL_DAILY_LIMIT: '200', AI_TUTOR_GLOBAL_MINUTE_LIMIT: '20'};
}

test('bridge rejects public, incorrect, short-secret, GET and disabled requests without inference', async () => {
  const {handleTutorInference} = await gateway;
  const env = environment();
  let calls = 0;
  env.AI_BUDGET = {getByName: () => {calls++; throw Error('unexpected');}};
  assert.equal((await handleTutorInference(request(undefined, {Authorization: ''}), env)).status, 401);
  assert.equal((await handleTutorInference(request(undefined, {Authorization: 'Bearer wrong'}), env)).status, 401);
  assert.equal((await handleTutorInference(request(), {...env, AI_BRIDGE_SECRET: 'short'})).status, 401);
  assert.equal((await handleTutorInference(new Request('https://learn.example/internal/tutor/infer'), env)).status, 405);
  assert.equal((await handleTutorInference(request(), {...env, AI_TUTOR_ENABLED: 'false'})).status, 503);
  assert.equal(calls, 0);
});

test('bridge validates payload bounds, schema and body size even without Content-Length', async () => {
  const {handleTutorInference} = await gateway;
  const env = environment();
  env.AI_BUDGET = {getByName: () => {throw Error('must not invoke');}};
  for (const payload of [{}, null, [], {query: 'q', context: 'c', model: 'attacker'}, {query: '', context: 'c'},
    {query: 'q'.repeat(501), context: 'c'}, {query: 'q', context: 'c'.repeat(6001)}, {query: 1, context: 'c'}]) {
    assert.equal((await handleTutorInference(request(payload), env)).status, 400);
  }
  const large = new Request('https://learn.example/internal/tutor/infer', {
    method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + secret}, body: 'x'.repeat(24577),
  });
  assert.equal((await handleTutorInference(large, env)).status, 400);
});

test('authorized request travels through global budget and returns bounded uncached answer', async () => {
  const {handleTutorInference, handleBudgetedInference} = await gateway;
  const env = environment(), ledger = storage();
  let called = 0;
  env.AI.run = async (model, input) => {
    called++;
    assert.equal(model, '@cf/meta/llama-3.3-70b-instruct-fp8-fast');
    assert.equal(input.max_tokens, 450);
    assert.equal(input.stream, false);
    assert.deepEqual(input.messages.map(message => message.role), ['system', 'user']);
    assert.equal(JSON.parse(input.messages[1].content).learner_question, 'despite và although?');
    return {response: 'A'.repeat(7000)};
  };
  env.AI_BUDGET = {getByName: name => {
    assert.equal(name, 'tutor-global');
    return {fetch: req => handleBudgetedInference(req, env, ledger)};
  }};
  const response = await handleTutorInference(request(), env);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  const generated = await response.json();
  assert.equal(generated.answer.length, 6000);
  assert.equal(generated.model, '@cf/meta/llama-3.3-70b-instruct-fp8-fast');
  assert.equal(generated.prompt_version, 'cloudflare-explain-v1');
  assert.equal(called, 1);
});

test('concurrent requests reserve global quota before generation', async () => {
  const {handleBudgetedInference} = await gateway;
  const env = environment(), ledger = storage();
  env.AI_TUTOR_GLOBAL_DAILY_LIMIT = '2';
  let calls = 0;
  env.AI.run = async () => {calls++; return {response: 'Answer'};};
  const responses = await Promise.all(Array.from({length: 8}, () => handleBudgetedInference(request(), env, ledger, Date.UTC(2026, 9, 21))));
  assert.equal(responses.filter(response => response.status === 200).length, 2);
  assert.equal(responses.filter(response => response.status === 429).length, 6);
  assert.equal(calls, 2);
});

test('global minute and UTC day reset independently; failures still consume a reservation', async () => {
  const {handleBudgetedInference} = await gateway;
  const env = environment(), ledger = storage();
  const now = Date.UTC(2026, 9, 21);
  env.AI_TUTOR_GLOBAL_DAILY_LIMIT = '2';
  env.AI_TUTOR_GLOBAL_MINUTE_LIMIT = '1';
  env.AI.run = async () => {throw Error('private prompt/token/detail');};
  let response = await handleBudgetedInference(request(), env, ledger, now);
  assert.equal(response.status, 503);
  assert.doesNotMatch(await response.text(), /private/);
  assert.equal((await handleBudgetedInference(request(), env, ledger, now + 1000)).status, 429);
  env.AI.run = async () => ({response: 'Answer'});
  assert.equal((await handleBudgetedInference(request(), env, ledger, now + 60000)).status, 200);
  assert.equal((await handleBudgetedInference(request(), env, ledger, now + 120000)).status, 429);
  assert.equal((await handleBudgetedInference(request(), env, ledger, now + 86400000)).status, 200);
});

test('storage errors and invalid caps fail closed; empty provider answer is generic', async () => {
  const {handleBudgetedInference} = await gateway;
  const env = environment();
  const failed = {transaction: async () => {throw Error('private storage');}};
  assert.equal((await handleBudgetedInference(request(), env, failed)).status, 503);
  for (const cap of ['NaN', '-1', '10001', '0']) {
    assert.equal((await handleBudgetedInference(request(), {...env, AI_TUTOR_GLOBAL_DAILY_LIMIT: cap}, storage())).status, 429);
  }
  env.AI.run = async () => ({response: ''});
  assert.equal((await handleBudgetedInference(request(), env, storage())).status, 503);
});

test('ingress internal route never forwards browser credentials to Django', async () => {
  const {default: worker} = await router;
  const env = {...environment(), DJANGO_ALLOWED_HOSTS: 'learn.example', APP: {getByName: () => {throw Error('must not forward');}}};
  assert.equal((await worker.fetch(request(undefined, {Authorization: ''}), env)).status, 401);
  assert.equal((await worker.fetch(new Request('https://learn.example/internal/anything'), env)).status, 404);
});

test('draft task has a separate fixed schema prompt and bounded output tokens', async () => {
  const {handleBudgetedInference} = await gateway;
  const env = environment();
  env.AI.run = async (model, input) => {
    assert.equal(input.max_tokens, 1200);
    assert.match(input.messages[0].content, /exactly 3/);
    assert.match(input.messages[0].content, /unreviewed drafts/);
    return {response: '{"questions":[]}'};
  };
  const response = await handleBudgetedInference(request({task: 'draft_part5', query: 'Create drafts', context: 'Grammar note'}), env, storage());
  assert.equal(response.status, 200);
  assert.equal((await response.json()).prompt_version, 'cloudflare-draft-v1');
  const invalid = await handleBudgetedInference(request({task: 'arbitrary_tool', query: 'x', context: 'y'}), env, storage());
  assert.equal(invalid.status, 400);
});

test('bridge reports the model identifier selected by the Worker environment', async () => {
  const {handleBudgetedInference} = await gateway;
  const env = {...environment(), AI_TUTOR_MODEL: '@cf/custom-selection'};
  env.AI.run = async model => {assert.equal(model, '@cf/custom-selection'); return {response: 'Answer'};};
  const result = await (await handleBudgetedInference(request(), env, storage())).json();
  assert.equal(result.model, '@cf/custom-selection');
});
