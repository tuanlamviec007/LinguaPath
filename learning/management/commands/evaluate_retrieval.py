"""Read-only lexical retrieval regression with guarded report output."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from learning.models import Flashcard, LEARNER_REVIEW_STATUSES
from learning.retrieval_baseline import retrieve_context as baseline_retrieve
from learning.retrieval_v1 import retrieve_context as previous_retrieve
from learning.retrieval_evaluation import BENCHMARK_PATH, _sense_identity, evaluate_cases, load_benchmark
from .evaluate_tutor_answers import MAX_REPORT_BYTES, _atomic_report, _output_path


ROOT = Path(__file__).resolve().parents[3]
MAX_FIXTURE_BYTES = 1024 * 1024
MAX_CASES = 200
MAX_QUERY_LENGTH = 500
FIXED_BENCHMARKS = (BENCHMARK_PATH, BENCHMARK_PATH.with_name('retrieval_benchmark_v2.json'))
SENSE_MATCH_POLICY = {
    'version': 'literal-source-sense-v1',
    'normalization': ['NFC', 'casefold', 'whitespace'],
    'preserves_accents': True,
    'preserves_punctuation': True,
    'semantic_equivalence': False,
}
SCOPE = 'Vocabulary retrieval only; AI/editorial regression, not independent holdout; no LLM answer-quality evaluation.'


def _report_path(value, source, *, overwrite):
    target = _output_path(value, source, overwrite=overwrite)
    # Custom fixtures must not make either bundled benchmark writable through
    # a hard-link alias outside application source directories.
    for fixture in FIXED_BENCHMARKS:
        if (target.resolve() == fixture.resolve()
                or (target.exists() and fixture.exists() and os.path.samefile(target, fixture))):
            raise CommandError('Report output must not replace a fixed benchmark fixture or its alias.')
    return target


def _bounded_fixture(source):
    if not source.is_file():
        raise ValueError('Benchmark input must be an existing regular file.')
    with source.open('rb') as stream:
        raw = stream.read(MAX_FIXTURE_BYTES + 1)
    if len(raw) > MAX_FIXTURE_BYTES:
        raise ValueError('Benchmark exceeds the 1 MiB limit.')
    # Validate a private, frozen copy of these exact bounded bytes. Reading the
    # mutable source again could attach one version's hash to another's labels.
    with tempfile.TemporaryDirectory(prefix='retrieval-fixture-') as directory:
        frozen = Path(directory) / 'fixture.json'
        frozen.write_bytes(raw)
        benchmark = load_benchmark(frozen)
    cases = benchmark['cases']
    if not 1 <= len(cases) <= MAX_CASES or any(len(case['query']) > MAX_QUERY_LENGTH for case in cases):
        raise ValueError('Benchmark allows at most 200 cases and 500 characters per query.')
    return benchmark, raw


class Command(BaseCommand):
    help = 'So sánh truy xuất từ vựng trên regression có nhãn; không gọi LLM, sửa DB hoặc xác nhận holdout độc lập.'

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group()
        source.add_argument('--benchmark-version', choices=['1', '2'], default=None,
            help='Tập regression lịch sử 1 hoặc 2; mặc định là 1, không phải holdout độc lập.')
        source.add_argument('--benchmark-file', type=Path, help='Fixture JSON riêng, tối đa1 MiB/200 ca/500 ký tự mỗi truy vấn.')
        parser.add_argument('--output', type=Path, help='File JSON tổng hợp trong thư mục đã tồn tại (tùy chọn).')
        parser.add_argument('--overwrite', action='store_true', help='Cho phép thay riêng file báo cáo hiện có sau kiểm tra đường dẫn.')
        parser.add_argument('--include-test', action='store_true', help='Mở thêm split test đã ghi nhãn; không biến regression thành holdout.')
        parser.add_argument('--retrieval-mode', choices=['auto', 'description'], default='auto',
            help='auto: luồng thường; description: chỉ đo ứng viên từ mô tả, không so với baseline khác tác vụ.')

    def handle(self, *args, **options):
        from learning.retrieval import retrieve_context

        if options.get('benchmark_file') is not None and options.get('benchmark_version') is not None:
            raise CommandError('--benchmark-file and --benchmark-version are mutually exclusive.')
        if options.get('overwrite') and not options.get('output'):
            raise CommandError('--overwrite requires --output.')
        benchmark_path = (Path(options['benchmark_file']) if options.get('benchmark_file') is not None
            else FIXED_BENCHMARKS[1 if options.get('benchmark_version') == '2' else 0]).expanduser().absolute()
        output = _report_path(options['output'], benchmark_path, overwrite=options['overwrite']) if options.get('output') else None
        try:
            benchmark, fixture_bytes = _bounded_fixture(benchmark_path)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            raise CommandError('Cannot load a valid bounded retrieval benchmark.') from exc
        cases = [case for case in benchmark['cases'] if options['include_test'] or case['split'] == 'dev']
        if not cases:
            raise CommandError('Selected benchmark split contains no cases.')
        cards = Flashcard.objects.learner_visible().filter(content__is_published=True,
            content__review_status__in=LEARNER_REVIEW_STATUSES, content__exam_type='TOEIC')
        if options['retrieval_mode'] == 'description':
            cards = cards.filter(content__content_type='vocabulary')
        corpus = list(cards.order_by('id').values(
            'id', 'term', 'meaning_vi', 'part_of_speech', 'example_en', 'example_vi',
            'topic', 'cefr_level', 'content_id', 'content__title', 'content__topic', 'content__review_status',
        ))
        available = {row['term'].strip().casefold() for row in corpus}
        expected = {term.strip().casefold() for case in cases for term in case['expected_terms']}
        missing = sorted(expected - available)
        if missing:
            raise CommandError('Thiếu từ nguồn trong tập đã chọn; hãy nạp seed trước: ' + ', '.join(missing))
        available_senses = {_sense_identity(row) for row in corpus}
        expected_senses = {_sense_identity(sense) for case in cases for sense in case.get('expected_senses', [])}
        if expected_senses - available_senses:
            raise CommandError('Thiếu nghĩa nguồn khớp nhãn trong tập đã chọn; hãy đối chiếu học liệu khả dụng.')
        try:
            scorer_sha256 = hashlib.sha256((ROOT / 'learning/retrieval_evaluation.py').read_bytes()).hexdigest()
            retriever_sha256 = {name: hashlib.sha256((ROOT / 'learning' / filename).read_bytes()).hexdigest()
                for name, filename in [('baseline', 'retrieval_baseline.py'), ('previous', 'retrieval_v1.py'),
                    ('improved', 'retrieval.py'), ('description_index', 'retrieval_description.py')]}
        except OSError as exc:
            raise CommandError('Cannot fingerprint retrieval evaluator source.') from exc
        self.stdout.write(self.style.WARNING('AI/editorial regression, not independent holdout. No model calls or human quality approval.'))
        description = options['retrieval_mode'] == 'description'
        retrievers = {'improved': lambda query, limit: retrieve_context(query, limit=limit, retrieval_mode='description')} if description else {
            'baseline': baseline_retrieve, 'previous': previous_retrieve, 'improved': retrieve_context}
        results = {
            'generated_at': timezone.now().isoformat(),
            'benchmark_version': benchmark.get('version'),
            'benchmark_sha256': hashlib.sha256(fixture_bytes).hexdigest(),
            'visible_card_count': len(corpus), 'k': 3,
            'corpus_sha256': hashlib.sha256(json.dumps(corpus, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest(),
            'includes_test': options['include_test'],
            'retrieval_mode': options['retrieval_mode'],
            'retriever_sha256': retriever_sha256,
            'scorer_sha256': scorer_sha256, 'sense_match_policy': SENSE_MATCH_POLICY,
            'command_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope': SCOPE + (' Description mode measures candidate retrieval only, not confirmed answers; automatic baselines omitted.' if description else ''),
            **{name: evaluate_cases(cases, retriever) for name, retriever in retrievers.items()},
        }
        for name in retrievers:
            # Publish aggregate metrics only; keep query/gold diagnostics out of reports.
            results[name].pop('cases')
            results[name]['by_split'] = {split: metrics for split, metrics in results[name]['by_split'].items() if metrics['queries']}
            for split, metrics in results[name]['by_split'].items():
                self.stdout.write(f"{name} {split}: Recall@3={metrics['recall_at_3']}, MRR@3={metrics['mrr_at_3']}, negative abstention={metrics['negative_abstention_rate']}")
        if output is not None:
            try:
                raw = (json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
                if len(raw) > MAX_REPORT_BYTES:
                    raise ValueError('Oversized report')
            except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
                raise CommandError('Cannot produce a valid bounded retrieval report.') from exc
            # Recheck aliases and file state before atomic replacement.
            output = _report_path(output, benchmark_path, overwrite=options['overwrite'])
            _atomic_report(output, raw, overwrite=options['overwrite'])
            self.stdout.write(self.style.SUCCESS(f'Đã ghi kết quả: {output}'))
