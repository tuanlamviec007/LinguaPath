"""D07: synthetic PostgreSQL read scaling, isolated by Django's test database.

This measures a populated materialized projection, not rebuild throughput,
concurrent load, Neon capacity or production response time. No provider calls.
"""
from datetime import timedelta
import json
import statistics
import time
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from .models import Flashcard, LearningContent, VocabularyQuizSession
from .weak_word_models import WeakWordOutcome, WeakWordProjectionState, WeakWordQuizReceipt
from .weak_word_outcomes import PROJECTION_VERSION, materialized_weak_word_summary, word_identity


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL EXPLAIN ANALYZE is required')
class WeakWordPostgresReadPlanTests(TestCase):
    def test_read_plan_stays_bounded_without_loading_history_payloads(self):
        now = timezone.now()
        content = LearningContent.objects.create(title='Synthetic query-plan bank', exam_type='TOEIC',
            content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
        cards = Flashcard.objects.bulk_create([Flashcard(content=content, term=f'plan-word-{i}',
            meaning_vi=f'nghĩa riêng {i}', part_of_speech='noun', cefr_level='B1') for i in range(3000)], batch_size=200)
        snapshot = [{'number': i, 'card_id': card.pk, 'term': card.term, 'meaning_vi': card.meaning_vi,
            'part_of_speech': 'noun', 'correct_key': 'A',
            'options': [{'key': 'A', 'text': card.meaning_vi}, {'key': 'B', 'text': 'khác'}],
            'synthetic_context_padding': 'x' * 1800} for i, card in enumerate(cards[:15], 1)]
        answers = {str(i): 'B' for i in range(1, 16)}
        snapshot_bytes = len(json.dumps(snapshot, ensure_ascii=False).encode())
        measurements = []
        for history_count in (10, 1000, 5000):
            with self.subTest(history_count=history_count):
                user = get_user_model().objects.create_user(username=f'plan-synthetic-{history_count}')
                last_quiz = None
                for start in range(0, history_count, 100):
                    quizzes = VocabularyQuizSession.objects.bulk_create([VocabularyQuizSession(user=user,
                        exam_type='TOEIC', mode='meaning', status='submitted', question_count=15,
                        correct_count=0, snapshot=snapshot, answers=answers,
                        submitted_at=now - timedelta(seconds=history_count - i + 1))
                        for i in range(start, min(start + 100, history_count))], batch_size=100)
                    # Bulk fixtures deliberately model an already-populated projection;
                    # rebuild correctness/concurrency is tested in separate suites.
                    WeakWordQuizReceipt.objects.bulk_create([WeakWordQuizReceipt(user=user, quiz=quiz,
                        fingerprint='a' * 64) for quiz in quizzes], batch_size=100)
                    last_quiz = quizzes[-1]
                WeakWordProjectionState.objects.create(user=user, version=PROJECTION_VERSION, ready=True)
                WeakWordOutcome.objects.bulk_create([WeakWordOutcome(user=user, exam_type='TOEIC',
                    card_id=card.pk, identity_hash=word_identity(card.term, card.meaning_vi), group_key='b' * 64,
                    mode='meaning', term=card.term, meaning_vi=card.meaning_vi, part_of_speech='noun',
                    last_attempt_at=last_quiz.submitted_at, last_quiz_id=last_quiz.pk,
                    is_wrong=True, wrong_count=history_count) for card in cards[:15]])
                samples, queries = [], []

                def capture(execute, sql, params, many, context):
                    # Capture before psycopg wraps iterator SELECTs in DECLARE CURSOR.
                    self.assertTrue(sql.lstrip().upper().startswith('SELECT'), sql)
                    self.assertFalse(many)
                    for forbidden in ('"snapshot"', '"answers"', '"draft_answers"'):
                        self.assertNotIn(forbidden, sql.lower())
                    queries.append((sql, params))
                    return execute(sql, params, many, context)

                for unused in range(3):
                    queries = []
                    started = time.perf_counter()
                    with connection.execute_wrapper(capture):
                        summary = materialized_weak_word_summary(user, 'TOEIC', now=now)
                    samples.append(round((time.perf_counter() - started) * 1000, 3))
                    self.assertTrue(summary['ready'])
                    self.assertEqual(summary['count'], 15)
                    self.assertTrue(all(word['wrong_count'] == history_count for word in summary['words']))
                    self.assertEqual(len(queries), 5)
                plans = []
                with connection.cursor() as cursor:
                    for sql, params in queries:
                        cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql, params)
                        document = cursor.fetchone()[0][0]
                        root = document['Plan']
                        # Do not export SQL, identities, parameters or plan filters.
                        plans.append({'node': root['Node Type'], 'actual_rows': root['Actual Rows'],
                            'shared_hit_blocks': root.get('Shared Hit Blocks', 0),
                            'shared_read_blocks': root.get('Shared Read Blocks', 0),
                            'execution_ms': document['Execution Time']})
                measurements.append({'history_sessions': history_count,
                    'logical_snapshot_bytes': snapshot_bytes * history_count,
                    'visible_cards': 3000, 'weak_words': 15, 'select_queries': len(queries),
                    'history_payload_columns_selected': 0, 'read_samples_ms': samples,
                    'median_read_ms': round(statistics.median(samples), 3), 'plans': plans})
        print('\nD07_POSTGRES_READ_PLAN ' + json.dumps({'version': 1,
            'backend': 'isolated PostgreSQL test database', 'measurements': measurements,
            'scope': 'Synthetic materialized reads, warm samples; not production latency, concurrent load or rebuild throughput.'}))
