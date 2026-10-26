import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from planner.models import LearnerProfile
from .models import AnswerOption, AttemptAnswer, ErrorNotebookEntry, LearningContent, PracticeAttempt, Question


class ResumePracticeFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='resume-flow')
        cls.other = get_user_model().objects.create_user(username='resume-other')
        LearnerProfile.objects.create(user=cls.user, onboarding_complete=True)
        cls.content = LearningContent.objects.create(title='Resume lesson', content_type='reading', skill='reading', review_status='language_checked', is_published=True)
        cls.q1 = Question.objects.create(content=cls.content, order=1, prompt='What time?', explanation='The text states nine.')
        cls.q2 = Question.objects.create(content=cls.content, order=2, prompt='Where?', explanation='The text states Room A.')
        cls.correct1 = AnswerOption.objects.create(question=cls.q1, label='A', text='Nine', is_correct=True)
        cls.wrong1 = AnswerOption.objects.create(question=cls.q1, label='B', text='Ten')
        cls.correct2 = AnswerOption.objects.create(question=cls.q2, label='A', text='Room A', is_correct=True)
        AnswerOption.objects.create(question=cls.q2, label='B', text='Room B')

    def setUp(self):
        self.client.force_login(self.user)
        self.client.post(reverse('learning:practice', args=[self.content.id]))
        self.attempt = PracticeAttempt.objects.get(user=self.user)
        self.save_url = reverse('learning:save_draft', args=[self.attempt.id])
        self.submit_url = reverse('learning:submit_attempt', args=[self.attempt.id])
        self.draft_revision = 0

    def save(self, answers):
        response = self.client.post(self.save_url, json.dumps({'answers': answers, 'draft_revision': self.draft_revision}), content_type='application/json')
        if response.status_code == 200:
            self.draft_revision = response.json()['draft_revision']
        return response

    def test_draft_restores_choices_and_dashboard_links_same_attempt_without_new_one(self):
        response = self.save({str(self.q1.id): self.correct1.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'ok', 'status', 'saved_count', 'last_saved_at', 'draft_revision', 'revision'})
        self.assertEqual(response.json()['saved_count'], 1)
        self.assertFalse(AttemptAnswer.objects.exists())
        self.assertFalse(ErrorNotebookEntry.objects.exists())
        page = self.client.get(reverse('learning:take_attempt', args=[self.attempt.id]))
        self.assertEqual(page.context['questions'][0].selected_option_id, self.correct1.id)
        self.assertIsNone(page.context['questions'][1].selected_option_id)
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.context['resume_attempts'][0].id, self.attempt.id)
        self.assertEqual(dashboard.context['resume_attempts'][0].saved_count, 1)
        start = self.client.get(reverse('learning:practice', args=[self.content.id]))
        self.assertEqual(start.context['active_attempt'].id, self.attempt.id)
        again = self.client.post(reverse('learning:practice', args=[self.content.id]))
        self.assertRedirects(again, reverse('learning:take_attempt', args=[self.attempt.id]))
        self.assertEqual(PracticeAttempt.objects.count(), 1)

    def test_draft_and_resume_are_private_and_csrf_protected(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('learning:take_attempt', args=[self.attempt.id])).status_code, 404)
        self.assertEqual(self.save({str(self.q1.id): self.correct1.id}).status_code, 404)
        self.assertEqual(self.client.post(self.submit_url).status_code, 404)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.user)
        self.assertEqual(guarded.post(self.save_url, json.dumps({'answers': {}}), content_type='application/json').status_code, 403)

    def test_invalid_payload_and_foreign_options_do_not_replace_good_draft(self):
        self.save({str(self.q1.id): self.correct1.id})
        for answers in [[], {str(self.q1.id): self.correct2.id}, {str(self.q1.id): True}, {'9' * 100: self.correct1.id}]:
            with self.subTest(answers=answers):
                self.assertEqual(self.save(answers).status_code, 400)
                self.assertEqual(self.attempt.draft_answers.get().selected_option_id, self.correct1.id)
        self.assertEqual(self.client.get(self.save_url).status_code, 405)
        self.assertEqual(self.client.post(self.save_url, '{broken', content_type='application/json').status_code, 400)

    def test_submit_uses_saved_choice_and_is_idempotent(self):
        self.save({str(self.q1.id): self.correct1.id})
        first = self.client.post(self.submit_url, {'draft_revision': self.draft_revision})
        self.assertRedirects(first, reverse('learning:attempt_result', args=[self.attempt.id]))
        self.attempt.refresh_from_db()
        self.assertEqual((self.attempt.correct_count, self.attempt.question_count, self.attempt.status), (1, 2, 'submitted'))
        self.assertFalse(self.attempt.draft_answers.exists())
        self.assertEqual(ErrorNotebookEntry.objects.count(), 1)
        second = self.client.post(self.submit_url)
        self.assertRedirects(second, reverse('learning:attempt_result', args=[self.attempt.id]))
        self.assertEqual(AttemptAnswer.objects.count(), 2)
        self.assertEqual(ErrorNotebookEntry.objects.count(), 1)
        self.assertEqual(self.save({str(self.q1.id): self.wrong1.id}).status_code, 409)

    def test_final_post_overrides_saved_draft_but_foreign_option_is_rejected(self):
        self.save({str(self.q1.id): self.correct1.id})
        bad = self.client.post(self.submit_url, {f'question_{self.q1.id}': self.correct2.id, 'draft_revision': self.draft_revision})
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(AttemptAnswer.objects.exists())
        self.client.post(self.submit_url, {f'question_{self.q1.id}': self.wrong1.id, f'question_{self.q2.id}': self.correct2.id, 'draft_revision': self.draft_revision})
        self.assertEqual(self.attempt.answers.get(question=self.q1).selected_option_id, self.wrong1.id)

    def test_content_edit_closes_resume_and_releases_draft_foreign_keys(self):
        self.save({str(self.q1.id): self.correct1.id})
        self.q1.prompt = 'A revised question'
        self.q1.save(update_fields=['prompt'])
        page = self.client.get(reverse('learning:take_attempt', args=[self.attempt.id]))
        self.assertRedirects(page, reverse('learning:practice_list'))
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'abandoned')
        self.assertFalse(self.attempt.draft_answers.exists())
        self.assertFalse(self.attempt.answers.exists())

    def test_content_edit_rejects_save_and_final_submit_without_grading(self):
        self.q1.prompt = 'Updated question'
        self.q1.save(update_fields=['prompt'])
        self.assertEqual(self.save({str(self.q1.id): self.correct1.id}).status_code, 409)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'abandoned')
        self.assertEqual(self.client.post(self.submit_url).status_code, 404)

    def test_abandon_is_explicit_post_and_allows_fresh_attempt(self):
        self.save({str(self.q1.id): self.correct1.id})
        url = reverse('learning:abandon_attempt', args=[self.attempt.id])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse('learning:practice_list'))
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'abandoned')
        self.assertFalse(self.attempt.draft_answers.exists())
        self.client.post(reverse('learning:practice', args=[self.content.id]))
        self.assertEqual(PracticeAttempt.objects.filter(user=self.user, status='in_progress').count(), 1)
        self.assertNotEqual(PracticeAttempt.objects.get(user=self.user, status='in_progress').id, self.attempt.id)
