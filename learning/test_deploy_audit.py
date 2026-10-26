import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRET = 'test-production-secret-key-' + ('x' * 40)


class ProductionSettingsTests(SimpleTestCase):
    def run_settings(self, extra_env, code='import config.settings'):
        env = os.environ.copy()
        for name in (
            'DJANGO_DEBUG', 'DJANGO_SECRET_KEY', 'DJANGO_SECURE_SSL_REDIRECT',
            'DJANGO_SESSION_COOKIE_SECURE', 'DJANGO_CSRF_COOKIE_SECURE',
            'DJANGO_SECURE_HSTS_SECONDS', 'DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS',
            'DJANGO_SECURE_HSTS_PRELOAD', 'DJANGO_TRUST_PROXY_SSL_HEADER',
            'DJANGO_CSRF_TRUSTED_ORIGINS', 'DATABASE_URL', 'DJANGO_DB_CONN_MAX_AGE',
            'DJANGO_DB_CONNECT_TIMEOUT',
        ):
            env.pop(name, None)
        env.update(extra_env)
        return subprocess.run(
            [sys.executable, '-c', code],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_production_settings_reject_missing_secret(self):
        result = self.run_settings({'DJANGO_DEBUG': 'false'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY is required in production', result.stderr)

    def test_development_defaults_remain_sqlite_and_unredirected(self):
        code = (
            'import json, config.settings as s; '
            'print(json.dumps({"debug": s.DEBUG, "engine": s.DATABASES["default"]["ENGINE"], '
            '"redirect": s.SECURE_SSL_REDIRECT, "session": s.SESSION_COOKIE_SECURE, '
            '"csrf": s.CSRF_COOKIE_SECURE}))'
        )
        result = self.run_settings({}, code)
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(settings['debug'])
        self.assertEqual(settings['engine'], 'django.db.backends.sqlite3')
        self.assertFalse(settings['redirect'])
        self.assertFalse(settings['session'])
        self.assertFalse(settings['csrf'])

    def test_production_settings_enable_secure_defaults_and_static_root(self):
        code = (
            'import json, config.settings as s; '
            'print(json.dumps({"debug": s.DEBUG, "redirect": s.SECURE_SSL_REDIRECT, '
            '"session": s.SESSION_COOKIE_SECURE, "csrf": s.CSRF_COOKIE_SECURE, '
            '"hsts": s.SECURE_HSTS_SECONDS, "static_root": str(s.STATIC_ROOT), '
            '"static_backend": s.STORAGES["staticfiles"]["BACKEND"], '
            '"whitenoise": "whitenoise.middleware.WhiteNoiseMiddleware" in s.MIDDLEWARE, '
            '"csrf_origins": s.CSRF_TRUSTED_ORIGINS, '
            '"proxy_header": getattr(s, "SECURE_PROXY_SSL_HEADER", None)}))'
        )
        result = self.run_settings({
            'DJANGO_DEBUG': 'false',
            'DJANGO_SECRET_KEY': SECRET,
            'DATABASE_URL': 'postgresql://lingua:password@db.example:5432/lingua',
            'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://linguapath.example, https://www.linguapath.example',
        }, code)
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(settings['debug'])
        self.assertTrue(settings['redirect'])
        self.assertTrue(settings['session'])
        self.assertTrue(settings['csrf'])
        self.assertEqual(settings['hsts'], 31536000)
        self.assertEqual(settings['static_root'], str(PROJECT_ROOT / 'staticfiles'))
        self.assertEqual(settings['static_backend'], 'whitenoise.storage.CompressedManifestStaticFilesStorage')
        self.assertTrue(settings['whitenoise'])
        self.assertEqual(settings['csrf_origins'], ['https://linguapath.example', 'https://www.linguapath.example'])
        self.assertIsNone(settings['proxy_header'])

    def test_production_requires_database_url(self):
        result = self.run_settings({'DJANGO_DEBUG': 'false', 'DJANGO_SECRET_KEY': SECRET})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DATABASE_URL is required in production', result.stderr)

    def test_production_rejects_sqlite_database_url(self):
        result = self.run_settings({
            'DJANGO_DEBUG': 'false', 'DJANGO_SECRET_KEY': SECRET,
            'DATABASE_URL': 'sqlite:////tmp/linguapath.sqlite3',
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Production DATABASE_URL must use PostgreSQL', result.stderr)

    def test_database_url_configures_postgresql_without_connecting(self):
        code = (
            'import json, config.settings as s; '
            'd=s.DATABASES["default"]; '
            'print(json.dumps({"engine":d["ENGINE"], "name":d["NAME"], '
            '"host":d["HOST"], "max_age":d["CONN_MAX_AGE"], '
            '"health_checks":d["CONN_HEALTH_CHECKS"]}))'
        )
        result = self.run_settings({
            'DJANGO_DEBUG': 'false', 'DJANGO_SECRET_KEY': SECRET,
            'DATABASE_URL': 'postgresql://learner:pw@postgres.internal:5432/linguapath',
        }, code)
        self.assertEqual(result.returncode, 0, result.stderr)
        db = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(db['engine'], 'django.db.backends.postgresql')
        self.assertEqual(db['name'], 'linguapath')
        self.assertEqual(db['host'], 'postgres.internal')
        self.assertEqual(db['max_age'], 60)
        self.assertTrue(db['health_checks'])

    def test_postgresql_connection_setup_has_bounded_timeout(self):
        code = 'import config.settings as s; print(s.DATABASES["default"]["OPTIONS"]["connect_timeout"])'
        base = {'DJANGO_DEBUG':'false','DJANGO_SECRET_KEY':SECRET,
            'DATABASE_URL':'postgresql://learner:pw@postgres.internal:5432/linguapath'}
        for extra, expected in (({},5),({'DJANGO_DB_CONNECT_TIMEOUT':'9'},9),
                ({'DATABASE_URL':base['DATABASE_URL']+'?connect_timeout=7'},7)):
            with self.subTest(extra=extra):
                result=self.run_settings({**base,**extra},code)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout.strip(),str(expected))
        for value in ('0','31','-1','bad'):
            with self.subTest(value=value):
                result=self.run_settings({**base,'DJANGO_DB_CONNECT_TIMEOUT':value},code)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('connect timeout must be an integer between 1 and 30',result.stderr)
                self.assertNotIn('learner:pw',result.stderr)

    def test_proxy_ssl_header_is_opt_in(self):
        code = 'import json, config.settings as s; print(json.dumps(getattr(s,"SECURE_PROXY_SSL_HEADER",None)))'
        result = self.run_settings({
            'DJANGO_DEBUG': 'false', 'DJANGO_SECRET_KEY': SECRET,
            'DATABASE_URL': 'postgresql://learner:pw@localhost:5432/linguapath',
            'DJANGO_TRUST_PROXY_SSL_HEADER': 'true',
        }, code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), ['HTTP_X_FORWARDED_PROTO', 'https'])

    def test_production_settings_reject_short_or_default_secret(self):
        for secret in ('short', 'dev-only-insecure-key-change-before-deployment'):
            with self.subTest(secret=secret):
                result = self.run_settings({
                    'DJANGO_DEBUG': 'false',
                    'DJANGO_SECRET_KEY': secret,
                })
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('at least 50 characters', result.stderr)
