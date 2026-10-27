import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
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
for url in ('/social/facebook/login/', '/social/facebook/login/callback/'):
 response=c.get(url)
 assert response.status_code==503
 assert 'Phương thức này chưa sẵn sàng' in response.content.decode()
 assert 'no-store' in response.get('Cache-Control','')
for url, status, text in [('/social/3rdparty/login/error/', 401, 'Chưa thể đăng nhập'),
                  ('/social/3rdparty/login/cancelled/', 200, 'Bạn đã hủy đăng nhập')]:
 response=c.get(url)
 assert response.status_code==status
 assert text in response.content.decode()
 assert 'Quay lại đăng nhập' in response.content.decode()
 assert '_auth_user_id' not in c.session
print('social-guards-passed')
'''
        env=os.environ.copy()
        env.update(DJANGO_SETTINGS_MODULE='config.settings', DJANGO_DEBUG='true',
            DATABASE_URL='sqlite:///:memory:', SOCIAL_AUTH_ENABLED='true',
            GOOGLE_CLIENT_ID='synthetic-client', GOOGLE_CLIENT_SECRET='synthetic-secret',
            FACEBOOK_CLIENT_ID='', FACEBOOK_CLIENT_SECRET='',
            DJANGO_ALLOWED_HOSTS='testserver', AI_TUTOR_ENABLED='false')
        result=subprocess.run([sys.executable,'-c',code],env=env,
            cwd=Path(__file__).resolve().parent.parent,capture_output=True,text=True,timeout=40)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('social-guards-passed',result.stdout)

    def test_linked_social_data_cannot_be_silently_omitted_even_after_disable(self):
        setup = """
import django
django.setup()
from django.core.management import call_command
from django.contrib.auth import get_user_model
from allauth.socialaccount.models import SocialAccount
from allauth.account.models import EmailAddress
call_command('migrate', verbosity=0)
users=get_user_model()
owner=users.objects.create_user(username='owner', password='audit-password-123')
users.objects.create_user(username='other', password='audit-password-123')
email_only=users.objects.create_user(username='email-only', password='audit-password-123')
EmailAddress.objects.create(user=email_only, email='email-only@example.test', verified=True, primary=True)
SocialAccount.objects.create(user=owner, provider='google', uid='synthetic-id', extra_data={'email':'private@example.test', 'access_token':'never-export'})
"""
        check = """
import django
django.setup()
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
users=get_user_model()
client=Client()
owner=users.objects.get(username='owner')
client.force_login(owner, backend='django.contrib.auth.backends.ModelBackend')
response=client.post(reverse('privacy_center'), {'action':'export','password':'audit-password-123'})
assert response.status_code == 409
assert 'chưa sẵn sàng' in response.content.decode()
assert 'never-export' not in response.content.decode()
assert not response.has_header('Content-Disposition')
if not __import__('django.conf', fromlist=['settings']).settings.SOCIAL_AUTH_ENABLED:
 response=client.post(reverse('privacy_center'), {'action':'delete','password':'audit-password-123','confirm_delete':'XOA','confirm_understood':'yes'})
 assert response.status_code == 409 and users.objects.filter(pk=owner.pk).exists()
client.force_login(users.objects.get(username='email-only'), backend='django.contrib.auth.backends.ModelBackend')
response=client.post(reverse('privacy_center'), {'action':'export','password':'audit-password-123'})
assert response.status_code == 409
client.force_login(users.objects.get(username='other'), backend='django.contrib.auth.backends.ModelBackend')
response=client.post(reverse('privacy_center'), {'action':'export','password':'audit-password-123'})
assert response.status_code == 200 and response.json()['account']['username'] == 'other'
print('social-export-guard-passed')
"""
        with TemporaryDirectory(prefix='lingua-social-privacy-') as temp:
            env = os.environ.copy()
            env.update(DJANGO_SETTINGS_MODULE='config.settings', DJANGO_DEBUG='true',
                       DATABASE_URL='sqlite:///' + str(Path(temp) / 'test.sqlite3'),
                       DJANGO_ALLOWED_HOSTS='testserver', AI_TUTOR_ENABLED='false',
                       SOCIAL_AUTH_ENABLED='true', GOOGLE_CLIENT_ID='synthetic', GOOGLE_CLIENT_SECRET='synthetic')
            for code, enabled in ((setup, 'true'), (check, 'true'), (check, 'false')):
                env['SOCIAL_AUTH_ENABLED'] = enabled
                result = subprocess.run([sys.executable, '-c', code], env=env,
                    cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=40)
                self.assertEqual(result.returncode, 0, result.stderr)
                if code == check:
                    self.assertIn('social-export-guard-passed', result.stdout)
