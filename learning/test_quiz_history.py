"""Private archive journeys: filtering, score evidence and historical results."""
from datetime import datetime, timedelta
from html import unescape
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .models import (
    Flashcard, FlashcardReview, LearningContent, UserFlashcardState,
    VocabularyQuizDailyReward, VocabularyQuizSession,
)


class QuizHistoryJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='history-owner')
        cls.other = get_user_model().objects.create_user(username='history-other')
        for user in (cls.user, cls.other):
            LearnerProfile.objects.create(user=user, exam_goal='TOEIC', onboarding_complete=True)

    def setUp(self):
        self.client.force_login(self.user)

    def completed(self, **overrides):
        return VocabularyQuizSession.objects.create(**{
            'user': self.user, 'exam_type': 'TOEIC', 'status': 'submitted',
            'submitted_at': timezone.now() - timedelta(minutes=1),
            'question_count': 5, 'correct_count': 3, 'cefr_level': 'B1',
            'topic': 'Travel', **overrides,
        })

    def page(self, **filters):
        response = self.client.get(reverse('learning:quiz_history'), filters)
        self.assertEqual(response.status_code, 200)
        return response

    def test_archive_is_get_only_authenticated_private_and_uncacheable(self):
        own = self.completed(topic='My visible quiz')
        self.completed(user=self.other, topic='Other learner private topic')
        self.completed(exam_type='IELTS', topic='Different exam topic')
        self.completed(status='in_progress', submitted_at=None, topic='Unsubmitted topic')
        self.completed(status='abandoned', topic='Abandoned topic')
        self.completed(submitted_at=None, topic='Missing submission date')
        self.completed(submitted_at=timezone.now() + timedelta(days=1), topic='Future topic')
        response = self.page()
        self.assertEqual((response.context['history_count'], response.context['filtered_count']), (1, 1))
        self.assertEqual([q.pk for q in response.context['quizzes']], [own.pk])
        self.assertEqual(response.context['topics'], ['My visible quiz'])
        self.assertNotContains(response, 'Other learner private topic')
        self.assertNotContains(response, 'Different exam topic')
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(self.client.post(reverse('learning:quiz_history')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('learning:quiz_history')).status_code, 302)

    def test_profile_exam_change_switches_archive_without_rewriting_history(self):
        toeic = self.completed()
        ielts = self.completed(exam_type='IELTS', topic='Academic vocabulary')
        LearnerProfile.objects.filter(user=self.user).update(exam_goal='IELTS')
        response = self.page(period='all')
        self.assertEqual([q.pk for q in response.context['quizzes']], [ielts.pk])
        toeic.refresh_from_db()
        self.assertEqual(toeic.exam_type, 'TOEIC')

    def test_summary_weights_first_try_questions_and_keeps_reviews_separate(self):
        parent = self.completed(question_count=5, correct_count=5)
        self.completed(question_count=15, correct_count=3, vocabulary_source='saved')
        self.completed(question_count=2, correct_count=2, is_retry=True, parent_quiz=parent)
        self.completed(question_count=1, correct_count=1, is_retry=True, vocabulary_source='weak')
        summary = self.page().context['summary']
        self.assertEqual((summary['new_count'], summary['review_count']), (2, 2))
        self.assertEqual((summary['questions'], summary['correct'], summary['accuracy']), (20, 8, 40))
        review_summary = self.page(kind='review').context['summary']
        self.assertEqual((review_summary['new_count'], review_summary['review_count']), (0, 2))
        self.assertEqual((review_summary['questions'], review_summary['correct']), (0, 0))
        self.assertIsNone(review_summary['accuracy'])

    def test_source_and_attempt_type_filters_are_independent(self):
        library = self.completed()
        saved = self.completed(vocabulary_source='saved')
        saved_retry = self.completed(vocabulary_source='saved', is_retry=True, parent_quiz=saved)
        weak = self.completed(vocabulary_source='weak', is_retry=True)
        self.assertEqual({q.pk for q in self.page(source='saved').context['quizzes']}, {saved.pk, saved_retry.pk})
        self.assertEqual([q.pk for q in self.page(source='saved', kind='new').context['quizzes']], [saved.pk])
        self.assertEqual([q.pk for q in self.page(source='saved', kind='review').context['quizzes']], [saved_retry.pk])
        self.assertEqual([q.pk for q in self.page(source='weak').context['quizzes']], [weak.pk])
        self.assertEqual([q.pk for q in self.page(source='all').context['quizzes']], [library.pk])
        self.assertEqual(self.page(source='weak', kind='new').context['filtered_count'], 0)

    def test_level_and_topic_filters_apply_to_historical_quiz_metadata(self):
        match = self.completed(cefr_level='B2', topic='Office')
        self.completed(cefr_level='B1', topic='Office')
        self.completed(cefr_level='B2', topic='Travel')
        response = self.page(level='B2', topic='Office')
        self.assertEqual([q.pk for q in response.context['quizzes']], [match.pk])
        self.assertEqual(response.context['history_count'], 3)
        self.assertEqual(response.context['summary']['new_count'], 1)
        self.assertEqual(response.context['topics'], ['Office', 'Travel'])

    def test_period_uses_inclusive_local_calendar_days_and_excludes_future(self):
        local_zone = ZoneInfo('Asia/Ho_Chi_Minh')
        now = datetime(2026, 10, 23, 0, 30, tzinfo=local_zone)
        start7 = datetime(2026, 10, 17, 0, 0, tzinfo=local_zone)
        start30 = datetime(2026, 9, 24, 0, 0, tzinfo=local_zone)
        today = self.completed(submitted_at=now - timedelta(minutes=1))
        seven_boundary = self.completed(submitted_at=start7)
        before7 = self.completed(submitted_at=start7 - timedelta(microseconds=1))
        thirty_boundary = self.completed(submitted_at=start30)
        before30 = self.completed(submitted_at=start30 - timedelta(microseconds=1))
        self.completed(submitted_at=now + timedelta(seconds=1))
        with timezone.override(local_zone), patch('learning.quiz_history.timezone.now', return_value=now):
            self.assertEqual({q.pk for q in self.page(period='7').context['quizzes']}, {today.pk, seven_boundary.pk})
            self.assertEqual({q.pk for q in self.page().context['quizzes']}, {today.pk, seven_boundary.pk, before7.pk, thirty_boundary.pk})
            self.assertEqual({q.pk for q in self.page(period='all').context['quizzes']}, {today.pk, seven_boundary.pk, before7.pk, thirty_boundary.pk, before30.pk})

    def test_invalid_filters_and_bad_page_fall_back_to_safe_defaults(self):
        own = self.completed()
        response = self.page(source='private', kind='anything', period='-1', level='Z9', topic='Someone else', page='bad')
        self.assertEqual(response.context['selected_source'], '')
        self.assertEqual(response.context['selected_kind'], '')
        self.assertEqual(response.context['selected_period'], '30')
        self.assertEqual(response.context['selected_level'], '')
        self.assertEqual(response.context['selected_topic'], '')
        self.assertEqual([q.pk for q in response.context['quizzes']], [own.pk])

    def test_twenty_per_page_stable_ties_and_filter_preserving_escaped_links(self):
        special_topic = 'Travel & Work <script>alert(1)</script>'
        same_time = timezone.now() - timedelta(minutes=1)
        quizzes = [self.completed(topic=special_topic, submitted_at=same_time, vocabulary_source='saved') for _ in range(23)]
        filters = {'source':'saved', 'kind':'new', 'period':'all', 'level':'B1', 'topic':special_topic}
        first = self.page(**filters)
        second = self.page(**filters, page=2)
        first_ids = [q.pk for q in first.context['quizzes']]
        second_ids = [q.pk for q in second.context['quizzes']]
        self.assertEqual((len(first_ids), len(second_ids)), (20, 3))
        self.assertEqual(first_ids + second_ids, [q.pk for q in reversed(quizzes)])
        self.assertEqual(parse_qs(first.context['pagination_query']), {k:[v] for k,v in filters.items()})
        self.assertNotIn('page', parse_qs(first.context['pagination_query']))
        hrefs = [unescape(href) for href in re.findall(r'href="([^"]+)"', first.content.decode())]
        next_link = next(href for href in hrefs if parse_qs(urlsplit(href).query).get('page') == ['2'])
        self.assertEqual(parse_qs(urlsplit(next_link).query), {**{k:[v] for k,v in filters.items()}, 'page':['2']})
        self.assertNotContains(first, special_topic)
        self.assertContains(first, '&lt;script&gt;')

    def test_review_remains_review_after_parent_deletion(self):
        parent = self.completed()
        retry = self.completed(is_retry=True, parent_quiz=parent, question_count=1, correct_count=1)
        parent.delete()
        response = self.page()
        self.assertEqual([q.pk for q in response.context['quizzes']], [retry.pk])
        self.assertEqual(response.context['summary']['review_count'], 1)
        self.assertEqual(response.context['summary']['new_count'], 0)
        self.assertIsNone(response.context['summary']['accuracy'])

    def test_hidden_deleted_source_remains_in_own_submitted_history_and_result(self):
        content = LearningContent.objects.create(title='Archive source', content_type='vocabulary', skill='vocabulary', exam_type='TOEIC', review_status='teacher_approved', is_published=True)
        card = Flashcard.objects.create(content=content, term='agenda', meaning_vi='chương trình họp', cefr_level='B1')
        snapshot = [{'number':1, 'card_id':card.pk, 'term':card.term, 'meaning_vi':card.meaning_vi,
                     'example_en':'Please check the agenda.', 'example_vi':'Vui lòng xem chương trình họp.',
                     'cefr_level':'B1', 'source_url':'', 'correct_key':'A',
                     'options':[{'key':'A','text':card.meaning_vi},{'key':'B','text':'vé tàu'}]}]
        quiz = self.completed(question_count=1, correct_count=1, snapshot=snapshot, answers={'1':'A'})
        content.is_published = False
        content.save(update_fields=['is_published'])
        card.delete()
        response = self.page()
        self.assertEqual([q.pk for q in response.context['quizzes']], [quiz.pk])
        result = self.client.get(reverse('learning:quiz_result', args=[quiz.pk]))
        self.assertContains(result, 'agenda')
        self.assertFalse(result.context['results'][0]['can_save'])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('learning:quiz_result', args=[quiz.pk])).status_code, 404)

    def test_reading_archive_does_not_award_xp_or_change_learning_records(self):
        quiz = self.completed(xp_earned=26)
        before = (VocabularyQuizSession.objects.count(), VocabularyQuizDailyReward.objects.count(), FlashcardReview.objects.count(), UserFlashcardState.objects.count())
        self.page()
        self.page(kind='review')
        self.page(period='all')
        after = (VocabularyQuizSession.objects.count(), VocabularyQuizDailyReward.objects.count(), FlashcardReview.objects.count(), UserFlashcardState.objects.count())
        self.assertEqual(before, after)
        quiz.refresh_from_db()
        self.assertEqual((quiz.status, quiz.xp_earned), ('submitted', 26))

    def test_hub_recent_results_use_current_exam_real_submission_and_stable_order(self):
        same_time = timezone.now() - timedelta(minutes=1)
        first = self.completed(submitted_at=same_time)
        second = self.completed(submitted_at=same_time)
        self.completed(user=self.other)
        self.completed(exam_type='IELTS')
        self.completed(submitted_at=timezone.now() + timedelta(days=1))
        self.completed(submitted_at=None)
        response = self.client.get(reverse('learning:quiz_hub'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([q.pk for q in response.context['recent_quizzes']], [second.pk, first.pk])
