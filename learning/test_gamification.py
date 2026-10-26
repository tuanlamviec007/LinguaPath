from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from .gamification import get_learning_rewards
from .models import Flashcard, FlashcardReview, LearningContent, MistakeReviewSession, PracticeAttempt, VocabularyQuizDailyReward, VocabularyQuizSession


class LearningRewardsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='reward-owner')
        cls.other = get_user_model().objects.create_user(username='reward-other')
        cls.content = LearningContent.objects.create(title='Rewards words', content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        cls.card = Flashcard.objects.create(content=cls.content, term='invoice', meaning_vi='hóa đơn')

    def review(self, card=None, days_ago=0):
        review = FlashcardReview.objects.create(user=self.user, flashcard=card or self.card, rating='known', due_at=timezone.now())
        if days_ago:
            FlashcardReview.objects.filter(pk=review.pk).update(reviewed_at=timezone.now() - timedelta(days=days_ago))
        return review

    def test_empty_profile_has_no_fake_points_or_badges(self):
        result = get_learning_rewards(self.user)
        self.assertEqual(result['total_xp'], 0)
        self.assertEqual(result['streak_days'], 0)
        self.assertEqual(result['level'], 1)
        self.assertFalse(any(b['earned'] for b in result['badges']))

    def test_repeated_same_card_same_day_counts_once(self):
        for _ in range(8):
            self.review()
        result = get_learning_rewards(self.user)
        self.assertEqual(result['total_xp'], 5)
        self.assertEqual(result['reviewed_today'], 1)
        self.assertEqual(result['quests'][0]['current'], 1)

    def test_review_xp_daily_cap_and_new_day(self):
        for i in range(35):
            card = Flashcard.objects.create(content=self.content, term=f'review{i}', meaning_vi=f'Nghĩa {i}')
            self.review(card)
        self.review(days_ago=1)
        result = get_learning_rewards(self.user)
        self.assertEqual(result['today_xp'], 150)
        self.assertEqual(result['total_xp'], 155)
        self.assertEqual(result['daily_progress'], 100)
        self.assertEqual(result['streak_days'], 2)
        self.assertTrue(result['quests'][0]['done'])

    def test_submitted_practice_per_content_day_is_capped(self):
        for _ in range(4):
            PracticeAttempt.objects.create(user=self.user, content=self.content, status='submitted', submitted_at=timezone.now(), question_count=3)
        result = get_learning_rewards(self.user)
        self.assertEqual(result['today_xp'], 20)
        self.assertTrue(result['quests'][2]['done'])

    def test_in_progress_practice_does_not_award_xp(self):
        PracticeAttempt.objects.create(user=self.user, content=self.content, status='in_progress')
        self.assertEqual(get_learning_rewards(self.user)['total_xp'], 0)

    def test_other_users_activities_are_excluded(self):
        FlashcardReview.objects.create(user=self.other, flashcard=self.card, rating='known', due_at=timezone.now())
        self.assertEqual(get_learning_rewards(self.user)['total_xp'], 0)

    def test_streak_can_end_yesterday_and_breaks_with_gap(self):
        self.review(days_ago=1)
        self.review(days_ago=2)
        self.review(days_ago=4)
        result = get_learning_rewards(self.user)
        self.assertEqual(result['streak_days'], 2)
        self.assertEqual(result['today_xp'], 0)

    def test_quiz_activity_grants_first_badge_and_daily_quest(self):
        quiz = VocabularyQuizSession.objects.create(user=self.user, status='submitted', question_count=5, correct_count=4, submitted_at=timezone.now(), xp_earned=28)
        VocabularyQuizDailyReward.objects.create(user=self.user, quiz=quiz, day=timezone.localdate(), xp=28)
        result = get_learning_rewards(self.user)
        self.assertEqual(result['total_xp'], 28)
        self.assertEqual(result['streak_days'], 1)
        self.assertTrue(result['quests'][1]['done'])
        self.assertTrue(next(b for b in result['badges'] if b['name'] == 'Quiz explorer')['earned'])

    def test_xp_progress_levels_are_game_specific(self):
        for days_ago in range(60):
            self.review(days_ago=days_ago)
        result = get_learning_rewards(self.user)
        self.assertEqual(result['total_xp'], 300)
        self.assertEqual(result['level'], 2)
        self.assertEqual(result['xp_in_level'], 50)
        self.assertEqual(result['xp_to_next'], 200)
        self.assertEqual(result['level_progress'], 20)
        self.assertIn('không quy đổi', result['rules'])

    def test_future_activity_is_not_rewarded(self):
        review = self.review()
        FlashcardReview.objects.filter(pk=review.pk).update(reviewed_at=timezone.now() + timedelta(days=1))
        PracticeAttempt.objects.create(user=self.user, content=self.content, status='submitted', submitted_at=timezone.now() + timedelta(days=1))
        self.assertEqual(get_learning_rewards(self.user)['total_xp'], 0)
        self.assertEqual(get_learning_rewards(self.user)['streak_days'], 0)

    def test_mistake_review_day_keeps_streak_without_awarding_extra_xp(self):
        self.review(days_ago=1)
        MistakeReviewSession.objects.create(user=self.user, exam_type='TOEIC', status='submitted', fingerprint='test-fingerprint', submitted_at=timezone.now(), question_count=1)
        result = get_learning_rewards(self.user)
        self.assertEqual(result['streak_days'], 2)
        self.assertEqual(result['today_xp'], 0)

    def test_streak_badge_stays_earned_after_gap(self):
        for day in (4, 5, 6):
            self.review(days_ago=day)
        result = get_learning_rewards(self.user)
        self.assertEqual(result['streak_days'], 0)
        self.assertEqual(result['longest_streak'], 3)
        self.assertTrue(next(b for b in result['badges'] if b['name'] == 'Nhịp học ba ngày')['earned'])
