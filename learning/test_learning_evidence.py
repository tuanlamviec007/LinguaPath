"""Regression tests for frozen grading evidence and cross-tab draft writes."""
import copy
import json
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from planner.models import LearnerProfile
from .models import AnswerOption, AttemptAnswer, LearningContent, PracticeAttempt, Question
from .practice_sessions import start_or_resume
from .mistake_review import start_or_resume_mistake_review


class LearningEvidenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='evidence-owner')
        cls.other = get_user_model().objects.create_user(username='evidence-other')
        LearnerProfile.objects.create(user=cls.user, onboarding_complete=True)
        cls.content = LearningContent.objects.create(title='Original title', content_type='reading', skill='reading',
                                                    review_status='teacher_approved', is_published=True)
        cls.question = Question.objects.create(content=cls.content, prompt='ORIGINAL PROMPT', passage='Original passage',
                                              explanation='ORIGINAL EXPLANATION', explanation_vi='GIẢI THÍCH GỐC')
        cls.right = AnswerOption.objects.create(question=cls.question, label='A', text='ORIGINAL RIGHT', is_correct=True)
        cls.wrong = AnswerOption.objects.create(question=cls.question, label='B', text='ORIGINAL WRONG', is_correct=False)

    def setUp(self):
        self.client.force_login(self.user)
        self.attempt, _ = start_or_resume(self.user, self.content)
        self.save_url = reverse('learning:save_draft', args=[self.attempt.pk])
        self.submit_url = reverse('learning:submit_attempt', args=[self.attempt.pk])
        self.result_url = reverse('learning:attempt_result', args=[self.attempt.pk])

    def save(self, answers, revision=0, url=None):
        return self.client.post(url or self.save_url,
                                json.dumps({'answers': answers, 'draft_revision': revision}), content_type='application/json')

    def submit(self, option=None, revision=0):
        return self.client.post(self.submit_url, {'draft_revision': revision,
                                f'question_{self.question.pk}': (option or self.right).pk})

    def review(self):
        self.submit(self.wrong)
        session, _ = start_or_resume_mistake_review(self.user, 'TOEIC')
        return session, reverse('learning:save_mistake_review_draft', args=[session.pk]), reverse('learning:submit_mistake_review', args=[session.pk])

    def test_result_and_answer_evidence_survive_source_edits_and_selected_option_deletion(self):
        self.assertEqual(self.submit().status_code, 302)
        self.attempt.refresh_from_db()
        frozen = copy.deepcopy(self.attempt.result_snapshot)
        self.question.prompt = 'MUTATED PROMPT'; self.question.explanation_vi = 'MUTATED EXPLANATION'; self.question.save()
        self.content.title = 'MUTATED TITLE'; self.content.save()
        self.right.delete()
        self.wrong.is_correct = True; self.wrong.text = 'MUTATED ANSWER'; self.wrong.save()
        response = self.client.get(self.result_url)
        for original in ('ORIGINAL PROMPT', 'GIẢI THÍCH GỐC', 'ORIGINAL RIGHT', 'Original title'):
            self.assertContains(response, original)
        for mutated in ('MUTATED PROMPT', 'MUTATED EXPLANATION', 'MUTATED TITLE', 'MUTATED ANSWER'):
            self.assertNotContains(response, mutated)
        self.assertFalse(response.context['legacy_result'])
        self.assertEqual(self.attempt.answers.get().evidence_snapshot, frozen['answers'][0])
        self.assertIsNone(self.attempt.answers.get().selected_option)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.result_snapshot, frozen)

    def test_notebook_uses_original_wrong_answer_after_option_delete(self):
        self.submit(self.wrong)
        self.wrong.delete()
        self.question.prompt = 'CHANGED NOTEBOOK PROMPT'; self.question.save()
        response = self.client.get(reverse('learning:mistake_notebook'))
        self.assertContains(response, 'ORIGINAL WRONG')
        self.assertContains(response, 'ORIGINAL PROMPT')
        self.assertNotContains(response, 'CHANGED NOTEBOOK PROMPT')

    def test_legacy_result_is_explicit_and_not_backfilled(self):
        self.submit()
        PracticeAttempt.objects.filter(pk=self.attempt.pk).update(result_snapshot={})
        AttemptAnswer.objects.filter(attempt=self.attempt).update(evidence_snapshot={})
        response = self.client.get(self.result_url)
        self.assertContains(response, 'Lượt luyện cũ chưa lưu bản gốc')
        self.assertTrue(response.context['legacy_result'])
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.result_snapshot, {})
        self.assertEqual(self.attempt.answers.get().evidence_snapshot, {})

    def test_malformed_new_result_is_not_reconstructed_from_current_bank(self):
        self.submit()
        for corrupt in ([], [1], {'version': 1, 'answers': [None]}, {'version': 1, 'answers': []}):
            PracticeAttempt.objects.filter(pk=self.attempt.pk).update(result_snapshot=corrupt)
            response = self.client.get(self.result_url)
            self.assertContains(response, 'Không thể đọc bản kết quả gốc')
            self.assertNotContains(response, 'ORIGINAL PROMPT')

    def test_corrupt_answer_evidence_never_falls_back_to_live_notebook_wording(self):
        self.submit(self.wrong)
        for corrupt in ([], {'question': {}}):
            AttemptAnswer.objects.filter(attempt=self.attempt).update(evidence_snapshot=corrupt)
            response = self.client.get(reverse('learning:mistake_notebook'))
            self.assertContains(response, 'Không thể đọc bản bằng chứng gốc')
            self.assertNotContains(response, 'ORIGINAL PROMPT')

    def test_two_practice_tabs_cannot_silently_clear_newer_draft(self):
        first = self.save({str(self.question.pk): self.right.pk})
        self.assertEqual(first.json()['draft_revision'], 1)
        stale = self.save({}, revision=0)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['status'], 'conflict')
        self.assertEqual(self.attempt.draft_answers.get().selected_option_id, self.right.pk)
        self.assertFalse(self.attempt.answers.exists())
        accepted = self.save({}, revision=1)
        self.assertEqual(accepted.json()['draft_revision'], 2)
        self.assertFalse(self.attempt.draft_answers.exists())

    def test_stale_practice_submit_preserves_choices_and_does_not_grade(self):
        self.save({str(self.question.pk): self.right.pk})
        stale = self.submit(self.wrong, revision=0)
        self.assertEqual(stale.status_code, 409)
        self.assertTrue(stale.context['draft_conflict'])
        self.assertEqual(stale.context['questions'][0].selected_option_id, self.wrong.pk)
        self.assertEqual(self.attempt.draft_answers.get().selected_option_id, self.right.pk)
        self.assertFalse(self.attempt.answers.exists())

    def test_submit_once_then_save_conflict_and_repeated_submit_unchanged(self):
        self.save({str(self.question.pk): self.right.pk})
        self.assertEqual(self.submit(revision=1).status_code, 302)
        self.attempt.refresh_from_db(); frozen = copy.deepcopy(self.attempt.result_snapshot)
        response = self.save({str(self.question.pk): self.wrong.pk}, revision=1)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['status'], 'submitted')
        self.assertEqual(self.submit(self.wrong, revision=0).status_code, 302)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.result_snapshot, frozen)
        self.assertEqual(self.attempt.answers.count(), 1)

    def test_revisionless_preupgrade_tab_cannot_replace_newer_draft(self):
        self.save({str(self.question.pk): self.right.pk})
        response = self.client.post(self.save_url, json.dumps({'answers': {}}), content_type='application/json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.post(self.submit_url).status_code, 409)
        self.assertTrue(self.attempt.draft_answers.exists())

    def test_revision_payload_is_strict_and_does_not_save(self):
        for invalid in (True, [], {}, None, -1, '1.0', '٠', 2147483647):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.save({}, invalid).status_code, 400)
        self.assertFalse(self.attempt.draft_answers.exists())
        self.assertEqual(self.client.post(self.submit_url, {'draft_revision': ['0', '0']}).status_code, 400)

    def test_two_review_tabs_and_stale_submit_do_not_replace_newer_answers(self):
        session, save_url, submit_url = self.review()
        self.assertEqual(self.save({str(self.question.pk): self.right.pk}, url=save_url).json()['draft_revision'], 1)
        self.assertEqual(self.save({}, url=save_url).status_code, 409)
        stale = self.client.post(submit_url, {'draft_revision': 0, f'question_{self.question.pk}': self.wrong.pk})
        self.assertEqual(stale.status_code, 409)
        self.assertTrue(stale.context['draft_conflict'])
        self.assertEqual(stale.context['questions'][0]['selected_option_id'], self.wrong.pk)
        session.refresh_from_db()
        self.assertEqual(session.status, 'in_progress')
        self.assertEqual(session.draft_answers, {str(self.question.pk): self.right.pk})
        self.assertFalse(session.items.filter(answer__isnull=False).exists())
        response = self.client.post(submit_url, {'draft_revision': 1, f'question_{self.question.pk}': self.right.pk})
        self.assertEqual(response.status_code, 302)
        session.refresh_from_db(); frozen = copy.deepcopy(session.result_snapshot)
        self.assertEqual(self.save({}, revision=1, url=save_url).json()['status'], 'submitted')
        self.assertEqual(self.client.post(submit_url, {'draft_revision': 'bad'}).status_code, 302)
        session.refresh_from_db()
        self.assertEqual(session.result_snapshot, frozen)

    def test_owner_and_csrf_protection_cover_revision_conflicts(self):
        self.client.force_login(self.other)
        self.assertEqual(self.save({}, 0).status_code, 404)
        self.assertEqual(self.client.get(self.result_url).status_code, 404)
        self.assertEqual(self.submit().status_code, 404)
        guarded = Client(enforce_csrf_checks=True); guarded.force_login(self.user)
        self.assertEqual(guarded.post(self.save_url, '{}', content_type='application/json').status_code, 403)
        self.assertEqual(guarded.post(self.submit_url, {'draft_revision': 0}).status_code, 403)

    def test_stale_get_invalidation_cannot_abandon_a_submitted_result(self):
        from types import SimpleNamespace
        from .views import _abandon_changed_attempt
        stale = PracticeAttempt.objects.get(pk=self.attempt.pk)
        self.submit()
        response = _abandon_changed_attempt(SimpleNamespace(user=self.user), stale)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.result_url)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'submitted')
        self.assertTrue(self.attempt.result_snapshot)


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections
from django.test import RequestFactory, TransactionTestCase, skipUnlessDBFeature
from .practice_sessions import DraftConflictError, save_draft


@skipUnlessDBFeature('has_select_for_update')
class LearningWriterConcurrencyTests(TransactionTestCase):
    """Real row-lock tests run on PostgreSQL CI; SQLite cannot prove this."""
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='concurrent-writer')
        self.content = LearningContent.objects.create(title='Concurrent content', content_type='reading', skill='reading',
                                                    is_published=True, review_status='teacher_approved')
        self.question = Question.objects.create(content=self.content, prompt='Concurrent?', explanation='Yes')
        self.option = AnswerOption.objects.create(question=self.question, label='A', text='Yes', is_correct=True)
        AnswerOption.objects.create(question=self.question, label='B', text='No')
        self.attempt, _ = start_or_resume(self.user, self.content)

    def run_pair(self, first, second):
        barrier = Barrier(2)
        def run(action):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                barrier.wait(timeout=5)
                return action(user)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, action) for action in (first, second)]
            return [future.result(timeout=15) for future in futures]

    def test_resume_and_save_have_consistent_owner_lock_order(self):
        def resume(user):
            content = LearningContent.objects.get(pk=self.content.pk)
            return start_or_resume(user, content)[0].pk
        def save(user):
            return save_draft(user, self.attempt.pk, {str(self.question.pk): self.option.pk}, 0)['draft_revision']
        self.assertEqual(self.run_pair(resume, save), [self.attempt.pk, 1])
        self.assertEqual(PracticeAttempt.objects.filter(user=self.user, status='in_progress').count(), 1)

    def test_simultaneous_save_submit_accept_only_one_revision_zero_writer(self):
        from .views import submit_attempt
        def save(user):
            try:
                save_draft(user, self.attempt.pk, {str(self.question.pk): self.option.pk}, 0)
                return 200
            except DraftConflictError:
                return 409
        def submit(user):
            request = RequestFactory().post('/', {'draft_revision': 0, f'question_{self.question.pk}': self.option.pk})
            request.user = user
            return submit_attempt(request, self.attempt.pk).status_code
        statuses = self.run_pair(save, submit)
        self.assertIn(statuses, ([200, 409], [409, 302]))
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.draft_revision, 1)
        self.assertLessEqual(self.attempt.answers.count(), 1)
