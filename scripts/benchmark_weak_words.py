"""Synthetic SQLite benchmark, hard-wired to its own in-memory database.

Run from the checkout with the project's Python environment. It never connects
to the configured application database or model providers. This measures the
materialized read path only, not PostgreSQL concurrency or production latency.
"""
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--histories', type=int, nargs='+', default=[10, 1000, 5000])
    parser.add_argument('--cards', type=int, default=3000)
    parser.add_argument('--questions', type=int, default=15)
    args = parser.parse_args()
    if (any(not 1 <= count <= 10000 for count in args.histories)
            or not 1 <= args.questions <= args.cards <= 10000):
        parser.error('Use histories 1..10000 and 1 <= questions <= cards <= 10000.')

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    # Set these before importing/configuring Django; never reuse the caller's
    # DATABASE_URL or a persistent SQLite path for a destructive fixture run.
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    os.environ['DJANGO_DEBUG'] = 'true'
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['AI_TUTOR_ENABLED'] = 'false'
    os.environ['OPENAI_API_KEY'] = ''
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone
    from learning.models import Flashcard, LearningContent, VocabularyQuizSession
    from learning.weak_word_models import WeakWordOutcome
    from learning.weak_word_outcomes import rebuild_user_outcomes, materialized_weak_word_summary

    assert connection.settings_dict['ENGINE'] == 'django.db.backends.sqlite3'
    assert connection.settings_dict['NAME'] == ':memory:'
    call_command('migrate', verbosity=0)
    content = LearningContent.objects.create(title='Synthetic performance bank', exam_type='TOEIC',
        content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
    cards = Flashcard.objects.bulk_create([Flashcard(content=content, term=f'word-{index}',
        meaning_vi=f'nghĩa riêng {index}', part_of_speech='noun', cefr_level='B1') for index in range(args.cards)], batch_size=200)
    snapshot = [{'number': index, 'card_id': card.pk, 'term': card.term, 'meaning_vi': card.meaning_vi,
        'part_of_speech': card.part_of_speech, 'correct_key': 'A',
        'options': [{'key': 'A', 'text': card.meaning_vi}, {'key': 'B', 'text': 'khác'}],
        'synthetic_context_padding': 'x' * 1800} for index, card in enumerate(cards[:args.questions], 1)]
    answers = {str(index): 'B' for index in range(1, args.questions + 1)}
    snapshot_bytes = len(json.dumps(snapshot, ensure_ascii=False).encode('utf-8'))
    measurements = []
    now = timezone.now()
    for count in args.histories:
        user = get_user_model().objects.create_user(username=f'synthetic-history-{count}')
        for start in range(0, count, 100):
            VocabularyQuizSession.objects.bulk_create([VocabularyQuizSession(user=user, exam_type='TOEIC',
                status='submitted', mode='meaning', question_count=args.questions, correct_count=0,
                snapshot=snapshot, answers=answers, submitted_at=now - timedelta(seconds=count - index + 1))
                for index in range(start, min(start + 100, count))], batch_size=100)
        started = time.perf_counter()
        rebuilt = rebuild_user_outcomes(user, now=now)
        rebuild_ms = (time.perf_counter() - started) * 1000
        durations, query_counts = [], []
        for _ in range(3):
            started = time.perf_counter()
            with CaptureQueriesContext(connection) as captured:
                result = materialized_weak_word_summary(user, 'TOEIC', now=now)
            durations.append((time.perf_counter() - started) * 1000)
            query_counts.append(len(captured))
            assert result['ready'] and result['count'] == args.questions
            assert all(word['wrong_count'] == count for word in result['words'])
            assert all('"snapshot"' not in query['sql'] and '"answers"' not in query['sql'] for query in captured)
            assert all(query['sql'].lstrip().upper().startswith('SELECT') for query in captured)
        measurement = {'history_sessions': count, 'logical_snapshot_bytes': snapshot_bytes * count,
            'outcome_groups': WeakWordOutcome.objects.filter(user=user).count(),
            'weak_words': result['count'], 'read_samples_ms': [round(value, 3) for value in durations],
            'median_read_ms': round(statistics.median(durations), 3), 'read_query_counts': query_counts,
            'selected_history_payload_columns': 0, 'rebuild_ms': round(rebuild_ms, 3),
            'rebuilt_quizzes': rebuilt['quizzes']}
        measurements.append(measurement)
        print(json.dumps(measurement), flush=True)
    report = {'generated_at': timezone.now().isoformat(), 'database': 'isolated SQLite :memory:',
        'scope': 'Synthetic local materialized read benchmark, not PostgreSQL/production latency or a before-after claim.',
        'visible_cards': args.cards, 'questions_per_session': args.questions,
        'snapshot_bytes_per_session': snapshot_bytes, 'read_repetitions': 3, 'measurements': measurements,
        'code_sha256': {str(path): hashlib.sha256((root/path).read_bytes()).hexdigest() for path in (
            Path('learning/weak_word_outcomes.py'), Path('learning/weak_word_models.py'),
            Path('learning/quiz_answers.py'), Path('learning/quiz_recall.py'))},
        'malformed_history_policy': 'Conflicting duplicate card identities/recall cues within one session are excluded for that card; exact duplicates keep first valid answer once. Canonical quizzes contain unique card IDs.'}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
