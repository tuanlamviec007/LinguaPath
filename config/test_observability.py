import json
import logging
import io
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import path

from .observability import RequestObservationMiddleware, SafeJSONFormatter, observation_logging_config


def normal(request, item):
    return HttpResponse('ok')


def readiness(request):
    return HttpResponse('unavailable', status=503)


def broken(request):
    raise RuntimeError('private-exception-secret')


urlpatterns = [path('items/<str:item>/', normal, name='item'),
               path('healthz/', readiness, name='readiness'), path('broken/', broken, name='broken')]


@override_settings(ROOT_URLCONF=__name__, MIDDLEWARE=['config.observability.RequestObservationMiddleware'])
class ObservationMiddlewareTests(SimpleTestCase):
    def test_request_event_uses_template_and_new_ids_without_request_contents(self):
        with self.assertLogs('linguapath.http', level='INFO') as captured:
            first = self.client.post('/items/path-secret/?token=query-secret', 'body-secret',
                content_type='text/plain', HTTP_X_REQUEST_ID='client-secret',
                HTTP_AUTHORIZATION='Bearer header-secret', HTTP_COOKIE='sessionid=cookie-secret')
            second = self.client.get('/items/other/')
        identifier = first['X-Request-ID']
        self.assertRegex(identifier, r'^[0-9a-f-]{36}$')
        self.assertNotEqual(identifier, second['X-Request-ID'])
        payload = json.loads(SafeJSONFormatter().format(captured.records[0]))
        self.assertEqual(payload['route'], 'items/<str:item>/')
        self.assertEqual(payload['request_id'], identifier)
        self.assertEqual((payload['method'], payload['status']), ('POST', 200))
        self.assertGreaterEqual(payload['duration_ms'], 0)
        self.assertNotRegex(json.dumps(payload), r'path-secret|query-secret|body-secret|client-secret|header-secret|cookie-secret')

    def test_readiness_failure_is_a_generic_error_event(self):
        with self.assertLogs('linguapath.http', level='ERROR') as captured:
            response = self.client.get('/healthz/?token=private')
        payload = json.loads(SafeJSONFormatter().format(captured.records[0]))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload['event'], 'readiness_failure')
        self.assertEqual(payload['route'], 'healthz/')
        self.assertEqual(payload['request_id'], response['X-Request-ID'])
        self.assertNotIn('private', json.dumps(payload))

    def test_unmatched_url_never_logs_raw_path(self):
        with self.assertLogs('linguapath.http', level='INFO') as captured:
            response = self.client.get('/not-found-sensitive-value/?password=private')
        self.assertEqual(response.status_code, 404)
        payload = json.loads(SafeJSONFormatter().format(captured.records[0]))
        self.assertEqual(payload['route'], '<unmatched>')
        self.assertNotIn('sensitive', json.dumps(payload))
        self.assertIn('X-Request-ID', response)

    @override_settings(DEBUG=False)
    def test_framework_500_keeps_correlation_and_does_not_log_exception_message(self):
        self.client.raise_request_exception = False
        with self.assertLogs('linguapath.http', level='ERROR') as captured:
            response = self.client.get('/broken/?secret=private')
        self.assertEqual(response.status_code, 500)
        payload = json.loads(SafeJSONFormatter().format(captured.records[0]))
        self.assertEqual(payload['status'], 500)
        self.assertEqual(payload['request_id'], response['X-Request-ID'])
        self.assertNotIn('private', json.dumps(payload))

    def test_logging_failure_does_not_break_response(self):
        middleware = RequestObservationMiddleware(lambda request: HttpResponse('ok'))
        with patch('config.observability.logger.log', side_effect=OSError('private-collector')):
            response = middleware(RequestFactory().get('/'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('X-Request-ID', response)


class SafeFormatterTests(SimpleTestCase):
    def test_arbitrary_messages_arguments_exception_request_and_extra_fields_are_redacted(self):
        try:
            raise RuntimeError('exception-secret')
        except RuntimeError:
            import sys
            record = logging.LogRecord('django.request', logging.ERROR, 'private-filename', 1,
                                       'secret URL %s', ('query-secret',), sys.exc_info())
        record.request = RequestFactory().get('/private-path/?password=private-query')
        record.status_code = 500
        record.token = 'private-token'
        record.observation = {'event': 'unrecognized-secret', 'prompt': 'private-prompt'}
        payload = json.loads(SafeJSONFormatter().format(record))
        self.assertEqual(payload['code'], 'message_redacted')
        self.assertEqual(payload['status'], 500)
        self.assertEqual(payload['level'], 'error')
        self.assertNotRegex(json.dumps(payload), r'private|secret|traceback|exception|URL')

    def test_invalid_structured_values_cannot_inject_a_line_or_raw_request_id(self):
        record = logging.LogRecord('linguapath.http', logging.INFO, '', 1, '', (), None)
        record.observation = {'event': 'http_request', 'request_id': 'private-id',
                              'status': True, 'method': 'private-method',
                              'route': 'private\nroute', 'duration_ms': float('nan'), 'secret': 'private'}
        payload = json.loads(SafeJSONFormatter().format(record))
        self.assertEqual(payload['route'], '<unmatched>')
        self.assertEqual(payload['method'], 'OTHER')
        self.assertNotIn('request_id', payload)
        self.assertNotIn('status', payload)
        self.assertNotIn('duration_ms', payload)
        self.assertNotIn('private', json.dumps(payload))

    def test_logging_configuration_protects_framework_request_and_security_channels(self):
        config = observation_logging_config()
        for name in ('django', 'django.request', 'django.security', 'django.server', 'linguapath.http'):
            self.assertEqual(config['loggers'][name]['handlers'], ['safe_console'])
            self.assertFalse(config['loggers'][name]['propagate'])
        self.assertEqual(config['root']['handlers'], ['safe_console'])

    @skipUnless(os.name == 'posix', 'Gunicorn deployment runtime requires POSIX')
    def test_gunicorn_logger_loads_by_uri_and_redacts_error_and_access_channels(self):
        from gunicorn.config import Config
        cfg = Config()
        cfg.set('logger_class', 'config.observability.SafeGunicornLogger')
        cfg.set('accesslog', '-')
        error, access = logging.getLogger('gunicorn.error'), logging.getLogger('gunicorn.access')
        previous = [(channel, channel.handlers[:], channel.level, channel.propagate) for channel in (error, access)]
        stderr, stdout = io.StringIO(), io.StringIO()
        identifier = '838a8366-3077-43f8-9b75-d5b15f96c574'
        try:
            with patch('sys.stderr', stderr), patch('sys.stdout', stdout):
                server_logger = cfg.logger_class(cfg)
                server_logger.info('Starting server on private-bind-address')
                try:
                    raise RuntimeError('private-stack-secret')
                except RuntimeError:
                    server_logger.exception('Private request /private-path?token=private-query')
                server_logger.access(SimpleNamespace(status_code=503, headers=[('X-Request-ID', identifier)]),
                    object(), {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/private-path', 'QUERY_STRING': 'private-query',
                               'HTTP_AUTHORIZATION': 'private-token', 'REMOTE_ADDR': '192.0.2.1'}, timedelta(milliseconds=14))
            errors = [json.loads(line) for line in stderr.getvalue().splitlines()]
            request = json.loads(stdout.getvalue())
            self.assertEqual([row['code'] for row in errors], ['server_lifecycle', 'server_error'])
            self.assertEqual(request['event'], 'gunicorn_request')
            self.assertEqual(request['request_id'], identifier)
            self.assertEqual((request['status'], request['duration_ms']), (503, 14))
            self.assertNotRegex(stderr.getvalue() + stdout.getvalue(), r'private|192\.0\.2\.1|Traceback|RuntimeError')
        finally:
            for channel, handlers, level, propagate in previous:
                channel.handlers, channel.propagate = handlers, propagate
                channel.setLevel(level)
