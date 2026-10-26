import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .models import (
    AnswerOption,
    AttemptAnswer,
    LearningContent,
    PracticeAttempt,
    Question,
)


class ListeningWorkspaceHttpTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.learner = user_model.objects.create_user(username='workspace-learner', password='Strong-pass-123!')
        self.other = user_model.objects.create_user(username='workspace-other', password='Strong-pass-123!')
        LearnerProfile.objects.create(user=self.learner, exam_goal='TOEIC', onboarding_complete=True)
        self.content = LearningContent.objects.create(
            title='Listening: station announcement', exam_type='TOEIC',
            content_type='listening', skill='listening', review_status='teacher_approved',
            is_published=True,
        )
        self.question = Question.objects.create(
            content=self.content, order=1, prompt='Where should passengers wait?',
            audio_url='https://cdn.example.test/audio/station.mp3',
            audio_script='PRIVATE_SCRIPT_SENTINEL: Passengers should wait by platform two.',
            transcript='PRIVATE_TRANSCRIPT_SENTINEL: Passengers should wait by platform two.',
            explanation='PRIVATE_EXPLANATION_SENTINEL: Platform two is stated.',
            explanation_vi='PRIVATE_VI_EXPLANATION_SENTINEL',
        )
        self.correct = AnswerOption.objects.create(
            question=self.question, label='A', text='By platform two', is_correct=True,
            explanation_vi='PRIVATE_OPTION_EXPLANATION_SENTINEL',
        )
        self.wrong = AnswerOption.objects.create(
            question=self.question, label='B', text='By platform four', is_correct=False,
        )
        self.client.force_login(self.learner)
        response = self.client.post(reverse('learning:practice', args=[self.content.pk]))
        self.assertEqual(response.status_code, 302)
        self.attempt = PracticeAttempt.objects.get(user=self.learner, content=self.content)

    def test_listening_attempt_page_exposes_supported_audio_and_transcript_without_answer_key(self):
        response = self.client.get(reverse('learning:take_attempt', args=[self.attempt.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.question.audio_url)
        self.assertContains(response, '<audio', html=False)
        self.assertContains(response, 'PRIVATE_SCRIPT_SENTINEL')
        self.assertContains(response, 'PRIVATE_TRANSCRIPT_SENTINEL')
        self.assertContains(response, 'data-listening-player', html=False)
        self.assertContains(response, 'Bản chép lời hỗ trợ luyện tập')
        self.assertContains(response, 'Giọng đọc thiết bị')
        for secret in ('PRIVATE_EXPLANATION_SENTINEL', 'PRIVATE_VI_EXPLANATION_SENTINEL', 'PRIVATE_OPTION_EXPLANATION_SENTINEL'):
            self.assertNotContains(response, secret)
        self.assertNotContains(response, 'correct_option_id')
        self.assertNotContains(response, 'is_correct')

    def test_submitted_result_reveals_transcript_and_explanation(self):
        response = self.client.post(
            reverse('learning:submit_attempt', args=[self.attempt.pk]),
            {f'question_{self.question.pk}': str(self.correct.pk)},
        )
        self.assertRedirects(response, reverse('learning:attempt_result', args=[self.attempt.pk]))
        result = self.client.get(response.url)
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, 'PRIVATE_TRANSCRIPT_SENTINEL')
        self.assertContains(result, 'PRIVATE_VI_EXPLANATION_SENTINEL')

    def test_audio_only_content_still_has_native_player_and_script_only_content_uses_speech(self):
        audio_only = self._make_extra_listening('Audio only', audio_url='https://cdn.example.test/audio/only.mp3')
        self.client.post(reverse('learning:practice', args=[audio_only.pk]))
        audio_attempt = PracticeAttempt.objects.get(user=self.learner, content=audio_only)
        audio_page = self.client.get(reverse('learning:take_attempt', args=[audio_attempt.pk]))
        self.assertContains(audio_page, 'https://cdn.example.test/audio/only.mp3')
        self.assertContains(audio_page, '<audio', html=False)
        self.assertNotContains(audio_page, 'data-speak=')

        script_only = self._make_extra_listening(
            'Script only', audio_script='SCRIPT_ONLY_SENTINEL: Please board at gate five.',
        )
        self.client.post(reverse('learning:practice', args=[script_only.pk]))
        script_attempt = PracticeAttempt.objects.get(user=self.learner, content=script_only)
        script_page = self.client.get(reverse('learning:take_attempt', args=[script_attempt.pk]))
        self.assertNotContains(script_page, '<audio', html=False)
        self.assertContains(script_page, 'SCRIPT_ONLY_SENTINEL')
        self.assertContains(script_page, 'data-speak=')
        self.assertContains(script_page, 'Bản chép lời hỗ trợ luyện tập')

    def test_shared_stimulus_renders_one_player_per_adjacent_question_group_before_and_after_submit(self):
        grouped = LearningContent.objects.create(
            title='Shared listening stimulus', exam_type='TOEIC', content_type='listening', skill='listening',
            review_status='teacher_approved', is_published=True,
        )
        questions = []
        for order, (prompt, passage, audio_url, script) in enumerate((
            ('Question one?', 'Shared passage', 'https://cdn.example.test/audio/shared.mp3', 'Shared script one.'),
            ('Question two?', 'Shared passage', 'https://cdn.example.test/audio/shared.mp3', 'Shared script one.'),
            ('Question three?', 'Different passage', 'https://cdn.example.test/audio/different.mp3', 'Different script.'),
        ), start=1):
            question = Question.objects.create(
                content=grouped, order=order, prompt=prompt, passage=passage,
                audio_url=audio_url, audio_script=script, transcript=script,
                explanation='Explanation.',
            )
            correct = AnswerOption.objects.create(question=question, label='A', text='Correct', is_correct=True)
            AnswerOption.objects.create(question=question, label='B', text='Incorrect', is_correct=False)
            questions.append((question, correct))

        self.client.post(reverse('learning:practice', args=[grouped.pk]))
        grouped_attempt = PracticeAttempt.objects.get(user=self.learner, content=grouped)
        practice_page = self.client.get(reverse('learning:take_attempt', args=[grouped_attempt.pk]))
        self.assertEqual(practice_page.status_code, 200)
        self.assertEqual(practice_page.content.count(b'data-listening-player'), 2)

        # Simulate persisted answers returned in a different insertion order.
        # Result grouping must follow question order, not database default order.
        grouped_attempt.status = 'submitted'
        grouped_attempt.correct_count = 3
        grouped_attempt.submitted_at = timezone.now()
        grouped_attempt.save(update_fields=['status', 'correct_count', 'submitted_at'])
        for question, correct in (questions[1], questions[2], questions[0]):
            AttemptAnswer.objects.create(
                attempt=grouped_attempt, question=question,
                selected_option=correct, is_correct=True,
            )
        result_page = self.client.get(reverse('learning:attempt_result', args=[grouped_attempt.pk]))
        self.assertEqual(result_page.status_code, 200)
        self.assertEqual(result_page.content.count(b'data-listening-player'), 2)

    def _make_extra_listening(self, title, *, audio_url='', audio_script=''):
        content = LearningContent.objects.create(
            title=title, exam_type='TOEIC', content_type='listening', skill='listening',
            review_status='teacher_approved', is_published=True,
        )
        question = Question.objects.create(
            content=content, order=1, prompt='Which gate?', audio_url=audio_url,
            audio_script=audio_script, transcript=audio_script or 'A separate transcript.',
            explanation='The gate is stated in the announcement.',
        )
        AnswerOption.objects.create(question=question, label='A', text='Gate five', is_correct=True)
        AnswerOption.objects.create(question=question, label='B', text='Gate six', is_correct=False)
        return content

    def test_attempt_pages_and_mutations_are_private_to_owner(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('learning:take_attempt', args=[self.attempt.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('learning:attempt_result', args=[self.attempt.pk])).status_code, 404)
        draft_response = self.client.post(
            reverse('learning:save_draft', args=[self.attempt.pk]),
            data=json.dumps({'answers': {str(self.question.pk): self.correct.pk}}),
            content_type='application/json',
        )
        self.assertEqual(draft_response.status_code, 404)
        submit_response = self.client.post(
            reverse('learning:submit_attempt', args=[self.attempt.pk]),
            {f'question_{self.question.pk}': str(self.correct.pk)},
        )
        self.assertEqual(submit_response.status_code, 404)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'in_progress')
        self.assertFalse(AttemptAnswer.objects.filter(attempt=self.attempt).exists())

    def test_submit_is_post_only_and_idempotent_after_submission(self):
        get_response = self.client.get(reverse('learning:submit_attempt', args=[self.attempt.pk]))
        self.assertEqual(get_response.status_code, 400)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'in_progress')
        self.assertFalse(AttemptAnswer.objects.filter(attempt=self.attempt).exists())

        submitted = self.client.post(
            reverse('learning:submit_attempt', args=[self.attempt.pk]),
            {f'question_{self.question.pk}': str(self.correct.pk)},
        )
        self.assertRedirects(submitted, reverse('learning:attempt_result', args=[self.attempt.pk]))
        answer_count = AttemptAnswer.objects.filter(attempt=self.attempt).count()
        self.assertEqual(self.client.get(reverse('learning:take_attempt', args=[self.attempt.pk])).status_code, 404)
        again = self.client.post(reverse('learning:submit_attempt', args=[self.attempt.pk]), {})
        self.assertRedirects(again, reverse('learning:attempt_result', args=[self.attempt.pk]))
        self.assertEqual(AttemptAnswer.objects.filter(attempt=self.attempt).count(), answer_count)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'submitted')
        self.assertIsNotNone(self.attempt.submitted_at)

    def test_anonymous_learner_is_redirected_before_reading_or_submitting_attempt(self):
        self.client.logout()
        read_response = self.client.get(reverse('learning:take_attempt', args=[self.attempt.pk]))
        submit_response = self.client.post(reverse('learning:submit_attempt', args=[self.attempt.pk]), {})
        self.assertEqual(read_response.status_code, 302)
        self.assertEqual(submit_response.status_code, 302)
        self.assertIn(reverse('login'), read_response.url)
        self.assertIn(reverse('login'), submit_response.url)

