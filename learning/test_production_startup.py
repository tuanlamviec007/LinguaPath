"""The entrypoint must stop before serving when the release gate fails."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]


class ProductionStartupTests(SimpleTestCase):
    def run_startup(self, gate_exit):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in ('python', 'gunicorn'):
                stub = folder / name
                stub.write_text('#!' + sys.executable + '\n'
                    'import os,sys\n'
                    'from pathlib import Path\n'
                    'name=Path(sys.argv[0]).name\n'
                    'with open(os.environ["STARTUP_TRACE"],"a") as f: f.write(name+" "+" ".join(sys.argv[1:])+"\\n")\n'
                    'sys.exit(int(os.environ["GATE_EXIT"]) if name=="python" else 0)\n')
                stub.chmod(0o700)
            env = {**os.environ, 'PATH': directory + os.pathsep + os.environ.get('PATH', ''),
                'STARTUP_TRACE': str(folder/'trace'), 'GATE_EXIT': str(gate_exit), 'PORT':'18080'}
            result = subprocess.run(['sh', str(ROOT/'scripts/start-production.sh')], cwd=ROOT,
                env=env, capture_output=True, text=True, timeout=10)
            return result, (folder/'trace').read_text().splitlines()

    def test_failed_gate_prevents_gunicorn_start(self):
        result, trace = self.run_startup(7)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(trace, ['python manage.py check_release'])

    def test_successful_gate_precedes_serving_with_safe_logger(self):
        result, trace = self.run_startup(0)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(trace[0], 'python manage.py check_release')
        self.assertEqual(len(trace), 2)
        self.assertTrue(trace[1].startswith('gunicorn config.wsgi:application '))
        self.assertIn('--logger-class config.observability.SafeGunicornLogger', trace[1])
        self.assertIn('--bind 0.0.0.0:18080', trace[1])

    def test_ci_backend_guard_rejects_sqlite_before_any_checks_or_tests(self):
        env={**os.environ,'PYTHON':sys.executable,'DATABASE_URL':'sqlite:///:memory:','DJANGO_DEBUG':'true'}
        result=subprocess.run(['sh',str(ROOT/'scripts/check-project.sh'),'--require-postgresql'],
            cwd=ROOT,env=env,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('PostgreSQL is required',result.stderr)
        self.assertNotIn('Creating test database',result.stderr)
