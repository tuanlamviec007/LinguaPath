"""Projection integrity, rollout and reads that never hydrate quiz snapshots."""
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .models import Flashcard, LearningContent, VocabularyQuizSession
from .weak_word_models import WeakWordOutcome, WeakWordPendingOutcome, WeakWordProjectionState, WeakWordQuizReceipt
from .weak_word_outcomes import materialized_weak_word_summary, rebuild_user_outcomes, record_quiz_outcomes


class WeakWordOutcomeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='projection-owner')
        self.other = get_user_model().objects.create_user(username='projection-other')
        self.now = timezone.now()
        self.content = LearningContent.objects.create(title='Projection words', exam_type='TOEIC',
            content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
        self.card = Flashcard.objects.create(content=self.content, term='deadline', meaning_vi='hạn chót',
            part_of_speech='noun', cefr_level='B1')

    def question(self, card=None, **overrides):
        card = card or self.card
        return {'number': 1, 'card_id': card.pk, 'term': card.term, 'meaning_vi': card.meaning_vi,
            'part_of_speech': card.part_of_speech, 'correct_key': 'A',
            'options': [{'key': 'A', 'text': card.meaning_vi}, {'key': 'B', 'text': 'khác'}], **overrides}

    def quiz(self, *, correct=False, mode='meaning', time=None, bulk=False, **overrides):
        question = self.question()
        values = {'user': self.user, 'exam_type': 'TOEIC', 'status': 'submitted', 'mode': mode,
            'question_count': 1, 'submitted_at': time or self.now - timedelta(minutes=1),
            'snapshot': [question], 'answers': {'1': ('deadline' if correct else 'other') if mode == 'recall' else ('A' if correct else 'B')}}
        values.update(overrides)
        if bulk:
            return VocabularyQuizSession.objects.bulk_create([VocabularyQuizSession(**values)])[0]
        return VocabularyQuizSession.objects.create(**values)

    def summary(self, user=None, **kwargs):
        return materialized_weak_word_summary(user or self.user, 'TOEIC', **kwargs)

    def test_latest_outcome_counts_all_mistakes_and_record_is_idempotent(self):
        self.quiz(time=self.now - timedelta(days=2))
        latest = self.quiz(time=self.now - timedelta(minutes=2))
        self.assertFalse(record_quiz_outcomes(latest))
        self.assertEqual(self.summary()['words'][0]['wrong_count'], 2)
        self.assertEqual(WeakWordQuizReceipt.objects.count(), 2)
        self.quiz(correct=True, time=self.now - timedelta(minutes=1))
        self.assertEqual(self.summary()['count'], 0)
        self.quiz(time=self.now)
        self.assertEqual(self.summary()['words'][0]['wrong_count'], 3)

    def test_timestamp_and_quiz_id_break_ties_even_for_out_of_order_ingestion(self):
        at = self.now - timedelta(minutes=2)
        self.quiz(time=at)
        self.quiz(correct=True, time=at)
        self.quiz(time=at - timedelta(seconds=1))
        self.assertEqual(self.summary()['count'], 0)
        last = self.quiz(time=at)
        self.assertEqual(self.summary()['words'][0]['last_quiz_id'], last.pk)

    def test_current_identity_and_visibility_do_not_transfer_revised_mistakes(self):
        self.quiz()
        Flashcard.objects.filter(pk=self.card.pk).update(term='DEADLINE  ', meaning_vi='  HẠN   CHÓT ')
        self.assertEqual(self.summary()['count'], 1)
        Flashcard.objects.filter(pk=self.card.pk).update(meaning_vi='nghĩa mới')
        self.assertEqual(self.summary()['count'], 0)
        Flashcard.objects.filter(pk=self.card.pk).update(meaning_vi='hạn chót')
        self.assertEqual(self.summary()['count'], 1)
        LearningContent.objects.filter(pk=self.content.pk).update(is_published=False)
        self.assertEqual(self.summary()['count'], 0)

    def test_recall_ambiguity_can_change_without_rebuilding_history(self):
        self.quiz(time=self.now - timedelta(days=1))
        self.quiz(correct=True, mode='recall', time=self.now)
        self.assertEqual(self.summary()['count'], 0)
        other = Flashcard.objects.create(content=self.content, term='due date', meaning_vi='hạn chót',
            part_of_speech='noun', cefr_level='B1')
        # Same initial and word count are required to make the actual displayed
        # cue ambiguous; use another one-word lemma beginning with d.
        Flashcard.objects.filter(pk=other.pk).update(term='date')
        self.assertEqual(self.summary()['count'], 1)
        self.assertEqual(self.summary()['words'][0]['wrong_count'], 1)
        other.delete()
        self.assertEqual(self.summary()['count'], 0)

    def test_session_internal_ambiguity_remains_invalid_after_other_card_disappears(self):
        other = Flashcard.objects.create(content=self.content, term='date', meaning_vi='hạn chót', part_of_speech='noun')
        first, second = self.question(), self.question(other, number=2)
        self.quiz(mode='recall', snapshot=[first, second], answers={'1': 'wrong', '2': 'wrong'})
        other.delete()
        self.assertEqual(self.summary()['count'], 0)
        self.assertEqual(WeakWordOutcome.objects.count(), 0)

    def test_future_evidence_waits_then_merges_without_reading_or_writing_snapshots(self):
        self.quiz()
        future = self.quiz(correct=True, time=self.now + timedelta(days=1))
        self.assertEqual(WeakWordPendingOutcome.objects.count(), 1)
        self.assertEqual(self.summary(now=self.now)['count'], 1)
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.summary(now=self.now + timedelta(days=2))['count'], 0)
        self.assertTrue(all('SELECT' in query['sql'].upper() for query in captured))
        self.assertTrue(all('"snapshot"' not in query['sql'] and '"answers"' not in query['sql'] for query in captured))
        future.refresh_from_db()
        self.assertEqual(future.answers, {'1': 'A'})

    def test_malformed_and_duplicate_evidence_is_not_double_counted(self):
        good = self.question()
        self.quiz(snapshot=[None, {'card_id': True}, self.question(options=[]), good, deepcopy(good)])
        self.assertEqual(self.summary()['words'][0]['wrong_count'], 1)
        self.quiz(snapshot={'bad': 'shape'})
        self.quiz(answers=[])
        self.quiz(status='abandoned')
        self.quiz(submitted_at=None)
        self.assertEqual(self.summary()['words'][0]['wrong_count'], 1)

    def test_conflicting_duplicate_identity_cannot_clear_or_open_a_mistake(self):
        self.quiz(time=self.now - timedelta(days=1))
        original = self.question(term='old-term', meaning_vi='nghĩa đã sửa')
        current = self.question(number=2)
        self.quiz(correct=True, snapshot=[original, current], answers={'1': 'A', '2': 'A'}, time=self.now)
        self.assertEqual(self.summary()['words'][0]['wrong_count'], 1)
        self.assertEqual(WeakWordOutcome.objects.count(), 1)
        self.quiz(user=self.other, snapshot=[original, current], answers={'1': 'B', '2': 'B'})
        self.assertEqual(self.summary(self.other)['count'], 0)

    def test_conflicting_duplicate_recall_cues_never_replace_valid_meaning_evidence(self):
        self.quiz(time=self.now - timedelta(days=1))
        self.quiz(mode='recall', snapshot=[self.question(), self.question(number=2, part_of_speech='verb')],
                  answers={'1': 'deadline', '2': 'deadline'}, time=self.now)
        self.assertEqual(self.summary()['words'][0]['wrong_count'], 1)
        self.assertEqual(WeakWordOutcome.objects.count(), 1)

    def test_legacy_or_bulk_import_requires_backfill_and_never_returns_partial_counts(self):
        self.quiz(bulk=True)
        self.assertFalse(self.summary()['ready'])
        self.quiz()
        self.assertTrue(self.summary()['needs_backfill'])
        result = rebuild_user_outcomes(self.user)
        self.assertEqual((result['quizzes'], result['groups']), (2, 1))
        self.assertEqual(self.summary()['words'][0]['wrong_count'], 2)

    def test_bulk_import_after_ready_state_is_detected_using_metadata_only(self):
        self.quiz()
        self.quiz(correct=True, bulk=True)
        with CaptureQueriesContext(connection) as captured:
            self.assertFalse(self.summary()['ready'])
        self.assertTrue(all('"snapshot"' not in query['sql'] and '"answers"' not in query['sql'] for query in captured))

    def test_backfill_is_idempotent_preserves_source_and_reconciles_saved_edits(self):
        quiz = self.quiz()
        original_snapshot = deepcopy(quiz.snapshot)
        quiz.answers = {'1': 'A'}
        quiz.save(update_fields=['answers'])
        self.assertFalse(self.summary()['ready'])
        first = rebuild_user_outcomes(self.user)
        second = rebuild_user_outcomes(self.user)
        self.assertEqual(first, second)
        self.assertEqual(self.summary()['count'], 0)
        quiz.refresh_from_db()
        self.assertEqual(quiz.snapshot, original_snapshot)
        self.assertEqual(WeakWordQuizReceipt.objects.count(), 1)

    def test_deleted_source_history_requires_explicit_reconciliation(self):
        quiz = self.quiz()
        quiz.delete()
        self.assertFalse(self.summary()['ready'])
        rebuild_user_outcomes(self.user)
        self.assertEqual(self.summary()['count'], 0)
        self.assertTrue(self.summary()['ready'])

    def test_changing_source_owner_invalidates_both_accounts(self):
        quiz = self.quiz()
        quiz.user = self.other
        quiz.save(update_fields=['user'])
        self.assertFalse(self.summary()['ready'])
        self.assertFalse(self.summary(self.other)['ready'])
        rebuild_user_outcomes(self.other)
        rebuild_user_outcomes(self.user)
        self.assertEqual(self.summary()['count'], 0)
        self.assertEqual(self.summary(self.other)['count'], 1)

    def test_backwards_clock_fails_closed_until_reconciliation(self):
        self.quiz(time=self.now - timedelta(days=2))
        self.quiz(correct=True, time=self.now - timedelta(minutes=1))
        before = self.now - timedelta(days=1)
        self.assertFalse(self.summary(now=before)['ready'])
        rebuild_user_outcomes(self.user, now=before)
        self.assertEqual(self.summary(now=before)['count'], 1)
        self.assertEqual(self.summary(now=self.now)['count'], 0)

    def test_wrong_evidence_is_private_and_exam_scoped(self):
        self.quiz()
        self.quiz(user=self.other, exam_type='IELTS')
        self.assertEqual(self.summary()['count'], 1)
        self.assertEqual(self.summary(self.other)['count'], 0)
        self.assertEqual(materialized_weak_word_summary(self.other, 'IELTS')['count'], 0)

    def test_submission_and_projection_roll_back_together(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.quiz()
                raise RuntimeError('rollback')
        self.assertFalse(VocabularyQuizSession.objects.exists())
        self.assertFalse(WeakWordOutcome.objects.exists())
        self.assertFalse(WeakWordQuizReceipt.objects.exists())

    def test_rebuild_failure_restores_prior_complete_projection(self):
        self.quiz()
        with patch.object(WeakWordOutcome.objects, 'bulk_create', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                rebuild_user_outcomes(self.user)
        self.assertTrue(WeakWordProjectionState.objects.get(user=self.user).ready)
        self.assertEqual(self.summary()['words'][0]['wrong_count'], 1)
        self.assertEqual(WeakWordQuizReceipt.objects.count(), 1)

    def test_backfill_command_preview_then_resumable_account_batch(self):
        self.quiz(bulk=True)
        before = WeakWordProjectionState.objects.count()
        call_command('backfill_weak_word_outcomes', stdout=StringIO())
        self.assertEqual(WeakWordProjectionState.objects.count(), before)
        call_command('backfill_weak_word_outcomes', apply=True, user_id=self.user.pk, stdout=StringIO())
        self.assertTrue(self.summary()['ready'])
        self.assertEqual(self.summary()['count'], 1)
        call_command('backfill_weak_word_outcomes', apply=True, after_user_id=self.user.pk, stdout=StringIO())
        self.assertTrue(WeakWordProjectionState.objects.get(user=self.other).ready)

    def test_materialized_reads_do_not_select_history_payloads(self):
        for _ in range(5):
            self.quiz()
        with CaptureQueriesContext(connection) as captured:
            summary = self.summary()
        self.assertEqual(summary['words'][0]['wrong_count'], 5)
        self.assertLessEqual(len(captured), 5)
        self.assertFalse(any('"snapshot"' in query['sql'] or '"answers"' in query['sql'] for query in captured))
