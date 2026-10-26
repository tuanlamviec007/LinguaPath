"""Bounded tutor evaluation, offline unless an operator explicitly enables live calls."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from learning.tutor_evaluation import load_evaluation_cases, run_tutor_evaluation


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES = ROOT / 'learning' / 'data' / 'tutor_router_regression_v1.json'
MAX_REPORT_BYTES = 20 * 1024 * 1024
PROTECTED_DIRECTORIES = ('learning', 'planner', 'config', 'static', 'templates',
                         'scripts', 'deploy', '.github', '.openai')
CODE_FILES = ('learning/ai.py', 'learning/ai_context.py', 'learning/ai_provider.py',
              'learning/retrieval.py', 'learning/tutor_knowledge.py',
              'learning/retrieval_description.py',
              'learning/tutor_evaluation.py',
              'learning/management/commands/evaluate_tutor_answers.py')


def _output_path(value, source, *, overwrite):
    target = Path(value).expanduser().absolute()
    if target.suffix.lower() != '.json' or target.is_symlink():
        raise CommandError('Output must be a separate JSON file, not a symbolic link.')
    if target.resolve() == source.resolve():
        raise CommandError('Report output must not replace the input fixture.')
    if target.exists() and source.exists() and os.path.samefile(target, source):
        raise CommandError('Report output must not be a hard link to the input fixture.')
    resolved = target.resolve()
    if any(resolved.is_relative_to(ROOT / directory) for directory in PROTECTED_DIRECTORIES):
        raise CommandError('Reports must not replace files in application source directories.')
    if not target.parent.is_dir() or target.is_dir():
        raise CommandError('Output must be a file in an existing directory.')
    if target.exists() and not overwrite:
        raise CommandError('Output already exists; explicitly use --overwrite or choose another path.')
    return target


def _atomic_report(target, raw, *, overwrite):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent,
                prefix='.tutor-evaluation-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, target)
        else:
            # Link creation is exclusive even if a second evaluator races us.
            os.link(temporary, target)
            temporary.unlink()
        temporary = None
    except OSError as error:
        raise CommandError('Could not save tutor evaluation; the destination was not replaced.') from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class Command(BaseCommand):
    help = ('Evaluate tutor responses and source routing. Offline by default; live mode '
            'requires an existing active staff account and an explicit request cap.')

    def add_arguments(self, parser):
        parser.add_argument('--cases', type=Path, default=DEFAULT_CASES)
        parser.add_argument('--exam', choices=['TOEIC', 'IELTS'], default='TOEIC')
        parser.add_argument('--output', type=Path, required=True)
        parser.add_argument('--overwrite', action='store_true')
        parser.add_argument('--live', action='store_true')
        parser.add_argument('--user-id', type=int)
        parser.add_argument('--max-live-calls', type=int, default=0)

    def handle(self, *args, **options):
        source = Path(options['cases']).expanduser().absolute()
        output = _output_path(options['output'], source, overwrite=options['overwrite'])
        if not options['live'] and (options['user_id'] is not None or options['max_live_calls'] != 0):
            raise CommandError('--user-id and --max-live-calls require --live; offline mode uses no account.')
        if options['live'] and (options['user_id'] is None or not 1 <= options['max_live_calls'] <= 10):
            raise CommandError('--live requires --user-id and --max-live-calls between 1 and 10.')
        try:
            fixture = load_evaluation_cases(source)
            with source.open('rb') as stream:
                fixture_bytes = stream.read(1024 * 1024 + 1)
            if len(fixture_bytes) > 1024 * 1024:
                raise ValueError('Fixture changed beyond its bound')
            # Bind the byte hash to the same content that the validated loader
            # returned; a concurrent fixture edit must not receive a false hash.
            if json.dumps(json.loads(fixture_bytes), sort_keys=True, ensure_ascii=False,
                    separators=(',', ':'), allow_nan=False) != json.dumps(fixture,
                    sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False):
                raise ValueError('Fixture changed while loading')
            provenance = {'fixture_file_sha256': hashlib.sha256(fixture_bytes).hexdigest(),
                'code_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES}}
        except (OSError, ValueError, TypeError) as error:
            raise CommandError('Cannot load a valid bounded evaluation fixture and code provenance.') from error
        user = None
        if options['live']:
            if len(fixture['cases']) > options['max_live_calls']:
                raise CommandError('Fixture case count exceeds --max-live-calls; choose a smaller fixture.')
            if not 0 < options['user_id'] <= 2**63 - 1:
                raise CommandError('--user-id must identify an existing active staff account.')
            user = get_user_model().objects.filter(pk=options['user_id'], is_active=True, is_staff=True).first()
            if user is None:
                raise CommandError('--user-id must identify an existing active staff account.')
        try:
            report = run_tutor_evaluation(fixture, exam=options['exam'], live=options['live'],
                user=user, max_live_calls=options['max_live_calls'])
            report['run_provenance'] = provenance
            raw = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
            if len(raw) > MAX_REPORT_BYTES:
                raise ValueError('Oversized report')
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
            raise CommandError('Tutor evaluation could not produce a valid bounded report.') from error
        # Recheck symlink/hard-link changes before an explicit replacement.
        output = _output_path(output, source, overwrite=options['overwrite'])
        _atomic_report(output, raw, overwrite=options['overwrite'])
        self.stdout.write(f'Tutor evaluation report saved: {output}')
        self.stdout.write('Source-routing checks are not semantic quality scores or independent human adjudication.')
        if not options['live']:
            self.stdout.write('Offline: no model requests, quota reservations or learner account context.')
        else:
            self.stdout.write('Live requests use the existing per-user/global quota; no retries or quota bypass.')
        if report.get('summary', {}).get('errors', 0):
            raise CommandError('One or more cases failed; the saved report records redacted case errors.')
