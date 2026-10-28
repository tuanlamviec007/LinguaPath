from types import SimpleNamespace as Row
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from planner.models import LearnerProfile
from .daily_focus import daily_focus
from .models import Flashcard, LearningContent, VocabularyQuizSession


class DailyFocusTests(SimpleTestCase):
    def test_quiz_then_practice_then_plan_priority(self):
        quiz = Row(pk=12, saved_count=2, question_count=5)
        practice = Row(pk=22, saved_count=3, question_count=8, content=Row(title='A lesson'))
        task = Row(content=Row(content_type='vocabulary', title='Words'), content_id=32,
                   cefr_level='A2', estimated_minutes=10, reason='At your level', status='todo')
        self.assertEqual(daily_focus(quiz, [practice], task, [task])['href'], reverse('learning:quiz_take', args=[12]))
        self.assertEqual(daily_focus(None, [practice], task, [task])['href'], reverse('learning:take_attempt', args=[22]))
        self.assertEqual(daily_focus(None, [], task, [task])['href'], reverse('learning:flashcards_content', args=[32])+'?level=A2')

    def test_empty_plan_is_not_a_completed_plan(self):
        self.assertEqual(daily_focus(None, [], None, [])['kind'], 'explore')
        self.assertEqual(daily_focus(None, [], None, [Row(status='done')])['kind'], 'complete')


class DailyFocusDashboardTests(TestCase):
    def test_returning_learner_gets_safe_next_action_and_beginner_keeps_guide(self):
        user = get_user_model().objects.create_user(username='focus-learner', password='synthetic-test-password')
        LearnerProfile.objects.create(user=user, onboarding_complete=True)
        content = LearningContent.objects.create(title='<script>unsafe</script>', content_type='vocabulary',
                  skill='vocabulary', is_published=True, review_status='language_checked')
        card = Flashcard.objects.create(content=content, term='ready', meaning_vi='sẵn sàng', cefr_level='A1')
        self.client.force_login(user)
        beginner = self.client.get(reverse('dashboard'))
        self.assertContains(beginner, 'Một việc nên làm tiếp theo.')
        self.assertIsNone(beginner.context['daily_focus'])
        with patch('learning.getting_started.starter_progress', return_value={'complete':True}):
            page = self.client.get(reverse('dashboard'))
        self.assertEqual(page.context['daily_focus']['kind'], 'task')
        self.assertContains(page, 'id="daily-focus-title"')
        self.assertContains(page, '&lt;script&gt;unsafe&lt;/script&gt;')
        self.assertNotContains(page, '<script>unsafe</script>')
        self.assertContains(page, '?view=all#today-tasks-title')

        quiz = VocabularyQuizSession.objects.create(user=user, question_count=1,
               snapshot=[{'card_id':card.pk,'number':1,'options':[{'key':'A','text':'sẵn sàng'}]}])
        with patch('learning.getting_started.starter_progress', return_value={'complete':True}):
            page = self.client.get(reverse('dashboard'))
        self.assertEqual(page.context['daily_focus']['href'], reverse('learning:quiz_take',args=[quiz.pk]))
        self.assertNotContains(page, 'id="quiz-resume-title"')
