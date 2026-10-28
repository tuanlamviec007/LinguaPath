"""Server-side transport to the authenticated Workers AI bridge."""
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from django.conf import settings


def provider_name():
    return os.environ.get('AI_TUTOR_PROVIDER', 'openai').strip().lower()


def bridge_configuration():
    endpoint = os.environ.get('CLOUDFLARE_AI_ENDPOINT', '').strip()
    secret = os.environ.get('AI_BRIDGE_SECRET', '').strip()
    parts = urlsplit(endpoint)
    allowed_hosts = (set(settings.ALLOWED_HOSTS) | set(getattr(settings, 'CLOUDFLARE_AI_ALLOWED_HOSTS', []))) - {'*'}
    valid = (
        parts.scheme == 'https' and parts.hostname in allowed_hosts
        and parts.path == '/internal/tutor/infer' and parts.port in (None, 443)
        and not parts.username and not parts.password and not parts.query and not parts.fragment
        and 32 <= len(secret) <= 256
    )
    return (endpoint, secret) if valid else ('', '')


def tutor_ai_available():
    if not settings.AI_TUTOR_ENABLED:
        return False
    if provider_name() == 'cloudflare':
        try:
            return bool(bridge_configuration()[0])
        except ValueError:
            return False
    return provider_name() == 'openai' and bool(os.environ.get('OPENAI_API_KEY', '').strip())


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward the internal credential to a redirect target.
        return None


def cloudflare_rag_request(operation, payload, *, index=False):
    if operation not in ('infer', 'search', 'index') or index != (operation == 'index'):
        raise ValueError('Invalid bridge operation')
    endpoint, secret = bridge_configuration()
    if index:
        secret = os.environ.get('AI_INDEX_SECRET', '').strip()
    if not endpoint or not 32 <= len(secret) <= 256:
        raise ValueError('Workers AI bridge is not configured')
    endpoint = endpoint.removesuffix('/internal/tutor/infer') + '/internal/tutor/' + operation
    encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    if len(encoded) > 24576:
        raise ValueError('Bridge request too large')
    request = Request(endpoint, data=encoded, method='POST', headers={
        'Authorization': f'Bearer {secret}', 'Content-Type': 'application/json', 'Accept': 'application/json',
        'User-Agent': 'LinguaPath-Tutor-Service/1.0',
    })
    with build_opener(NoRedirect()).open(request, timeout=25) as response:
        raw = response.read(32769)
    if len(raw) > 32768:
        raise ValueError('Workers AI response is too large')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('Invalid bridge response')
    return result


def generate_cloudflare_answer(query, context, *, task='explain', include_metadata=False, history=None):
    endpoint, secret = bridge_configuration()
    if not endpoint:
        raise ValueError('Workers AI bridge is not configured')
    payload = {'query': query[:500], 'context': context[:5400]}
    if history:
        payload['history'] = [{'role': m['role'], 'content': m['content'][:1000]} for m in history[-6:]]
        while payload['history'] and len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) > 24576:
            payload['history'] = payload['history'][2:]
    if task != 'explain':
        if task not in ('draft_part5', 'chat'):
            raise ValueError('Unknown AI task')
        payload['task'] = task
    payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = Request(endpoint, data=payload, method='POST', headers={
        'Authorization': f'Bearer {secret}', 'Content-Type': 'application/json',
        'Accept': 'application/json', 'User-Agent': 'LinguaPath-Tutor-Service/1.0',
    })
    with build_opener(NoRedirect()).open(request, timeout=45 if task == 'draft_part5' else 25) as response:
        raw = response.read(32769)
    if len(raw) > 32768:
        raise ValueError('Workers AI response is too large')
    result = json.loads(raw)
    answer = result.get('answer') if isinstance(result, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError('Workers AI response has no answer')
    answer = answer.strip()[:6000]
    if not include_metadata:
        return answer
    # Older bridges do not report these fields. Do not invent a model identity
    # from the Django environment: model selection happens inside the Worker.
    def metadata_text(key, length):
        value = result.get(key)
        return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= length else None
    return {'answer': answer, 'provider': 'cloudflare',
            'model': metadata_text('model', 200),
            'prompt_version': metadata_text('prompt_version', 100)}
