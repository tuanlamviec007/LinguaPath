from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from learning.models import Flashcard, LearningContent, PracticeAttempt, Question, UserFlashcardState
from planner.models import LearnerProfile
from planner.services import generate_daily_plan


class DailyPlanTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='planner-test', password='secure-test-password')
        self.profile = LearnerProfile.objects.create(user=self.user, exam_goal='TOEIC', daily_minutes=10)
        self.reading = LearningContent.objects.create(title='Reading review', exam_type='TOEIC', content_type='reading', skill='reading', estimated_minutes=10, review_status='language_checked', is_published=True)
        self.listening = LearningContent.objects.create(title='Listening review', exam_type='TOEIC', content_type='listening', skill='listening', estimated_minutes=10, review_status='language_checked', is_published=True)
        Question.objects.create(content=self.reading, prompt='Sample reading question?', explanation='Read the text.')
        Question.objects.create(content=self.listening, prompt='Sample listening question?', audio_url='https://example.test/clip.mp3', explanation='Listen to the clip.')

    def test_recent_weak_skill_is_ranked_ahead_of_strong_skill(self):
        PracticeAttempt.objects.create(user=self.user, content=self.reading, status='submitted', submitted_at=timezone.now(), correct_count=1, question_count=5)
        PracticeAttempt.objects.create(user=self.user, content=self.listening, status='submitted', submitted_at=timezone.now(), correct_count=5, question_count=5)
        tasks = generate_daily_plan(self.user, self.profile, date(2026, 10, 19))
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks.first().content, self.reading)
        self.assertIn('Reading', tasks.first().reason)
        self.assertEqual(tasks.first().recommendation_version, 'rule-v2-cefr')

    def test_only_published_content_for_profile_exam_is_selected(self):
        self.reading.is_published = False
        self.reading.save(update_fields=['is_published'])
        LearningContent.objects.create(title='IELTS reading', exam_type='IELTS', content_type='reading', skill='reading', review_status='language_checked', is_published=True)
        tasks = generate_daily_plan(self.user, self.profile, date(2026, 10, 19))
        self.assertEqual(list(tasks.values_list('content_id', flat=True)), [self.listening.id])

    def test_plan_includes_listening_with_original_script_and_browser_tts(self):
        self.profile.daily_minutes = 20
        self.profile.save(update_fields=['daily_minutes'])
        self.listening.questions.all().update(audio_url='')
        self.listening.questions.all().update(audio_script='A: The class begins at nine.')
        tasks = generate_daily_plan(self.user, self.profile, date(2026, 10, 19))
        self.assertIn(self.listening.id, set(tasks.values_list('content_id', flat=True)))

    def test_plan_prefers_distinct_skills_and_explains_high_accuracy_as_diversity(self):
        self.profile.daily_minutes = 20
        self.profile.save(update_fields=['daily_minutes'])
        PracticeAttempt.objects.create(user=self.user, content=self.reading, status='submitted', submitted_at=timezone.now(), correct_count=1, question_count=5)
        PracticeAttempt.objects.create(user=self.user, content=self.listening, status='submitted', submitted_at=timezone.now(), correct_count=5, question_count=5)
        tasks = list(generate_daily_plan(self.user, self.profile, date(2026, 10, 19)))
        self.assertEqual({task.content.skill for task in tasks}, {'reading', 'listening'})
        listening_task = next(task for task in tasks if task.content.skill == 'listening')
        self.assertIn('Bài bổ sung', listening_task.reason)
        self.assertNotIn('tỷ lệ đúng gần đây thấp', listening_task.reason)

    def test_vocabulary_plan_uses_current_cefr_and_progresses_toward_target(self):
        self.profile.current_cefr = 'A2'
        self.profile.target_cefr = 'B1'
        self.profile.save(update_fields=['current_cefr', 'target_cefr'])
        a2 = LearningContent.objects.create(title='A2 words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        b1 = LearningContent.objects.create(title='B1 words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        a2_card = Flashcard.objects.create(content=a2, term='meeting', meaning_vi='cuộc họp', cefr_level='A2')
        Flashcard.objects.create(content=b1, term='negotiate', meaning_vi='đàm phán', cefr_level='B1')

        first = generate_daily_plan(self.user, self.profile, date(2026, 10, 19))
        self.assertEqual(list(first.filter(content__content_type='vocabulary').values_list('cefr_level', flat=True)), ['A2'])

        self.profile.daily_minutes = 20
        self.profile.save(update_fields=['daily_minutes'])
        self.reading.is_published = False
        self.reading.save(update_fields=['is_published'])
        self.listening.is_published = False
        self.listening.save(update_fields=['is_published'])
        UserFlashcardState.objects.create(user=self.user, flashcard=a2_card, last_rating='known', reviewed_at=timezone.now() - timezone.timedelta(days=5), due_at=timezone.now() - timezone.timedelta(days=2), review_count=1)
        next_day = generate_daily_plan(self.user, self.profile, date(2026, 10, 20))
        vocab_tasks = next_day.filter(content__content_type='vocabulary')
        self.assertIn('B1', list(vocab_tasks.values_list('cefr_level', flat=True)))
        reason = vocab_tasks.get(cefr_level='B1').reason
        self.assertIn('tự đánh giá “Đã nhớ”', reason)
        self.assertIn('không xác nhận nhớ lâu hoặc nâng mức CEFR hiện tại', reason)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_cefr, 'A2')

    def test_target_level_caps_vocabulary_recommendation(self):
        self.profile.current_cefr = 'A1'
        self.profile.target_cefr = 'A1'
        self.profile.save(update_fields=['current_cefr', 'target_cefr'])
        a1 = LearningContent.objects.create(title='A1 words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        b1 = LearningContent.objects.create(title='B1 words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        a1_card = Flashcard.objects.create(content=a1, term='hello', meaning_vi='xin chào', cefr_level='A1')
        Flashcard.objects.create(content=b1, term='negotiate', meaning_vi='đàm phán', cefr_level='B1')
        UserFlashcardState.objects.create(user=self.user, flashcard=a1_card, last_rating='known', reviewed_at=timezone.now(), due_at=timezone.now() + timezone.timedelta(days=2), review_count=1)
        tasks = generate_daily_plan(self.user, self.profile, date(2026, 10, 19))
        self.assertFalse(tasks.filter(content=b1).exists())
