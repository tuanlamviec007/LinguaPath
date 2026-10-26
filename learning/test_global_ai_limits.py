"""Shared request-cap guarantees; no provider requests are made here."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as datetime_timezone
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone

from .ai_limits import reserve_tutor_call
from .global_ai_models import GlobalTutorUsageBudget
from .models import TutorUsageBudget


@override_settings(AI_TUTOR_ENABLED=True, AI_TUTOR_DAILY_LIMIT=20, AI_TUTOR_MINUTE_LIMIT=3,
                   AI_TUTOR_GLOBAL_DAILY_LIMIT=200, AI_TUTOR_GLOBAL_MINUTE_LIMIT=20)
class GlobalTutorBudgetTests(TestCase):
    def setUp(self):
        self.users = [get_user_model().objects.create_user(username=f'global-budget-{i}') for i in range(2)]
        self.now = datetime(2026, 10, 24, 10, 0, tzinfo=datetime_timezone.utc)

    def counters(self):
        budget = GlobalTutorUsageBudget.objects.get(key='tutor')
        return budget.day_count, budget.minute_count

    @override_settings(AI_TUTOR_GLOBAL_DAILY_LIMIT=2)
    def test_daily_capacity_is_shared_by_accounts_and_provider_configuration(self):
        with patch.dict('os.environ', {'AI_TUTOR_PROVIDER': 'openai'}):
            self.assertEqual(reserve_tutor_call(self.users[0], self.now), (True, 'allowed'))
        with patch.dict('os.environ', {'AI_TUTOR_PROVIDER': 'cloudflare'}):
            self.assertEqual(reserve_tutor_call(self.users[1], self.now), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.users[1], self.now), (False, 'global_daily_limit'))
        self.assertEqual(self.counters(), (2, 2))
        self.assertEqual(list(TutorUsageBudget.objects.order_by('user_id').values_list('day_count', flat=True)), [1, 1])

    @override_settings(AI_TUTOR_GLOBAL_MINUTE_LIMIT=2)
    def test_minute_capacity_is_shared_and_resets_at_sixty_seconds(self):
        self.assertEqual(reserve_tutor_call(self.users[0], self.now), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.users[1], self.now + timedelta(seconds=30)), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.users[1], self.now + timedelta(seconds=59)), (False, 'global_minute_limit'))
        self.assertEqual(reserve_tutor_call(self.users[1], self.now + timedelta(seconds=60)), (True, 'allowed'))
        self.assertEqual(self.counters(), (3, 1))

    @override_settings(AI_TUTOR_DAILY_LIMIT=1, AI_TUTOR_GLOBAL_DAILY_LIMIT=2)
    def test_user_denial_does_not_spend_another_accounts_global_allowance(self):
        self.assertEqual(reserve_tutor_call(self.users[0], self.now), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.users[0], self.now), (False, 'daily_limit'))
        self.assertEqual(reserve_tutor_call(self.users[1], self.now), (True, 'allowed'))
        self.assertEqual(self.counters(), (2, 2))

    @override_settings(AI_TUTOR_MINUTE_LIMIT=1)
    def test_user_minute_denial_leaves_global_counter_unchanged(self):
        self.assertEqual(reserve_tutor_call(self.users[0], self.now), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.users[0], self.now), (False, 'minute_limit'))
        self.assertEqual(self.counters(), (1, 1))

    @override_settings(AI_TUTOR_GLOBAL_DAILY_LIMIT=1)
    def test_global_denial_does_not_create_or_charge_new_user_budget(self):
        self.assertEqual(reserve_tutor_call(self.users[0], self.now), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.users[1], self.now), (False, 'global_daily_limit'))
        self.assertFalse(TutorUsageBudget.objects.filter(user=self.users[1]).exists())
        self.assertEqual(self.counters(), (1, 1))

    def test_error_after_global_save_rolls_back_both_counters(self):
        self.assertEqual(reserve_tutor_call(self.users[0], self.now), (True, 'allowed'))
        with patch.object(TutorUsageBudget, 'save', side_effect=RuntimeError('private database detail')):
            with self.assertLogs('learning.ai_limits', level='ERROR') as captured:
                self.assertEqual(reserve_tutor_call(self.users[0], self.now), (False, 'unavailable'))
        self.assertEqual(self.counters(), (1, 1))
        user_budget = TutorUsageBudget.objects.get(user=self.users[0])
        self.assertEqual((user_budget.day_count, user_budget.minute_count), (1, 1))
        self.assertNotIn('private database detail', '\n'.join(captured.output))

    def test_global_storage_failure_fails_closed_without_user_charge(self):
        with patch.object(GlobalTutorUsageBudget.objects, 'get_or_create', side_effect=RuntimeError('secret')):
            with self.assertLogs('learning.ai_limits', level='ERROR'):
                self.assertEqual(reserve_tutor_call(self.users[0], self.now), (False, 'unavailable'))
        self.assertFalse(TutorUsageBudget.objects.exists())

    @override_settings(TIME_ZONE='Asia/Ho_Chi_Minh', AI_TUTOR_GLOBAL_DAILY_LIMIT=1, AI_TUTOR_DAILY_LIMIT=1)
    def test_daily_windows_follow_local_midnight_even_inside_existing_minute(self):
        before_midnight = datetime(2026, 10, 24, 16, 59, 59, tzinfo=datetime_timezone.utc)
        self.assertEqual(reserve_tutor_call(self.users[0], before_midnight), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.users[0], before_midnight + timedelta(seconds=2)), (True, 'allowed'))
        global_budget = GlobalTutorUsageBudget.objects.get()
        user_budget = TutorUsageBudget.objects.get()
        self.assertEqual(global_budget.day.isoformat(), '2026-10-25')
        self.assertEqual(user_budget.day, global_budget.day)
        self.assertEqual(self.counters(), (1, 2))

    @override_settings(AI_TUTOR_GLOBAL_DAILY_LIMIT=1)
    def test_backwards_day_does_not_refresh_global_capacity(self):
        self.assertEqual(reserve_tutor_call(self.users[0], self.now), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.users[1], self.now - timedelta(days=1)), (False, 'global_daily_limit'))
        self.assertEqual(self.counters(), (1, 1))

    @override_settings(AI_TUTOR_GLOBAL_MINUTE_LIMIT=1)
    def test_backwards_clock_does_not_refresh_global_minute(self):
        self.assertEqual(reserve_tutor_call(self.users[0], self.now), (True, 'allowed'))
        self.assertEqual(reserve_tutor_call(self.users[1], self.now - timedelta(seconds=1)), (False, 'global_minute_limit'))
        self.assertEqual(self.counters(), (1, 1))

    def test_zero_for_any_cap_denies_without_spending_allowance(self):
        for setting in ('AI_TUTOR_DAILY_LIMIT', 'AI_TUTOR_MINUTE_LIMIT',
                        'AI_TUTOR_GLOBAL_DAILY_LIMIT', 'AI_TUTOR_GLOBAL_MINUTE_LIMIT'):
            with self.subTest(setting=setting), override_settings(**{setting: 0}):
                self.assertFalse(reserve_tutor_call(self.users[0], self.now)[0])
                self.assertEqual(self.counters(), (0, 0))
                self.assertFalse(TutorUsageBudget.objects.exclude(day_count=0, minute_count=0).exists())

    def test_invalid_limit_types_and_ranges_fail_closed_before_persistence(self):
        for setting in ('AI_TUTOR_DAILY_LIMIT', 'AI_TUTOR_MINUTE_LIMIT',
                        'AI_TUTOR_GLOBAL_DAILY_LIMIT', 'AI_TUTOR_GLOBAL_MINUTE_LIMIT'):
            for value in ('20', True, None, 1.5, -1, 2147483648):
                with self.subTest(setting=setting, value=value), override_settings(**{setting: value}):
                    with self.assertLogs('learning.ai_limits', level='ERROR'):
                        self.assertEqual(reserve_tutor_call(self.users[0], self.now), (False, 'unavailable'))
        self.assertFalse(GlobalTutorUsageBudget.objects.exists())
        self.assertFalse(TutorUsageBudget.objects.exists())

    def test_disabled_or_anonymous_requests_create_neither_budget(self):
        with override_settings(AI_TUTOR_ENABLED=False):
            self.assertEqual(reserve_tutor_call(self.users[0], self.now), (False, 'disabled'))
        self.assertEqual(reserve_tutor_call(None, self.now), (False, 'anonymous'))
        self.assertFalse(GlobalTutorUsageBudget.objects.exists())
        self.assertFalse(TutorUsageBudget.objects.exists())


@skipUnlessDBFeature('has_select_for_update')
@override_settings(AI_TUTOR_ENABLED=True, AI_TUTOR_DAILY_LIMIT=20, AI_TUTOR_MINUTE_LIMIT=3,
                   AI_TUTOR_GLOBAL_DAILY_LIMIT=2, AI_TUTOR_GLOBAL_MINUTE_LIMIT=20)
class GlobalTutorConcurrencyTests(TransactionTestCase):
    def test_concurrent_first_reservations_cannot_exceed_global_capacity(self):
        users = [get_user_model().objects.create_user(username=f'concurrent-budget-{i}') for i in range(4)]
        now = timezone.now()
        barrier = Barrier(4)

        def reserve(user_id):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=user_id)
                barrier.wait(timeout=10)
                return reserve_tutor_call(user, now)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(reserve, [user.pk for user in users]))
        self.assertEqual(results.count((True, 'allowed')), 2)
        self.assertEqual(results.count((False, 'global_daily_limit')), 2)
        self.assertEqual(GlobalTutorUsageBudget.objects.get().day_count, 2)
        self.assertEqual(sum(TutorUsageBudget.objects.values_list('day_count', flat=True)), 2)
