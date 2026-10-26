"""PostgreSQL proof that backfill and an in-flight submission do not lose work."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from .locking import nonkey_row_lock
from .models import Flashcard, LearningContent, VocabularyQuizSession
from .weak_word_models import WeakWordProjectionState, WeakWordQuizReceipt
from .weak_word_outcomes import materialized_weak_word_summary, rebuild_user_outcomes, record_quiz_outcomes


@skipUnlessDBFeature('has_select_for_no_key_update')
class WeakWordBackfillConcurrencyTests(TransactionTestCase):
    def test_backfill_then_inflight_submission_preserves_both_receipts_and_mistakes(self):
        user = get_user_model().objects.create_user(username='backfill-concurrent-owner')
        content = LearningContent.objects.create(title='Concurrency fixture', exam_type='TOEIC',
            content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        card = Flashcard.objects.create(content=content, term='deadline', meaning_vi='hạn chót', cefr_level='B1')
        snapshot = [{'number': 1, 'card_id': card.pk, 'term': card.term, 'meaning_vi': card.meaning_vi,
            'part_of_speech': '', 'correct_key': 'A',
            'options': [{'key': 'A', 'text': card.meaning_vi}, {'key': 'B', 'text': 'khác'}]}]
        values = {'user_id': user.pk, 'exam_type': 'TOEIC', 'status': 'submitted', 'mode': 'meaning',
            'question_count': 1, 'snapshot': snapshot, 'answers': {'1': 'B'}, 'submitted_at': timezone.now()}
        VocabularyQuizSession.objects.create(**values)
        self.assertEqual(WeakWordQuizReceipt.objects.filter(user=user).count(), 1)
        locked, inserted = Event(), Event()

        def backfill():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '8s'")
                    nonkey_row_lock(get_user_model().objects.all()).get(pk=user.pk)
                    locked.set()
                    if not inserted.wait(timeout=10):
                        raise AssertionError('FK insert could not proceed while User NO KEY UPDATE was held.')
                    # The other transaction's quiz is not committed yet. This
                    # rebuild must include only the baseline; the subsequent
                    # projection then adds the in-flight quiz exactly once.
                    return rebuild_user_outcomes(user.pk)
            finally:
                locked.set()
                close_old_connections()

        def submit():
            close_old_connections()
            try:
                if not locked.wait(timeout=10):
                    raise AssertionError('Backfill failed to acquire its User lock.')
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '8s'")
                    # bulk_create deliberately pauses between an ordinary
                    # save's INSERT and its post_save projection. Both remain
                    # in the same transaction, as production submission does.
                    quiz = VocabularyQuizSession.objects.bulk_create([
                        VocabularyQuizSession(**{**values, 'submitted_at': timezone.now()})])[0]
                    with connection.cursor() as cursor:
                        # Django's PostgreSQL FKs can initially be deferred;
                        # force the check now so this handshake actually proves
                        # KEY SHARE compatibility, rather than postponing it.
                        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                    inserted.set()
                    record_quiz_outcomes(quiz)
                    record_quiz_outcomes(quiz)  # Receipt retry cannot double count.
                    return quiz.pk
            finally:
                inserted.set()
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            rebuilding = pool.submit(backfill)
            submitting = pool.submit(submit)
            rebuilt = rebuilding.result(timeout=25)
            new_id = submitting.result(timeout=25)
        self.assertEqual(rebuilt['quizzes'], 1)
        self.assertEqual(VocabularyQuizSession.objects.filter(user=user).count(), 2)
        self.assertEqual(WeakWordQuizReceipt.objects.filter(user=user).count(), 2)
        self.assertTrue(WeakWordProjectionState.objects.get(user=user).ready)
        summary = materialized_weak_word_summary(user, 'TOEIC')
        self.assertTrue(summary['ready'])
        self.assertEqual(summary['count'], 1)
        self.assertEqual(summary['words'][0]['wrong_count'], 2)
        self.assertEqual(summary['words'][0]['last_quiz_id'], new_id)
