from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.db.migrations.exceptions import InconsistentMigrationHistory

from config.readiness import SchemaNotReady, check_schema_ready


class Command(BaseCommand):
    help = 'Require reachable database and applied migrations; never writes or seeds data.'

    def handle(self, *args, **options):
        try:
            check_schema_ready()
        except (DatabaseError, SchemaNotReady, InconsistentMigrationHistory):
            raise CommandError(
                'Database schema is not ready. Verify database connectivity and '
                'run the reviewed migration release step before starting traffic.'
            ) from None
        self.stdout.write(self.style.SUCCESS('Database schema is ready.'))
