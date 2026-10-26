from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from .spaced_repetition import schedule_review


class EarlyHardReviewTests(SimpleTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 23, 8, tzinfo=timezone.utc)

    def state(self, **changes):
        values = dict(interval_days=8, due_at=self.now + timedelta(hours=1),
                      ease_factor=2.3, successful_reviews=3, lapse_count=1, review_count=4)
        values.update(changes)
        return SimpleNamespace(**values)

    def test_early_hard_keeps_interval_and_original_deadline(self):
        state = self.state()
        result = schedule_review(state, 'hard', self.now)
        self.assertEqual(result['interval_days'], 8)
        self.assertEqual(result['due_at'], state.due_at)
        self.assertEqual(result['successful_reviews'], 3)
        self.assertAlmostEqual(result['ease_factor'], 2.15)

    def test_early_hard_cannot_move_a_relearning_deadline_to_tomorrow(self):
        state = self.state(interval_days=0, due_at=self.now + timedelta(minutes=10), successful_reviews=0)
        result = schedule_review(state, 'hard', self.now)
        self.assertEqual(result['interval_days'], 0)
        self.assertEqual(result['due_at'], state.due_at)

    def test_hard_at_deadline_still_schedules_a_normal_review(self):
        result = schedule_review(self.state(due_at=self.now), 'hard', self.now)
        self.assertEqual(result['interval_days'], 10)
        self.assertEqual(result['due_at'], self.now + timedelta(days=10))

    def test_again_can_bring_a_future_review_back_for_relearning(self):
        result = schedule_review(self.state(due_at=self.now + timedelta(days=8)), 'again', self.now)
        self.assertEqual(result['due_at'], self.now + timedelta(minutes=10))
        self.assertEqual(result['interval_days'], 0)
        self.assertEqual(result['successful_reviews'], 0)
        self.assertEqual(result['lapse_count'], 2)
