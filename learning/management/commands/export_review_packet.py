"""Create a read-only review sample; never approve or publish source content."""
import json
import os
from pathlib import Path
import tempfile

from django.core.management.base import BaseCommand, CommandError

from learning.content_review import build_review_packet


class Command(BaseCommand):
    help = 'Export exact content IDs as a bounded human-review sample; no database writes or approval.'

    def add_arguments(self, parser):
        parser.add_argument('--content-id', type=int, action='append', required=True, dest='content_ids')
        parser.add_argument('--max-items', type=int, default=20)
        parser.add_argument('--output', type=Path, required=True)
        parser.add_argument('--overwrite', action='store_true')

    def handle(self, *args, **options):
        output = options['output'].expanduser().absolute()
        if not output.parent.is_dir():
            raise CommandError('Output directory must already exist.')
        if output.exists() and not options['overwrite']:
            raise CommandError('Output already exists; choose another path or explicitly use --overwrite.')
        if output.is_dir():
            raise CommandError('Output must be a file path.')
        try:
            packet = build_review_packet(options['content_ids'], max_items=options['max_items'])
        except ValueError as error:
            raise CommandError(str(error)) from None
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                    prefix='.review-packet-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(packet, stream, ensure_ascii=False, indent=2, default=str)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            if options['overwrite']:
                os.replace(temporary, output)
            else:
                # A concurrent export cannot overwrite a newly created file.
                os.link(temporary, output)
                temporary.unlink()
            temporary = None
        except OSError as error:
            raise CommandError('Could not save review packet; the destination was not replaced.') from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.stdout.write(f'Review sample saved: {output}')
        self.stdout.write('No approval, publication, learner records or model requests were changed.')
