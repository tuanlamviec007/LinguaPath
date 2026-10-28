"""Import the shipped content snapshot once into an empty content database."""
import hashlib
import gzip
import json
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from learning.models import AnswerOption, Flashcard, LearningContent, Question


CONTENT_DIRECTORY = Path(__file__).resolve().parents[2] / 'data' / 'production'
CONTENT_MODELS = {
    'learning.learningcontent': LearningContent,
    'learning.flashcard': Flashcard,
    'learning.question': Question,
    'learning.answeroption': AnswerOption,
}


class Command(BaseCommand):
    help = 'Initialize content only on an empty database; never overwrites edits or creates users.'

    def add_arguments(self, parser):
        parser.add_argument('--if-empty', action='store_true', help='Skip an already populated content database.')

    def handle(self, *args, **options):
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                # Transaction-scoped lock serializes concurrent first builds,
                # including connections behind a transaction pooler.
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_advisory_xact_lock(%s)', [539220261026])
            if any(model.objects.exists() for model in CONTENT_MODELS.values()):
                if options['if_empty']:
                    self.stdout.write('Content already exists; snapshot import skipped. Existing content was not changed.')
                    return
                raise CommandError('Content is not empty. This command never overwrites an existing content database.')

            fixture = CONTENT_DIRECTORY / 'initial_content.json.gz'
            manifest_path = CONTENT_DIRECTORY / 'manifest.json'
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                with fixture.open('rb') as handle:
                    digest = hashlib.file_digest(handle, 'sha256').hexdigest()
                if (manifest.get('version') != 1 or digest != manifest.get('sha256')
                        or set(manifest.get('counts', {})) != set(CONTENT_MODELS)
                        or any(type(n) is not int or n <= 0 for n in manifest['counts'].values())):
                    raise ValueError
                # Reject any unexpected models before invoking Django's loader.
                with gzip.open(fixture, 'rt', encoding='utf-8') as handle:
                    rows = json.load(handle)
                if not isinstance(rows, list) or any(not isinstance(row, dict) or row.get('model') not in CONTENT_MODELS for row in rows):
                    raise ValueError
                del rows
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                raise CommandError('The bundled content snapshot or manifest is missing or invalid; no content was imported.') from None

            call_command('loaddata', str(fixture), verbosity=0)
            counts = {name: model.objects.count() for name, model in CONTENT_MODELS.items()}
            if counts != manifest['counts']:
                raise CommandError('Imported content counts do not match the manifest; the import was rolled back.')
            self.stdout.write('Content snapshot imported: ' + ', '.join(f'{name}={count}' for name, count in counts.items()))
