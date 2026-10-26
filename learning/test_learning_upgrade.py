from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from planner.services import generate_daily_plan
from .ai import answer_tutor_question
from .models import Flashcard, LearningContent, PracticeAttempt, Question, TutorUsageBudget, UserFlashcardState


class AdaptiveReviewFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='adaptive-learner')
        LearnerProfile.objects.create(user=self.user, onboarding_complete=True)
        content = LearningContent.objects.create(title='Adaptive words', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        self.card = Flashcard.objects.create(content=content, term='reliable', meaning_vi='đáng tin cậy')
        self.client.force_login(self.user)

    def test_review_intervals_grow_only_after_due_recall_and_reset_on_lapse(self):
        url = reverse('learning:review_flashcard', args=[self.card.id])
        now = timezone.now()
        for expected_days in [1, 3, 7]:
            with patch('learning.views.timezone.now', return_value=now):
                self.client.post(url, {'rating': 'known'})
            state = UserFlashcardState.objects.get(user=self.user, flashcard=self.card)
            self.assertEqual(state.interval_days, expected_days)
            self.assertEqual(state.due_at, now + timedelta(days=expected_days))
            # A duplicate click before the due time must not extend the interval.
            with patch('learning.views.timezone.now', return_value=now + timedelta(seconds=1)):
                self.client.post(url, {'rating': 'known'})
            state.refresh_from_db()
            self.assertEqual(state.interval_days, expected_days)
            now = state.due_at + timedelta(seconds=1)
        self.assertEqual(state.review_count, 3)
        with patch('learning.views.timezone.now', return_value=now):
            self.client.post(url, {'rating': 'again'})
        state.refresh_from_db()
        self.assertEqual(state.successful_reviews, 0)
        self.assertEqual(state.lapse_count, 1)
        self.assertEqual(state.due_at, now + timedelta(minutes=10))

    def test_progress_calendar_is_private_and_includes_overdue_cards_today(self):
        other = get_user_model().objects.create_user(username='other-reviewer')
        now = timezone.now()
        for user, due in [(self.user, now - timedelta(days=2)), (other, now + timedelta(days=1))]:
            UserFlashcardState.objects.create(user=user, flashcard=self.card, last_rating='hard', reviewed_at=now, due_at=due)
        page = self.client.get(reverse('progress'))
        self.assertEqual(page.context['reviewed_card_count'], 1)
        self.assertEqual(page.context['upcoming_reviews'][0]['count'], 1)
        self.assertEqual(sum(day['count'] for day in page.context['upcoming_reviews']), 1)


class AdvancedPracticeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_advanced_content', verbosity=0)
        cls.user = get_user_model().objects.create_user(username='advanced-learner')
        cls.profile = LearnerProfile.objects.create(user=cls.user, current_cefr='B1', target_cefr='B2', daily_minutes=12, onboarding_complete=True)

    def setUp(self):
        self.client.force_login(self.user)

    def test_seed_can_be_repeated_and_every_item_passes_publication_gate(self):
        ids = list(LearningContent.objects.order_by('id').values_list('id', flat=True))
        call_command('seed_advanced_content', verbosity=0)
        self.assertEqual(list(LearningContent.objects.order_by('id').values_list('id', flat=True)), ids)
        self.assertEqual(Question.objects.count(), 32)
        for content in LearningContent.objects.all():
            self.assertEqual(content.publication_issues(), [])
            self.assertEqual(content.review_status, 'language_checked')

    def test_library_filters_level_skill_and_search_without_losing_counts(self):
        page = self.client.get(reverse('learning:practice_list'), {'skill': 'reading', 'level': 'B2'})
        self.assertEqual(page.context['total_content'], 8)
        self.assertEqual(page.context['total_questions'], 32)
        self.assertEqual(page.context['filtered_count'], 2)
        self.assertTrue(all(c.skill == 'reading' and c.cefr_level == 'B2' for c in page.context['content_list']))
        empty = self.client.get(reverse('learning:practice_list'), {'q': 'no-such-lesson'})
        self.assertContains(empty, 'Chưa tìm thấy bài phù hợp')

    def test_listening_uses_one_shared_audio_for_four_questions(self):
        content = LearningContent.objects.filter(content_type='listening').first()
        self.client.post(reverse('learning:practice', args=[content.id]))
        attempt = PracticeAttempt.objects.get(user=self.user, content=content)
        page = self.client.get(reverse('learning:take_attempt', args=[attempt.id]))
        self.assertContains(page, '<audio ', count=1)
        self.assertEqual(len(page.context['questions']), 4)
        answers = {f'question_{q.id}': q.options.get(is_correct=True).id for q in content.questions.all()}
        self.client.post(reverse('learning:submit_attempt', args=[attempt.id]), answers)
        attempt.refresh_from_db()
        self.assertEqual(attempt.correct_count, 4)

    def test_planner_does_not_assign_advanced_lessons_to_a1_and_prefers_current_band(self):
        newcomer = get_user_model().objects.create_user(username='newcomer')
        profile = LearnerProfile.objects.create(user=newcomer, current_cefr='A1', daily_minutes=12)
        self.assertFalse(generate_daily_plan(newcomer, profile).exists())
        tasks = generate_daily_plan(self.user, self.profile)
        self.assertTrue(tasks.exists())
        self.assertTrue(all(t.content.cefr_level == 'B1' for t in tasks))


@override_settings(AI_TUTOR_ENABLED=True, AI_TUTOR_DAILY_LIMIT=1, AI_TUTOR_MINUTE_LIMIT=3)
class PaidTutorIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='limited-tutor')
        content = LearningContent.objects.create(title='Tutor terms', content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
        Flashcard.objects.create(content=content, term='deadline', meaning_vi='hạn chót', example_en='The deadline is Friday.')

    def test_limit_prevents_second_external_call_but_preserves_learning_context(self):
        client = Mock()
        client.responses.create.return_value.output_text = 'Deadline nghĩa là hạn chót.'
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('learning.ai.OpenAI', return_value=client) as factory:
            first = answer_tutor_question('deadline', user=self.user, use_ai=True)
            second = answer_tutor_question('deadline', user=self.user, use_ai=True)
        self.assertEqual(first['mode'], 'llm_rag')
        self.assertEqual(second['mode'], 'budget_limited')
        self.assertIn('hạn chót', second['answer'])
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(client.responses.create.call_count, 1)

    def test_retrieval_only_does_not_reserve_a_paid_call(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            result = answer_tutor_question('deadline', user=self.user, use_ai=True)
        self.assertEqual(result['mode'], 'retrieval_only')
        self.assertFalse(TutorUsageBudget.objects.exists())
