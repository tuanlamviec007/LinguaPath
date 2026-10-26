"""An inference-off web boot must not load the optional model SDK."""
import json
import os
from pathlib import Path
import subprocess
import sys

from django.test import SimpleTestCase


class LazyProviderImportTests(SimpleTestCase):
    def test_guest_home_does_not_import_sdk_and_factory_still_forwards_options(self):
        code = '''
import django,json,sys,types
from unittest.mock import Mock
from django.test import Client
django.setup()
page=Client().get('/')
assert page.status_code == 200
assert 'openai' not in sys.modules
from learning import ai
fake=types.ModuleType('openai')
factory=Mock(return_value=object())
fake.OpenAI=factory
sys.modules['openai']=fake
result=ai.OpenAI(api_key='synthetic-key',timeout=20,max_retries=0)
factory.assert_called_once_with(api_key='synthetic-key',timeout=20,max_retries=0)
assert result is factory.return_value
print(json.dumps({'status':page.status_code,'sdk_lazy':True,'factory_compatible':True}))
'''
        env = os.environ.copy()
        env.update(DJANGO_SETTINGS_MODULE='config.settings', DJANGO_DEBUG='true',
            DATABASE_URL='sqlite:///:memory:', AI_TUTOR_ENABLED='false',
            DJANGO_ALLOWED_HOSTS='testserver', OPENAI_API_KEY='')
        process = subprocess.run([sys.executable, '-c', code], env=env,
            cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True,
            check=False, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout.splitlines()[-1]),
            {'status': 200, 'sdk_lazy': True, 'factory_compatible': True})
