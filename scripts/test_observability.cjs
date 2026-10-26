const {test} = require('node:test');
const assert = require('node:assert/strict');
const router = import('../deploy/cloudflare/router.js');

function environment(fetch) {
  return {DJANGO_ALLOWED_HOSTS: 'learn.example', DJANGO_SECRET_KEY: 'private-secret',
    DATABASE_URL: 'private-database', APP: {getByName: () => ({fetch})}};
}

async function capture(callback) {
  const records = [];
  const info = console.info, error = console.error;
  console.info = value => records.push(JSON.parse(value));
  console.error = value => records.push(JSON.parse(value));
  try { return {value: await callback(), records}; }
  finally {console.info = info; console.error = error;}
}

test('edge generates correlation IDs and logs no body, credentials, path, IP or query', async () => {
  const {default: worker} = await router;
  const djangoID = '838a8366-3077-43f8-9b75-d5b15f96c574';
  let forwardedEdgeID;
  const env = environment(async request => {
    assert.equal(request.headers.get('X-Request-ID'), null);
    forwardedEdgeID = request.headers.get('X-Edge-Request-ID');
    assert.notEqual(forwardedEdgeID, 'spoofed-edge');
    assert.equal(await request.text(), 'private-prompt-body');
    return new Response('ok', {headers: {'X-Request-ID': djangoID}});
  });
  const {value: response, records} = await capture(() => worker.fetch(new Request('https://learn.example/private-path/?token=private-query', {
    method: 'POST', body: 'private-prompt-body', headers: {Authorization: 'Bearer private-authorization',
      'Cookie': 'sessionid=private-cookie', 'CF-Connecting-IP': '192.0.2.1',
      'X-Request-ID': 'spoofed-request', 'X-Edge-Request-ID': 'spoofed-edge'},
  }), env));
  assert.equal(response.headers.get('X-Edge-Request-ID'), forwardedEdgeID);
  assert.equal(response.headers.get('X-Request-ID'), djangoID);
  assert.equal(records.length, 1);
  assert.deepEqual(Object.keys(records[0]).sort(), ['event','edge_request_id','request_id','method','category','status','duration_ms'].sort());
  assert.equal(records[0].request_id, djangoID);
  assert.equal(records[0].category, 'application');
  assert.doesNotMatch(JSON.stringify(records), /private|spoofed|192\.0\.2\.1/);
});

test('edge outage and health failures retain a generic category, status and fresh ID', async () => {
  const {default: worker} = await router;
  const env = environment(() => {throw new Error('private-connection-token');});
  const {value: response, records} = await capture(() => worker.fetch(new Request('https://learn.example/healthz/?token=private-query'), env));
  assert.equal(response.status, 503);
  assert.equal(records[0].category, 'readiness');
  assert.equal(records[0].status, 503);
  assert.equal(records[0].edge_request_id, response.headers.get('X-Edge-Request-ID'));
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.doesNotMatch(JSON.stringify(records) + await response.text(), /private|token|connection/);
});

test('edge marks early rejection and ignores non-UUID upstream correlation text', async () => {
  const {default: worker} = await router;
  const env = environment(() => new Response('ok', {headers: {'X-Request-ID': 'private-upstream-text'}}));
  const result = await capture(async () => [
    await worker.fetch(new Request('https://rejected.example/private-path'), env),
    await worker.fetch(new Request('https://learn.example/'), env),
  ]);
  assert.equal(result.value[0].status, 400);
  assert.ok(result.value[0].headers.get('X-Edge-Request-ID'));
  assert.equal(result.records.length, 2);
  assert.notEqual(result.records[0].edge_request_id, result.records[1].edge_request_id);
  assert.equal(result.records[1].request_id, undefined);
  assert.doesNotMatch(JSON.stringify(result.records), /private|rejected\.example/);
});
