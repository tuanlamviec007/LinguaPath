from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .getting_started import starter_progress
from .models import Flashcard, FlashcardReview, LearningContent, VocabularyQuizSession


class GettingStartedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='beginner', password='test-pass')
        cls.other = get_user_model().objects.create_user(username='other', password='test-pass')
        cls.profile = LearnerProfile.objects.create(user=cls.user, onboarding_complete=True)
        content = LearningContent.objects.create(title='Words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary')
        cls.card = Flashcard.objects.create(content=content, term='ready', meaning_vi='sẵn sàng')

    def test_next_step_follows_owned_activity_and_ignores_empty_or_future_quizzes(self):
        now = timezone.now()
        VocabularyQuizSession.objects.create(user=self.other, exam_type='TOEIC', status='submitted', question_count=1, submitted_at=now)
        VocabularyQuizSession.objects.create(user=self.user, exam_type='IELTS', status='submitted', question_count=1, submitted_at=now)
        VocabularyQuizSession.objects.create(user=self.user, exam_type='TOEIC', status='submitted', question_count=0, submitted_at=now)
        future = VocabularyQuizSession.objects.create(user=self.user, exam_type='TOEIC', status='submitted', question_count=1, submitted_at=now + timedelta(days=1))
        self.assertEqual(starter_progress(self.user, self.profile)['completed'], 1)
        self.client.force_login(self.user)
        page = self.client.get(reverse('learning:getting_started'))
        self.assertContains(page, 'Học từ đầu tiên')
        FlashcardReview.objects.create(user=self.user, flashcard=self.card, rating='known', due_at=now)
        page = self.client.get(reverse('learning:getting_started'))
        self.assertContains(page, 'Thử quiz từ vựng')
        self.assertEqual(page.context['starter']['completed'], 2)
        future.submitted_at = now
        future.save(update_fields=['submitted_at'])
        page = self.client.get(reverse('learning:getting_started'))
        self.assertTrue(page.context['starter']['complete'])
        self.assertContains(page, 'Về trang học tập')

    def test_guest_can_try_demo_without_creating_activity(self):
        page = self.client.get(reverse('learning:getting_started'))
        self.assertContains(page, 'Thử học trước, đăng ký sau')
        self.assertContains(page, reverse('home') + '#quick-demo')
        self.assertEqual(FlashcardReview.objects.count(), 0)
        self.assertEqual(VocabularyQuizSession.objects.count(), 0)
