"""Read-only learning activity summaries for learner-facing progress views."""

from datetime import datetime, time, timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from .models import FlashcardReview, MistakeReviewSession, PracticeAttempt, VocabularyQuizSession


DAY_LABELS = ('T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN')
SKILL_LABELS = (
    ('reading', 'Reading'),
    ('listening', 'Listening'),
    ('vocabulary', 'Từ vựng'),
)
SKILL_SAMPLE_THRESHOLD = 5


def build_activity_summary(user, exam='TOEIC', today=None):
    """Summarize submitted practice, vocabulary reviews and mistake retry activity.

    Dates are grouped in Django's active local timezone. Historical events remain
    part of the learner's activity even if their content is no longer published;
    only the selected exam, owner, and event dates scope this summary.
    """
    now = timezone.now()
    today = today or timezone.localdate(now)
    local_tz = timezone.get_current_timezone()
    tomorrow = today + timedelta(days=1)

    attempts = PracticeAttempt.objects.filter(
        user=user,
        status='submitted',
        submitted_at__isnull=False,
        content__exam_type=exam,
    )
    reviews = FlashcardReview.objects.filter(
        user=user,
        reviewed_at__isnull=False,
        flashcard__content__exam_type=exam,
    )

    mistake_reviews = MistakeReviewSession.objects.filter(
        user=user, exam_type=exam, status='submitted', submitted_at__isnull=False,
    )
    quizzes = VocabularyQuizSession.objects.filter(
        user=user, exam_type=exam, status='submitted', submitted_at__isnull=False,
    )

    first_day = today - timedelta(days=6)
    attempt_days = _daily_counts(attempts, 'submitted_at', first_day, tomorrow, local_tz, now)
    review_days = _daily_counts(reviews, 'reviewed_at', first_day, tomorrow, local_tz, now)

    retry_days = _daily_counts(mistake_reviews, 'submitted_at', first_day, tomorrow, local_tz, now)
    quiz_days = _daily_counts(quizzes, 'submitted_at', first_day, tomorrow, local_tz, now)

    days = []
    for offset in range(7):
        day = first_day + timedelta(days=offset)
        attempt_count = attempt_days.get(day, 0)
        review_count = review_days.get(day, 0)
        retry_count = retry_days.get(day, 0)
        quiz_count = quiz_days.get(day, 0)
        days.append({
            'date': day,
            'label': DAY_LABELS[day.weekday()],
            'today': day == today,
            'attempts': attempt_count,
            'reviews': review_count,
            'mistake_reviews': retry_count,
            'quizzes': quiz_count,
            'active': bool(attempt_count or review_count or retry_count or quiz_count),
        })

    streak_first_day = today - timedelta(days=365)
    streak_attempt_days = _daily_counts(attempts, 'submitted_at', streak_first_day, tomorrow, local_tz, now)
    streak_review_days = _daily_counts(reviews, 'reviewed_at', streak_first_day, tomorrow, local_tz, now)
    streak_retry_days = _daily_counts(mistake_reviews, 'submitted_at', streak_first_day, tomorrow, local_tz, now)
    streak_quiz_days = _daily_counts(quizzes, 'submitted_at', streak_first_day, tomorrow, local_tz, now)
    active_dates = {
        *streak_attempt_days.keys(),
        *streak_review_days.keys(),
        *streak_retry_days.keys(),
        *streak_quiz_days.keys(),
    }
    streak_days = _current_streak(active_dates, today)

    thirty_day_start = today - timedelta(days=29)
    start_at, end_at = _day_bounds(thirty_day_start, tomorrow, local_tz)
    by_skill = {
        row['content__skill']: row
        for row in attempts.filter(
            submitted_at__gte=start_at,
            submitted_at__lt=end_at,
            submitted_at__lte=now,
        ).values('content__skill').annotate(
            correct=Sum('correct_count'),
            total=Sum('question_count'),
            total_attempts=Count('id'),
        )
    }
    practice_url = reverse('learning:practice_list')
    skill_rows = []
    for key, label in SKILL_LABELS:
        row = by_skill.get(key)
        total = row['total'] if row and row['total'] is not None else 0
        correct = row['correct'] if row and row['correct'] is not None else 0
        enough_data = total >= SKILL_SAMPLE_THRESHOLD
        skill_rows.append({
            'key': key,
            'label': label,
            'correct': correct,
            'total': total,
            'accuracy': int(round(100 * correct / total)) if enough_data else None,
            'sufficient': enough_data,
            'total_attempts': row['total_attempts'] if row else 0,
            'href': f'{practice_url}?skill={key}',
        })

    return {
        'days': days,
        'active_days': sum(day['active'] for day in days),
        'submitted_attempts': sum(attempt_days.values()),
        'review_events': sum(review_days.values()),
        'mistake_review_events': sum(retry_days.values()),
        'quiz_events': sum(quiz_days.values()),
        'streak_days': streak_days,
        'skill_rows': skill_rows,
    }


def _daily_counts(queryset, datetime_field, start_day, end_day, local_tz, now):
    start_at, end_at = _day_bounds(start_day, end_day, local_tz)
    if now < start_at:
        return {}
    rows = queryset.filter(
        **{
            f'{datetime_field}__gte': start_at,
            f'{datetime_field}__lt': end_at,
            f'{datetime_field}__lte': now,
        }
    ).annotate(
        activity_day=TruncDate(datetime_field, tzinfo=local_tz),
    ).values('activity_day').annotate(count=Count('id'))
    return {row['activity_day']: row['count'] for row in rows if row['activity_day'] is not None}


def _day_bounds(start_day, end_day, local_tz):
    """Return aware start/end instants for a half-open local-date range."""
    start = timezone.make_aware(datetime.combine(start_day, time.min), local_tz)
    end = timezone.make_aware(datetime.combine(end_day, time.min), local_tz)
    return start, end


def _current_streak(active_dates, today):
    if today in active_dates:
        current = today
    elif today - timedelta(days=1) in active_dates:
        current = today - timedelta(days=1)
    else:
        return 0

    streak = 0
    while current in active_dates:
        streak += 1
        current -= timedelta(days=1)
    return streak
