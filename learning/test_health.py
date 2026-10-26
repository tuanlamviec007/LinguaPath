from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.db import connection
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.test import RequestFactory, SimpleTestCase, TestCase

from config.health import liveness, readiness
from config.readiness import SchemaNotReady, check_schema_ready


class ReadinessTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get('/healthz/')

    @patch('config.health.check_schema_ready')
    def test_checks_schema_and_disables_caching(self, check_schema):
        response = readiness(self.request)
        check_schema.assert_called_once_with()
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])

    def test_unavailable_database_or_schema_returns_generic_503(self):
        for error in (DatabaseError('private details'), SchemaNotReady('private details'),
                      InconsistentMigrationHistory('private details')):
            with self.subTest(error=type(error).__name__), patch(
                'config.health.check_schema_ready', side_effect=error,
            ):
                response = readiness(self.request)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn(b'private', response.content)
                self.assertIn('no-store', response['Cache-Control'])

    @patch('config.health.check_schema_ready')
    def test_post_is_rejected_without_database_access(self, check_schema):
        self.assertEqual(readiness(RequestFactory().post('/healthz/')).status_code, 405)
        check_schema.assert_not_called()

    @patch('config.health.check_schema_ready', side_effect=DatabaseError('offline'))
    def test_liveness_does_not_query_database(self, check_schema):
        response = liveness(RequestFactory().get('/livez/'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        check_schema.assert_not_called()
        self.assertEqual(liveness(RequestFactory().post('/livez/')).status_code, 405)


class SchemaProbeTests(SimpleTestCase):
    @patch('config.readiness.MigrationExecutor')
    @patch('config.readiness.connection')
    def test_pending_schema_fails_without_running_migrations(self, connection, executor_class):
        executor = executor_class.return_value
        executor.migration_plan.return_value = [('pending', False)]
        with self.assertRaises(SchemaNotReady):
            check_schema_ready()
        executor.loader.check_consistent_history.assert_called_once_with(connection)
        executor.migrate.assert_not_called()
        connection.cursor.return_value.__enter__.return_value.execute.assert_called_once_with('SELECT 1')

    @patch('config.readiness.apps.get_models', return_value=[])
    @patch('config.readiness.MigrationExecutor')
    @patch('config.readiness.connection')
    def test_applied_schema_passes_without_running_migrations(self, connection, executor_class, models):
        executor_class.return_value.migration_plan.return_value = []
        check_schema_ready()
        executor_class.return_value.migrate.assert_not_called()

    @patch('learning.management.commands.check_schema.check_schema_ready')
    def test_release_command_fails_closed_and_redacts_details(self, check_schema):
        for error in (DatabaseError('private connection'), SchemaNotReady('pending'),
                      InconsistentMigrationHistory('private history')):
            with self.subTest(error=type(error).__name__):
                check_schema.side_effect = error
                with self.assertRaises(CommandError) as caught:
                    call_command('check_schema', stdout=StringIO())
                self.assertNotIn('private', str(caught.exception))

    def test_real_empty_database_fails_without_creating_schema(self):
        with TemporaryDirectory(prefix='linguapath-probe-test-') as tmp:
            env = os.environ.copy()
            env.update({
                'DJANGO_SETTINGS_MODULE': 'config.settings',
                'DJANGO_DEBUG': 'true',
                'DATABASE_URL': 'sqlite:///' + str(Path(tmp) / 'empty.sqlite3'),
            })
            code = '''
import django, json
django.setup()
from django.db import connection
from django.test import RequestFactory
from config.health import liveness, readiness
request = RequestFactory().get('/healthz/')
print(json.dumps({'ready': readiness(request).status_code,
                  'alive': liveness(request).status_code,
                  'tables': connection.introspection.table_names()}))
connection.close()
'''
            result = subprocess.run(
                [sys.executable, '-c', code], env=env,
                cwd=Path(__file__).resolve().parent.parent,
                capture_output=True, text=True, timeout=20, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'ready': 503, 'alive': 200, 'tables': []})


class AppliedSchemaTests(TestCase):
    def test_real_migrated_test_database_is_ready(self):
        check_schema_ready()
        response = readiness(RequestFactory().get('/healthz/'))
        self.assertEqual(response.status_code, 200)
        output = StringIO()
        call_command('check_schema', stdout=output)
        self.assertIn('schema is ready', output.getvalue())

    def test_applied_records_with_missing_application_table_are_not_ready(self):
        # Keep actual applied migration records but simulate a dropped app table.
        tables = connection.introspection.table_names()
        tables.remove('learning_flashcard')
        with patch('config.readiness.connection.introspection.table_names', return_value=tables):
            with self.assertRaises(SchemaNotReady):
                check_schema_ready()
            self.assertEqual(readiness(RequestFactory().get('/healthz/')).status_code, 503)
