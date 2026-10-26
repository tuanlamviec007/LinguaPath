import json

from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .mistake_review import (
    MistakeReviewInputError, MistakeReviewUnavailable,
    abandon_mistake_review, get_mistake_review_questions,
    save_mistake_review_draft, start_or_resume_mistake_review,
    submit_mistake_review,
)
from .models import (
    AnswerOption, AttemptAnswer, ErrorNotebookEntry, LearningContent,
    MistakeReviewAnswer, PracticeAttempt, Question,
)


class MistakeReviewDraftTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='retry-draft-owner')
        cls.other = get_user_model().objects.create_user(username='retry-draft-other')
        LearnerProfile.objects.create(user=cls.user, exam_goal='TOEIC', onboarding_complete=True)
        cls.content = LearningContent.objects.create(
            title='A review set', exam_type='TOEIC', content_type='reading', skill='reading',
            is_published=True, review_status='teacher_approved',
        )
        cls.q1 = Question.objects.create(
            content=cls.content, order=1, prompt='First question?', passage='Reading passage',
            transcript='TRANSCRIPT_SECRET', audio_script='SCRIPT_SECRET',
            explanation='EXPLANATION_SECRET', explanation_vi='VI_EXPLANATION_SECRET',
        )
        cls.q2 = Question.objects.create(content=cls.content, order=2, prompt='Second question?', explanation='Other explanation')
        cls.right1 = AnswerOption.objects.create(question=cls.q1, label='A', text='First option', is_correct=True, explanation_vi='RATIONALE_SECRET')
        cls.wrong1 = AnswerOption.objects.create(question=cls.q1, label='B', text='Second option', is_correct=False)
        cls.right2 = AnswerOption.objects.create(question=cls.q2, label='A', text='One', is_correct=True)
        cls.wrong2 = AnswerOption.objects.create(question=cls.q2, label='B', text='Two', is_correct=False)
        cls.original = PracticeAttempt.objects.create(
            user=cls.user, content=cls.content, status='submitted', question_count=2,
            correct_count=0, question_ids=[cls.q1.pk, cls.q2.pk], submitted_at=timezone.now(),
        )
        for question, option in ((cls.q1, cls.wrong1), (cls.q2, cls.wrong2)):
            answer = AttemptAnswer.objects.create(attempt=cls.original, question=question, selected_option=option, is_correct=False)
            ErrorNotebookEntry.objects.create(answer=answer)
        cls.session, _ = start_or_resume_mistake_review(cls.user, 'TOEIC')

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('learning:save_mistake_review_draft', args=[self.session.pk])

    def save_http(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type='application/json')

    def test_replace_and_clear_draft_never_grades_or_marks_mistakes(self):
        first = save_mistake_review_draft(self.user, self.session.pk, {str(self.q1.pk): self.right1.pk, str(self.q2.pk): self.wrong2.pk})
        self.assertEqual(first['saved_count'], 2)
        self.assertIsInstance(first['last_saved_at'], str)
        save_mistake_review_draft(self.user, self.session.pk, {str(self.q1.pk): self.wrong1.pk}, draft_revision=1)
        self.session.refresh_from_db()
        self.assertEqual(self.session.draft_answers, {str(self.q1.pk): self.wrong1.pk})
        self.assertEqual(self.session.status, 'in_progress')
        self.assertEqual(self.session.correct_count, 0)
        self.assertFalse(MistakeReviewAnswer.objects.exists())
        self.assertEqual(AttemptAnswer.objects.count(), 2)
        self.assertFalse(ErrorNotebookEntry.objects.filter(reviewed_at__isnull=False).exists())
        cleared = save_mistake_review_draft(self.user, self.session.pk, {}, draft_revision=2)
        self.assertEqual(cleared['saved_count'], 0)
        self.session.refresh_from_db()
        self.assertEqual(self.session.draft_answers, {})
        self.assertIsNotNone(self.session.last_saved_at)

    def test_restore_dto_and_view_context_without_answer_evidence(self):
        save_mistake_review_draft(self.user, self.session.pk, {str(self.q1.pk): self.wrong1.pk})
        questions = get_mistake_review_questions(self.user, self.session.pk)
        restored = next(question for question in questions if question['id'] == self.q1.pk)
        self.assertEqual(restored['selected_option_id'], self.wrong1.pk)
        self.assertNotIn('transcript', restored)
        self.assertNotIn('audio_script', restored)
        self.assertNotIn('explanation', restored)
        self.assertNotIn('is_correct', restored['options'][0])
        response = self.client.get(reverse('learning:take_mistake_review', args=[self.session.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['draft_count'], 1)
        self.assertTrue(response.context['has_draft'])
        self.assertIsNotNone(response.context['last_saved_at'])
        for hidden in ('TRANSCRIPT_SECRET', 'SCRIPT_SECRET', 'EXPLANATION_SECRET', 'VI_EXPLANATION_SECRET', 'RATIONALE_SECRET'):
            self.assertNotContains(response, hidden)

    def test_foreign_question_or_mismatched_option_does_not_replace_saved_choices(self):
        save_mistake_review_draft(self.user, self.session.pk, {str(self.q1.pk): self.wrong1.pk})
        for answers in ({str(self.q1.pk): self.right2.pk}, {'999999': self.right1.pk}, {str(self.q1.pk): 999999}):
            with self.subTest(answers=answers), self.assertRaises(MistakeReviewInputError):
                save_mistake_review_draft(self.user, self.session.pk, answers, draft_revision=1)
        self.session.refresh_from_db()
        self.assertEqual(self.session.draft_answers, {str(self.q1.pk): self.wrong1.pk})

    def test_strict_payload_and_numeric_ids(self):
        for answers in ([], None, {'1': True}, {True: 1}, {'1': 1.0}, {'01': 1}, {'1': '1.0'}, {'1': -1}, {'1': 2**64}, {str(i): i for i in range(1, 12)}):
            with self.subTest(answers=answers), self.assertRaises(MistakeReviewInputError):
                save_mistake_review_draft(self.user, self.session.pk, answers)
        self.session.refresh_from_db()
        self.assertEqual(self.session.draft_answers, {})

    def test_owner_is_required_for_service_and_http(self):
        with self.assertRaises(Http404):
            save_mistake_review_draft(self.other, self.session.pk, {})
        self.client.force_login(self.other)
        self.assertEqual(self.save_http({'answers': {}}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.save_http({'answers': {}}).status_code, 302)

    def test_endpoint_respects_selected_exam_and_post_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        LearnerProfile.objects.filter(user=self.user).update(exam_goal='IELTS')
        self.assertEqual(self.save_http({'answers': {}}).status_code, 404)

    def test_json_endpoint_validates_shape_size_and_does_not_disclose_grades(self):
        for payload in ({}, [], {'answers': []}, {'answers': {str(self.q1.pk): self.right2.pk}}):
            with self.subTest(payload=payload):
                self.assertEqual(self.save_http(payload).status_code, 400)
        self.assertEqual(self.client.post(self.url, '{', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(self.url, b'\xff', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(self.url, 'x' * 16385, content_type='application/json').status_code, 400)
        response = self.save_http({'answers': {str(self.q1.pk): self.right1.pk}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'ok', 'status', 'saved_count', 'last_saved_at', 'draft_revision', 'revision'})
        self.assertEqual(response.json()['saved_count'], 1)

    def test_csrf_protection_is_not_exempted(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        payload = json.dumps({'answers': {str(self.q1.pk): self.wrong1.pk}})
        self.assertEqual(browser.post(self.url, payload, content_type='application/json').status_code, 403)
        browser.get(reverse('learning:take_mistake_review', args=[self.session.pk]))
        token = browser.cookies['csrftoken'].value
        response = browser.post(self.url, payload, content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)

    def test_submitted_session_clears_draft_and_does_not_use_omitted_saved_choices(self):
        save_mistake_review_draft(self.user, self.session.pk, {str(self.q1.pk): self.right1.pk})
        result = submit_mistake_review(self.user, self.session.pk, {}, draft_revision=1)
        self.assertEqual(result['correct_count'], 0)
        self.assertEqual(result['blank_count'], 2)
        self.session.refresh_from_db()
        self.assertEqual(self.session.draft_answers, {})
        self.assertIsNone(self.session.last_saved_at)
        self.assertEqual(self.save_http({'answers': {}}).status_code, 409)
        self.assertEqual(submit_mistake_review(self.user, self.session.pk, {}), result)

    def test_abandoned_session_discards_draft_and_rejects_future_saves(self):
        save_mistake_review_draft(self.user, self.session.pk, {str(self.q1.pk): self.wrong1.pk})
        abandon_mistake_review(self.user, self.session.pk)
        self.session.refresh_from_db()
        self.assertEqual(self.session.draft_answers, {})
        self.assertIsNone(self.session.last_saved_at)
        self.assertEqual(self.save_http({'answers': {}}).status_code, 409)

    def test_changed_content_invalidates_and_clears_draft_before_save(self):
        save_mistake_review_draft(self.user, self.session.pk, {str(self.q1.pk): self.right1.pk})
        Question.objects.filter(pk=self.q1.pk).update(prompt='Changed question')
        self.assertEqual(self.save_http({'answers': {}}).status_code, 409)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'abandoned')
        self.assertEqual(self.session.draft_answers, {})
        self.assertIsNone(self.session.last_saved_at)
        self.assertFalse(MistakeReviewAnswer.objects.exists())
        self.assertFalse(ErrorNotebookEntry.objects.filter(reviewed_at__isnull=False).exists())

    def test_opening_changed_content_clears_draft(self):
        save_mistake_review_draft(self.user, self.session.pk, {str(self.q1.pk): self.wrong1.pk})
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        with self.assertRaises(MistakeReviewUnavailable):
            get_mistake_review_questions(self.user, self.session.pk)
        self.session.refresh_from_db()
        self.assertEqual(self.session.draft_answers, {})
        self.assertIsNone(self.session.last_saved_at)
