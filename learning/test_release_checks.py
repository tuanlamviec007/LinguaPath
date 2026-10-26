from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.db import DatabaseError, connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.readiness import SchemaNotReady
from config.release_checks import evaluate_release
from .models import VocabularyQuizSession, WeakWordProjectionState, WeakWordQuizReceipt


PRODUCTION = dict(DEBUG=False, SECRET_KEY='private-production-placeholder-for-tests-' + 'x' * 40,
    ALLOWED_HOSTS=['learn.example'], CSRF_TRUSTED_ORIGINS=['https://learn.example'],
    SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'), SECURE_HSTS_SECONDS=0,
    AUTH_RATE_LIMIT_CLIENT_IP_HEADER='', AUTH_RATE_LIMIT_TRUSTED_PROXIES=(),
    AI_TUTOR_ENABLED=False)


@override_settings(**PRODUCTION)
class ProductionReleaseCheckTests(SimpleTestCase):
    def evaluate(self):
        with patch('config.release_checks.connection') as conn, \
             patch('config.release_checks.check_schema_ready'), \
             patch('learning.management.commands.check_weak_word_outcomes.projection_ready', return_value=True):
            conn.vendor = 'postgresql'
            return evaluate_release()

    def test_valid_configuration_passes_with_truthful_unverified_ingress_warning(self):
        report = self.evaluate()
        self.assertTrue(report['ready'])
        self.assertEqual(report['blocked'], [])
        self.assertEqual(report['mode'], 'production')
        self.assertFalse(report['release_approval'])
        self.assertIn('ingress_verification', {c['id'] for c in report['checks'] if c['status'] == 'warning'})
        self.assertNotIn(PRODUCTION['SECRET_KEY'], json.dumps(report))
        self.assertNotIn('learn.example', json.dumps(report))

    def test_each_production_security_requirement_blocks(self):
        cases = [('debug_disabled', {'DEBUG': True}),
            ('secret_key', {'SECRET_KEY': 'short'}),
            ('secure_cookies', {'SESSION_COOKIE_SECURE': False}),
            ('secure_cookies', {'CSRF_COOKIE_SECURE': False}),
            ('https_redirect', {'SECURE_SSL_REDIRECT': False}),
            ('allowed_hosts', {'ALLOWED_HOSTS': ['*']}),
            ('allowed_hosts', {'ALLOWED_HOSTS': ['linguapath.REPLACE_WITH_YOUR_SUBDOMAIN.workers.dev']}),
            ('allowed_hosts', {'ALLOWED_HOSTS': ['https://learn.example']}),
            ('allowed_hosts', {'ALLOWED_HOSTS': []}),
            ('allowed_hosts', {'ALLOWED_HOSTS': 'learn.example'}),
            ('csrf_origins', {'CSRF_TRUSTED_ORIGINS': ['http://learn.example']}),
            ('csrf_origins', {'CSRF_TRUSTED_ORIGINS': ['https://*.example']}),
            ('csrf_origins', {'CSRF_TRUSTED_ORIGINS': ['https://.example']}),
            ('csrf_origins', {'CSRF_TRUSTED_ORIGINS': ['https://learn.example/path']}),
            ('proxy_ssl_header', {'SECURE_PROXY_SSL_HEADER': ('HTTP_FORWARDED', 'https')}),
            ('auth_proxy_configuration', {'AUTH_RATE_LIMIT_CLIENT_IP_HEADER': 'HTTP_X_CLIENT_IP'}),
            ('auth_proxy_configuration', {'AUTH_RATE_LIMIT_TRUSTED_PROXIES': ('0.0.0.0/0',)}),
            ('auth_proxy_configuration', {'AUTH_RATE_LIMIT_TRUSTED_PROXIES': ('::/0',)}),
            ('auth_proxy_configuration', {'AUTH_RATE_LIMIT_TRUSTED_PROXIES': ('private invalid value',)}),
            ('auth_proxy_configuration', {'AUTH_RATE_LIMIT_TRUSTED_PROXIES': ('10.1.0.0/16',), 'AUTH_RATE_LIMIT_CLIENT_IP_HEADER': 'not_http'}),
            ('ai_configuration', {'AI_TUTOR_ENABLED': 'true'})]
        for check_id, values in cases:
            with self.subTest(check_id=check_id, values=values), override_settings(**values):
                report = self.evaluate()
                self.assertFalse(report['ready'])
                self.assertIn(check_id, report['blocked'])
                self.assertNotIn('private invalid value', json.dumps(report))

    def test_explicit_trusted_peers_and_header_are_valid_but_unverified(self):
        with override_settings(AUTH_RATE_LIMIT_TRUSTED_PROXIES=('10.1.0.0/16', '2001:db8::/32'),
                AUTH_RATE_LIMIT_CLIENT_IP_HEADER='HTTP_X_LINGUAPATH_CLIENT_IP'):
            report = self.evaluate()
        self.assertTrue(report['ready'])
        self.assertIn('ingress_verification', {c['id'] for c in report['checks'] if c['status'] == 'warning'})

    def test_same_origin_csrf_defaults_and_direct_tls_are_supported(self):
        with override_settings(CSRF_TRUSTED_ORIGINS=[], SECURE_PROXY_SSL_HEADER=None):
            self.assertTrue(self.evaluate()['ready'])
        with override_settings(CSRF_TRUSTED_ORIGINS=['https://learn.example:8443'],
                ALLOWED_HOSTS=['replacement-parts.example']):
            self.assertTrue(self.evaluate()['ready'])
        with override_settings(CSRF_TRUSTED_ORIGINS=['https://[2001:db8::1]:8443'],
                ALLOWED_HOSTS=['[2001:db8::1]']):
            self.assertTrue(self.evaluate()['ready'])

    def test_postgresql_is_required_even_with_other_settings_valid(self):
        with patch('config.release_checks.check_schema_ready'), \
             patch('learning.management.commands.check_weak_word_outcomes.projection_ready', return_value=True):
            report = evaluate_release()
        self.assertIn('postgresql_backend', report['blocked'])

    def test_ai_disabled_does_not_read_provider_or_reserve_inference(self):
        with patch('learning.ai_provider.provider_name') as provider, \
             patch('learning.ai_provider.tutor_ai_available') as available, \
             patch('learning.ai.reserve_tutor_call') as quota, patch('learning.ai.OpenAI') as model:
            self.assertTrue(self.evaluate()['ready'])
        provider.assert_not_called(); available.assert_not_called(); quota.assert_not_called(); model.assert_not_called()

    def test_enabled_ai_requires_recognized_available_provider_and_integer_caps(self):
        with override_settings(AI_TUTOR_ENABLED=True, AI_TUTOR_DAILY_LIMIT=20,
                AI_TUTOR_MINUTE_LIMIT=3, AI_TUTOR_GLOBAL_DAILY_LIMIT=200, AI_TUTOR_GLOBAL_MINUTE_LIMIT=20), \
             patch('learning.ai_provider.provider_name', return_value='openai') as provider, \
             patch('learning.ai_provider.tutor_ai_available', return_value=True) as available:
            self.assertTrue(self.evaluate()['ready'])
            for invalid in (-1, True, '20', 2**31):
                with self.subTest(invalid=invalid), override_settings(AI_TUTOR_GLOBAL_DAILY_LIMIT=invalid):
                    self.assertIn('ai_configuration', self.evaluate()['blocked'])
            available.return_value = False
            self.assertIn('ai_configuration', self.evaluate()['blocked'])
            available.return_value = True; provider.return_value = 'unrecognized'
            self.assertIn('ai_configuration', self.evaluate()['blocked'])

    def test_db_and_projection_failures_are_redacted_and_projection_waits_for_schema(self):
        for error in (DatabaseError('postgres://private-secret@host'), SchemaNotReady('private-table')):
            with self.subTest(error=type(error).__name__), \
                 patch('config.release_checks.check_schema_ready', side_effect=error), \
                 patch('learning.management.commands.check_weak_word_outcomes.projection_ready') as projection:
                report = evaluate_release(require_production=False)
            self.assertIn('database_schema', report['blocked'])
            self.assertNotIn('private', json.dumps(report))
            projection.assert_not_called()
        with patch('config.release_checks.check_schema_ready'), \
             patch('learning.management.commands.check_weak_word_outcomes.projection_ready', side_effect=DatabaseError('secret')):
            report = evaluate_release(require_production=False)
        self.assertIn('weak_word_projection', report['blocked'])
        self.assertNotIn('secret', json.dumps(report))

    def test_cli_prints_json_then_nonzero_without_exposing_settings(self):
        output = StringIO()
        with patch('config.release_checks.check_schema_ready', side_effect=SchemaNotReady('private-detail')):
            with self.assertRaises(CommandError):
                call_command('check_release', local=True, format='json', stdout=output)
        report = json.loads(output.getvalue())
        self.assertFalse(report['ready'])
        self.assertEqual(report['mode'], 'local')
        self.assertNotIn('private-detail', output.getvalue())


class LocalReleaseReadinessTests(TestCase):
    def test_real_local_database_passes_read_only_without_provider_calls(self):
        with CaptureQueriesContext(connection) as queries, patch('learning.ai_provider.tutor_ai_available') as available:
            report = evaluate_release(require_production=False)
        self.assertTrue(report['ready'])
        self.assertEqual(report['mode'], 'local')
        self.assertTrue(all(not q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER')) for q in queries))
        # Projection check must not read snapshot, answers or draft payloads.
        projection_sql = [q['sql'] for q in queries if 'weakword' in q['sql'].lower()]
        self.assertTrue(projection_sql)
        self.assertTrue(all('"snapshot"' not in q and '"answers"' not in q and '"draft_answers"' not in q for q in projection_sql))
        available.assert_not_called()

    def test_missing_projection_blocks_until_metadata_and_receipt_are_ready(self):
        user = get_user_model().objects.create_user(username='release-history')
        # Bulk import intentionally bypasses signal projection and remains blocked.
        VocabularyQuizSession.objects.bulk_create([VocabularyQuizSession(user=user, status='submitted',
            mode='meaning', question_count=0, submitted_at=timezone.now())])
        quiz = VocabularyQuizSession.objects.get(user=user)
        self.assertIn('weak_word_projection', evaluate_release(require_production=False)['blocked'])
        state = WeakWordProjectionState.objects.create(user=user, ready=True)
        self.assertIn('weak_word_projection', evaluate_release(require_production=False)['blocked'])
        WeakWordQuizReceipt.objects.create(quiz=quiz,user=user,fingerprint='a'*64)
        self.assertTrue(evaluate_release(require_production=False)['ready'])
        state.needs_rebuild = True; state.save(update_fields=['needs_rebuild'])
        self.assertIn('weak_word_projection', evaluate_release(require_production=False)['blocked'])

    def test_old_projection_command_keeps_its_read_only_behavior(self):
        output = StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command('check_weak_word_outcomes',stdout=output)
        self.assertIn('projections are ready',output.getvalue())
        self.assertTrue(all(not q['sql'].lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for q in queries))


class EmptyReleaseDatabaseTests(SimpleTestCase):
    def test_local_empty_db_is_not_migrated_or_seeded_by_release_gate(self):
        with TemporaryDirectory(prefix='lingua-release-') as tmp:
            env = os.environ.copy(); env.update(DJANGO_SETTINGS_MODULE='config.settings',DJANGO_DEBUG='true',
                DATABASE_URL='sqlite:///' + str(Path(tmp)/'empty.sqlite3'),AI_TUTOR_ENABLED='false')
            code = '''
import django,json
django.setup()
from config.release_checks import evaluate_release
from django.db import connection
report=evaluate_release(require_production=False)
print(json.dumps({'ready':report['ready'],'blocked':report['blocked'],'tables':connection.introspection.table_names()}))
'''
            result = subprocess.run([sys.executable,'-c',code],env=env,cwd=Path(__file__).resolve().parent.parent,
                capture_output=True,text=True,timeout=20,check=False)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'ready':False,'blocked':['database_schema'],'tables':[]})
