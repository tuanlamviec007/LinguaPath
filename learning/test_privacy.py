import json
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile, StudyTask
from .auth_limits import AuthReservationConflict
from .models import (
    AnswerOption, AttemptAnswer, AttemptDraftAnswer, ErrorNotebookEntry, Flashcard,
    FlashcardReview, LearningContent, MistakeReviewAnswer, MistakeReviewItem,
    MistakeReviewSession, PracticeAttempt, Question, SavedWord, TutorTurn,
    TutorUsageBudget, UserFlashcardState, VocabularyQuizDailyReward, VocabularyQuizSession,
    WeakWordOutcome,
)
from .practice_sessions import answer_evidence


PASSWORD = 'privacy-test-password-123!'


class PrivacyCenterTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.user = users.objects.create_user(username='privacy-owner', email='owner@example.invalid', password=PASSWORD)
        self.other = users.objects.create_user(username='other-private-account', email='other@example.invalid', password='other-private-password')
        self.content = LearningContent.objects.create(title='Shared lesson', content_type='vocabulary', skill='vocabulary',
            exam_type='TOEIC', review_status='language_checked', is_published=True)
        self.card = Flashcard.objects.create(content=self.content, term='deadline', meaning_vi='hạn chót', cefr_level='A1')
        self.question = Question.objects.create(content=self.content, prompt='When?', explanation='Friday.')
        self.option = AnswerOption.objects.create(question=self.question, label='A', text='Friday', is_correct=True)
        AnswerOption.objects.create(question=self.question, label='B', text='Monday')
        self.now = timezone.now()
        self.owner_data = self._records(self.user, 'OWNER_PRIVATE_MARKER')
        self.other_data = self._records(self.other, 'OTHER_PRIVATE_MARKER')
        self.active_quiz = VocabularyQuizSession.objects.create(user=self.user, status='in_progress', mode='recall', question_count=1,
            snapshot=[{'number': 1, 'term': 'UNRELEASED_RECALL_TARGET', 'meaning_vi': 'định nghĩa đang hỏi',
                       'part_of_speech': 'noun', 'cefr_level': 'A1', 'correct_key': 'UNRELEASED_KEY',
                       'example_en': 'UNRELEASED_EXAMPLE', 'options': []}],
            draft_answers={'1': 'own draft guess', 'api_key': 'unknown-draft-secret'})
        self.client.force_login(self.user)

    def _records(self, user, marker):
        LearnerProfile.objects.create(user=user, current_cefr='A1')
        StudyTask.objects.create(user=user, content=self.content, scheduled_for=timezone.localdate(), reason=marker)
        evidence = answer_evidence(self.question, self.option, True, self.content)
        attempt = PracticeAttempt.objects.create(user=user, content=self.content, status='submitted',
            submitted_at=self.now, question_count=1, correct_count=1, question_ids=[self.question.pk],
            result_snapshot={'version': 1, 'answers': [evidence], 'content_title': marker, 'unknown_secret': 'snapshot-secret'})
        answer = AttemptAnswer.objects.create(attempt=attempt, question=self.question, selected_option=self.option,
            is_correct=True, evidence_snapshot=evidence)
        entry = ErrorNotebookEntry.objects.create(answer=answer, learner_note=marker)
        draft = PracticeAttempt.objects.create(user=user, content=self.content)
        AttemptDraftAnswer.objects.create(attempt=draft, question=self.question, selected_option=self.option)
        quiz = VocabularyQuizSession.objects.create(user=user, status='submitted', submitted_at=self.now, mode='meaning',
            question_count=1, correct_count=0, snapshot=[{'number': 1, 'card_id': self.card.pk, 'term': self.card.term,
                'meaning_vi': self.card.meaning_vi, 'part_of_speech': '', 'cefr_level': 'A1', 'correct_key': 'A',
                'options': [{'key': 'A', 'text': self.card.meaning_vi}, {'key': 'B', 'text': 'thời tiết'}]}], answers={'1': 'B'})
        VocabularyQuizDailyReward.objects.create(user=user, quiz=quiz, day=timezone.localdate(), xp=20)
        TutorTurn.objects.create(user=user, question=marker, result={'answer': marker, 'mode': 'retrieval_only', 'sources': [],
            'password': 'injected-result-secret', 'api_key': 'injected-api-secret'})
        TutorUsageBudget.objects.create(user=user, day=timezone.localdate(), minute_started_at=self.now, day_count=1)
        FlashcardReview.objects.create(user=user, flashcard=self.card, rating='known', due_at=self.now + timedelta(days=1))
        UserFlashcardState.objects.create(user=user, flashcard=self.card, last_rating='known', reviewed_at=self.now,
            due_at=self.now + timedelta(days=1), review_count=1)
        SavedWord.objects.create(user=user, flashcard=self.card)
        review = MistakeReviewSession.objects.create(user=user, exam_type='TOEIC', status='submitted', fingerprint='f' * 64,
            submitted_at=self.now, question_count=1, correct_count=1, result_snapshot={'session_id': 1, 'answers': []})
        item = MistakeReviewItem.objects.create(session=review, source_entry=entry, question=self.question, position=1)
        MistakeReviewAnswer.objects.create(item=item, selected_option=self.option, is_correct=True)
        return {'attempt': attempt, 'draft': draft, 'answer': answer, 'entry': entry, 'quiz': quiz, 'review': review}

    def _export(self, **extra):
        return self.client.post(reverse('privacy_center'), {'action': 'export', 'password': PASSWORD, **extra})

    def _delete(self, **extra):
        return self.client.post(reverse('privacy_center'), {'action': 'delete', 'password': PASSWORD,
            'confirm_delete': 'XOA', 'confirm_understood': 'yes', **extra})

    def test_get_is_read_only_and_contains_explicit_privacy_actions(self):
        counts = (get_user_model().objects.count(), TutorTurn.objects.count(), PracticeAttempt.objects.count())
        page = self.client.get(reverse('privacy_center'), {'action': 'delete'})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Tải bản sao dữ liệu của tôi')
        self.assertContains(page, 'Không có nút hoàn tác')
        self.assertContains(page, 'bản sao lưu')
        self.assertContains(page, 'Nhập XOA')
        self.assertIn('no-store', page['Cache-Control'])
        self.assertEqual(counts, (get_user_model().objects.count(), TutorTurn.objects.count(), PracticeAttempt.objects.count()))

    def test_unusable_password_shows_limit_and_does_not_bypass_reauthentication(self):
        self.user.set_unusable_password()
        self.user.save(update_fields=['password'])
        self.client.force_login(self.user)
        page = self.client.get(reverse('privacy_center'))
        self.assertContains(page, 'chưa có mật khẩu LinguaPath', count=2)
        self.assertNotContains(page, 'name="password"')
        for action in ('export', 'delete'):
            response = self.client.post(reverse('privacy_center'), {
                'action': action, 'password': 'anything',
                'confirm_delete': 'XOA', 'confirm_understood': 'yes',
            })
            self.assertEqual(response.status_code, 403)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_export_is_owned_allowlisted_complete_for_saved_sections(self):
        response = self._export()
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        data = response.json()
        self.assertEqual(data['account']['username'], self.user.username)
        self.assertEqual(data['account']['email'], self.user.email)
        self.assertEqual(len(data['profile']), 1)
        self.assertEqual(len(data['practice_attempts']), 2)
        self.assertEqual(len(data['practice_answers']), 1)
        self.assertEqual(len(data['practice_drafts']), 1)
        self.assertEqual(len(data['vocabulary_quizzes']), 2)
        for section in ('study_tasks', 'error_notebook', 'mistake_review_sessions', 'mistake_review_items',
                        'mistake_review_answers', 'tutor_history', 'flashcard_reviews', 'spaced_repetition',
                        'saved_words', 'daily_rewards', 'tutor_usage', 'weak_word_projection'):
            self.assertEqual(len(data[section]), 1, section)
        self.assertEqual(data['practice_answers'][0]['evidence_snapshot']['question']['prompt'], 'When?')
        self.assertEqual(data['weak_word_outcomes'][0]['last_quiz_id'], self.owner_data['quiz'].pk)
        self.assertEqual(data['daily_rewards'][0]['quiz_id'], self.owner_data['quiz'].pk)
        raw = response.content.decode()
        self.assertIn('OWNER_PRIVATE_MARKER', raw)
        for secret in ('OTHER_PRIVATE_MARKER', self.other.username, self.other.email, 'other-private-password',
                       self.user.password, PASSWORD, settings.SECRET_KEY, 'injected-result-secret',
                       'injected-api-secret', 'snapshot-secret', 'unknown-draft-secret'):
            self.assertNotIn(secret, raw)
        for field in ('password', 'groups', 'user_permissions', 'session_key', 'session_data', 'api_key'):
            self.assertNotIn(field, data['account'])
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_export_does_not_open_unsubmitted_recall_key_or_target(self):
        response = self._export()
        data = response.json()
        active = next(quiz for quiz in data['vocabulary_quizzes'] if quiz['id'] == self.active_quiz.pk)
        self.assertFalse(active['answer_key_released'])
        self.assertEqual(active['draft_answers'], {'1': 'own draft guess'})
        self.assertEqual(active['snapshot'][0]['meaning_vi'], 'định nghĩa đang hỏi')
        raw = json.dumps(active)
        for text in ('UNRELEASED_RECALL_TARGET', 'UNRELEASED_KEY', 'UNRELEASED_EXAMPLE', 'correct_key'):
            self.assertNotIn(text, raw)
        submitted = next(quiz for quiz in data['vocabulary_quizzes'] if quiz['id'] == self.owner_data['quiz'].pk)
        self.assertTrue(submitted['answer_key_released'])
        self.assertEqual(submitted['snapshot'][0]['correct_key'], 'A')

    def test_export_unsubmitted_meaning_quiz_excludes_correct_definition_and_key(self):
        self.active_quiz.mode = 'meaning'
        self.active_quiz.snapshot = [{'number': 1, 'term': 'deadline', 'meaning_vi': 'UNRELEASED_DEFINITION',
            'correct_key': 'UNRELEASED_KEY', 'example_vi': 'UNRELEASED_TRANSLATION',
            'options': [{'key': 'A', 'text': 'visible choice'}]}]
        self.active_quiz.save()
        active = next(quiz for quiz in self._export().json()['vocabulary_quizzes'] if quiz['id'] == self.active_quiz.pk)
        raw = json.dumps(active)
        self.assertIn('visible choice', raw)
        self.assertNotIn('UNRELEASED', raw)

    def test_export_size_guard_returns_error_instead_of_partial_download(self):
        with patch('learning.privacy.MAX_EXPORT_BYTES', 64):
            response = self._export()
        self.assertEqual(response.status_code, 413)
        self.assertNotIn('Content-Disposition', response)
        self.assertContains(response, 'Chưa tạo bản xuất', status_code=413)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_export_requires_password_and_ignores_other_user_selector(self):
        denied = self._export(password='wrong')
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn('OWNER_PRIVATE_MARKER', denied.content.decode())
        allowed = self._export(user_id=self.other.pk, username=self.other.username)
        self.assertEqual(allowed.json()['account']['id'], self.user.pk)
        self.assertNotIn('OTHER_PRIVATE_MARKER', allowed.content.decode())

    def test_delete_requires_correct_password_confirmation_and_checkbox(self):
        for fields in ({'password': 'wrong'}, {'confirm_delete': 'wrong'}, {'confirm_understood': ''}):
            with self.subTest(fields=fields):
                response = self._delete(**fields)
                self.assertIn(response.status_code, (400, 403))
                self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
                self.assertTrue(TutorTurn.objects.filter(user=self.user).exists())

    def test_delete_cascades_only_owner_and_logs_out_after_explicit_post(self):
        owner_id, other_id = self.user.pk, self.other.pk
        response = self._delete(user_id=other_id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('login'))
        self.assertFalse(get_user_model().objects.filter(pk=owner_id).exists())
        self.assertTrue(get_user_model().objects.filter(pk=other_id).exists())
        for model in (PracticeAttempt, TutorTurn, SavedWord, FlashcardReview, UserFlashcardState,
                      VocabularyQuizSession, StudyTask, WeakWordOutcome):
            self.assertFalse(model.objects.filter(user_id=owner_id).exists(), model.__name__)
            self.assertTrue(model.objects.filter(user_id=other_id).exists(), model.__name__)
        self.assertTrue(AttemptAnswer.objects.filter(pk=self.other_data['answer'].pk).exists())
        self.assertTrue(LearningContent.objects.filter(pk=self.content.pk).exists())
        self.assertTrue(Question.objects.filter(pk=self.question.pk).exists())
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get(reverse('privacy_center')).status_code, 302)

    def test_staff_and_superuser_deletion_are_forbidden_even_after_password(self):
        for changes in ({'is_staff': True}, {'is_staff': False, 'is_superuser': True}):
            get_user_model().objects.filter(pk=self.user.pk).update(**changes)
            self.assertEqual(self._delete().status_code, 403)
            self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertEqual(self._export().status_code, 200)

    def test_csrf_is_required_before_reauth_or_deletion(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        with patch('learning.privacy.reserve_auth_request') as reserve:
            response = strict.post(reverse('privacy_center'), {'action': 'delete', 'password': PASSWORD,
                'confirm_delete': 'XOA', 'confirm_understood': 'yes'})
        self.assertEqual(response.status_code, 403)
        reserve.assert_not_called()
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
        strict.get(reverse('privacy_center'))
        response = strict.post(reverse('privacy_center'), {'action': 'export', 'password': PASSWORD,
            'csrfmiddlewaretoken': strict.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 200)

    def test_login_and_http_methods_are_enforced_without_side_effects(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('privacy_center')).status_code, 302)
        self.assertEqual(self._delete().status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.delete(reverse('privacy_center')).status_code, 405)
        self.assertEqual(self.client.put(reverse('privacy_center')).status_code, 405)
        self.assertEqual(self.client.post(reverse('privacy_center'), {'action': 'unknown'}).status_code, 400)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    @override_settings(AUTH_RATE_LIMITS={'privacy_reauth': {'window': 600, 'ip': 30, 'identifier': 1}})
    def test_reauth_attempts_have_shared_quota_using_authenticated_owner_not_form_id(self):
        self.assertEqual(self._export(password='wrong', username='forged-one').status_code, 403)
        limited = self._export(password=PASSWORD, username='forged-two')
        self.assertEqual(limited.status_code, 429)
        self.assertGreaterEqual(int(limited['Retry-After']), 1)
        self.assertIn('no-store', limited['Cache-Control'])
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_rate_limit_db_and_conflict_errors_fail_closed_without_details(self):
        for error, expected in ((DatabaseError('private-db-secret'), 503),
                                (AuthReservationConflict(), 429)):
            with self.subTest(error=type(error)), patch('learning.privacy.reserve_auth_request', side_effect=error):
                response = self._delete()
                self.assertEqual(response.status_code, expected)
                self.assertIn('Retry-After', response)
                self.assertNotIn('private-db-secret', response.content.decode())
                self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
