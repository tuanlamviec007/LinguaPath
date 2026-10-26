from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import TestCase
from django.utils.functional import SimpleLazyObject
from .models import (
    AnswerOption,
    AttemptDraftAnswer,
    LearningContent,
    PracticeAttempt,
    Question,
)
from .practice_sessions import (
    DraftValidationError,
    PracticeUnavailableError,
    fingerprint_questions,
    save_draft,
    start_or_resume,
)


class PracticeSessionServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='session-user', password='secret12345')
        self.other_user = get_user_model().objects.create_user(username='other-session-user', password='secret12345')
        self.content = LearningContent.objects.create(
            title='Practice session test', exam_type='TOEIC', content_type='reading',
            skill='reading', is_published=True, review_status='teacher_approved',
        )
        self.q1 = self.make_question(1)
        self.q2 = self.make_question(2)

    def make_question(self, order):
        question = Question.objects.create(
            content=self.content,
            order=order,
            prompt=f'Question {order}?',
            passage='Read the notice.',
            explanation='The notice gives the answer.',
            explanation_vi='Đọc thông báo.',
        )
        correct = AnswerOption.objects.create(
            question=question, label='A', text=f'Answer {order}', is_correct=True,
            explanation_vi='Đáp án đúng.',
        )
        wrong = AnswerOption.objects.create(
            question=question, label='B', text=f'Other {order}', is_correct=False,
            explanation_vi='Không khớp.',
        )
        return question, correct, wrong

    def test_fingerprint_is_stable_and_changes_when_content_changes(self):
        questions = list(self.content.questions.prefetch_related('options').order_by('order', 'id'))
        before = fingerprint_questions(questions)
        self.assertEqual(before, fingerprint_questions(questions))
        self.q1[1].text = 'Edited answer'
        self.q1[1].save(update_fields=['text'])
        refreshed = list(self.content.questions.prefetch_related('options').order_by('order', 'id'))
        self.assertNotEqual(before, fingerprint_questions(refreshed))

    def test_start_creates_and_later_resumes_same_active_attempt(self):
        attempt, created = start_or_resume(self.user, self.content)
        resumed, resumed_created = start_or_resume(self.user, self.content)
        self.assertTrue(created)
        self.assertFalse(resumed_created)
        self.assertEqual(resumed.pk, attempt.pk)
        self.assertEqual(attempt.question_count, 2)
        self.assertEqual(attempt.question_ids, [self.q1[0].id, self.q2[0].id])
        self.assertEqual(len(attempt.content_fingerprint), 64)

    def test_start_accepts_lazy_request_user(self):
        lazy_user = SimpleLazyObject(lambda: self.user)
        attempt, created = start_or_resume(lazy_user, self.content)
        self.assertTrue(created)
        self.assertEqual(attempt.user_id, self.user.pk)

    def test_start_abandons_stale_fingerprint_and_creates_fresh_attempt(self):
        old, _ = start_or_resume(self.user, self.content)
        self.q1[0].prompt = 'Content changed after start'
        self.q1[0].save(update_fields=['prompt'])
        fresh, created = start_or_resume(self.user, self.content)
        old.refresh_from_db()
        self.assertTrue(created)
        self.assertNotEqual(old.pk, fresh.pk)
        self.assertEqual(old.status, 'abandoned')

    def test_start_abandons_invalid_snapshot_ids_or_count(self):
        attempt, _ = start_or_resume(self.user, self.content)
        attempt.question_count = 99
        attempt.save(update_fields=['question_count'])
        fresh, created = start_or_resume(self.user, self.content)
        attempt.refresh_from_db()
        self.assertTrue(created)
        self.assertEqual(attempt.status, 'abandoned')
        self.assertEqual(fresh.question_count, 2)

    def test_start_abandons_legacy_active_attempt_with_blank_fingerprint(self):
        attempt = PracticeAttempt.objects.create(
            user=self.user,
            content=self.content,
            status='in_progress',
            question_count=2,
            question_ids=[self.q1[0].pk, self.q2[0].pk],
            content_fingerprint='',
        )
        fresh, created = start_or_resume(self.user, self.content)
        attempt.refresh_from_db()
        self.assertTrue(created)
        self.assertNotEqual(fresh.pk, attempt.pk)
        self.assertEqual(attempt.status, 'abandoned')

    def test_unpublished_content_abandons_active_attempt_and_fails(self):
        attempt, _ = start_or_resume(self.user, self.content)
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        with self.assertRaises(PracticeUnavailableError):
            start_or_resume(self.user, self.content)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'abandoned')

    def test_save_draft_replaces_rows_without_grading(self):
        attempt, _ = start_or_resume(self.user, self.content)
        first = save_draft(self.user, attempt.pk, {self.q1[0].pk: self.q1[1].pk})
        self.assertEqual(first['saved_count'], 1)
        self.assertIsNotNone(first['last_saved_at'])
        self.assertEqual(AttemptDraftAnswer.objects.filter(attempt=attempt).count(), 1)
        self.assertEqual(attempt.answers.count(), 0)
        attempt.refresh_from_db()
        self.assertEqual(attempt.correct_count, 0)
        self.assertIsNotNone(attempt.last_saved_at)

        second = save_draft(self.user, attempt.pk, {self.q2[0].pk: self.q2[2].pk}, draft_revision=first['draft_revision'])
        self.assertEqual(second['saved_count'], 1)
        self.assertEqual(list(AttemptDraftAnswer.objects.filter(attempt=attempt).values_list('question_id', 'selected_option_id')),
                         [(self.q2[0].pk, self.q2[2].pk)])

    def test_empty_draft_clears_saved_responses(self):
        attempt, _ = start_or_resume(self.user, self.content)
        save_draft(self.user, attempt.pk, {self.q1[0].pk: self.q1[1].pk})
        result = save_draft(self.user, attempt.pk, {}, draft_revision=1)
        self.assertEqual(result['saved_count'], 0)
        self.assertFalse(AttemptDraftAnswer.objects.filter(attempt=attempt).exists())

    def test_draft_is_private_to_attempt_owner(self):
        attempt, _ = start_or_resume(self.user, self.content)
        with self.assertRaises(Http404):
            save_draft(self.other_user, attempt.pk, {self.q1[0].pk: self.q1[1].pk})

    def test_draft_rejects_malformed_and_foreign_question_or_option(self):
        attempt, _ = start_or_resume(self.user, self.content)
        with self.assertRaises(DraftValidationError):
            save_draft(self.user, attempt.pk, {'not-an-id': self.q1[1].pk})
        with self.assertRaises(DraftValidationError):
            save_draft(self.user, attempt.pk, {self.q1[0].pk: self.q2[1].pk})
        outside_content = LearningContent.objects.create(
            title='Another published practice', exam_type='TOEIC', content_type='reading',
            skill='reading', is_published=True, review_status='teacher_approved',
        )
        outside = Question.objects.create(
            content=outside_content, order=1, prompt='Outside question?', explanation='No.',
        )
        outside_option = AnswerOption.objects.create(
            question=outside, label='A', text='Outside', is_correct=True,
        )
        with self.assertRaises(DraftValidationError):
            save_draft(self.user, attempt.pk, {outside.pk: outside_option.pk})
        self.assertFalse(AttemptDraftAnswer.objects.filter(attempt=attempt).exists())

    def test_changed_content_abandons_attempt_and_does_not_save_draft(self):
        attempt, _ = start_or_resume(self.user, self.content)
        save_draft(self.user, attempt.pk, {self.q1[0].pk: self.q1[1].pk})
        self.q1[0].prompt = 'Changed prompt'
        self.q1[0].save(update_fields=['prompt'])
        with self.assertRaises(PracticeUnavailableError):
            save_draft(self.user, attempt.pk, {self.q1[0].pk: self.q1[1].pk})
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'abandoned')
        self.assertFalse(AttemptDraftAnswer.objects.filter(attempt=attempt).exists())

    def test_draft_payload_is_capped_at_500(self):
        attempt, _ = start_or_resume(self.user, self.content)
        oversized = {str(index + 1): str(index + 1) for index in range(501)}
        with self.assertRaises(DraftValidationError):
            save_draft(self.user, attempt.pk, oversized)

    def test_draft_rejects_ids_over_signed_64_bit_without_writing(self):
        attempt, _ = start_or_resume(self.user, self.content)
        huge_id = '9' * 100
        for answers in (
            {huge_id: self.q1[1].pk},
            {self.q1[0].pk: huge_id},
        ):
            with self.subTest(answers=answers):
                with self.assertRaises(DraftValidationError):
                    save_draft(self.user, attempt.pk, answers)
        self.assertFalse(AttemptDraftAnswer.objects.filter(attempt=attempt).exists())
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'in_progress')
