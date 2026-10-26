import { handleTutorInference } from './ai-gateway.js';

function clientIPFromEdge(request) {
  const value = request.headers.get('CF-Connecting-IP') || '';
  if (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(value)) {
    return value.split('.').every(part => Number(part) <= 255 && String(Number(part)) === part) ? value : '';
  }
  if (!value.includes(':') || !/^[0-9a-f:.]+$/i.test(value)) return '';
  try {
    // Parsing validates IPv6 locally; it never opens a network connection.
    return new URL(`http://[${value}]/`).hostname.slice(1, -1);
  } catch { return ''; }
}

async function routeRequest(request, env, edgeID) {
    const url = new URL(request.url);
    if (url.protocol !== 'https:') {
      url.protocol = 'https:';
      return Response.redirect(url.toString(), 308);
    }
    const allowed = (env.DJANGO_ALLOWED_HOSTS || '').split(',').map(h => h.trim());
    if (!allowed.includes(url.hostname)) return new Response('Invalid host', { status: 400 });
    if (url.pathname === '/internal/tutor/infer') return handleTutorInference(request, env);
    if (url.pathname.startsWith('/internal/')) return new Response('Not found', {status: 404});
    if (!env.DJANGO_SECRET_KEY || !env.DATABASE_URL) {
      return new Response('Service configuration incomplete', { status: 503 });
    }
    // The container port is reachable through this Worker only. Never trust
    // a client-supplied forwarding header when Django decides whether TLS is on.
    const forwarded = new Request(request);
    forwarded.headers.set('X-Forwarded-Proto', 'https');
    forwarded.headers.set('Host', url.host);
    forwarded.headers.delete('Forwarded');
    forwarded.headers.delete('X-Forwarded-Host');
    forwarded.headers.delete('X-Forwarded-For');
    forwarded.headers.delete('X-Real-IP');
    // The browser never chooses either correlation identifier. Django creates
    // its own request ID; the edge ID is for the independently logged hop.
    forwarded.headers.delete('X-Request-ID');
    forwarded.headers.set('X-Edge-Request-ID', edgeID);
    // Overwrite client-supplied private headers using the Cloudflare edge
    // value. Django still requires an explicit trusted direct-peer CIDR.
    forwarded.headers.delete('X-LinguaPath-Client-IP');
    const clientIP = clientIPFromEdge(request);
    if (clientIP) forwarded.headers.set('X-LinguaPath-Client-IP', clientIP);
    try {
      return await env.APP.getByName('linguapath-production').fetch(forwarded);
    } catch {
      return new Response('Service temporarily unavailable', {
        status: 503, headers: { 'Cache-Control': 'no-store', 'Retry-After': '15' },
      });
    }
}

export default {
  async fetch(request, env) {
    const edgeID = crypto.randomUUID();
    const started = Date.now();
    let response;
    try {
      response = await routeRequest(request, env, edgeID);
    } catch {
      // No raw URL, request payload, credential or exception is serialized.
      response = new Response('Service temporarily unavailable', {
        status: 503, headers: {'Cache-Control': 'no-store', 'Retry-After': '15'},
      });
    }
    const path = new URL(request.url).pathname;
    const category = path === '/healthz/' ? 'readiness' : path === '/livez/' ? 'liveness'
      : path === '/internal/tutor/infer' ? 'internal_ai' : 'application';
    const record = {event: 'worker_request', edge_request_id: edgeID,
      method: ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'].includes(request.method) ? request.method : 'OTHER',
      category, status: response.status, duration_ms: Math.max(0, Date.now() - started)};
    const requestID = response.headers.get('X-Request-ID');
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(requestID || '')) record.request_id = requestID;
    try {
      if (response.status >= 500) console.error(JSON.stringify(record));
      else console.info(JSON.stringify(record));
    } catch { /* A log collector failure must not break the response. */ }
    const outgoing = new Response(response.body, response);
    outgoing.headers.set('X-Edge-Request-ID', edgeID);
    return outgoing;
  },
};
