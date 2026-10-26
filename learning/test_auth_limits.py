from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as datetime_timezone
from io import StringIO
from threading import Barrier
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import DatabaseError, connections
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import resolve

from config.auth_throttle import AuthThrottleMiddleware, LIMIT_MESSAGE, UNAVAILABLE_MESSAGE, client_ip
from .auth_limits import DEFAULT_AUTH_RATE_LIMITS, reserve_auth_request
from .auth_models import AuthRateBucket


NOW = datetime(2026, 10, 24, 12, 0, 1, tzinfo=datetime_timezone.utc)
SMALL_LIMITS = {action: {'window': 60, 'ip': 3, 'identifier': 2} for action in DEFAULT_AUTH_RATE_LIMITS}
MIDDLEWARE = list(settings.MIDDLEWARE)
if 'config.auth_throttle.AuthThrottleMiddleware' not in MIDDLEWARE:
    MIDDLEWARE.insert(MIDDLEWARE.index('django.middleware.csrf.CsrfViewMiddleware') + 1,
                      'config.auth_throttle.AuthThrottleMiddleware')


@override_settings(AUTH_RATE_LIMITS=SMALL_LIMITS)
class AuthReservationTests(TestCase):
    def reserve(self, ip='192.0.2.1', username='Learner', now=NOW, action='login'):
        return reserve_auth_request(action, ip, username, now=now)

    def test_pair_limit_preserves_capacity_for_other_identifiers_and_ips(self):
        self.assertTrue(self.reserve().allowed)
        self.assertTrue(self.reserve(username='  ＬＥＡＲＮＥＲ  ').allowed)
        denied = self.reserve(username='learner')
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.retry_after, 59)
        self.assertEqual(AuthRateBucket.objects.get(scope='ip').request_count, 2)
        self.assertTrue(self.reserve(username='Different learner').allowed)
        # No global username bucket lets one IP lock out a victim elsewhere.
        self.assertTrue(self.reserve(ip='192.0.2.2').allowed)

    def test_identifier_spray_hits_ip_limit_before_creating_unbounded_pairs(self):
        for identifier in ('one', 'two', 'three'):
            self.assertTrue(self.reserve(username=identifier).allowed)
        for index in range(10):
            self.assertFalse(self.reserve(username=f'spray-{index}').allowed)
        self.assertEqual(AuthRateBucket.objects.count(), 4)
        self.assertEqual(AuthRateBucket.objects.get(scope='ip').request_count, 3)

    def test_windows_expire_and_reuse_existing_rows(self):
        self.reserve(); self.reserve()
        self.assertFalse(self.reserve(now=NOW + timedelta(seconds=57)).allowed)
        self.assertEqual(self.reserve(now=NOW + timedelta(seconds=58)).retry_after, 1)
        self.assertTrue(self.reserve(now=NOW + timedelta(seconds=59)).allowed)
        self.assertEqual(AuthRateBucket.objects.count(), 2)
        self.assertEqual(set(AuthRateBucket.objects.values_list('request_count', flat=True)), {1})

    def test_clock_rollback_does_not_reset_a_used_window(self):
        self.reserve(); self.reserve()
        self.assertFalse(self.reserve(now=NOW - timedelta(seconds=120)).allowed)

    def test_ip_representations_and_action_budgets_are_consistent(self):
        self.reserve(ip='::ffff:192.0.2.1'); self.reserve(ip='192.0.2.1')
        self.assertFalse(self.reserve(ip='::ffff:c000:201').allowed)
        self.assertTrue(self.reserve(action='register').allowed)

    def test_empty_identifiers_still_have_ip_limit(self):
        for _ in range(3):
            self.assertTrue(self.reserve(username='').allowed)
        self.assertFalse(self.reserve(username='').allowed)
        self.assertEqual(AuthRateBucket.objects.count(), 1)

    def test_hmac_keys_do_not_store_client_or_submitted_identifier(self):
        self.reserve(username='PrivateLearner@example.test')
        for bucket in AuthRateBucket.objects.all():
            self.assertRegex(bucket.bucket_key, r'^[a-f0-9]{64}$')
            self.assertNotIn('PrivateLearner', str(bucket.__dict__))
            self.assertNotIn('192.0.2.1', str(bucket.__dict__))

    def test_database_failure_rolls_back_both_quota_reservations(self):
        from .auth_limits import _locked_bucket

        def fail_pair(action, scope, *args):
            if scope == 'identifier':
                raise DatabaseError('Do not log connection details')
            return _locked_bucket(action, scope, *args)

        with patch('learning.auth_limits._locked_bucket', side_effect=fail_pair):
            with self.assertRaises(DatabaseError):
                self.reserve()
        self.assertFalse(AuthRateBucket.objects.exists())

    def test_invalid_or_zero_policies_fail_closed(self):
        for config in ({'login': {'ip': True}}, {'login': {'window': 0}}, {'login': {'identifier': -1}},
                       {'login': {'typo': 2}}, {'typo': {}}):
            with self.subTest(config=config), override_settings(AUTH_RATE_LIMITS=config):
                with self.assertRaises(ImproperlyConfigured):
                    self.reserve()
        with override_settings(AUTH_RATE_LIMITS={'login': {'ip': 0}}):
            self.assertFalse(self.reserve().allowed)


class AuthClientIPTests(TestCase):
    def request(self, remote='192.0.2.9', **headers):
        return RequestFactory().post('/accounts/login/', REMOTE_ADDR=remote, **headers)

    def test_untrusted_forwarding_headers_never_change_bucket_identity(self):
        req = self.request(HTTP_X_FORWARDED_FOR='198.51.100.1', HTTP_CF_CONNECTING_IP='198.51.100.2')
        self.assertEqual(client_ip(req), '192.0.2.9')

    @override_settings(AUTH_RATE_LIMIT_TRUSTED_PROXIES=['192.0.2.0/24'], AUTH_RATE_LIMIT_CLIENT_IP_HEADER='HTTP_X_VERIFIED_CLIENT_IP')
    def test_only_explicit_proxy_and_single_valid_header_are_trusted(self):
        self.assertEqual(client_ip(self.request(HTTP_X_VERIFIED_CLIENT_IP='198.51.100.9')), '198.51.100.9')
        self.assertEqual(client_ip(self.request(remote='203.0.113.4', HTTP_X_VERIFIED_CLIENT_IP='198.51.100.9')), '203.0.113.4')
        for invalid in ('198.51.100.9, 198.51.100.10', 'unknown', '', '198.51.100.9:8080'):
            self.assertEqual(client_ip(self.request(HTTP_X_VERIFIED_CLIENT_IP=invalid)), '192.0.2.9')

    @override_settings(AUTH_RATE_LIMIT_TRUSTED_PROXIES=['2001:db8::/32'], AUTH_RATE_LIMIT_CLIENT_IP_HEADER='HTTP_X_VERIFIED_CLIENT_IP')
    def test_ipv6_proxies_and_mapped_client_addresses_are_canonical(self):
        self.assertEqual(client_ip(self.request(remote='2001:db8::1', HTTP_X_VERIFIED_CLIENT_IP='::ffff:198.51.100.9')), '198.51.100.9')

    def test_missing_or_invalid_socket_address_uses_one_conservative_bucket(self):
        self.assertEqual(client_ip(self.request(remote='invalid')), 'unknown')
        self.assertEqual(client_ip(self.request(remote='')), 'unknown')

    def test_invalid_proxy_configuration_is_not_silently_trusted(self):
        for values in ({'AUTH_RATE_LIMIT_TRUSTED_PROXIES': '*'},
                       {'AUTH_RATE_LIMIT_TRUSTED_PROXIES': ['invalid']},
                       {'AUTH_RATE_LIMIT_CLIENT_IP_HEADER': 'X-Forwarded-For'}):
            with self.subTest(values=values), override_settings(**values):
                with self.assertRaises(ImproperlyConfigured):
                    client_ip(self.request())


@override_settings(MIDDLEWARE=MIDDLEWARE, AUTH_RATE_LIMITS=SMALL_LIMITS,
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthThrottleIntegrationTests(TestCase):
    def setUp(self):
        clock = patch('learning.auth_limits.timezone.now', return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.client = Client(enforce_csrf_checks=True)
        self.client.get('/accounts/login/')
        self.token = self.client.cookies['csrftoken'].value

    def post(self, path='/accounts/login/', username='learner', **kwargs):
        return self.client.post(path, {'username': username, 'password': 'incorrect',
                                     'csrfmiddlewaretoken': self.token, **kwargs})

    def test_csrf_rejection_does_not_consume_quota(self):
        for _ in range(4):
            self.assertEqual(self.client.post('/accounts/login/', {'username': 'learner'}).status_code, 403)
        self.assertFalse(AuthRateBucket.objects.exists())
        self.assertEqual(self.post().status_code, 200)

    def test_login_and_admin_login_have_separate_post_quotas_and_generic_responses(self):
        for path, action in (('/accounts/login/', 'login'), ('/admin/login/', 'admin_login')):
            with self.subTest(path=path):
                self.assertEqual(self.post(path).status_code, 200)
                self.assertEqual(self.post(path).status_code, 200)
                denied = self.post(path)
                self.assertEqual(denied.status_code, 429)
                self.assertEqual(denied.content.decode(), LIMIT_MESSAGE)
                self.assertGreaterEqual(int(denied['Retry-After']), 1)
                self.assertIn('no-store', denied['Cache-Control'])
                self.assertEqual(AuthRateBucket.objects.get(action=action, scope='identifier').request_count, 2)

    def test_registration_throttle_stops_actual_account_creation(self):
        # Invalid registrations also cost quota; the blocked valid form must not create a user.
        self.post('/accounts/register/'); self.post('/accounts/register/')
        denied = self.post('/accounts/register/', password1='Strong audit password 78452', password2='Strong audit password 78452')
        self.assertEqual(denied.status_code, 429)
        self.assertFalse(get_user_model().objects.filter(username='learner').exists())

    def test_password_reset_uses_email_identifier_and_never_reaches_mail_on_denial(self):
        for email in ('Private@example.test', ' private@EXAMPLE.test '):
            self.assertEqual(self.post('/accounts/password_reset/', email=email).status_code, 302)
        denied = self.post('/accounts/password_reset/', email='private@example.test')
        self.assertEqual(denied.status_code, 429)
        self.assertEqual(AuthRateBucket.objects.get(action='password_reset', scope='identifier').request_count, 2)

    def test_successful_login_is_counted_without_new_session_when_denied(self):
        get_user_model().objects.create_user(username='learner', password='Correct password 38729')
        self.post(); self.post()
        self.assertEqual(self.post(password='Correct password 38729').status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_allowed_successful_login_also_consumes_quota(self):
        user = get_user_model().objects.create_user(username='learner', password='Correct password 38729')
        self.assertEqual(self.post(password='Correct password 38729').status_code, 302)
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))
        self.assertEqual(set(AuthRateBucket.objects.values_list('request_count', flat=True)), {1})

    def test_allowed_signup_creates_account_and_reserves_both_buckets(self):
        response = self.post('/accounts/register/', password1='Strong audit password 78452', password2='Strong audit password 78452')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username='learner').exists())
        self.assertEqual(AuthRateBucket.objects.filter(action='register', request_count=1).count(), 2)

    def test_get_and_unrelated_posts_never_consume_auth_quota(self):
        for _ in range(4):
            self.assertEqual(self.client.get('/accounts/login/').status_code, 200)
        self.client.post('/not-an-auth-route/', {'csrfmiddlewaretoken': self.token})
        self.assertFalse(AuthRateBucket.objects.exists())

    def test_database_errors_are_fail_closed_and_do_not_log_identifiers(self):
        with patch('config.auth_throttle.reserve_auth_request', side_effect=DatabaseError('secret DSN')):
            with self.assertLogs('config.auth_throttle', level='WARNING') as captured:
                response = self.post(username='VeryPrivateLearner')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content.decode(), UNAVAILABLE_MESSAGE)
        self.assertEqual(response['Retry-After'], '30')
        self.assertNotIn('VeryPrivateLearner', '\n'.join(captured.output))
        self.assertNotIn('secret DSN', '\n'.join(captured.output))

    def test_misordered_csrf_is_fail_closed(self):
        req = RequestFactory().post('/accounts/login/', {'username': 'learner'})
        req.resolver_match = resolve('/accounts/login/')
        middleware = AuthThrottleMiddleware(lambda request: None)
        self.assertEqual(middleware.process_view(req, None, (), {}).status_code, 503)
        self.assertFalse(AuthRateBucket.objects.exists())


class AuthRatePurgeTests(TestCase):
    def test_purge_is_bounded_and_preserves_recent_or_live_windows(self):
        now = datetime.now(tz=datetime_timezone.utc)
        for index in range(3):
            reserve_auth_request('login', f'192.0.2.{index + 1}', '', now=now - timedelta(days=3))
        reserve_auth_request('login', '192.0.2.10', '', now=now)
        reserve_auth_request('login', '192.0.2.11', '', now=now - timedelta(hours=2))
        preview = StringIO()
        call_command('purge_expired_auth_buckets', batch_size=2, stdout=preview)
        self.assertEqual(AuthRateBucket.objects.count(), 5)
        self.assertIn('Dry run: 2', preview.getvalue())
        call_command('purge_expired_auth_buckets', batch_size=2, apply=True, stdout=StringIO())
        self.assertEqual(AuthRateBucket.objects.count(), 3)
        self.assertEqual(AuthRateBucket.objects.filter(expires_at__gte=now - timedelta(hours=24)).count(), 2)


@skipUnlessDBFeature('has_select_for_update')
@override_settings(AUTH_RATE_LIMITS={'login': {'window': 60, 'ip': 2, 'identifier': 2}})
class AuthRateConcurrencyTests(TransactionTestCase):
    def test_multiple_workers_cannot_overbook_the_shared_ip_budget(self):
        barrier = Barrier(6)

        def reserve(index):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return reserve_auth_request('login', '192.0.2.1', f'learner-{index}', now=NOW).allowed
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=6) as pool:
            allowed = list(pool.map(reserve, range(6)))
        self.assertEqual(sum(allowed), 2)
        self.assertEqual(AuthRateBucket.objects.get(scope='ip').request_count, 2)
        self.assertEqual(AuthRateBucket.objects.filter(scope='identifier').count(), 2)
