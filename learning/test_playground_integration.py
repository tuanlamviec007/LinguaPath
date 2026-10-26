"""Cross-feature checks for the workplace pack, quiz, and learner dashboard."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from planner.models import LearnerProfile

from .models import LearningContent, VocabularyQuizDailyReward, VocabularyQuizSession


class LearningPlaygroundIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_toeic_workplace', publish_provisional=True, stdout=StringIO())
        cls.user = get_user_model().objects.create_user(username='playground-learner')
        cls.other = get_user_model().objects.create_user(username='playground-other')
        LearnerProfile.objects.create(user=cls.user, exam_goal='TOEIC', onboarding_complete=True)
        LearnerProfile.objects.create(user=cls.other, exam_goal='TOEIC', onboarding_complete=True)

    def setUp(self):
        self.client.force_login(self.user)

    def test_workplace_exercises_are_discoverable_in_existing_meaning_and_cloze_filters(self):
        for mode in ('meaning', 'cloze'):
            with self.subTest(mode=mode):
                response = self.client.get(reverse('learning:practice_list'), {'mode': mode, 'q': 'Workplace'})
                self.assertEqual(response.status_code, 200)
                actual_ids = {item.pk for item in response.context['content_list']}
                expected_ids = set(LearningContent.objects.filter(
                    question_type__startswith='lp-workplace-v1-',
                    question_type__endswith=f'-{mode}',
                ).values_list('pk', flat=True))
                self.assertEqual(len(expected_ids), 4)
                self.assertEqual(actual_ids, expected_ids)

    def test_published_pack_quiz_connects_to_private_rewards_and_activity(self):
        hub = self.client.get(reverse('learning:quiz_hub'))
        self.assertEqual(hub.status_code, 200)
        self.assertEqual(hub.context['available_count'], 40)
        self.assertIn('Office collaboration', hub.context['topics'])

        started = self.client.post(reverse('learning:quiz_start'), {
            'topic': 'Office collaboration', 'level': '', 'count': '5',
        })
        quiz = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertRedirects(started, reverse('learning:quiz_take', args=[quiz.pk]))
        self.assertEqual(quiz.question_count, 5)
        self.assertEqual(quiz.topic, 'Office collaboration')

        submitted = self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), {
            f'answer_{question["number"]}': question['correct_key'] for question in quiz.snapshot
        })
        self.assertRedirects(submitted, reverse('learning:quiz_result', args=[quiz.pk]))
        quiz.refresh_from_db()
        self.assertEqual(quiz.correct_count, 5)
        self.assertEqual(quiz.xp_earned, 30)
        self.assertEqual(VocabularyQuizDailyReward.objects.filter(user=self.user).count(), 1)

        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context['rewards']['total_xp'], 30)
        self.assertEqual(dashboard.context['rewards']['quiz_count'], 1)
        self.assertEqual(dashboard.context['activity']['quiz_events'], 1)
        self.assertEqual(dashboard.context['activity']['streak_days'], 1)
        self.assertContains(dashboard, reverse('learning:quiz_hub'))

        self.client.force_login(self.other)
        other_dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(other_dashboard.context['rewards']['total_xp'], 0)
        self.assertEqual(other_dashboard.context['activity']['quiz_events'], 0)
        self.assertEqual(self.client.get(reverse('learning:quiz_result', args=[quiz.pk])).status_code, 404)
        other_hub = self.client.get(reverse('learning:quiz_hub'))
        self.assertFalse(other_hub.context['recent_quizzes'])
