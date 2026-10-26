"""Export a blank human rubric or summarize a completed rubric; no model calls."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from learning.tutor_scoring import build_tutor_scorecard, load_evaluation_json, score_tutor_run
from .evaluate_tutor_answers import MAX_REPORT_BYTES, _atomic_report, _output_path


class Command(BaseCommand):
    help = 'Create a human scorecard for a Tutor evaluation run, or summarize a returned scorecard without approving a release.'

    def add_arguments(self, parser):
        parser.add_argument('--run', type=Path, required=True)
        parser.add_argument('--scorecard', type=Path)
        parser.add_argument('--output', type=Path, required=True)
        parser.add_argument('--overwrite', action='store_true')

    def handle(self, *args, **options):
        sources = [options['run'].expanduser().absolute()]
        if options['scorecard'] is not None:
            sources.append(options['scorecard'].expanduser().absolute())
        for source in sources:
            target = _output_path(options['output'], source, overwrite=options['overwrite'])
        try:
            run = load_evaluation_json(sources[0])
            if len(sources) == 1:
                report = build_tutor_scorecard(run)
            else:
                report = score_tutor_run(run, load_evaluation_json(sources[1]))
            raw = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
            if len(raw) > MAX_REPORT_BYTES:
                raise ValueError('Report exceeds its bound.')
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
            raise CommandError('Cannot read a valid run/scorecard with matching versions and rubric fields.') from error
        for source in sources:
            target = _output_path(target, source, overwrite=options['overwrite'])
        _atomic_report(target, raw, overwrite=options['overwrite'])
        self.stdout.write(f'Tutor human review file saved: {target}')
        self.stdout.write('No model requests or database writes. Completeness is not professional review, independent holdout verification or release approval.')
