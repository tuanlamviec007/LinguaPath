from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .ai_limits import reserve_tutor_call
from .models import TutorUsageBudget


class TutorBudgetReservationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='budget-user', password='test-password-123',
        )
        self.now = timezone.now()

    @override_settings(AI_TUTOR_ENABLED=False)
    def test_disabled_tutor_denies_without_creating_budget(self):
        self.assertEqual(reserve_tutor_call(self.user, self.now), (False, 'disabled'))
        self.assertFalse(TutorUsageBudget.objects.exists())

    @override_settings(AI_TUTOR_ENABLED=True)
    def test_anonymous_user_is_denied_without_creating_budget(self):
        self.assertEqual(reserve_tutor_call(None, self.now), (False, 'anonymous'))
        self.assertFalse(TutorUsageBudget.objects.exists())

    @override_settings(AI_TUTOR_ENABLED=True, AI_TUTOR_DAILY_LIMIT=2, AI_TUTOR_MINUTE_LIMIT=3)
    def test_daily_limit_counts_only_granted_reservations(self):
        self.assertEqual(reserve_tutor_call(self.user, self.now), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.user, self.now + timedelta(seconds=61)), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.user, self.now + timedelta(seconds=122)), (False, 'daily_limit'))
        budget = TutorUsageBudget.objects.get(user=self.user)
        self.assertEqual(budget.day_count, 2)
        self.assertEqual(budget.minute_count, 0)

    @override_settings(AI_TUTOR_ENABLED=True, AI_TUTOR_DAILY_LIMIT=20, AI_TUTOR_MINUTE_LIMIT=2)
    def test_minute_limit_resets_after_fixed_60_second_window(self):
        self.assertEqual(reserve_tutor_call(self.user, self.now), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.user, self.now + timedelta(seconds=30)), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.user, self.now + timedelta(seconds=59)), (False, 'minute_limit'))
        self.assertEqual(reserve_tutor_call(self.user, self.now + timedelta(seconds=60)), (True, 'allowed'))
        budget = TutorUsageBudget.objects.get(user=self.user)
        self.assertEqual(budget.day_count, 3)
        self.assertEqual(budget.minute_count, 1)

    @override_settings(AI_TUTOR_ENABLED=True, AI_TUTOR_DAILY_LIMIT=3, AI_TUTOR_MINUTE_LIMIT=3)
    def test_new_local_day_resets_daily_count(self):
        self.assertEqual(reserve_tutor_call(self.user, self.now), (True, 'allowed'))
        tomorrow = self.now + timedelta(days=1)
        self.assertEqual(reserve_tutor_call(self.user, tomorrow), (True, 'allowed'))
        budget = TutorUsageBudget.objects.get(user=self.user)
        self.assertEqual(budget.day_count, 1)

    @override_settings(AI_TUTOR_ENABLED=True, AI_TUTOR_DAILY_LIMIT=20, AI_TUTOR_MINUTE_LIMIT=3)
    def test_persistence_error_fails_closed_with_generic_reason(self):
        with self.assertLogs('learning.ai_limits', level='ERROR') as captured:
            with patch.object(TutorUsageBudget.objects, 'get_or_create', side_effect=RuntimeError('secret db detail')):
                self.assertEqual(reserve_tutor_call(self.user, self.now), (False, 'unavailable'))
        self.assertNotIn('secret db detail', '\n'.join(captured.output))

