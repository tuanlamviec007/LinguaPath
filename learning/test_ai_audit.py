from django.contrib.auth import get_user_model
from django.test import TestCase

from .ai import answer_tutor_question, retrieve_learning_context
from .models import AnswerOption, AttemptAnswer, LearningContent, PracticeAttempt, Question


class TutorAnswerDisclosureTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user_a = User.objects.create_user(username='tutor-a', password='test-password-123')
        self.user_b = User.objects.create_user(username='tutor-b', password='test-password-123')
        self.content = LearningContent.objects.create(
            title='Meeting notice',
            exam_type='TOEIC',
            content_type='reading',
            skill='reading',
            review_status='language_checked',
            is_published=True,
        )
        self.question = Question.objects.create(
            content=self.content,
            prompt='When does the meeting begin?',
            passage='The meeting begins at 10 a.m.',
            explanation='The notice states the meeting time.',
            explanation_vi='Thông báo cho biết thời gian bắt đầu cuộc họp.',
        )
        self.correct = AnswerOption.objects.create(
            question=self.question, label='A', text='At 10 a.m.', is_correct=True,
        )
        self.wrong = AnswerOption.objects.create(
            question=self.question, label='B', text='At 11 a.m.', is_correct=False,
        )
        self.attempt_a = PracticeAttempt.objects.create(
            user=self.user_a, content=self.content, question_count=1,
            question_ids=[self.question.id], status='in_progress',
        )

    def _answer(self, user, question_id=None):
        return answer_tutor_question(
            'Please explain the meeting question.',
            exam='TOEIC', question_id=question_id, user=user,
        )

    def test_exact_question_is_not_retrieved_before_user_submits(self):
        AttemptAnswer.objects.create(
            attempt=self.attempt_a, question=self.question,
            selected_option=self.wrong, is_correct=False,
        )

        result = self._answer(self.user_a, self.question.id)

        self.assertEqual(result['mode'], 'no_match')
        self.assertEqual(result['sources'], [])
        self.assertNotIn('At 10 a.m.', result['answer'])
        self.assertNotIn('Thông báo cho biết', result['answer'])

    def test_submitted_question_is_available_only_to_the_learner_who_submitted_it(self):
        AttemptAnswer.objects.create(
            attempt=self.attempt_a, question=self.question,
            selected_option=self.wrong, is_correct=False,
        )
        self.attempt_a.status = 'submitted'
        self.attempt_a.save(update_fields=['status'])

        owner_result = self._answer(self.user_a, self.question.id)
        other_result = self._answer(self.user_b, self.question.id)
        anonymous_result = self._answer(None, self.question.id)

        self.assertIn('At 10 a.m. (đúng)', owner_result['answer'])
        self.assertEqual(owner_result['sources'], ['Meeting notice'])
        for result in (other_result, anonymous_result):
            self.assertEqual(result['mode'], 'no_match')
            self.assertEqual(result['sources'], [])
            self.assertNotIn('At 10 a.m.', result['answer'])
            self.assertNotIn('Thông báo cho biết', result['answer'])

    def test_direct_question_denial_does_not_fall_back_to_generic_question_search(self):
        AttemptAnswer.objects.create(
            attempt=self.attempt_a, question=self.question,
            selected_option=self.correct, is_correct=True,
        )

        evidence = retrieve_learning_context(
            'When does the meeting begin?',
            exam='TOEIC', question_id=self.question.id, user=self.user_a,
        )

        self.assertEqual(evidence, [])

    def test_generic_question_search_is_limited_to_this_users_submitted_questions(self):
        AttemptAnswer.objects.create(
            attempt=self.attempt_a, question=self.question,
            selected_option=self.correct, is_correct=True,
        )
        self.attempt_a.status = 'submitted'
        self.attempt_a.save(update_fields=['status'])

        owner_evidence = retrieve_learning_context(
            'When does the meeting begin?', exam='TOEIC', user=self.user_a,
        )
        other_evidence = retrieve_learning_context(
            'When does the meeting begin?', exam='TOEIC', user=self.user_b,
        )
        anonymous_evidence = retrieve_learning_context(
            'When does the meeting begin?', exam='TOEIC', user=None,
        )

        self.assertTrue(any('At 10 a.m. (đúng)' in item['text'] for item in owner_evidence))
        self.assertFalse(any('At 10 a.m.' in item['text'] for item in other_evidence))
        self.assertFalse(any('At 10 a.m.' in item['text'] for item in anonymous_evidence))

    def test_draft_review_content_is_not_used_as_tutor_evidence(self):
        AttemptAnswer.objects.create(
            attempt=self.attempt_a, question=self.question,
            selected_option=self.correct, is_correct=True,
        )
        self.attempt_a.status = 'submitted'
        self.attempt_a.save(update_fields=['status'])
        self.content.review_status = 'draft'
        self.content.save(update_fields=['review_status'])

        result = self._answer(self.user_a, self.question.id)

        self.assertEqual(result['mode'], 'no_match')
        self.assertEqual(result['sources'], [])
        self.assertNotIn('At 10 a.m.', result['answer'])
