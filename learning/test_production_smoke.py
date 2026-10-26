"""Smoke-harness contracts only: this suite never executes Docker or a network."""
from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings
from planner.models import LearnerProfile


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'smoke-production.py'
spec = importlib.util.spec_from_file_location('linguapath_production_smoke', SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
CI_ENV = {'CI': 'true', 'GITHUB_ACTIONS': 'true',
    'DATABASE_URL': 'postgresql://linguapath_ci:ci-only@127.0.0.1:5432/linguapath_ci'}
TOKEN = 'a' * 64


def headers(*, session=False):
    values = [('Set-Cookie', 'csrftoken=csrf-token; Secure; SameSite=Lax')]
    if session:
        values.extend([('Set-Cookie', 'sessionid=session-token; Secure; HttpOnly; SameSite=Lax'),
                       ('Location', '/dashboard/')])
    return values


def login_responses():
    return [(200, headers(), f'<input value="{TOKEN}" name="csrfmiddlewaretoken">'.encode()),
        (403, [], b'csrf rejected'), (302, headers(session=True), b''),
        (200, [('Cache-Control', 'private, no-store')], b'private dashboard')]


class SmokeConfigurationTests(SimpleTestCase):
    def test_requires_exact_disposable_ci_database_before_any_docker_operation(self):
        urls = ['', 'sqlite:////tmp/local.sqlite3',
            'postgresql://linguapath_ci:p@db.example/linguapath_ci',
            'postgresql://linguapath_ci:p@localhost/linguapath_ci',
            'postgresql://linguapath_ci:p@127.0.0.1/production',
            'postgresql://admin:p@127.0.0.1/linguapath_ci',
            'postgresql://linguapath_ci:p@127.0.0.1:5433/linguapath_ci',
            'postgresql://linguapath_ci:p@127.0.0.1/linguapath_ci?options=other',
            'postgresql://linguapath_ci:p@127.0.0.1:invalid/linguapath_ci']
        for url in urls:
            with self.subTest(url=url), patch.object(smoke, 'DockerSmoke') as docker:
                report = smoke.run_smoke('linguapath-ci:abc', env={**CI_ENV, 'DATABASE_URL': url})
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['failure'], 'disposable_loopback_database_required')
                docker.assert_not_called()

    def test_valid_config_is_ci_linux_only_and_restricts_local_image_and_port(self):
        smoke.validate_config('linguapath-ci:abc123', CI_ENV['DATABASE_URL'], 18080, CI_ENV, 'linux')
        for change in ({'image': '--privileged'}, {'image': 'external.example/app:latest'},
                       {'image': 'linguapath-ci:latest;whoami'}, {'port': 80},
                       {'port': True}, {'platform': 'win32'}, {'env': {}}):
            values = dict(image='linguapath-ci:abc', database_url=CI_ENV['DATABASE_URL'], port=18080, env=CI_ENV, platform='linux')
            values.update(change)
            with self.subTest(change=change), self.assertRaises(smoke.SmokeFailure):
                smoke.validate_config(**values)

    def test_missing_docker_fails_clearly_without_installing_or_shell_commands(self):
        with patch.object(smoke.shutil, 'which', return_value=None), patch.object(smoke, 'DockerSmoke') as docker:
            report = smoke.run_smoke('linguapath-ci:abc', env=CI_ENV)
        self.assertEqual(report['failure'], 'docker_unavailable')
        docker.assert_not_called()


class SmokeHTTPTests(SimpleTestCase):
    def test_form_parser_handles_attribute_order_and_rejects_absent_or_ambiguous_tokens(self):
        self.assertEqual(smoke.csrf_token(f'<input value="{TOKEN}" type="hidden" name="csrfmiddlewaretoken">'.encode()), TOKEN)
        for body in (b'no form', b'<input name="csrfmiddlewaretoken" value="bad">',
                     f'<input name="csrfmiddlewaretoken" value="{TOKEN}">' .encode() * 2):
            with self.subTest(body=body[:30]), self.assertRaises(smoke.SmokeFailure): smoke.csrf_token(body)

    def test_secure_session_cookie_requires_httponly(self):
        self.assertEqual(smoke.require_secure_cookie(headers(session=True), 'sessionid', httponly=True), 'session-token')
        for values in ([], [('Set-Cookie', 'sessionid=token; Secure')], [('Set-Cookie', 'sessionid=token; HttpOnly')]):
            with self.assertRaises(smoke.SmokeFailure): smoke.require_secure_cookie(values, 'sessionid', httponly=True)

    def test_login_requires_csrf_rejection_and_uses_same_session_for_dashboard(self):
        request = Mock(side_effect=login_responses())
        cookies = smoke.login_and_session(18080, 'synthetic-user', 'synthetic-password', request=request)
        self.assertEqual(cookies['sessionid'], 'session-token')
        self.assertEqual(request.call_args_list[1].kwargs['fields'], {'username': 'csrf-probe'})
        self.assertEqual(request.call_args_list[2].kwargs['fields']['csrfmiddlewaretoken'], TOKEN)
        self.assertEqual(request.call_args_list[3].kwargs['cookies']['sessionid'], 'session-token')

    def test_login_failure_and_forged_post_acceptance_are_failures(self):
        for position, replacement, error in ((1, (200, [], b''), 'csrf_request_not_rejected'),
                                              (2, (200, [], b''), 'synthetic_login_failed'),
                                              (3, (302, [('Location','/accounts/login/')], b''), 'authenticated_session_not_preserved')):
            responses = login_responses(); responses[position] = replacement
            with self.subTest(position=position), self.assertRaisesMessage(smoke.SmokeFailure, error):
                smoke.login_and_session(18080, 'user', 'password', request=Mock(side_effect=responses))

    def test_readiness_requires_both_noncacheable_endpoints_and_has_a_bounded_wait(self):
        valid = (200, [('Cache-Control', 'no-store')], b'{}')
        request = Mock(return_value=valid)
        smoke.wait_ready(18080, request=request)
        self.assertEqual([call.args[1] for call in request.call_args_list], ['/livez/', '/healthz/'])
        request = Mock(return_value=(503, [], b'')); pause=Mock()
        with self.assertRaisesMessage(smoke.SmokeFailure, 'container_not_ready'):
            smoke.wait_ready(18080, request=request, clock=Mock(side_effect=[0, 21]), pause=pause)
        pause.assert_not_called()
        with self.assertRaisesMessage(smoke.SmokeFailure, 'health_response_cacheable'):
            smoke.wait_ready(18080, request=Mock(return_value=(200, [], b'')))

    def test_http_uses_localhost_proxy_simulation_and_bounds_body_without_logging(self):
        connection = Mock(); response = connection.getresponse.return_value
        response.status=200; response.getheaders.return_value=[]; response.read.return_value=b'{}'
        with patch.object(smoke.http.client, 'HTTPConnection', return_value=connection) as factory:
            smoke.http_request(18080, '/test/', method='POST', fields={'password':'PRIVATE'}, cookies={'sessionid':'SESSION'})
        factory.assert_called_once_with('127.0.0.1',18080,timeout=5)
        self.assertEqual(connection.request.call_args.kwargs['headers']['X-Forwarded-Proto'], 'https')
        self.assertEqual(connection.request.call_args.kwargs['headers']['Host'], smoke.HOST)
        connection.close.assert_called_once()
        response.read.return_value=b'x'*(smoke.MAX_BODY+1)
        with patch.object(smoke.http.client, 'HTTPConnection', return_value=connection), self.assertRaisesMessage(smoke.SmokeFailure, 'http_response_too_large'):
            smoke.http_request(18080, '/')


class SmokeDockerTests(SimpleTestCase):
    def test_docker_passes_secrets_by_environment_names_and_never_pulls_images(self):
        instance = smoke.DockerSmoke('linguapath-ci:abc',18080,CI_ENV)
        with patch.object(smoke.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            instance.start(); instance.create_fixture()
        args = run.call_args_list[0].args[0]
        self.assertIn('--pull=never',args); self.assertIn('host',args)
        all_args = json.dumps([call.args for call in run.call_args_list])
        self.assertNotIn(instance.env['DJANGO_SECRET_KEY'], all_args)
        self.assertNotIn(instance.env['SMOKE_PASSWORD'], all_args)
        self.assertNotIn(CI_ENV['DATABASE_URL'], all_args)
        self.assertIn('DJANGO_SECRET_KEY',args)
        self.assertEqual(run.call_args_list[1].kwargs['input'],smoke.CREATE_USER)
        self.assertNotIn('shell',run.call_args_list[0].kwargs)

    def test_docker_errors_do_not_expose_subprocess_stderr_or_secrets(self):
        instance=smoke.DockerSmoke('linguapath-ci:abc',18080,CI_ENV)
        with patch.object(smoke.subprocess, 'run', return_value=SimpleNamespace(returncode=1,stderr='PRIVATE CONNECTION PASSWORD')):
            with self.assertRaisesMessage(smoke.SmokeFailure,'docker_command_failed') as caught:
                instance.start()
        self.assertNotIn('PRIVATE',str(caught.exception))

    def test_successful_or_failed_runs_always_cleanup_and_report_limits(self):
        for failure in (False,True):
            fake=Mock(); fake.env={'SMOKE_USERNAME':'fake','SMOKE_PASSWORD':'fake'}; fake.name='fake-container'; fake.cleanup.return_value=[]
            with self.subTest(failure=failure), patch.object(smoke.shutil,'which',return_value='/usr/bin/docker'), \
                 patch.object(smoke,'DockerSmoke',return_value=fake), patch.object(smoke,'wait_ready'), \
                 patch.object(smoke,'login_and_session',side_effect=smoke.SmokeFailure('synthetic_login_failed') if failure else None,return_value={'sessionid':'fake'}), \
                 patch.object(smoke,'require_dashboard') as dashboard:
                report=smoke.run_smoke('linguapath-ci:abc',env=CI_ENV)
            fake.cleanup.assert_called_once()
            self.assertEqual(report['status'],'failed' if failure else 'passed')
            self.assertEqual(report['tls'],'simulated_proxy_headers')
            self.assertIn('not public HTTPS',report['scope'])
            if not failure:
                dashboard.assert_called_once_with(18080,{'sessionid':'fake'})
                self.assertIn(('postgres_session_after_restart','passed'),[(x['id'],x['status']) for x in report['checks']])

    def test_cleanup_failure_prevents_passed_report_and_removes_container_after_fixture_error(self):
        instance=smoke.DockerSmoke('linguapath-ci:abc',18080,CI_ENV)
        instance.started=instance.fixture_attempted=True
        with patch.object(instance,'command',side_effect=[smoke.SmokeFailure('docker_command_failed'),None]) as command:
            errors=instance.cleanup()
        self.assertEqual(errors,['fixture_cleanup_failed'])
        self.assertEqual(command.call_args_list[-1].args[0],['rm','--force',instance.name])
        fake=Mock(); fake.env={'SMOKE_USERNAME':'fake','SMOKE_PASSWORD':'fake'}; fake.cleanup.return_value=['fixture_cleanup_failed']
        with patch.object(smoke.shutil,'which',return_value='/usr/bin/docker'),patch.object(smoke,'DockerSmoke',return_value=fake), \
             patch.object(smoke,'wait_ready'),patch.object(smoke,'login_and_session',return_value={}),patch.object(smoke,'require_dashboard'):
            self.assertEqual(smoke.run_smoke('linguapath-ci:abc',env=CI_ENV)['status'],'failed')

    def test_main_prints_only_generic_result_and_exits_nonzero_without_docker(self):
        output=StringIO()
        with patch.dict(smoke.os.environ,CI_ENV,clear=True),patch.object(smoke.shutil,'which',return_value=None),redirect_stdout(output):
            code=smoke.main(['--image','linguapath-ci:abc'])
        self.assertEqual(code,1)
        result=json.loads(output.getvalue())
        self.assertEqual(result['failure'],'docker_unavailable')
        self.assertNotIn('ci-only',output.getvalue())


@override_settings(ALLOWED_HOSTS=[smoke.HOST], SECURE_SSL_REDIRECT=True,
    SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
    SESSION_ENGINE='django.contrib.sessions.backends.db')
class SmokeDjangoContractTests(TestCase):
    """Real Django HTTP contracts with a fresh in-process client on every hop.

    This checks the harness against real forms/CSRF/session responses; it does
    not execute a container or replace the PostgreSQL restart check in CI.
    """
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='synthetic-smoke-test', password='test-only-strong-password')
        LearnerProfile.objects.create(user=self.user, onboarding_complete=True)

    def request(self, port, path, *, method='GET', fields=None, cookies=None):
        client = Client(enforce_csrf_checks=True)
        for name, value in (cookies or {}).items():
            client.cookies[name] = value
        response = client.generic(method, path, data=urlencode(fields or {}),
            content_type='application/x-www-form-urlencoded', secure=True,
            HTTP_HOST=smoke.HOST, HTTP_ORIGIN='https://' + smoke.HOST)
        header_items = list(response.items()) + [
            ('Set-Cookie', value.OutputString()) for value in response.cookies.values()]
        return response.status_code, header_items, response.content

    def test_real_forms_csrf_and_database_session_match_harness_contract(self):
        smoke.wait_ready(18080, request=self.request)
        cookies = smoke.login_and_session(18080, self.user.username,
            'test-only-strong-password', request=self.request)
        self.assertIn('sessionid', cookies)
        # Another fresh client only has the exported cookie; session state is
        # recovered from the test database, not an earlier Client instance.
        smoke.require_dashboard(18080, cookies, request=self.request)

    def test_invalidated_real_session_is_not_reported_as_preserved(self):
        cookies = smoke.login_and_session(18080, self.user.username,
            'test-only-strong-password', request=self.request)
        self.user.delete()
        with self.assertRaisesMessage(smoke.SmokeFailure, 'authenticated_session_not_preserved'):
            smoke.require_dashboard(18080, cookies, request=self.request)
