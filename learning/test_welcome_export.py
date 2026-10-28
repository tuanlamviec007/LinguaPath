from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys

from django.test import SimpleTestCase


class WelcomeExportTests(SimpleTestCase):
    def test_export_is_public_static_and_routes_app_actions_to_existing_backend(self):
        root=Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as folder:
            result=subprocess.run([sys.executable,str(root/'scripts/export-welcome.py'),folder],cwd=root,
                                  capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr[-500:])
            output=Path(folder);html=(output/'index.html').read_text()
            self.assertIn('https://linguapath-app.onrender.com/accounts/register/',html)
            self.assertIn('href="/learn/start/"',html)
            self.assertIn('formaction="/demo/B/#quick-demo"',html)
            self.assertNotIn('csrfmiddlewaretoken',html)
            self.assertNotIn('preview-student',html)
            self.assertIn('Đúng rồi!',(output/'demo/B/index.html').read_text())
            self.assertIn('Chưa đúng lần này.',(output/'demo/A/index.html').read_text())
            self.assertTrue((output/'static/images/lumi-owl.webp').exists())
            self.assertFalse((output/'_worker.js').exists())
            self.assertFalse((output/'functions').exists())
