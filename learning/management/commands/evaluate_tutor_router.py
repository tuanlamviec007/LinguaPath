"""Offline, editorial router regressions; deliberately not a held-out benchmark."""
import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from learning.models import Flashcard, LEARNER_REVIEW_STATUSES


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / 'data' / 'tutor_router_regression_v1.json'


def _identity(item, *, expected=False):
    kind = item.get('kind')
    if kind == 'knowledge':
        value = item.get('knowledge_id') if expected else item.get('source_id')
        if isinstance(value, str) and value.strip():
            return ('knowledge', value.strip())
    elif kind == 'flashcard':
        value = item.get('term')
        if isinstance(value, str) and value.strip():
            return ('flashcard', value.strip().casefold())
    if expected:
        raise ValueError('Expected source must have a knowledge_id or flashcard term.')
    # Unexpected source types must count as false positives, never as abstention.
    return (str(kind or 'unknown'), str(item.get('source_id', 'unknown')))


def load_cases(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('cases'), list) or not data['cases']:
        raise ValueError('Router fixture requires a non-empty cases list.')
    if not isinstance(data.get('provenance'), str) or not data['provenance'].strip():
        raise ValueError('Router fixture must declare its editorial provenance.')
    ids = set()
    for row in data['cases']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in ids:
            raise ValueError('Router case IDs must be unique non-empty strings.')
        ids.add(row['id'])
        if (not isinstance(row.get('query'), str) or not row['query'].strip() or len(row['query']) > 500
                or not isinstance(row.get('category'), str) or not row['category'].strip()
                or not isinstance(row.get('expected'), list)):
            raise ValueError('Router case query, category or expected sources are invalid.')
        if any(not isinstance(item, dict) for item in row['expected']):
            raise ValueError('Expected sources must be objects.')
        identities = [_identity(item, expected=True) for item in row['expected']]
        if len(identities) != len(set(identities)):
            raise ValueError('Expected source identities must not repeat.')
    return data


def summarize(records):
    positive = [row for row in records if row['expected']]
    negative = [row for row in records if not row['expected']]
    expected_count = sum(len(row['expected']) for row in positive)
    found_count = sum(len(row['expected']) - len(row['omissions']) for row in positive)
    exact = sum(row['exact_match'] for row in records)
    abstained = sum(not row['actual'] for row in negative)
    return {
        'cases': len(records), 'positive_cases': len(positive), 'negative_cases': len(negative),
        'exact_matches': exact,
        'exact_match_rate': round(exact / len(records), 4) if records else None,
        'expected_sources': expected_count, 'covered_expected_sources': found_count,
        'positive_coverage': round(found_count / expected_count, 4) if expected_count else None,
        'negative_abstentions': abstained,
        'negative_abstention_rate': round(abstained / len(negative), 4) if negative else None,
        'omissions': sum(len(row['omissions']) for row in records),
        'false_positives': sum(len(row['false_positives']) for row in records),
    }


def evaluate(cases, retriever, *, exam, limit):
    records = []
    for row in cases:
        expected = {_identity(item, expected=True) for item in row['expected']}
        actual = {_identity(item) for item in retriever(row['query'], exam=exam, limit=limit)}
        # Lists of [kind, identifier] are a stable JSON representation of sets.
        records.append({
            'id': row['id'], 'category': row['category'], 'query': row['query'],
            'expected': sorted(expected), 'actual': sorted(actual),
            'omissions': sorted(expected - actual), 'false_positives': sorted(actual - expected),
            'exact_match': expected == actual,
        })
    return {
        'overall': summarize(records),
        'by_category': {category: summarize([row for row in records if row['category'] == category])
                        for category in sorted({row['category'] for row in records})},
        'cases': records,
    }


class Command(BaseCommand):
    help = 'Run AI-editorial tutor routing regressions offline; no inference or database writes.'

    def add_arguments(self, parser):
        parser.add_argument('--cases', default=str(DEFAULT_CASES))
        parser.add_argument('--output')
        parser.add_argument('--exam', choices=['TOEIC', 'IELTS'], default='TOEIC')
        parser.add_argument('--limit', type=int, default=3)

    def handle(self, *args, **options):
        from learning.ai import retrieve_learning_context

        if not 1 <= options['limit'] <= 10:
            raise CommandError('--limit must be between 1 and 10.')
        path = Path(options['cases']).resolve()
        try:
            fixture = load_cases(path)
        except (OSError, ValueError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
        cards = Flashcard.objects.learner_visible().filter(content__is_published=True,
            content__review_status__in=LEARNER_REVIEW_STATUSES, content__exam_type=options['exam'])
        corpus = list(cards.order_by('pk').values(
            'id', 'term', 'meaning_vi', 'part_of_speech', 'example_en', 'example_vi', 'topic',
            'cefr_level', 'content_id', 'content__title', 'content__topic', 'content__review_status'))
        report = {
            'generated_at': timezone.now().isoformat(), 'fixture_version': fixture.get('version'),
            'provenance': fixture['provenance'],
            'scope': 'Production tutor routing without a learner or question_id; AI-editorial regressions, not an independent holdout or model answer-quality evaluation.',
            'exam': options['exam'], 'limit': options['limit'], 'visible_card_count': len(corpus),
            'fixture_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'corpus_sha256': hashlib.sha256(json.dumps(corpus, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            'router_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                              for name in ('ai.py', 'retrieval.py')},
            'knowledge_sha256': hashlib.sha256((ROOT / 'tutor_knowledge.py').read_bytes()).hexdigest(),
            **evaluate(fixture['cases'], retrieve_learning_context, exam=options['exam'], limit=options['limit']),
        }
        metrics = report['overall']
        self.stdout.write(f"Router regressions: exact={metrics['exact_matches']}/{metrics['cases']}; "
                          f"source coverage={metrics['positive_coverage']}; negative abstention={metrics['negative_abstention_rate']}")
        self.stdout.write('AI-editorial regression only; not an independent holdout; no model requests.')
        if options.get('output'):
            try:
                output = Path(options['output']).resolve()
                # Never overwrite either the fixture or production source files.
                if output == path or output == DEFAULT_CASES.resolve() or output.suffix.lower() != '.json':
                    raise ValueError('Output must be a separate JSON report path.')
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            except (OSError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(self.style.SUCCESS(f'Report: {output}'))
