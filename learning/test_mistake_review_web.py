from datetime import timedelta
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile, StudyTask
from .activity import build_activity_summary
from .models import (
    AnswerOption, AttemptAnswer, ErrorNotebookEntry, LearningContent,
    MistakeReviewAnswer, MistakeReviewSession, PracticeAttempt, Question,
)


class MistakeReviewWebTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='retry-web')
        self.profile = LearnerProfile.objects.create(user=self.user, onboarding_complete=True)
        self.content = LearningContent.objects.create(
            title='Original notices', exam_type='TOEIC', content_type='reading', skill='reading',
            is_published=True, review_status='language_checked',
        )
        self.q1, self.right1, self.wrong1 = self.make_question('What day is delivery?', 1)
        self.q2, self.right2, self.wrong2 = self.make_question('Where is reception?', 2)
        self.e1 = self.make_error(self.q1, self.wrong1)
        self.e2 = self.make_error(self.q2, self.wrong2)
        self.client.force_login(self.user)

    def make_question(self, prompt, order):
        question = Question.objects.create(
            content=self.content, prompt=prompt, order=order, passage='VISIBLE_RETRY_PASSAGE',
            explanation='SECRET_EXPLANATION', explanation_vi='SECRET_EXPLANATION_VI',
            transcript='SECRET_TRANSCRIPT', audio_script='SECRET_AUDIO_SCRIPT',
        )
        right = AnswerOption.objects.create(question=question, label='A', text='First option', is_correct=True, explanation_vi='SECRET_OPTION_REASON')
        wrong = AnswerOption.objects.create(question=question, label='B', text='Second option', is_correct=False)
        return question, right, wrong

    def make_error(self, question, selected_option, content=None):
        attempt = PracticeAttempt.objects.create(
            user=self.user, content=content or self.content, status='submitted',
            question_ids=[question.id], question_count=1, submitted_at=timezone.now() - timedelta(days=1),
        )
        answer = AttemptAnswer.objects.create(attempt=attempt, question=question, selected_option=selected_option, is_correct=False)
        return ErrorNotebookEntry.objects.create(answer=answer)

    def start(self, category=''):
        response = self.client.post(reverse('learning:start_mistake_review'), {'category': category})
        self.assertEqual(response.status_code, 302)
        session = MistakeReviewSession.objects.get(user=self.user, status='in_progress')
        self.assertEqual(urlsplit(response.url).path, reverse('learning:take_mistake_review', args=[session.pk]))
        return session

    def test_start_resume_and_retry_page_never_exposes_explanation_keys_or_scripts(self):
        session = self.start()
        resumed = self.start()
        self.assertEqual(session.pk, resumed.pk)
        self.assertEqual(session.question_count, 2)
        page = self.client.get(reverse('learning:take_mistake_review', args=[session.pk]))
        self.assertContains(page, 'VISIBLE_RETRY_PASSAGE')
        for hidden in ('SECRET_EXPLANATION', 'SECRET_EXPLANATION_VI', 'SECRET_TRANSCRIPT', 'SECRET_AUDIO_SCRIPT', 'SECRET_OPTION_REASON', 'is_correct', 'correct_option_id'):
            self.assertNotContains(page, hidden)
        self.assertEqual(len(page.context['questions']), 2)
        self.assertNotIn('audio_script', page.context['questions'][0])
        self.assertNotIn('transcript', page.context['questions'][0])

    def test_submit_blank_review_updates_sources_once_and_preserves_original_scores(self):
        duplicate = self.make_error(self.q1, self.wrong1)
        task = StudyTask.objects.create(user=self.user, content=self.content, scheduled_for=timezone.localdate(), estimated_minutes=5)
        original_counts = (PracticeAttempt.objects.count(), AttemptAnswer.objects.count())
        session = self.start()
        new_error = self.make_error(self.q1, self.wrong1)  # Created after session: must remain pending.
        stats_before_submit = build_activity_summary(self.user)
        response = self.client.post(reverse('learning:submit_mistake_review', args=[session.pk]), {f'question_{self.q1.pk}': self.right1.pk})
        self.assertRedirects(response, reverse('learning:mistake_review_result', args=[session.pk]))
        for entry in (self.e1, duplicate):
            entry.refresh_from_db()
            self.assertIsNotNone(entry.reviewed_at)
        for entry in (self.e2, new_error):
            entry.refresh_from_db()
            self.assertIsNone(entry.reviewed_at)
        task.refresh_from_db()
        self.assertEqual(task.status, 'todo')
        self.assertEqual(PracticeAttempt.objects.count(), original_counts[0] + 1)
        self.assertEqual(AttemptAnswer.objects.count(), original_counts[1] + 1)
        self.assertTrue(all(attempt.correct_count == 0 for attempt in PracticeAttempt.objects.all()))
        stats_after_submit = build_activity_summary(self.user)
        self.assertEqual(stats_after_submit['skill_rows'], stats_before_submit['skill_rows'])
        self.assertEqual(stats_after_submit['submitted_attempts'], stats_before_submit['submitted_attempts'])
        self.assertEqual(stats_after_submit['review_events'], stats_before_submit['review_events'])
        self.assertEqual(stats_after_submit['mistake_review_events'], stats_before_submit['mistake_review_events'] + 1)
        result = self.client.get(response.url)
        self.assertEqual(result.context['result']['correct_count'], 1)
        self.assertEqual(result.context['result']['blank_count'], 1)
        self.assertContains(result, 'SECRET_EXPLANATION_VI')
        self.assertContains(result, 'SECRET_OPTION_REASON')
        before = MistakeReviewAnswer.objects.count()
        self.client.post(reverse('learning:submit_mistake_review', args=[session.pk]), {})
        self.assertEqual(MistakeReviewAnswer.objects.count(), before)
        self.e2.refresh_from_db()
        self.assertIsNone(self.e2.reviewed_at)

    def test_result_is_not_available_before_submit_and_other_accounts_cannot_access(self):
        session = self.start()
        self.assertEqual(self.client.get(reverse('learning:mistake_review_result', args=[session.pk])).status_code, 404)
        other = get_user_model().objects.create_user(username='retry-other')
        self.client.force_login(other)
        for name in ('take_mistake_review', 'mistake_review_result'):
            self.assertEqual(self.client.get(reverse(f'learning:{name}', args=[session.pk])).status_code, 404)
        for name in ('submit_mistake_review', 'abandon_mistake_review'):
            self.assertEqual(self.client.post(reverse(f'learning:{name}', args=[session.pk]), {}).status_code, 404)

    def test_wrong_option_binding_is_rejected_atomically_and_get_cannot_start_or_submit(self):
        self.assertEqual(self.client.get(reverse('learning:start_mistake_review')).status_code, 405)
        session = self.start()
        response = self.client.post(reverse('learning:submit_mistake_review', args=[session.pk]), {
            f'question_{self.q1.pk}': self.right1.pk, f'question_{self.q2.pk}': self.right1.pk,
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MistakeReviewAnswer.objects.exists())
        self.e1.refresh_from_db()
        self.assertIsNone(self.e1.reviewed_at)
        self.assertEqual(self.client.get(reverse('learning:submit_mistake_review', args=[session.pk])).status_code, 405)

    def test_changed_content_abandons_without_grading_or_reviewing_sources(self):
        session = self.start()
        self.q1.prompt = 'Changed prompt'
        self.q1.save(update_fields=['prompt'])
        response = self.client.post(reverse('learning:submit_mistake_review', args=[session.pk]), {f'question_{self.q1.pk}': self.right1.pk})
        self.assertRedirects(response, reverse('learning:mistake_notebook'))
        session.refresh_from_db()
        self.assertEqual(session.status, 'abandoned')
        self.assertFalse(MistakeReviewAnswer.objects.exists())
        self.e1.refresh_from_db()
        self.assertIsNone(self.e1.reviewed_at)

    def test_notebook_scope_pagination_and_explicit_note_actions(self):
        for _ in range(20):
            self.make_error(self.q1, self.wrong1)
        page = self.client.get(reverse('learning:mistake_notebook'))
        self.assertEqual(len(page.context['entries']), 20)
        self.assertEqual(page.context['total_count'], 22)
        self.assertEqual(page.context['retry_count'], 2)
        page2 = self.client.get(reverse('learning:mistake_notebook'), {'page': 2})
        self.assertEqual(len(page2.context['entries']), 2)
        endpoint = reverse('learning:update_mistake_entry', args=[self.e1.pk])
        self.client.post(endpoint, {'category': 'detail', 'review_action': 'mark_reviewed'})
        self.e1.refresh_from_db()
        saved_time = self.e1.reviewed_at
        self.client.post(endpoint, {'category': 'detail', 'learner_note': 'My note', 'review_action': 'save'})
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.reviewed_at, saved_time)
        self.assertEqual(self.e1.learner_note, 'My note')
        self.client.post(endpoint, {'category': 'detail', 'review_action': 'reopen'})
        self.e1.refresh_from_db()
        self.assertIsNone(self.e1.reviewed_at)

    def test_profile_exam_and_visibility_filter_history_and_session_access(self):
        session = self.start()
        self.content.review_status = 'draft'
        self.content.save(update_fields=['review_status'])
        page = self.client.get(reverse('learning:mistake_notebook'))
        self.assertEqual(page.context['total_count'], 0)
        self.assertEqual(page.context['retry_count'], 0)
        self.content.review_status = 'language_checked'
        self.content.save(update_fields=['review_status'])
        self.profile.exam_goal = 'IELTS'
        self.profile.save(update_fields=['exam_goal'])
        self.assertEqual(self.client.get(reverse('learning:take_mistake_review', args=[session.pk])).status_code, 404)
        page = self.client.get(reverse('learning:mistake_notebook'))
        self.assertEqual(page.context['total_count'], 0)

    def test_empty_invalid_filters_and_oversized_ids_are_handled_without_server_error(self):
        self.assertEqual(self.client.post(reverse('learning:start_mistake_review'), {'category': 'invalid'}).status_code, 400)
        page = self.client.get(reverse('learning:mistake_notebook'), {'state': 'invalid', 'category': 'invalid', 'page': 'bad'})
        self.assertEqual(page.context['state'], 'new')
        self.assertEqual(page.context['category'], '')
        self.assertEqual(self.client.get(reverse('learning:take_mistake_review', args=[10**80])).status_code, 404)
        ErrorNotebookEntry.objects.all().update(reviewed_at=timezone.now())
        self.assertRedirects(self.client.post(reverse('learning:start_mistake_review')), reverse('learning:mistake_notebook'))

    def test_guest_cannot_start_a_review(self):
        self.client.logout()
        self.assertEqual(self.client.post(reverse('learning:start_mistake_review')).status_code, 302)
