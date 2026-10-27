"""The restore harness must never reach tools for non-CI destinations."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

spec = importlib.util.spec_from_file_location('restore_rehearsal', Path(__file__).resolve().parents[1] / 'scripts/rehearse-restore.py')
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class RestoreGuardTests(SimpleTestCase):
    def test_only_exact_disposable_ci_destination_is_allowed(self):
        env = {'CI': 'true', 'GITHUB_ACTIONS': 'true'}
        valid = 'postgresql://linguapath_ci:synthetic@127.0.0.1:5432/linguapath_ci'
        self.assertEqual(restore.validate_config(valid, env, 'linux').hostname, '127.0.0.1')
        for url in (valid.replace('127.0.0.1', 'production.example'),
                    valid.replace('/linguapath_ci', '/production'),
                    valid.replace('linguapath_ci:', 'owner:'), valid+'?host=production.example',
                    valid+'#production', valid.replace(':5432', ':5433'), 'not a URL'):
            with self.subTest(url=url), self.assertRaises(restore.RestoreFailure):
                restore.validate_config(url, env, 'linux')
        for altered in ({}, {'CI':'true'}, {'GITHUB_ACTIONS':'true'}):
            with self.assertRaises(restore.RestoreFailure):
                restore.validate_config(valid, altered, 'linux')
        with self.assertRaises(restore.RestoreFailure):
            restore.validate_config(valid, env, 'darwin')

    def test_rejected_destination_never_connects_or_runs_subprocess(self):
        with patch.dict('os.environ', {'CI':'true','GITHUB_ACTIONS':'true',
                        'DATABASE_URL':'postgresql://owner:synthetic@production.example/app'}, clear=True), \
             patch.object(restore.psycopg, 'connect') as connect, \
             patch.object(restore.subprocess, 'run') as run:
            with self.assertRaises(restore.RestoreFailure):
                restore.main()
        connect.assert_not_called()
        run.assert_not_called()
