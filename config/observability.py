"""Small, allowlisted HTTP events without learner content or credentials.

Ordinary Python/Django log messages may contain URLs and exception details.
The formatter deliberately does not serialize their message, args, request,
stack or traceback. Use explicit, bounded fields for actionable events.
"""
import json
import logging
import math
import re
import time
import uuid
from datetime import datetime, timezone


_REQUEST_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z')
_METHODS = {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'}
_EVENTS = {'http_request', 'readiness_failure', 'application_log', 'gunicorn_request'}
_LEVELS = {logging.DEBUG: 'debug', logging.INFO: 'info', logging.WARNING: 'warning',
           logging.ERROR: 'error', logging.CRITICAL: 'critical'}
logger = logging.getLogger('linguapath.http')


def _request_id(value):
    return value if isinstance(value, str) and _REQUEST_ID.fullmatch(value) else None


def _status(value):
    return value if type(value) is int and 100 <= value <= 599 else None


class SafeJSONFormatter(logging.Formatter):
    """Allowlist fields; never render a raw message or exception as a fallback."""

    def format(self, record):
        result = {
            'time': datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            'level': _LEVELS.get(record.levelno, 'info'),
        }
        data = getattr(record, 'observation', None)
        if not isinstance(data, dict) or not isinstance(data.get('event'), str) or data['event'] not in _EVENTS:
            data = {'event': 'application_log'}
        result['event'] = 'gunicorn_event' if data['event'] == 'application_log' and record.name == 'gunicorn.error' else data['event']
        request = getattr(record, 'request', None)
        correlation = _request_id(data.get('request_id')) or _request_id(getattr(request, 'request_id', None))
        if correlation:
            result['request_id'] = correlation
        status = _status(data.get('status')) or _status(getattr(record, 'status_code', None))
        if status is not None:
            result['status'] = status
        if data['event'] in {'http_request', 'readiness_failure', 'gunicorn_request'}:
            method = data.get('method')
            result['method'] = method if isinstance(method, str) and method in _METHODS else 'OTHER'
            # Only middleware-owned route templates enter this field. Never
            # fall back to request.path, get_full_path(), raw URI or query.
            route = data.get('route')
            result['route'] = route if isinstance(route, str) and len(route) <= 160 and not any(ord(c) < 32 for c in route) else '<unmatched>'
            duration = data.get('duration_ms')
            if type(duration) in (int, float) and math.isfinite(duration) and duration >= 0:
                result['duration_ms'] = round(duration, 2)
        if data['event'] == 'application_log':
            result['code'] = ('server_error' if record.levelno >= logging.ERROR else 'server_lifecycle') if record.name == 'gunicorn.error' else 'message_redacted'
        return json.dumps(result, ensure_ascii=False, separators=(',', ':'))


def observation_logging_config():
    """Console only; collection, retention and alert delivery are separate work."""
    handler = {'class': 'logging.StreamHandler', 'formatter': 'safe_json'}
    protected = {'handlers': ['safe_console'], 'level': 'WARNING', 'propagate': False}
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {'safe_json': {'()': 'config.observability.SafeJSONFormatter'}},
        'handlers': {'safe_console': handler},
        'root': {'handlers': ['safe_console'], 'level': 'INFO'},
        'loggers': {
            'linguapath.http': {'handlers': ['safe_console'], 'level': 'INFO', 'propagate': False},
            'django': dict(protected),
            'django.request': dict(protected),
            'django.security': dict(protected),
            'django.server': dict(protected),
        },
    }


class RequestObservationMiddleware:
    """Generate a correlation ID independent of all inbound request headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        started = time.monotonic()
        response = self.get_response(request)
        response['X-Request-ID'] = request.request_id
        match = getattr(request, 'resolver_match', None)
        route = getattr(match, 'route', None)
        route = route if isinstance(route, str) else '<unmatched>'
        view_name = getattr(match, 'view_name', '')
        event = 'readiness_failure' if response.status_code >= 500 and view_name == 'readiness' else 'http_request'
        observation = {
            'event': event, 'request_id': request.request_id,
            'method': request.method, 'route': route, 'status': response.status_code,
            'duration_ms': max(0, (time.monotonic() - started) * 1000),
        }
        try:
            logger.log(logging.ERROR if response.status_code >= 500 else logging.INFO,
                       'HTTP observation', extra={'observation': observation})
        except Exception:
            # A failed stdout collector must not take an otherwise healthy
            # learner request down or expose diagnostics to its response.
            pass
        return response


def __getattr__(name):
    # Gunicorn is a POSIX deployment dependency. Keep it lazy so importing
    # Django settings/formatters still works in the user's Windows dev setup.
    if name != 'SafeGunicornLogger':
        raise AttributeError(name)
    from gunicorn.glogging import Logger

    class SafeGunicornLogger(Logger):
        """Keep server error/access channels out of Gunicorn's raw format."""

        def setup(self, cfg):
            super().setup(cfg)
            for channel in (self.error_log, self.access_log):
                for handler in channel.handlers:
                    handler.setFormatter(SafeJSONFormatter())

        def access(self, resp, req, environ, request_time):
            if not self.cfg.accesslog:
                return
            # Deliberately avoid the default atoms(), which collects raw
            # request headers, path/query, remote address and environment.
            status = getattr(resp, 'status_code', None)
            identifier = None
            for key, value in getattr(resp, 'headers', ()):
                if isinstance(key, str) and key.lower() == 'x-request-id':
                    identifier = _request_id(value)
                    break
            data = {'event': 'gunicorn_request', 'status': status,
                    'request_id': identifier, 'method': environ.get('REQUEST_METHOD'),
                    'route': '<server>', 'duration_ms': max(0, request_time.total_seconds() * 1000)}
            try:
                self.access_log.info('Gunicorn HTTP observation', extra={'observation': data})
            except Exception:
                pass

    globals()[name] = SafeGunicornLogger
    return SafeGunicornLogger
