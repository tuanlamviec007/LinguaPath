"""Check a review sample and human annotations without importing or approving."""
import json
import os
from pathlib import Path
import tempfile

from django.core.management.base import BaseCommand, CommandError

from learning.review_validation import load_review_packet, ReviewPacketLoadError, validate_review_packet


class Command(BaseCommand):
    help = 'Validate an annotated review sample against current sources; never import, approve, or publish.'

    def add_arguments(self, parser):
        parser.add_argument('--input', type=Path, required=True)
        parser.add_argument('--output', type=Path)
        parser.add_argument('--overwrite', action='store_true')

    def handle(self, *args, **options):
        source = options['input'].expanduser().absolute()
        output = options['output'].expanduser().absolute() if options['output'] else None
        if output is not None:
            if output.resolve() == source.resolve():
                raise CommandError('Report output must not replace the input review packet.')
            if not output.parent.is_dir() or output.is_dir():
                raise CommandError('Output must be a file in an existing directory.')
            if output.exists() and not options['overwrite']:
                raise CommandError('Output already exists; explicitly use --overwrite or choose another path.')
        try:
            with source.open('rb') as stream:
                packet = load_review_packet(stream)
            report = validate_review_packet(packet)
        except (OSError, ReviewPacketLoadError) as error:
            raise CommandError('Cannot read a valid, bounded UTF-8 review packet.') from error
        if output is None:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                        prefix='.review-validation-', suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(report, stream, ensure_ascii=False, indent=2)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                if options['overwrite']:
                    os.replace(temporary, output)
                else:
                    os.link(temporary, output)
                    temporary.unlink()
                temporary = None
            except OSError as error:
                raise CommandError('Could not save validation report; destination was not replaced.') from error
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            self.stdout.write(f'Review validation report saved: {output}')
        if report['status'] != 'current':
            raise CommandError('Review packet is invalid or no longer matches current sources; see the report.')
