from datetime import date, datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from planner.models import LearnerProfile

from .activity import build_activity_summary
from .models import Flashcard, FlashcardReview, LearningContent, PracticeAttempt


class BuildActivitySummaryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='activity-user')
        self.other_user = get_user_model().objects.create_user(username='other-activity-user')
        LearnerProfile.objects.create(user=self.user, exam_goal='TOEIC')
        self.today = date(2026, 10, 19)
        self.toeic_reading = self.content('TOEIC reading', 'TOEIC', 'reading')
        self.toeic_listening = self.content('TOEIC listening', 'TOEIC', 'listening')
        self.toeic_vocab = self.content('TOEIC vocabulary', 'TOEIC', 'vocabulary')

    def content(self, title, exam, skill, *, published=True):
        return LearningContent.objects.create(
            title=title,
            exam_type=exam,
            content_type=skill,
            skill=skill,
            is_published=published,
        )

    def attempt(self, user, content, day=None, *, timestamp=None, status='submitted', correct=0, total=0):
        attempt = PracticeAttempt.objects.create(
            user=user,
            content=content,
            status=status,
            question_count=total,
            correct_count=correct,
        )
        if timestamp is None and day is not None:
            timestamp = self.local_midnight(day) + timedelta(hours=12)
        if timestamp is not None:
            PracticeAttempt.objects.filter(pk=attempt.pk).update(submitted_at=timestamp)
        return attempt

    def review(self, user, content, *, timestamp=None):
        card = Flashcard.objects.create(
            content=content,
            term=f'word-{Flashcard.objects.count()}',
            meaning_vi='nghĩa',
        )
        review = FlashcardReview.objects.create(
            user=user,
            flashcard=card,
            rating='known',
            due_at=timezone.now(),
        )
        if timestamp is not None:
            FlashcardReview.objects.filter(pk=review.pk).update(reviewed_at=timestamp)
        return review

    @staticmethod
    def local_midnight(day):
        return timezone.make_aware(datetime.combine(day, datetime.min.time()), timezone.get_current_timezone())

    def summary(self, **kwargs):
        return build_activity_summary(self.user, today=self.today, **kwargs)

    def test_returns_seven_local_days_oldest_first_and_counts_duplicate_events(self):
        with timezone.override('Asia/Ho_Chi_Minh'):
            local_today = self.local_midnight(self.today)
            self.attempt(self.user, self.toeic_reading, timestamp=local_today)
            self.attempt(self.user, self.toeic_reading, timestamp=local_today + timedelta(hours=1))
            self.review(self.user, self.toeic_vocab, timestamp=local_today + timedelta(hours=2))
            self.review(self.user, self.toeic_vocab, timestamp=local_today + timedelta(hours=3))
            self.review(self.user, self.toeic_vocab, timestamp=local_today + timedelta(hours=4))

            result = self.summary()

        self.assertEqual(len(result['days']), 7)
        self.assertEqual([item['date'] for item in result['days']], [self.today - timedelta(days=n) for n in range(6, -1, -1)])
        self.assertEqual(result['days'][-1], {
            'date': self.today,
            'label': 'T2',
            'today': True,
            'attempts': 2,
            'reviews': 3,
            'mistake_reviews': 0,
            'quizzes': 0,
            'active': True,
        })
        self.assertEqual(result['active_days'], 1)
        self.assertEqual(result['submitted_attempts'], 2)
        self.assertEqual(result['review_events'], 3)

    def test_scope_is_user_exam_submitted_and_non_null_timestamp(self):
        with timezone.override('Asia/Ho_Chi_Minh'):
            self.attempt(self.user, self.toeic_reading, self.today, total=1)
            self.attempt(self.other_user, self.toeic_reading, self.today, total=1)
            ielts = self.content('IELTS reading', 'IELTS', 'reading')
            self.attempt(self.user, ielts, self.today, total=1)
            self.attempt(self.user, self.toeic_reading, self.today, status='in_progress', total=1)
            self.attempt(self.user, self.toeic_reading, status='submitted', total=1)  # Null submitted_at.
            result = self.summary()

        self.assertEqual(result['submitted_attempts'], 1)
        self.assertEqual(sum(item['attempts'] for item in result['days']), 1)

    def test_seven_day_range_uses_local_midnight_and_excludes_old_and_future_events(self):
        with timezone.override('Asia/Ho_Chi_Minh'):
            oldest = self.today - timedelta(days=6)
            before_oldest = self.local_midnight(oldest) - timedelta(seconds=1)
            at_oldest = self.local_midnight(oldest)
            at_tomorrow = self.local_midnight(self.today + timedelta(days=1))
            self.attempt(self.user, self.toeic_reading, timestamp=before_oldest)
            self.attempt(self.user, self.toeic_reading, timestamp=at_oldest)
            self.attempt(self.user, self.toeic_reading, timestamp=at_tomorrow)
            self.review(self.user, self.toeic_vocab, timestamp=at_oldest)
            result = self.summary()

        self.assertEqual(result['submitted_attempts'], 1)
        self.assertEqual(result['review_events'], 1)
        self.assertEqual(result['days'][0]['attempts'], 1)
        self.assertEqual(result['days'][0]['reviews'], 1)

    def test_utc_events_are_bucketed_by_active_local_timezone(self):
        with timezone.override('Asia/Ho_Chi_Minh'):
            # 16:59 UTC is 23:59 in Vietnam; 17:00 UTC is midnight next day.
            self.attempt(
                self.user, self.toeic_reading,
                timestamp=datetime(2026, 10, 18, 16, 59, tzinfo=datetime_timezone.utc),
            )
            self.attempt(
                self.user, self.toeic_reading,
                timestamp=datetime(2026, 10, 18, 17, 0, tzinfo=datetime_timezone.utc),
            )
            result = self.summary()

        self.assertEqual(result['days'][-2]['date'], date(2026, 10, 18))
        self.assertEqual(result['days'][-2]['attempts'], 1)
        self.assertEqual(result['days'][-1]['attempts'], 1)

    def test_future_timestamps_within_today_are_excluded(self):
        with timezone.override('Asia/Ho_Chi_Minh'):
            cutoff = self.local_midnight(self.today) + timedelta(hours=10)
            self.attempt(self.user, self.toeic_reading, timestamp=cutoff - timedelta(minutes=1))
            self.attempt(self.user, self.toeic_reading, timestamp=cutoff + timedelta(minutes=1))
            self.review(self.user, self.toeic_vocab, timestamp=cutoff + timedelta(minutes=2))
            with patch('learning.activity.timezone.now', return_value=cutoff):
                result = self.summary()

        self.assertEqual(result['submitted_attempts'], 1)
        self.assertEqual(result['review_events'], 0)
        self.assertEqual(result['days'][-1]['attempts'], 1)
        self.assertEqual(result['days'][-1]['reviews'], 0)

    def test_activity_submitted_at_observation_time_is_already_counted(self):
        with timezone.override('Asia/Ho_Chi_Minh'):
            observed = self.local_midnight(self.today) + timedelta(hours=10)
            self.attempt(self.user, self.toeic_reading, timestamp=observed, correct=4, total=5)
            with patch('learning.activity.timezone.now', return_value=observed):
                result = self.summary()
        self.assertEqual(result['submitted_attempts'], 1)
        self.assertEqual(result['skill_rows'][0]['accuracy'], 80)

    def test_streak_ends_today_or_yesterday_if_today_is_empty(self):
        with timezone.override('Asia/Ho_Chi_Minh'):
            self.attempt(self.user, self.toeic_reading, self.today - timedelta(days=2))
            self.review(self.user, self.toeic_vocab, timestamp=self.local_midnight(self.today - timedelta(days=1)))
            result = self.summary()
        self.assertEqual(result['streak_days'], 2)

        with timezone.override('Asia/Ho_Chi_Minh'):
            self.review(self.user, self.toeic_vocab, timestamp=self.local_midnight(self.today))
            result = self.summary()
        self.assertEqual(result['streak_days'], 3)

    def test_streak_stops_at_gap_and_is_zero_when_neither_today_nor_yesterday_active(self):
        with timezone.override('Asia/Ho_Chi_Minh'):
            self.attempt(self.user, self.toeic_reading, self.today - timedelta(days=2))
            self.attempt(self.user, self.toeic_reading, self.today - timedelta(days=4))
            self.assertEqual(self.summary()['streak_days'], 0)

            self.attempt(self.other_user, self.toeic_reading, self.today)
            self.attempt(self.other_user, self.toeic_reading, self.today - timedelta(days=1))
            self.attempt(self.other_user, self.toeic_reading, self.today - timedelta(days=3))
            self.assertEqual(build_activity_summary(self.other_user, today=self.today)['streak_days'], 2)

    def test_streak_query_is_bounded_to_366_calendar_days(self):
        with timezone.override('Asia/Ho_Chi_Minh'):
            for offset in range(367):
                self.attempt(self.user, self.toeic_reading, self.today - timedelta(days=offset))
            result = self.summary()
        self.assertEqual(result['streak_days'], 366)

    def test_skill_rows_use_thirty_local_days_and_hide_small_sample_accuracy(self):
        with timezone.override('Asia/Ho_Chi_Minh'):
            for correct, total in [(1, 2), (2, 3)]:
                self.attempt(self.user, self.toeic_reading, self.today, correct=correct, total=total)
            self.attempt(self.user, self.toeic_listening, self.today, correct=4, total=4)
            self.attempt(self.user, self.toeic_vocab, self.today, correct=1, total=1)
            old_day = self.today - timedelta(days=30)
            self.attempt(self.user, self.toeic_reading, old_day, correct=10, total=10)
            unpublished = self.content('Unpublished old content', 'TOEIC', 'reading', published=False)
            self.attempt(self.user, unpublished, self.today, correct=0, total=1)
            result = self.summary()

        reading, listening, vocabulary = result['skill_rows']
        self.assertEqual((reading['correct'], reading['total'], reading['accuracy']), (3, 6, 50))
        self.assertTrue(reading['sufficient'])
        self.assertEqual(reading['total_attempts'], 3)
        self.assertEqual((listening['correct'], listening['total'], listening['accuracy']), (4, 4, None))
        self.assertFalse(listening['sufficient'])
        self.assertEqual((vocabulary['correct'], vocabulary['total'], vocabulary['accuracy']), (1, 1, None))

    def test_missing_skill_data_returns_zeroes_and_filter_links(self):
        result = self.summary()
        self.assertEqual([(row['key'], row['label']) for row in result['skill_rows']], [
            ('reading', 'Reading'), ('listening', 'Listening'), ('vocabulary', 'Từ vựng'),
        ])
        for row in result['skill_rows']:
            self.assertEqual((row['correct'], row['total'], row['accuracy'], row['sufficient'], row['total_attempts']), (0, 0, None, False, 0))
            self.assertEqual(row['href'], reverse('learning:practice_list') + f"?skill={row['key']}")

