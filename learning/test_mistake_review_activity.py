from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .activity import build_activity_summary
from .models import MistakeReviewSession


class MistakeReviewActivityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='retry-activity')
        self.now = timezone.now()

    def make_review(self, **overrides):
        attrs = dict(user=self.user, exam_type='TOEIC', status='submitted', fingerprint='0' * 64,
                     question_count=10, correct_count=10, submitted_at=self.now - timedelta(seconds=1))
        attrs.update(overrides)
        return MistakeReviewSession.objects.create(**attrs)

    def test_completed_retry_counts_as_activity_without_inflating_practice_or_skill_accuracy(self):
        self.make_review()
        result = build_activity_summary(self.user)
        self.assertEqual(result['mistake_review_events'], 1)
        self.assertEqual(result['days'][-1]['mistake_reviews'], 1)
        self.assertEqual(result['streak_days'], 1)
        self.assertEqual(result['submitted_attempts'], 0)
        self.assertEqual(result['review_events'], 0)
        self.assertTrue(all(row['total'] == 0 and row['accuracy'] is None for row in result['skill_rows']))

    def test_retry_activity_is_owner_exam_submitted_and_date_scoped(self):
        self.make_review(status='abandoned')
        self.make_review(status='in_progress')
        self.make_review(exam_type='IELTS')
        other = get_user_model().objects.create_user(username='retry-activity-other')
        self.make_review(user=other)
        self.make_review(submitted_at=None)
        self.make_review(submitted_at=self.now + timedelta(days=1))
        self.make_review(submitted_at=self.now - timedelta(days=400))
        result = build_activity_summary(self.user)
        self.assertEqual(result['mistake_review_events'], 0)
        self.assertEqual(result['streak_days'], 0)
        self.assertFalse(any(day['active'] for day in result['days']))
