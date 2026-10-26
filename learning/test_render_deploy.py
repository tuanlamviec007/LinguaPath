"""Deployment contracts: safe content initialization and Render settings."""
import base64
import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase

from learning.models import AnswerOption, Flashcard, LearningContent, Question

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'learning.management.commands.bootstrap_learning_content.CONTENT_DIRECTORY'


class ContentBootstrapTests(TestCase):
    def setUp(self):
        content = LearningContent.objects.create(title='Fixture source', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        card = Flashcard.objects.create(content=content, term='voucher', meaning_vi='phiếu mua hàng', is_available=False)
        question = Question.objects.create(content=content, prompt='Pick the word.', explanation='Fixture explanation.')
        options = [AnswerOption.objects.create(question=question, label='A', text='voucher', is_correct=True), AnswerOption.objects.create(question=question, label='B', text='meeting')]
        self.data = serializers.serialize('json', [content, card, question, *options])
        content.delete()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.manifest = {'version': 1, 'counts': {'learning.learningcontent': 1, 'learning.flashcard': 1, 'learning.question': 1, 'learning.answeroption': 2}}
        self.write_fixture()

    def write_fixture(self):
        compressed = gzip.compress(self.data.encode(), mtime=0)
        self.manifest['sha256'] = hashlib.sha256(compressed).hexdigest()
        (self.path/'initial_content.json.gz').write_bytes(compressed)
        (self.path/'manifest.json').write_text(json.dumps(self.manifest))

    def run_bootstrap(self, **kwargs):
        with patch(MODULE, self.path):
            call_command('bootstrap_learning_content', stdout=io.StringIO(), **kwargs)

    def test_first_import_preserves_held_state_and_does_not_create_accounts(self):
        self.run_bootstrap(if_empty=True)
        self.assertEqual(Flashcard.objects.get().term, 'voucher')
        self.assertFalse(Flashcard.objects.get().is_available)
        self.assertEqual(LearningContent.objects.get().review_status, 'language_checked')
        self.assertEqual(AnswerOption.objects.filter(is_correct=True).count(), 1)
        self.assertFalse(get_user_model().objects.exists())

    def test_redeploy_never_overwrites_existing_content(self):
        self.run_bootstrap(if_empty=True)
        Flashcard.objects.update(meaning_vi='Người biên tập đã sửa')
        (self.path/'initial_content.json.gz').unlink()
        self.run_bootstrap(if_empty=True)
        self.assertEqual(Flashcard.objects.get().meaning_vi, 'Người biên tập đã sửa')

    def test_explicit_import_rejects_nonempty_database(self):
        self.run_bootstrap()
        with self.assertRaisesMessage(CommandError, 'never overwrites'):
            self.run_bootstrap()

    def test_tampered_fixture_fails_before_any_import(self):
        (self.path/'initial_content.json.gz').write_bytes(gzip.compress((self.data+' ').encode(),mtime=0))
        with self.assertRaises(CommandError):
            self.run_bootstrap()
        self.assertFalse(LearningContent.objects.exists())

    def test_wrong_expected_counts_roll_back_all_rows(self):
        self.manifest['counts']['learning.flashcard'] = 2
        self.write_fixture()
        with self.assertRaisesMessage(CommandError, 'rolled back'):
            self.run_bootstrap()
        self.assertFalse(LearningContent.objects.exists())
        self.assertFalse(Flashcard.objects.exists())

    def test_fixture_cannot_import_users_or_unexpected_models(self):
        self.data = '[{"model":"auth.user","pk":1,"fields":{}}]'
        self.manifest['sha256'] = hashlib.sha256(self.data.encode()).hexdigest()
        self.write_fixture()
        with self.assertRaises(CommandError):
            self.run_bootstrap()
        self.assertFalse(get_user_model().objects.exists())


class RenderSettingsTests(SimpleTestCase):
    def run_settings(self, overrides=None, code=None):
        env = {k: v for k,v in os.environ.items() if not k.startswith(('DJANGO_', 'RENDER_')) and k not in ('DATABASE_URL', 'AI_TUTOR_ENABLED')}
        env.update(DJANGO_SETTINGS_MODULE='config.settings_render', DJANGO_DEBUG='false', AI_TUTOR_ENABLED='false', DATABASE_URL='postgresql://test:test@db.example.invalid/linguapath?sslmode=require', DJANGO_SECRET_SEED=base64.b64encode(bytes(range(32))).decode(), RENDER_EXTERNAL_HOSTNAME='linguapath-test.onrender.com')
        env.update(overrides or {})
        return subprocess.run([sys.executable, '-c', code or 'import config.settings_render'], cwd=ROOT, env=env, text=True, capture_output=True, timeout=15)

    def test_generated_seed_produces_stable_long_key_and_secure_settings(self):
        code = 'import json,config.settings_render as s; print(json.dumps({"length":len(s.SECRET_KEY),"fingerprint":__import__("hashlib").sha256(s.SECRET_KEY.encode()).hexdigest(),"hosts":s.ALLOWED_HOSTS,"origins":s.CSRF_TRUSTED_ORIGINS,"debug":s.DEBUG,"cookies":s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE,"cursors":s.DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"]}))'
        first = self.run_settings(code=code)
        second = self.run_settings(code=code)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertEqual(result['length'], 128)
        self.assertEqual(result['hosts'], ['linguapath-test.onrender.com'])
        self.assertEqual(result['origins'], ['https://linguapath-test.onrender.com'])
        self.assertFalse(result['debug'])
        self.assertTrue(result['cookies'])
        self.assertTrue(result['cursors'])

    def test_invalid_seed_and_hostname_are_rejected(self):
        for override in ({'DJANGO_SECRET_SEED':'short'}, {'RENDER_EXTERNAL_HOSTNAME':'*.onrender.com'}, {'RENDER_EXTERNAL_HOSTNAME':'https://linguapath-test.onrender.com'}):
            with self.subTest(override=override):
                self.assertNotEqual(self.run_settings(override).returncode, 0)

    def test_explicit_existing_secret_is_not_rotated(self):
        result = self.run_settings({'DJANGO_SECRET_KEY':'test-existing-key-'+'x'*64}, 'import config.settings_render as s; assert s.SECRET_KEY == "test-existing-key-"+"x"*64')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_render_probe_reaches_liveness_without_https_redirect_or_database(self):
        code = 'import django; django.setup(); from django.test import Client; r=Client().get("/livez/",HTTP_HOST="linguapath-test.onrender.com"); assert r.status_code == 200, r.status_code'
        result = self.run_settings({'DJANGO_TRUST_PROXY_SSL_HEADER':'true'}, code)
        self.assertEqual(result.returncode, 0, result.stderr)
