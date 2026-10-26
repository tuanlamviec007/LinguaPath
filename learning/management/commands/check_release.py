"""Require startup prerequisites; never repair data or call an AI provider."""
import json

from django.core.management.base import BaseCommand, CommandError

from config.release_checks import evaluate_release


class Command(BaseCommand):
    help = 'Check production configuration, schema and weak-word projections; --local explicitly checks development readiness only.'

    def add_arguments(self, parser):
        parser.add_argument('--local', action='store_true')
        parser.add_argument('--format', choices=('text', 'json'), default='text')

    def handle(self, *args, **options):
        report = evaluate_release(require_production=not options['local'])
        if options['format'] == 'json':
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(f"Release prerequisites ({report['mode']}): {'ready' if report['ready'] else 'blocked'}")
            for item in report['checks']:
                self.stdout.write(f"{item['status'].upper()} {item['id']}: {item['message']}")
            self.stdout.write('This check does not approve a release or certify the full audit.')
        if not report['ready']:
            raise CommandError('Release prerequisites are not ready; see the safe diagnostic report.')
