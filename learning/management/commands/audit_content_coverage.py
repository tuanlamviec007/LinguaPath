"""Export a structural source-library inventory without reading learner data."""
import json
import os
from pathlib import Path
import tempfile

from django.core.management.base import BaseCommand, CommandError

from learning.content_coverage import content_coverage


class Command(BaseCommand):
    help = 'Read-only source coverage report. Counts and metadata do not certify language or exam quality.'

    def add_arguments(self, parser):
        parser.add_argument('--exam', choices=('TOEIC', 'IELTS'), default='TOEIC')
        parser.add_argument('--output', type=Path)
        parser.add_argument('--overwrite', action='store_true', help='Explicitly replace an existing report file.')

    def handle(self, *args, **options):
        output = options['output']
        if output is not None and output.exists() and not options['overwrite']:
            raise CommandError('Output already exists; choose a new path or pass --overwrite.')
        report = content_coverage(options['exam'])
        encoded = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        if output is None:
            self.stdout.write(encoded)
            return
        temporary = None
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='.coverage-',
                                             dir=output.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if options['overwrite']:
                os.replace(temporary, output)
            else:
                # Link creation fails atomically if another process claimed
                # this path after the preflight check; never clobber silently.
                os.link(temporary, output)
                temporary.unlink()
            self.stdout.write(f'Coverage report written: {output}')
        except OSError as exc:
            raise CommandError('Could not write report safely; choose an available output path.') from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
