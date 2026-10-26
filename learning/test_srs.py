from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from .spaced_repetition import schedule_review


class ScheduleReviewTests(SimpleTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 19, 8, 30, tzinfo=timezone.utc)

    def state(self, **overrides):
        values = {
            'interval_days': 0,
            'ease_factor': 2.3,
            'successful_reviews': 0,
            'lapse_count': 0,
            'review_count': 0,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_first_known_review_is_one_day_and_increments_counters(self):
        result = schedule_review(self.state(), 'known', self.now)
        self.assertEqual(result['due_at'], self.now + timedelta(days=1))
        self.assertEqual(result['interval_days'], 1)
        self.assertEqual(result['successful_reviews'], 1)
        self.assertEqual(result['review_count'], 1)
        self.assertEqual(result['ease_factor'], 2.3)
        self.assertEqual(result['lapse_count'], 0)
        self.assertEqual(result['reviewed_at'], self.now)
        self.assertEqual(result['last_rating'], 'known')

    def test_second_known_review_is_three_days(self):
        result = schedule_review(
            self.state(successful_reviews=1, interval_days=1), 'known', self.now,
        )
        self.assertEqual(result['interval_days'], 3)
        self.assertEqual(result['due_at'], self.now + timedelta(days=3))
        self.assertEqual(result['successful_reviews'], 2)

    def test_later_known_review_multiplies_interval_by_ease(self):
        result = schedule_review(
            self.state(successful_reviews=2, interval_days=4, ease_factor=2.3),
            'known', self.now,
        )
        self.assertEqual(result['interval_days'], 10)
        self.assertEqual(result['due_at'], self.now + timedelta(days=10))
        self.assertEqual(result['successful_reviews'], 3)

    def test_again_resets_successes_and_lowers_ease_with_minimum(self):
        result = schedule_review(
            self.state(interval_days=8, ease_factor=1.35, successful_reviews=4,
                       lapse_count=2, review_count=5),
            'again', self.now,
        )
        self.assertEqual(result['interval_days'], 0)
        self.assertEqual(result['due_at'], self.now + timedelta(minutes=10))
        self.assertEqual(result['successful_reviews'], 0)
        self.assertEqual(result['lapse_count'], 3)
        self.assertEqual(result['ease_factor'], 1.3)
        self.assertEqual(result['review_count'], 6)

    def test_hard_keeps_successes_increases_interval_and_lowers_ease(self):
        result = schedule_review(
            self.state(interval_days=5, ease_factor=2.0, successful_reviews=2,
                       lapse_count=1),
            'hard', self.now,
        )
        self.assertEqual(result['interval_days'], 6)
        self.assertEqual(result['due_at'], self.now + timedelta(days=6))
        self.assertEqual(result['successful_reviews'], 2)
        self.assertEqual(result['lapse_count'], 1)
        self.assertEqual(result['ease_factor'], 1.85)

    def test_first_hard_review_schedules_one_day(self):
        result = schedule_review(self.state(), 'hard', self.now)
        self.assertEqual(result['interval_days'], 1)
        self.assertEqual(result['due_at'], self.now + timedelta(days=1))

    def test_intervals_are_capped_at_180_days(self):
        hard = schedule_review(self.state(interval_days=500), 'hard', self.now)
        known = schedule_review(
            self.state(interval_days=100, successful_reviews=3, ease_factor=3.0),
            'known', self.now,
        )
        self.assertEqual(hard['interval_days'], 180)
        self.assertEqual(known['interval_days'], 180)

    def test_unknown_rating_is_rejected(self):
        with self.assertRaises(ValueError):
            schedule_review(self.state(), 'easy', self.now)
