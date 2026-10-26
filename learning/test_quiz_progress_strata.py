from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .models import VocabularyQuizSession
from .quiz_progress import quiz_progress_summary


class QuizProgressStrataTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='quiz-strata')
        self.other = get_user_model().objects.create_user(username='quiz-strata-other')
        LearnerProfile.objects.create(user=self.user, exam_goal='TOEIC', onboarding_complete=True)
        self.now = timezone.now()

    def completed(self, **kwargs):
        return VocabularyQuizSession.objects.create(**{
            'user': self.user, 'exam_type': 'TOEIC', 'status': 'submitted',
            'submitted_at': self.now - timedelta(minutes=1), 'question_count': 5,
            'correct_count': 3, 'mode': 'meaning', 'cefr_level': 'A1',
            'vocabulary_source': 'all', **kwargs,
        })

    def test_weighted_counts_stay_separate_by_mode_selected_level_and_source(self):
        self.completed(question_count=1, correct_count=1)
        self.completed(question_count=9, correct_count=0)
        self.completed(mode='recall', correct_count=4)
        self.completed(cefr_level='B1', correct_count=2)
        self.completed(vocabulary_source='saved', correct_count=5)
        self.completed(cefr_level='', question_count=2, correct_count=2)
        self.completed(is_retry=True, mode='recall', correct_count=5)
        result = quiz_progress_summary(self.user, 'TOEIC')
        rows = {(r['mode'], r['cefr_level'], r['vocabulary_source']): r for r in result['strata']}
        self.assertEqual(len(rows), 5)
        meaning = rows['meaning', 'A1', 'all']
        self.assertEqual((meaning['completed'], meaning['questions'], meaning['correct'], meaning['accuracy']), (2, 10, 1, 10))
        self.assertEqual(rows['recall', 'A1', 'all']['accuracy'], 80)
        self.assertEqual(rows['meaning', 'B1', 'all']['accuracy'], 40)
        self.assertEqual(rows['meaning', 'A1', 'saved']['accuracy'], 100)
        self.assertEqual(rows['meaning', '', 'all']['level_label'], 'Mọi mức (trộn)')
        self.assertFalse(rows['meaning', '', 'all']['sufficient'])
        self.assertEqual(result['retry_count'], 1)
        self.assertEqual((result['completed'], result['correct'], result['questions'], result['accuracy']), (6, 14, 27, 52))

    def test_strata_use_only_own_submitted_exam_and_current_thirty_local_days(self):
        valid = self.completed()
        self.completed(user=self.other, mode='recall')
        self.completed(exam_type='IELTS', mode='recall')
        self.completed(status='in_progress', submitted_at=None, mode='recall')
        self.completed(submitted_at=self.now + timedelta(seconds=1), mode='recall')
        self.completed(submitted_at=self.now - timedelta(days=31), mode='recall')
        with patch('learning.quiz_progress.timezone.now', return_value=self.now):
            result = quiz_progress_summary(self.user, 'TOEIC')
        self.assertEqual(len(result['strata']), 1)
        self.assertEqual(result['strata'][0]['completed'], 1)
        self.assertEqual([r.pk for r in result['recent']], [valid.pk])

    def test_empty_history_has_no_strata_or_percentage(self):
        result = quiz_progress_summary(self.user, 'TOEIC')
        self.assertEqual(result['strata'], [])
        self.assertIsNone(result['accuracy'])
        self.assertEqual(result['retry_count'], 0)

    def test_large_snapshots_never_selected_for_counts_or_recent_metadata(self):
        parent = self.completed(snapshot=[{'payload': 'sensitive-answer-evidence' * 1000}], answers={'1': 'private-answer'})
        VocabularyQuizSession.objects.bulk_create([
            VocabularyQuizSession(user=self.user, status='submitted', submitted_at=self.now - timedelta(minutes=1),
                question_count=5, correct_count=1, mode='recall', parent_quiz=parent,
                snapshot=[{'payload': 'large evidence' * 100}], answers={'1': 'stored answer'})
            for _ in range(100)
        ])
        with CaptureQueriesContext(connection) as queries:
            result = quiz_progress_summary(self.user, 'TOEIC')
        self.assertEqual(result['completed'], 101)
        self.assertEqual(len(result['recent']), 6)
        self.assertLessEqual(len(queries), 4)
        for query in queries:
            self.assertNotIn('"snapshot"', query['sql'])
            self.assertNotIn('"answers"', query['sql'])
            self.assertNotIn('"draft_answers"', query['sql'])
        self.assertIn('snapshot', result['recent'][0].get_deferred_fields())
        self.assertIn('snapshot', result['recent'][0].parent_quiz.get_deferred_fields())

    def test_progress_table_describes_configuration_and_small_sample_without_ability_claim(self):
        self.completed(mode='recall', cefr_level='', question_count=2, correct_count=2)
        self.client.force_login(self.user)
        page = self.client.get(reverse('progress'))
        self.assertContains(page, 'Quiz mới theo cách luyện, mức đã chọn và nguồn')
        self.assertContains(page, 'Mọi mức (trộn)')
        self.assertContains(page, 'Chưa đủ dữ liệu')
        self.assertContains(page, 'không phải điểm năng lực')
        self.assertContains(page, 'scope="col"')
        self.assertContains(page, 'tabindex="0"')
        self.assertContains(page, 'Gõ từ tiếng Anh')

    def test_placement_wording_and_result_keep_choice_explicit(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse('learning:placement_test'))
        self.assertContains(page, 'Ước lượng vốn từ')
        self.assertNotContains(page, 'Ước lượng trình độ CEFR')
        self.assertContains(page, 'chưa được hiệu chuẩn bằng pilot')
        session = self.client.session
        session['placement_estimate'] = 'A2'
        session['placement_scores'] = {'A1': 3, 'A2': 2, 'B1': 0, 'B2': 0, 'C1': 0}
        session.save()
        page = self.client.get(reverse('learning:placement_result'))
        self.assertContains(page, 'Mức gợi ý: A2')
        self.assertContains(page, 'không xác nhận trình độ CEFR hoặc điểm TOEIC')
        self.assertContains(page, 'bắt đầu dễ hơn')
        self.assertContains(page, reverse('learning:placement_test'))
        self.user.learner_profile.refresh_from_db()
        self.assertEqual(self.user.learner_profile.current_cefr, 'A1')
