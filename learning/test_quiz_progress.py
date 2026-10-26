from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .models import Flashcard, LearningContent, VocabularyQuizSession
from .quiz_progress import quiz_progress_summary


class QuizProgressTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='quiz-progress')
        self.other = get_user_model().objects.create_user(username='quiz-progress-other')
        LearnerProfile.objects.create(user=self.user, onboarding_complete=True, exam_goal='TOEIC')

    def completed(self, **kwargs):
        return VocabularyQuizSession.objects.create(**{
            'user': self.user, 'exam_type': 'TOEIC', 'status': 'submitted',
            'submitted_at': timezone.now() - timedelta(minutes=1),
            'question_count': 5, 'correct_count': 3, **kwargs,
        })

    def test_progress_excludes_retry_scores_other_users_exams_and_dates(self):
        parent = self.completed()
        self.completed(parent_quiz=parent, is_retry=True, question_count=2, correct_count=2)
        self.completed(user=self.other, correct_count=5)
        self.completed(exam_type='IELTS', correct_count=5)
        self.completed(submitted_at=timezone.now() - timedelta(days=31), correct_count=5)
        self.completed(submitted_at=timezone.now() + timedelta(minutes=5), correct_count=5)
        self.completed(status='in_progress', submitted_at=None)
        result = quiz_progress_summary(self.user, 'TOEIC')
        self.assertEqual((result['completed'], result['questions'], result['correct'], result['accuracy']), (1, 5, 3, 60))
        self.assertEqual(result['retry_count'], 1)
        self.assertEqual(len(result['recent']), 2)
        self.client.force_login(self.user)
        page = self.client.get(reverse('progress'))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['quiz_progress']['accuracy'], 60)

    def test_retry_stays_separate_if_its_parent_was_removed(self):
        parent = self.completed()
        retry = self.completed(parent_quiz=parent, is_retry=True, question_count=2, correct_count=2)
        parent.delete()
        retry.refresh_from_db()
        self.assertIsNone(retry.parent_quiz_id)
        result = quiz_progress_summary(self.user, 'TOEIC')
        self.assertEqual((result['completed'], result['retry_count'], result['accuracy']), (0, 1, None))

    def test_dashboard_resumes_only_own_available_quiz_and_saved_count(self):
        content = LearningContent.objects.create(title='Resume quiz source', content_type='vocabulary', skill='vocabulary', exam_type='TOEIC', review_status='language_checked', is_published=True)
        card = Flashcard.objects.create(content=content, term='agenda', meaning_vi='chương trình họp')
        quiz = VocabularyQuizSession.objects.create(user=self.user, question_count=1, snapshot=[{'card_id': card.pk, 'number': 1, 'options': [{'key': 'A', 'text': 'chương trình họp'}]}], draft_answers={'1': 'A'}, draft_revision=1, last_saved_at=timezone.now())
        self.client.force_login(self.user)
        page = self.client.get(reverse('dashboard'))
        self.assertEqual(page.context['active_quiz'].pk, quiz.pk)
        self.assertContains(page, '1 / 1 câu đã lưu')
        self.client.force_login(self.other)
        LearnerProfile.objects.create(user=self.other, onboarding_complete=True)
        page = self.client.get(reverse('dashboard'))
        self.assertIsNone(page.context['active_quiz'])
        self.client.force_login(self.user)
        content.is_published = False
        content.save(update_fields=['is_published'])
        self.assertIsNone(self.client.get(reverse('dashboard')).context['active_quiz'])
