const { test } = require('node:test');
const assert = require('node:assert/strict');

const router = import('../deploy/cloudflare/router.js');
function environment(fetch) {
  return {
    DJANGO_ALLOWED_HOSTS: 'learn.example',
    DJANGO_SECRET_KEY: 'test-only-key',
    DATABASE_URL: 'test-only-database',
    APP: { getByName: name => {
      assert.equal(name, 'linguapath-production');
      return { fetch };
    } },
  };
}

test('overwrites private client IP from edge and removes spoofable forwarding chains', async () => {
  const { default: worker } = await router;
  for (const [edge, expected] of [['192.0.2.9','192.0.2.9'], ['2001:db8::9','2001:db8::9'], ['',null], ['192.0.2.9, 198.51.100.1',null], ['999.0.0.1',null], ['fe80::1%eth0',null], ['bad-value',null]]) {
    const env=environment(async request => {
      assert.equal(request.headers.get('X-LinguaPath-Client-IP'),expected);
      assert.equal(request.headers.get('X-Forwarded-For'),null);
      assert.equal(request.headers.get('X-Real-IP'),null);
      return new Response('ok');
    });
    const response=await worker.fetch(new Request('https://learn.example/accounts/login/', {headers:{
      'CF-Connecting-IP':edge, 'X-LinguaPath-Client-IP':'198.51.100.77',
      'X-Forwarded-For':'198.51.100.77', 'X-Real-IP':'198.51.100.77',
    }}),env);
    assert.equal(response.status,200);
  }
});

test('preserves POST body and cookie while replacing untrusted TLS headers', async () => {
  const { default: worker } = await router;
  const env = environment(async request => {
    assert.equal(request.headers.get('X-Forwarded-Proto'), 'https');
    assert.equal(request.headers.get('Host'), 'learn.example');
    assert.equal(request.headers.get('X-Forwarded-Host'), null);
    assert.equal(request.headers.get('Forwarded'), null);
    assert.equal(request.headers.get('Cookie'), 'sessionid=test-session');
    assert.equal(request.method, 'POST');
    assert.equal(await request.text(), 'answer=2');
    return new Response('saved', { headers: { 'Set-Cookie': 'sessionid=next; Secure; HttpOnly' } });
  });
  const response = await worker.fetch(new Request('https://learn.example/learn/submit/', {
    method: 'POST', body: 'answer=2', headers: {
      'X-Forwarded-Proto': 'http', 'Forwarded': 'proto=http',
      'X-Forwarded-Host': 'attacker.example', 'Cookie': 'sessionid=test-session',
    },
  }), env);
  assert.equal(await response.text(), 'saved');
  assert.match(response.headers.get('Set-Cookie'), /Secure/);
});

test('unknown hostname and missing secrets never forward traffic', async () => {
  const { default: worker } = await router;
  const env = environment(() => { throw new Error('must not forward'); });
  assert.equal((await worker.fetch(new Request('https://attacker.example/'), env)).status, 400);
  delete env.DATABASE_URL;
  assert.equal((await worker.fetch(new Request('https://learn.example/'), env)).status, 503);
});

test('redirects HTTP to HTTPS preserving path and query', async () => {
  const { default: worker } = await router;
  const response = await worker.fetch(new Request('http://learn.example/learn/?page=2'), environment());
  assert.equal(response.status, 308);
  assert.equal(response.headers.get('Location'), 'https://learn.example/learn/?page=2');
});

test('container outage returns uncached generic 503', async () => {
  const { default: worker } = await router;
  const env = environment(() => { throw new Error('private database detail'); });
  const response = await worker.fetch(new Request('https://learn.example/'), env);
  assert.equal(response.status, 503);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.doesNotMatch(await response.text(), /private/);
});
