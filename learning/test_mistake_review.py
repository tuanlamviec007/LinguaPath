from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.http import Http404
from django.test import TestCase
from django.utils import timezone

from .models import (
    AnswerOption,
    AttemptAnswer,
    ErrorNotebookEntry,
    LearningContent,
    MistakeReviewAnswer,
    MistakeReviewItem,
    MistakeReviewSession,
    PracticeAttempt,
    Question,
)
from .mistake_review import (
    MistakeReviewInputError,
    MistakeReviewUnavailable,
    NoMistakesAvailable,
    abandon_mistake_review,
    count_eligible_mistakes,
    get_mistake_review_questions,
    get_mistake_review_result,
    start_or_resume_mistake_review,
    submit_mistake_review,
)


class MistakeReviewServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='mistake-user', password='secret12345')
        self.other = get_user_model().objects.create_user(username='other-mistake-user', password='secret12345')
        self.content = self.make_content('Reading set')
        self.q1, self.q1_correct, self.q1_wrong = self.make_question(self.content, 1)
        self.q2, self.q2_correct, self.q2_wrong = self.make_question(self.content, 2)
        self.entry1 = self.make_mistake(self.user, self.q1, self.q1_wrong)
        self.entry2 = self.make_mistake(self.user, self.q2, self.q2_wrong)

    def make_content(self, title, *, kind='reading', exam='TOEIC', published=True, review='teacher_approved'):
        return LearningContent.objects.create(
            title=title, exam_type=exam, content_type=kind, skill=kind,
            is_published=published, review_status=review,
        )

    def make_question(self, content, order, *, audio_url='', transcript='Secret transcript'):
        question = Question.objects.create(
            content=content, order=order, prompt=f'Question {order}?', passage='A short passage.',
            audio_url=audio_url, audio_script='Never expose this script before submit.',
            transcript=transcript, explanation='Answer explanation.',
            explanation_vi='Giải thích đáp án.',
        )
        correct = AnswerOption.objects.create(
            question=question, label='A', text='Correct choice', is_correct=True,
            explanation_vi='Phương án đúng.',
        )
        wrong = AnswerOption.objects.create(
            question=question, label='B', text='Wrong choice', is_correct=False,
            explanation_vi='Phương án sai.',
        )
        return question, correct, wrong

    def make_mistake(self, user, question, selected_option, *, category='other', content=None):
        attempt = PracticeAttempt.objects.create(
            user=user, content=content or question.content, status='submitted',
            question_count=1, correct_count=0, question_ids=[question.pk],
            submitted_at=timezone.now(),
        )
        answer = AttemptAnswer.objects.create(
            attempt=attempt, question=question, selected_option=selected_option,
            is_correct=False,
        )
        return ErrorNotebookEntry.objects.create(answer=answer, category=category)

    def test_count_and_start_deduplicate_retries_using_latest_source_entry(self):
        earlier = self.entry1
        later = self.make_mistake(self.user, self.q1, self.q1_wrong, category='detail')

        self.assertEqual(count_eligible_mistakes(self.user, 'TOEIC'), 2)
        session, created = start_or_resume_mistake_review(self.user, 'TOEIC')
        self.assertTrue(created)
        items = list(session.items.order_by('position'))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].question_id, self.q1.pk)
        self.assertEqual(items[0].source_entry_id, later.pk)
        self.assertNotEqual(items[0].source_entry_id, earlier.pk)

    def test_category_filter_and_no_eligible_errors(self):
        detail_entry = self.make_mistake(self.user, self.q1, self.q1_wrong, category='detail')
        self.assertEqual(count_eligible_mistakes(self.user, 'TOEIC', 'detail'), 1)
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC', category='detail')
        self.assertEqual(session.question_count, 1)
        self.assertEqual(session.items.get().source_entry_id, detail_entry.pk)
        with self.assertRaises(NoMistakesAvailable):
            start_or_resume_mistake_review(self.other, 'TOEIC')

    def test_invalid_category_is_rejected(self):
        with self.assertRaises(MistakeReviewInputError):
            start_or_resume_mistake_review(self.user, 'TOEIC', category='not-a-category')

    def test_start_resumes_single_active_session_per_user_and_exam(self):
        first, created = start_or_resume_mistake_review(self.user, 'TOEIC')
        resumed, resumed_created = start_or_resume_mistake_review(self.user, 'TOEIC', category='grammar')
        self.assertTrue(created)
        self.assertFalse(resumed_created)
        self.assertEqual(first.pk, resumed.pk)
        self.assertEqual(MistakeReviewSession.objects.filter(user=self.user, status='in_progress').count(), 1)

    def test_session_cap_is_ten_distinct_questions(self):
        for order in range(3, 13):
            question, _, wrong = self.make_question(self.content, order)
            self.make_mistake(self.user, question, wrong)
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        self.assertEqual(session.question_count, 10)
        self.assertEqual(session.items.count(), 10)

    def test_get_payload_does_not_leak_answers_explanations_or_transcripts(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        questions = get_mistake_review_questions(self.user, session.pk)
        question = questions[0]
        self.assertEqual(question['content_title'], 'Reading set')
        self.assertEqual(set(question['options'][0]), {'id', 'label', 'text'})
        for forbidden in ('transcript', 'audio_script', 'explanation', 'explanation_vi', 'is_correct', 'correct_option_id'):
            self.assertNotIn(forbidden, question)
        for option in question['options']:
            self.assertNotIn('is_correct', option)

    def test_submit_correct_answers_reviews_only_source_errors_existing_at_start(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        original_attempt_count = PracticeAttempt.objects.count()
        original_answer_count = AttemptAnswer.objects.count()
        late_entry = self.make_mistake(self.user, self.q1, self.q1_wrong)
        result = submit_mistake_review(self.user, session.pk, {
            str(self.q1.pk): str(self.q1_correct.pk),
            str(self.q2.pk): str(self.q2_correct.pk),
        })
        self.entry1.refresh_from_db()
        self.entry2.refresh_from_db()
        late_entry.refresh_from_db()
        self.assertEqual(result['correct_count'], 2)
        self.assertEqual(result['wrong_count'], 0)
        self.assertEqual(result['blank_count'], 0)
        self.assertIsNotNone(self.entry1.reviewed_at)
        self.assertIsNotNone(self.entry2.reviewed_at)
        self.assertIsNone(late_entry.reviewed_at)
        self.assertEqual(PracticeAttempt.objects.count(), original_attempt_count + 1)
        self.assertEqual(AttemptAnswer.objects.count(), original_answer_count + 1)
        self.assertEqual(MistakeReviewAnswer.objects.filter(item__session=session).count(), 2)

    def test_wrong_and_blank_answers_remain_pending(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        result = submit_mistake_review(self.user, session.pk, {str(self.q1.pk): str(self.q1_wrong.pk)})
        self.entry1.refresh_from_db()
        self.entry2.refresh_from_db()
        self.assertEqual(result['correct_count'], 0)
        self.assertEqual(result['wrong_count'], 1)
        self.assertEqual(result['blank_count'], 1)
        self.assertIsNone(self.entry1.reviewed_at)
        self.assertIsNone(self.entry2.reviewed_at)

    def test_submit_is_idempotent_and_result_is_owner_scoped(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        answers = {str(self.q1.pk): str(self.q1_correct.pk)}
        first = submit_mistake_review(self.user, session.pk, answers)
        second = submit_mistake_review(self.user, session.pk, answers)
        self.assertEqual(first, second)
        self.assertEqual(MistakeReviewAnswer.objects.filter(item__session=session).count(), 2)
        self.assertEqual(get_mistake_review_result(self.user, session.pk), first)
        with self.assertRaises(Http404):
            get_mistake_review_result(self.other, session.pk)

    def test_invalid_answer_map_is_rejected_before_writing(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        outside_content = self.make_content('Outside')
        outside_question, _, outside_option = self.make_question(outside_content, 1)
        for answers in (
            {'999999': str(self.q1_correct.pk)},
            {str(self.q1.pk): str(outside_option.pk)},
            {str(self.q1.pk): 'not-an-id'},
            {str(self.q1.pk): str(2**100)},
        ):
            with self.subTest(answers=answers):
                with self.assertRaises(MistakeReviewInputError):
                    submit_mistake_review(self.user, session.pk, answers)
        self.assertFalse(MistakeReviewAnswer.objects.filter(item__session=session).exists())
        session.refresh_from_db()
        self.assertEqual(session.status, 'in_progress')

    def test_changed_question_invalidates_session_without_partial_grade(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        self.q1.prompt = 'Changed after retry started'
        self.q1.save(update_fields=['prompt'])
        with self.assertRaises(MistakeReviewUnavailable):
            submit_mistake_review(self.user, session.pk, {str(self.q1.pk): str(self.q1_correct.pk)})
        session.refresh_from_db()
        self.assertEqual(session.status, 'abandoned')
        self.assertFalse(MistakeReviewAnswer.objects.filter(item__session=session).exists())

    def test_unpublished_or_reviewed_source_invalidates_session(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        with self.assertRaises(MistakeReviewUnavailable):
            get_mistake_review_questions(self.user, session.pk)
        session.refresh_from_db()
        self.assertEqual(session.status, 'abandoned')

        self.content.is_published = True
        self.content.save(update_fields=['is_published'])
        session2, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        self.entry1.reviewed_at = timezone.now()
        self.entry1.save(update_fields=['reviewed_at'])
        with self.assertRaises(MistakeReviewUnavailable):
            get_mistake_review_questions(self.user, session2.pk)

    def test_stale_active_session_is_committed_abandoned_when_no_new_errors_remain(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        ErrorNotebookEntry.objects.filter(answer__attempt__user=self.user).update(reviewed_at=timezone.now())
        with self.assertRaises(NoMistakesAvailable):
            start_or_resume_mistake_review(self.user, 'TOEIC')
        session.refresh_from_db()
        self.assertEqual(session.status, 'abandoned')

    def test_submitted_result_is_immutable_after_source_deletion_and_content_edit(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        result = submit_mistake_review(self.user, session.pk, {str(self.q1.pk): str(self.q1_correct.pk)})
        self.q1.prompt = 'Changed after result'
        self.q1.save(update_fields=['prompt'])
        # Removing the original practice attempt cascades its notebook entry;
        # SET_NULL on the historical session item must allow this cleanup.
        self.entry1.answer.attempt.delete()
        self.assertEqual(get_mistake_review_result(self.user, session.pk), result)
        q1_result = next(row for row in result['answers'] if row['question_id'] == self.q1.pk)
        self.assertEqual(q1_result['prompt'], 'Question 1?')

    def test_missing_submitted_snapshot_does_not_fall_back_to_live_content(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        submit_mistake_review(self.user, session.pk, {})
        MistakeReviewSession.objects.filter(pk=session.pk).update(result_snapshot={})
        self.q1.prompt = 'Mutable content should not be exposed as a result'
        self.q1.save(update_fields=['prompt'])
        with self.assertRaises(MistakeReviewUnavailable):
            get_mistake_review_result(self.user, session.pk)

    def test_deleted_source_entry_invalidates_active_session(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        self.entry1.answer.attempt.delete()
        with self.assertRaises(MistakeReviewUnavailable):
            get_mistake_review_questions(self.user, session.pk)
        session.refresh_from_db()
        self.assertEqual(session.status, 'abandoned')

    def test_audio_script_only_listening_and_malformed_source_are_not_eligible(self):
        listening = self.make_content('Script-only listening', kind='listening')
        listen_question, _, listen_wrong = self.make_question(listening, 1)
        self.make_mistake(self.user, listen_question, listen_wrong)
        mismatch = self.make_mistake(self.user, self.q1, self.q1_wrong, content=self.make_content('Wrong source'))
        self.assertEqual(count_eligible_mistakes(self.user, 'TOEIC'), 2)
        self.assertNotIn(mismatch.pk, list(
            start_or_resume_mistake_review(self.user, 'TOEIC')[0].items.values_list('source_entry_id', flat=True)
        ))

    def test_script_only_notebook_explains_retry_limit_and_links_to_original_practice(self):
        from django.urls import reverse
        from planner.models import LearnerProfile
        LearnerProfile.objects.create(user=self.user, exam_goal='TOEIC', onboarding_complete=True)
        listening = self.make_content('Script-only listening', kind='listening')
        question, _, wrong = self.make_question(listening, 1)
        self.make_mistake(self.user, question, wrong)
        self.client.force_login(self.user)
        response = self.client.get(reverse('learning:mistake_notebook'))
        self.assertContains(response, 'Câu nghe này chưa có tệp âm thanh')
        self.assertContains(response, 'tính năng đọc lời thoại của trình duyệt')
        self.assertContains(response, reverse('learning:practice', args=[listening.pk]))
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('learning:mistake_notebook')), 'Mở bài nghe gốc')

    def test_explicit_abandon_is_idempotent_and_does_not_touch_sources(self):
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        self.assertTrue(abandon_mistake_review(self.user, session.pk))
        self.assertFalse(abandon_mistake_review(self.user, session.pk))
        self.entry1.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(session.status, 'abandoned')
        self.assertIsNone(self.entry1.reviewed_at)

    def test_one_active_session_per_exam_constraint(self):
        first, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        with self.assertRaises(IntegrityError), transaction.atomic():
            MistakeReviewSession.objects.create(
                user=self.user, exam_type='TOEIC', status='in_progress',
                fingerprint='0' * 64, question_count=0,
            )
        self.assertEqual(MistakeReviewSession.objects.filter(user=self.user, exam_type='TOEIC', status='in_progress').count(), 1)
        self.assertEqual(first.status, 'in_progress')
