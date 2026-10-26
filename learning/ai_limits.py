"""Atomic per-user and provider-independent global AI request reservations."""

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .locking import nonkey_row_lock

logger = logging.getLogger(__name__)


def _limit(name, default):
    value = getattr(settings, name, default)
    if type(value) is not int or not 0 <= value <= 2147483647:
        raise ValueError('Invalid AI request limit')
    return value


def _refresh_windows(budget, today, now):
    fields = []
    # A backwards clock must not grant another day's or minute's allowance.
    if budget.day < today:
        budget.day, budget.day_count = today, 0
        fields.extend(('day', 'day_count'))
    if budget.minute_started_at is None or now - budget.minute_started_at >= timedelta(seconds=60):
        budget.minute_started_at, budget.minute_count = now, 0
        fields.extend(('minute_started_at', 'minute_count'))
    return fields


def _save_fields(budget, fields):
    if fields:
        budget.save(update_fields=tuple(dict.fromkeys(fields)))


def reserve_tutor_call(user, now=None):
    """Reserve one AI tutor call, returning ``(allowed, reason)``.

    No learner prompt or response is stored. Both providers and editor drafts
    use this same ledger. Counters increment only after all four limits pass;
    a denied request spends neither allowance. A later provider failure still
    spends the accepted reservation. These are request caps, not billing caps.
    """
    if not getattr(settings, 'AI_TUTOR_ENABLED', True):
        return False, 'disabled'
    if user is None or not getattr(user, 'is_authenticated', False):
        return False, 'anonymous'

    try:
        now = now or timezone.now()
        today = timezone.localdate(now)
        daily_limit = _limit('AI_TUTOR_DAILY_LIMIT', 20)
        minute_limit = _limit('AI_TUTOR_MINUTE_LIMIT', 3)
        global_daily_limit = _limit('AI_TUTOR_GLOBAL_DAILY_LIMIT', 200)
        global_minute_limit = _limit('AI_TUTOR_GLOBAL_MINUTE_LIMIT', 20)
        # Import at call time so this module can be loaded while models are
        # being initialized and tests can import it independently.
        from .models import TutorUsageBudget
        from .global_ai_models import GlobalTutorUsageBudget

        with transaction.atomic():
            defaults = {'day': today, 'day_count': 0, 'minute_started_at': now, 'minute_count': 0}
            # One constant unique key serializes reservations across accounts,
            # processes and providers, including concurrent first creation.
            global_budget, _ = GlobalTutorUsageBudget.objects.get_or_create(key='tutor', defaults=defaults)
            global_budget = GlobalTutorUsageBudget.objects.select_for_update().get(pk=global_budget.pk)
            global_fields = _refresh_windows(global_budget, today, now)
            if global_budget.day_count >= global_daily_limit:
                _save_fields(global_budget, global_fields)
                return False, 'global_daily_limit'
            if global_budget.minute_count >= global_minute_limit:
                _save_fields(global_budget, global_fields)
                return False, 'global_minute_limit'

            # Parent user locks precede the per-user FK ledger. NO KEY UPDATE
            # allows unrelated admin-log/FK inserts without a lock inversion.
            nonkey_row_lock(get_user_model().objects.all()).get(pk=user.pk)
            budget, _ = TutorUsageBudget.objects.get_or_create(
                user=user,
                defaults=defaults,
            )
            budget = TutorUsageBudget.objects.select_for_update().get(pk=budget.pk)
            fields_to_update = _refresh_windows(budget, today, now)

            if budget.day_count >= daily_limit:
                reason = 'daily_limit'
            elif budget.minute_count >= minute_limit:
                reason = 'minute_limit'
            else:
                budget.day_count += 1
                budget.minute_count += 1
                fields_to_update.extend(('day_count', 'minute_count'))
                global_budget.day_count += 1
                global_budget.minute_count += 1
                global_fields.extend(('day_count', 'minute_count'))
                reason = 'allowed'

            _save_fields(global_budget, global_fields)
            _save_fields(budget, fields_to_update)
            return reason == 'allowed', reason
    except Exception:
        # Keep database exception details out of learner-facing output and logs.
        logger.error('AI tutor budget reservation failed; request denied.')
        return False, 'unavailable'
