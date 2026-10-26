"""End-to-end quiz journeys spanning drafts, final grading, retry and rewards."""
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile

from .activity import build_activity_summary
from .gamification import get_learning_rewards
from .models import Flashcard, LearningContent, VocabularyQuizDailyReward, VocabularyQuizSession


class QuizJourneyIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='quiz-journey-owner')
        cls.other = get_user_model().objects.create_user(username='quiz-journey-other')
        LearnerProfile.objects.create(user=cls.user, exam_goal='TOEIC', onboarding_complete=True)
        LearnerProfile.objects.create(user=cls.other, exam_goal='TOEIC', onboarding_complete=True)
        cls.content = LearningContent.objects.create(
            title='Quiz journey vocabulary', exam_type='TOEIC', content_type='vocabulary',
            skill='vocabulary', is_published=True, review_status='teacher_approved',
        )
        for term, meaning in (
            ('invoice', 'hóa đơn'), ('aircraft', 'máy bay'), ('agenda', 'lịch họp'),
            ('budget', 'ngân sách'), ('contract', 'hợp đồng'), ('salary', 'lương thưởng'),
            ('supplier', 'nhà cung cấp'), ('receptionist', 'lễ tân'),
        ):
            Flashcard.objects.create(
                content=cls.content, term=term, meaning_vi=meaning, topic='Journey',
                cefr_level='B1', part_of_speech='noun', example_en=f'The report mentions {term}.',
                example_vi='PRIVATE_JOURNEY_TRANSLATION_SENTINEL',
            )

    def setUp(self):
        self.client.force_login(self.user)
        self.today_at_noon = timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time())) + timedelta(hours=12)

    def start(self):
        response = self.client.post(reverse('learning:quiz_start'), {
            'level': 'B1', 'topic': 'Journey', 'count': '5',
        })
        self.assertEqual(response.status_code, 302)
        return VocabularyQuizSession.objects.get(user=self.user, status='in_progress')

    @staticmethod
    def choices(quiz, wrong_count=0):
        answers = {}
        for index, question in enumerate(quiz.snapshot):
            key = question['correct_key']
            if index < wrong_count:
                key = next(option['key'] for option in question['options'] if option['key'] != key)
            answers[f'answer_{question["number"]}'] = key
        return answers

    def test_saved_choices_resume_grade_once_and_retry_day_counts_without_extra_xp(self):
        with patch('django.utils.timezone.now', return_value=self.today_at_noon):
            parent = self.start()
            submitted_choices = self.choices(parent, wrong_count=2)
            partial_choices = {key: value for key, value in list(submitted_choices.items())[:2]}
            saved = self.client.post(reverse('learning:quiz_draft', args=[parent.pk]), {
                'revision': '0', **partial_choices,
            })
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()['saved_count'], 2)
            self.assertEqual(saved.json()['revision'], 1)
            self.assertFalse(VocabularyQuizDailyReward.objects.exists())
            self.assertEqual(get_learning_rewards(self.user)['total_xp'], 0)

            resumed = self.client.get(reverse('learning:quiz_take', args=[parent.pk]))
            self.assertEqual(resumed.status_code, 200)
            self.assertIn('no-store', resumed.headers['Cache-Control'])
            selected = {f'answer_{q["number"]}': q['selected_key'] for q in resumed.context['questions'] if q['selected_key']}
            self.assertEqual(selected, partial_choices)
            self.assertNotContains(resumed, 'PRIVATE_JOURNEY_TRANSLATION_SENTINEL')
            for question in resumed.context['questions']:
                self.assertNotIn('correct_key', question)
                self.assertNotIn('meaning_vi', question)

            submitted = self.client.post(reverse('learning:quiz_submit', args=[parent.pk]), {
                'draft_revision': '1', **submitted_choices,
            })
            self.assertEqual(submitted.status_code, 302)
            parent.refresh_from_db()
            self.assertEqual(parent.correct_count, 3)
            self.assertEqual(parent.xp_earned, 26)
            final_answers = parent.answers.copy()
            final_revision = parent.draft_revision
            late_save = self.client.post(reverse('learning:quiz_draft', args=[parent.pk]), {
                'revision': '1', **self.choices(parent),
            })
            self.assertEqual(late_save.status_code, 409)
            parent.refresh_from_db()
            self.assertEqual(parent.answers, final_answers)
            self.assertEqual(parent.draft_revision, final_revision)
            self.assertEqual(parent.xp_earned, 26)

        tomorrow = self.today_at_noon + timedelta(days=1)
        with patch('django.utils.timezone.now', return_value=tomorrow):
            started_retry = self.client.post(reverse('learning:quiz_retry', args=[parent.pk]))
            self.assertEqual(started_retry.status_code, 302)
            retry = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
            self.assertEqual(retry.parent_quiz_id, parent.pk)
            self.assertEqual(retry.question_count, 2)
            self.assertEqual(
                {question['card_id'] for question in retry.snapshot},
                {question['card_id'] for question in parent.snapshot[:2]},
            )
            graded = self.client.post(reverse('learning:quiz_submit', args=[retry.pk]), {
                'draft_revision': str(retry.draft_revision), **self.choices(retry),
            })
            self.assertEqual(graded.status_code, 302)
            retry.refresh_from_db()
            self.assertEqual(retry.correct_count, 2)
            self.assertEqual(retry.xp_earned, 0)
            self.assertEqual(VocabularyQuizDailyReward.objects.filter(user=self.user).count(), 1)

            rewards = get_learning_rewards(self.user)
            self.assertEqual(rewards['total_xp'], 26)
            self.assertEqual(rewards['today_xp'], 0)
            self.assertEqual(rewards['streak_days'], 2)
            self.assertTrue(rewards['quests'][1]['done'])
            # Activity ranges are half-open at their observation timestamp.
            with patch('django.utils.timezone.now', return_value=tomorrow + timedelta(seconds=1)):
                activity = build_activity_summary(self.user)
            self.assertEqual(activity['quiz_events'], 2)
            self.assertEqual(activity['streak_days'], 2)
            self.assertEqual(activity['days'][-1]['quizzes'], 1)

    def test_stale_tab_cannot_replace_saved_draft_or_submit_over_newer_revision(self):
        quiz = self.start()
        correct = self.choices(quiz)
        first = self.client.post(reverse('learning:quiz_draft', args=[quiz.pk]), {
            'revision': '0', 'answer_1': correct['answer_1'],
        })
        self.assertEqual(first.status_code, 200)
        original_draft = VocabularyQuizSession.objects.get(pk=quiz.pk).draft_answers
        wrong = self.choices(quiz, wrong_count=5)
        conflicting = self.client.post(reverse('learning:quiz_draft', args=[quiz.pk]), {
            'revision': '0', **wrong,
        })
        self.assertEqual(conflicting.status_code, 409)
        stale_submit = self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), {
            'draft_revision': '0', **wrong,
        })
        self.assertEqual(stale_submit.status_code, 409)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, 'in_progress')
        self.assertEqual(quiz.draft_revision, 1)
        self.assertEqual(quiz.draft_answers, original_draft)
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())

        self.client.force_login(self.other)
        denied = self.client.post(reverse('learning:quiz_draft', args=[quiz.pk]), {
            'revision': '1', **correct,
        })
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(self.client.post(reverse('learning:quiz_retry', args=[quiz.pk])).status_code, 404)
        quiz.refresh_from_db()
        self.assertEqual(quiz.draft_answers, original_draft)

    def test_retry_excludes_unpublished_misses_and_cannot_cross_current_exam(self):
        parent = self.start()
        self.client.post(reverse('learning:quiz_submit', args=[parent.pk]), {
            'draft_revision': '0', **self.choices(parent, wrong_count=2),
        })
        hidden = LearningContent.objects.create(
            title='Withdrawn quiz vocabulary', exam_type='TOEIC', content_type='vocabulary',
            skill='vocabulary', is_published=False, review_status='draft',
        )
        hidden_id = parent.snapshot[0]['card_id']
        Flashcard.objects.filter(pk=hidden_id).update(content=hidden)
        retried = self.client.post(reverse('learning:quiz_retry', args=[parent.pk]))
        self.assertEqual(retried.status_code, 302)
        retry = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertEqual(retry.question_count, 1)
        self.assertEqual([q['card_id'] for q in retry.snapshot], [parent.snapshot[1]['card_id']])
        self.client.post(reverse('learning:quiz_abandon', args=[retry.pk]))

        LearnerProfile.objects.filter(user=self.user).update(exam_goal='IELTS')
        before = VocabularyQuizSession.objects.filter(user=self.user).count()
        response = self.client.post(reverse('learning:quiz_retry', args=[parent.pk]))
        self.assertIn(response.status_code, (302, 400, 404))
        self.assertEqual(VocabularyQuizSession.objects.filter(user=self.user).count(), before)
        self.assertFalse(VocabularyQuizSession.objects.filter(user=self.user, status='in_progress').exists())
