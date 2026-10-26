from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from learning.models import AnswerOption, AttemptAnswer, Flashcard, LearningContent, PracticeAttempt, Question, UserFlashcardState
from planner.models import LearnerProfile
from planner.services import generate_daily_plan


class WorkflowAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='audit-learner')
        cls.profile = LearnerProfile.objects.create(user=cls.user, daily_minutes=10, onboarding_complete=True)
        cls.content = LearningContent.objects.create(
            title='Audit reading', content_type='reading', skill='reading',
            estimated_minutes=10, is_published=True, review_status='language_checked',
        )
        cls.question = Question.objects.create(content=cls.content, prompt='When does the class begin?', explanation='At nine.')
        cls.option = AnswerOption.objects.create(question=cls.question, label='A', text='Nine', is_correct=True)
        AnswerOption.objects.create(question=cls.question, label='B', text='Ten')

    def setUp(self):
        self.client.force_login(self.user)

    def test_plan_stays_within_budget_and_does_not_refill_after_completion(self):
        other = LearningContent.objects.create(
            title='Another reading', content_type='reading', skill='reading',
            estimated_minutes=10, is_published=True, review_status='language_checked',
        )
        Question.objects.create(content=other, prompt='Where?', explanation='Here.')
        self.profile.daily_minutes = 5
        self.assertFalse(generate_daily_plan(self.user, self.profile).exists())
        self.profile.daily_minutes = 10
        tasks = generate_daily_plan(self.user, self.profile)
        self.assertEqual(tasks.count(), 1)
        tasks.update(status='done', completed_at=timezone.now())
        again = generate_daily_plan(self.user, self.profile)
        self.assertEqual(again.count(), 1)
        self.assertEqual(sum(task.estimated_minutes for task in again), 10)
        self.assertEqual(again.get().status, 'done')

    def test_cefr_task_filter_keeps_only_due_cards_unless_library_is_explicit(self):
        content = LearningContent.objects.create(title='Audit vocabulary', content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
        known = Flashcard.objects.create(content=content, term='remembered', meaning_vi='đã nhớ', cefr_level='A1')
        due = Flashcard.objects.create(content=content, term='review', meaning_vi='ôn lại', cefr_level='A1')
        UserFlashcardState.objects.create(user=self.user, flashcard=known, last_rating='known', reviewed_at=timezone.now(), due_at=timezone.now() + timedelta(days=3))
        url = reverse('learning:flashcards_content', args=[content.id])
        page = self.client.get(url, {'level': 'A1'})
        self.assertEqual([card.id for card in page.context['cards']], [due.id])
        library = self.client.get(url, {'level': 'A1', 'all': '1'})
        self.assertEqual({card.id for card in library.context['cards']}, {known.id, due.id})
        empty = self.client.get(url, {'q': 'nonexistent-term'})
        self.assertContains(empty, 'Không tìm thấy thẻ phù hợp')
        self.assertNotContains(empty, 'Bạn đã ôn xong lượt hôm nay')

    def test_draft_published_flag_cannot_bypass_learner_visibility(self):
        self.content.review_status = 'draft'
        self.content.save(update_fields=['review_status'])
        self.assertNotContains(self.client.get(reverse('learning:practice_list')), self.content.title)
        self.assertEqual(self.client.get(reverse('learning:practice', args=[self.content.id])).status_code, 404)
        self.assertFalse(generate_daily_plan(self.user, self.profile).exists())

    def test_malformed_option_ids_do_not_crash_or_write_partial_answers(self):
        attempt = PracticeAttempt.objects.create(user=self.user, content=self.content, question_count=1, question_ids=[self.question.id])
        for value in ['not-an-id', '9' * 100, '１２', '-1']:
            with self.subTest(value=value):
                response = self.client.post(reverse('learning:submit_attempt', args=[attempt.id]), {f'question_{self.question.id}': value})
                self.assertEqual(response.status_code, 400)
                self.assertFalse(attempt.answers.exists())
                attempt.refresh_from_db()
                self.assertEqual(attempt.status, 'in_progress')

    def test_deleted_question_abandons_attempt_instead_of_grading_wrong_denominator(self):
        attempt = PracticeAttempt.objects.create(user=self.user, content=self.content, question_count=1, question_ids=[self.question.id])
        self.question.delete()
        response = self.client.post(reverse('learning:submit_attempt', args=[attempt.id]))
        self.assertRedirects(response, reverse('learning:practice_list'))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'abandoned')
        self.assertFalse(attempt.answers.exists())

    def test_tutor_endpoint_does_not_expose_key_until_own_attempt_is_submitted(self):
        data = {'question': 'Explain this answer', 'question_id': self.question.id}
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            before = self.client.post(reverse('tutor'), data, follow=True)
            self.assertEqual(before.context['mode'], 'no_match')
            attempt = PracticeAttempt.objects.create(user=self.user, content=self.content, status='submitted', question_count=1, submitted_at=timezone.now())
            AttemptAnswer.objects.create(attempt=attempt, question=self.question)
            after = self.client.post(reverse('tutor'), data, follow=True)
            self.assertEqual(after.context['mode'], 'retrieval_only')
            self.assertIn('Nine', after.context['answer'])
