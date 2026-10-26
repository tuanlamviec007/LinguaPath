#!/usr/bin/env python3
"""Exercise a local image against the disposable GitHub Actions PostgreSQL DB.

This deliberately uses localhost HTTP plus simulated trusted TLS-proxy headers.
It does not verify public HTTPS, Cloudflare ingress, backup/restore or load.
Only a prebuilt linguapath-ci image and the exact CI database are accepted.
"""
import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import http.client
from http.cookies import SimpleCookie
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit
from uuid import uuid4


HOST = 'linguapath.example'
MAX_BODY = 512 * 1024
IMAGE = re.compile(r'^linguapath-ci:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')
CREATE_USER = '''
import os
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from planner.models import LearnerProfile
assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql'
assert settings.DATABASES['default']['NAME'] == 'linguapath_ci'
assert os.environ['SMOKE_USERNAME'].startswith('ci_smoke_')
with transaction.atomic():
    user = get_user_model().objects.create_user(username=os.environ['SMOKE_USERNAME'], password=os.environ['SMOKE_PASSWORD'])
    LearnerProfile.objects.create(user=user, onboarding_complete=True)
'''
DELETE_USER = '''
import os
from django.conf import settings
from django.contrib.auth import get_user_model
assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql'
assert settings.DATABASES['default']['NAME'] == 'linguapath_ci'
assert os.environ['SMOKE_USERNAME'].startswith('ci_smoke_')
get_user_model().objects.filter(username=os.environ['SMOKE_USERNAME'], is_staff=False, is_superuser=False).delete()
'''


class SmokeFailure(Exception):
    """A public error code; never carry stderr, bodies or credentials."""


def validate_config(image, database_url, port, env, platform=None):
    if not (platform or sys.platform).startswith('linux'):
        raise SmokeFailure('linux_ci_required')
    if env.get('GITHUB_ACTIONS') != 'true' or env.get('CI') != 'true':
        raise SmokeFailure('disposable_github_ci_required')
    if not isinstance(image, str) or not IMAGE.fullmatch(image):
        raise SmokeFailure('prebuilt_ci_image_required')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise SmokeFailure('invalid_smoke_port')
    try:
        parsed = urlsplit(database_url)
        safe = (parsed.scheme in ('postgres', 'postgresql') and parsed.hostname == '127.0.0.1'
                and parsed.port in (None, 5432) and parsed.path == '/linguapath_ci'
                and parsed.username == 'linguapath_ci' and bool(parsed.password)
                and not parsed.query and not parsed.fragment)
    except (TypeError, ValueError):
        safe = False
    if not safe:
        raise SmokeFailure('disposable_loopback_database_required')


class TokenParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tokens = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'input' and values.get('name') == 'csrfmiddlewaretoken':
            value = values.get('value', '')
            if re.fullmatch(r'[A-Za-z0-9]{32,64}', value):
                self.tokens.append(value)


def csrf_token(body):
    parser = TokenParser()
    parser.feed(body.decode('utf-8', errors='replace'))
    if len(parser.tokens) != 1:
        raise SmokeFailure('csrf_form_token_missing')
    return parser.tokens[0]


def response_cookies(headers):
    jar = SimpleCookie()
    for name, value in headers:
        if name.lower() == 'set-cookie':
            jar.load(value)
    return jar


def require_secure_cookie(headers, name, *, httponly=False):
    cookie = response_cookies(headers).get(name)
    if cookie is None or not cookie.value or not cookie['secure'] or (httponly and not cookie['httponly']):
        raise SmokeFailure('secure_cookie_missing')
    return cookie.value


def http_request(port, path, *, method='GET', fields=None, cookies=None):
    headers = {'Host': HOST, 'X-Forwarded-Proto': 'https', 'Origin': 'https://' + HOST}
    if cookies:
        headers['Cookie'] = '; '.join(f'{name}={value}' for name, value in cookies.items())
    body = None
    if fields is not None:
        body = urlencode(fields).encode('ascii')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read(MAX_BODY + 1)
        if len(data) > MAX_BODY:
            raise SmokeFailure('http_response_too_large')
        return response.status, response.getheaders(), data
    finally:
        connection.close()


def wait_ready(port, *, request=None, clock=None, pause=None):
    request, clock, pause = request or http_request, clock or time.monotonic, pause or time.sleep
    deadline = clock() + 20
    for _ in range(40):
        try:
            live = request(port, '/livez/')
            ready = request(port, '/healthz/')
            if live[0] == ready[0] == 200:
                for response in (live, ready):
                    cache = ','.join(value for name, value in response[1] if name.lower() == 'cache-control')
                    if 'no-store' not in cache.lower():
                        raise SmokeFailure('health_response_cacheable')
                return
        except (OSError, http.client.HTTPException):
            pass
        if clock() >= deadline:
            break
        pause(.5)
    raise SmokeFailure('container_not_ready')


def login_and_session(port, username, password, *, request=None):
    request = request or http_request
    status, headers, body = request(port, '/accounts/login/')
    if status != 200:
        raise SmokeFailure('login_page_unavailable')
    cookies = {'csrftoken': require_secure_cookie(headers, 'csrftoken')}
    token = csrf_token(body)
    forged = request(port, '/accounts/login/', method='POST', fields={'username': 'csrf-probe'}, cookies=cookies)
    if forged[0] != 403:
        raise SmokeFailure('csrf_request_not_rejected')
    status, headers, _ = request(port, '/accounts/login/', method='POST',
        fields={'username': username, 'password': password, 'csrfmiddlewaretoken': token}, cookies=cookies)
    locations = [value for name, value in headers if name.lower() == 'location']
    if status != 302 or locations != ['/dashboard/']:
        raise SmokeFailure('synthetic_login_failed')
    cookies['sessionid'] = require_secure_cookie(headers, 'sessionid', httponly=True)
    rotated = response_cookies(headers).get('csrftoken')
    if rotated is not None:
        cookies['csrftoken'] = rotated.value
    require_dashboard(port, cookies, request=request)
    return cookies


def require_dashboard(port, cookies, *, request=None):
    status, headers, _ = (request or http_request)(port, '/dashboard/', cookies=cookies)
    cache = ','.join(value for name, value in headers if name.lower() == 'cache-control')
    if status != 200 or 'no-store' not in cache.lower():
        raise SmokeFailure('authenticated_session_not_preserved')


class DockerSmoke:
    def __init__(self, image, port, env):
        self.image, self.port = image, port
        self.name = 'linguapath-smoke-' + uuid4().hex
        self.env = dict(env)
        self.env.update(DJANGO_DEBUG='false', DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
            DJANGO_ALLOWED_HOSTS=HOST, DJANGO_CSRF_TRUSTED_ORIGINS='https://' + HOST,
            DJANGO_SECURE_SSL_REDIRECT='true', DJANGO_SESSION_COOKIE_SECURE='true',
            DJANGO_CSRF_COOKIE_SECURE='true', DJANGO_TRUST_PROXY_SSL_HEADER='true',
            DJANGO_SECURE_HSTS_SECONDS='0', DJANGO_AUTH_TRUSTED_PROXIES='',
            DJANGO_AUTH_CLIENT_IP_HEADER='', AI_TUTOR_ENABLED='false',
            PORT=str(port), WEB_CONCURRENCY='1',
            SMOKE_USERNAME='ci_smoke_' + uuid4().hex, SMOKE_PASSWORD=secrets.token_urlsafe(32))
        self.started = self.fixture_attempted = False

    def command(self, args, *, code=None, timeout=30):
        try:
            completed = subprocess.run(['docker', *args], env=self.env, input=code,
                text=True, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise SmokeFailure('docker_command_failed') from None
        if completed.returncode:
            raise SmokeFailure('docker_command_failed')

    def start(self):
        names = ('DATABASE_URL', 'DJANGO_DEBUG', 'DJANGO_SECRET_KEY', 'DJANGO_ALLOWED_HOSTS',
            'DJANGO_CSRF_TRUSTED_ORIGINS', 'DJANGO_SECURE_SSL_REDIRECT', 'DJANGO_SESSION_COOKIE_SECURE',
            'DJANGO_CSRF_COOKIE_SECURE', 'DJANGO_TRUST_PROXY_SSL_HEADER', 'DJANGO_SECURE_HSTS_SECONDS',
            'DJANGO_AUTH_TRUSTED_PROXIES', 'DJANGO_AUTH_CLIENT_IP_HEADER', 'AI_TUTOR_ENABLED', 'PORT', 'WEB_CONCURRENCY')
        args = ['run', '--detach', '--pull=never', '--name', self.name, '--network', 'host']
        for name in names:
            args.extend(['--env', name])
        # Mark before invocation so a partially created container is removed.
        self.started = True
        self.command([*args, self.image])

    def create_fixture(self):
        self.fixture_attempted = True
        self.command(['exec', '-i', '--env', 'SMOKE_USERNAME', '--env', 'SMOKE_PASSWORD', self.name,
            'python', 'manage.py', 'shell', '--no-imports'], code=CREATE_USER)

    def cleanup(self):
        errors = []
        if self.fixture_attempted:
            try:
                self.command(['exec', '-i', '--env', 'SMOKE_USERNAME', self.name,
                    'python', 'manage.py', 'shell', '--no-imports'], code=DELETE_USER)
            except SmokeFailure:
                errors.append('fixture_cleanup_failed')
        if self.started:
            try:
                self.command(['rm', '--force', self.name])
            except SmokeFailure:
                errors.append('container_cleanup_failed')
        return errors


def run_smoke(image, port=18080, *, env=None):
    env = dict(os.environ if env is None else env)
    report = {'version': 'linguapath-production-smoke-v1', 'generated_at': datetime.now(timezone.utc).isoformat(),
        'status': 'failed', 'tls': 'simulated_proxy_headers', 'checks': [], 'cleanup': [],
        'scope': 'Disposable CI image/PostgreSQL smoke only; not public HTTPS, Cloudflare ingress, load, backup/restore or production approval.'}
    smoke = None
    try:
        validate_config(image, env.get('DATABASE_URL', ''), port, env)
        if shutil.which('docker') is None:
            raise SmokeFailure('docker_unavailable')
        smoke = DockerSmoke(image, port, env)
        smoke.command(['info', '--format', '{{.ServerVersion}}'], timeout=10)
        smoke.start()
        wait_ready(port)
        report['checks'].append({'id': 'liveness_readiness', 'status': 'passed'})
        smoke.create_fixture()
        cookies = login_and_session(port, smoke.env['SMOKE_USERNAME'], smoke.env['SMOKE_PASSWORD'])
        report['checks'].extend([{'id': 'secure_cookies', 'status': 'passed'},
            {'id': 'csrf_rejection', 'status': 'passed'}, {'id': 'synthetic_login', 'status': 'passed'}])
        smoke.command(['restart', smoke.name])
        wait_ready(port)
        require_dashboard(port, cookies)
        report['checks'].append({'id': 'postgres_session_after_restart', 'status': 'passed'})
        report['status'] = 'passed'
    except SmokeFailure as error:
        report['failure'] = str(error)
    except Exception:
        report['failure'] = 'smoke_internal_error'
    finally:
        if smoke is not None:
            report['cleanup'] = smoke.cleanup()
            if report['cleanup']:
                report['status'] = 'failed'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--port', type=int, default=18080)
    args = parser.parse_args(argv)
    report = run_smoke(args.image, args.port)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
