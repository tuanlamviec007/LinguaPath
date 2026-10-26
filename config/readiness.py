"""Read-only deployment checks shared by the HTTP probe and release command."""

from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class SchemaNotReady(Exception):
    """The database cannot serve the migration state required by this code."""


def check_schema_ready():
    """Require a reachable database and all migrations, without applying any."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        cursor.fetchone()
    executor = MigrationExecutor(connection)
    executor.loader.check_consistent_history(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise SchemaNotReady('Database has unapplied migrations.')
    required_tables = {
        model._meta.db_table
        for model in apps.get_models(include_auto_created=True)
        if model._meta.can_migrate(connection)
    }
    if not required_tables.issubset(set(connection.introspection.table_names())):
        raise SchemaNotReady('Database is missing required tables.')
