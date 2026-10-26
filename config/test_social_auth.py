import json
import os
from pathlib import Path
import subprocess
import sys
from django.test import SimpleTestCase


class SocialAuthRolloutTests(SimpleTestCase):
    def test_unconfigured_login_keeps_password_form_and_disabled_provider_buttons(self):
        page = self.client.get('/accounts/login/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Google · Chưa kích hoạt')
        self.assertContains(page, 'Facebook · Chưa kích hoạt')
        self.assertContains(page, 'name="password"')
        self.assertNotContains(page, 'action="/social/google/login/"')

    def test_enabled_provider_routes_csrf_state_and_legacy_routes(self):
        code = '''
import django
from unittest.mock import patch
from django.core.management import call_command
from django.test import Client
from django.urls import resolve
django.setup()
call_command('migrate',verbosity=0)
c=Client(enforce_csrf_checks=True)
assert c.get('/social/google/login/').status_code == 200
assert c.post('/social/google/login/').status_code == 403
token=c.cookies['csrftoken'].value
with patch('requests.sessions.Session.request',side_effect=AssertionError('Unexpected network')):
 r=c.post('/social/google/login/',{'csrfmiddlewaretoken':token})
 assert r.status_code==302 and 'accounts.google.com' in r['Location']
 r=c.get('/social/google/login/callback/',{'state':'invalid','code':'synthetic'})
 assert '_auth_user_id' not in c.session
assert resolve('/accounts/login/').url_name=='login'
assert resolve('/social/login/').url_name=='account_login'
assert c.get('/social/password/reset/').status_code==404
print('social-guards-passed')
'''
        env=os.environ.copy()
        env.update(DJANGO_SETTINGS_MODULE='config.settings', DJANGO_DEBUG='true',
            DATABASE_URL='sqlite:///:memory:', SOCIAL_AUTH_ENABLED='true',
            GOOGLE_CLIENT_ID='synthetic-client', GOOGLE_CLIENT_SECRET='synthetic-secret',
            DJANGO_ALLOWED_HOSTS='testserver', AI_TUTOR_ENABLED='false')
        result=subprocess.run([sys.executable,'-c',code],env=env,
            cwd=Path(__file__).resolve().parent.parent,capture_output=True,text=True,timeout=40)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('social-guards-passed',result.stdout)
