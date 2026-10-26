"""Small adaptive review scheduler for LinguaPath flashcards.

This is a transparent project heuristic. It is not FSRS, official SM-2, or a
validated measurement of language proficiency.
"""

from datetime import timedelta
from math import ceil


MIN_EASE_FACTOR = 1.3
MAX_INTERVAL_DAYS = 180


def schedule_review(state, rating, now):
    """Return fields to persist after a review rating.

    ``state`` may be an unsaved state object or a test double. Missing SRS
    attributes are treated as their model defaults, which also makes the
    function safe for the first review before a state row has been persisted.
    """
    if rating not in {'again', 'hard', 'known'}:
        raise ValueError('rating must be one of: again, hard, known')

    old_interval = max(int(getattr(state, 'interval_days', 0) or 0), 0)
    ease = max(float(getattr(state, 'ease_factor', 2.3) or 2.3), MIN_EASE_FACTOR)
    successes = max(int(getattr(state, 'successful_reviews', 0) or 0), 0)
    lapses = max(int(getattr(state, 'lapse_count', 0) or 0), 0)
    review_count = max(int(getattr(state, 'review_count', 0) or 0), 0) + 1

    if rating == 'again':
        interval_days = 0
        due_at = now + timedelta(minutes=10)
        successful_reviews = 0
        lapse_count = lapses + 1
        ease_factor = max(MIN_EASE_FACTOR, ease - 0.2)
    elif rating == 'hard':
        previous_due = getattr(state, 'due_at', None)
        if previous_due is not None and previous_due > now:
            # Looking at a card before its scheduled review is not evidence
            # for a longer interval. Keep its existing deadline as well: even
            # adding the unchanged interval to ``now`` would postpone it.
            interval_days = old_interval
            due_at = previous_due
        else:
            interval_days = min(max(1, ceil(old_interval * 1.2)), MAX_INTERVAL_DAYS)
            due_at = now + timedelta(days=interval_days)
        successful_reviews = successes
        lapse_count = lapses
        ease_factor = max(MIN_EASE_FACTOR, ease - 0.15)
    else:
        if successes == 0:
            interval_days = 1
        elif successes == 1:
            interval_days = 3
        else:
            interval_days = ceil(max(old_interval, 3) * ease)
        interval_days = min(interval_days, MAX_INTERVAL_DAYS)
        due_at = now + timedelta(days=interval_days)
        successful_reviews = successes + 1
        lapse_count = lapses
        ease_factor = ease

    return {
        'last_rating': rating,
        'reviewed_at': now,
        'due_at': due_at,
        'review_count': review_count,
        'interval_days': interval_days,
        'ease_factor': ease_factor,
        'successful_reviews': successful_reviews,
        'lapse_count': lapse_count,
    }
