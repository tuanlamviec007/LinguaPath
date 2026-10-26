from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Flashcard, FlashcardReview, LearningContent, VocabularyQuizDailyReward, VocabularyQuizSession


class VocabularyQuizDraftTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='draft-quiz-owner')
        cls.other = get_user_model().objects.create_user(username='draft-quiz-other')
        cls.content = LearningContent.objects.create(title='Draft quiz words', content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
        for index in range(8):
            Flashcard.objects.create(content=cls.content, term=f'term{index}', meaning_vi=f'nghĩa {index}', example_en=f'Sentence {index}', example_vi=f'Bản dịch {index}')

    def setUp(self):
        self.client.force_login(self.user)
        self.client.post(reverse('learning:quiz_start'), {'count': '5'})
        self.quiz = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.url = reverse('learning:quiz_draft', args=[self.quiz.pk])

    def save(self, revision=0, **answers):
        return self.client.post(self.url, {'revision': str(revision)} | answers)

    def final_answers(self):
        return {f'answer_{q["number"]}': q['correct_key'] for q in self.quiz.snapshot}

    def test_save_restore_and_hub_saved_count_without_grading_or_xp(self):
        response = self.save(answer_1='A', answer_3='C')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['revision'], 1)
        self.assertEqual(response.json()['saved_count'], 2)
        self.assertEqual(response.json()['status'], 'saved')
        self.assertIsNotNone(response.json()['last_saved_at'])
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.draft_answers, {'1': 'A', '3': 'C'})
        self.assertEqual(self.quiz.answers, {})
        self.assertEqual(self.quiz.correct_count, 0)
        self.assertEqual(self.quiz.xp_earned, 0)
        self.assertEqual(self.quiz.status, 'in_progress')
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())
        self.assertFalse(FlashcardReview.objects.exists())
        play = self.client.get(reverse('learning:quiz_take', args=[self.quiz.pk]))
        self.assertEqual(play.context['questions'][0]['selected_key'], 'A')
        self.assertEqual(play.context['questions'][2]['selected_key'], 'C')
        self.assertEqual(play.context['quiz']['draft_revision'], 1)
        self.assertNotIn('correct_key', play.context['questions'][0])
        self.assertNotIn('meaning_vi', play.context['questions'][0])
        self.assertFalse(play.context['quiz_has_unsaved'])
        hub = self.client.get(reverse('learning:quiz_hub'))
        self.assertEqual(hub.context['active_quiz'].saved_count, 2)

    def test_full_snapshot_replaces_previous_choices_and_omissions_clear(self):
        self.save(answer_1='A', answer_2='B')
        response = self.save(revision=1, answer_2='D')
        self.assertEqual(response.json()['revision'], 2)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.draft_answers, {'2': 'D'})
        self.save(revision=2)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.draft_answers, {})
        self.assertEqual(self.quiz.draft_revision, 3)

    def test_noop_does_not_bump_revision_or_saved_timestamp(self):
        first = self.save(answer_1='A').json()
        second = self.save(revision=1, answer_1='A').json()
        self.assertEqual(second['revision'], first['revision'])
        self.assertEqual(second['last_saved_at'], first['last_saved_at'])

    def test_stale_tab_conflicts_without_overwrite_even_identical(self):
        self.save(answer_1='A')
        for answers in ({'answer_1': 'B'}, {'answer_1': 'A'}):
            response = self.save(revision=0, **answers)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['status'], 'conflict')
            self.assertEqual(response.json()['revision'], 1)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.draft_answers, {'1': 'A'})

    def test_invalid_snapshot_and_revision_do_not_mutate(self):
        invalid = [
            {}, {'revision': '-1'}, {'revision': 'x'}, {'revision': '1.0'},
            {'revision': '2147483648'}, {'revision': ['0', '0']},
            {'revision': '0', 'draft_revision': '1'},
            {'revision': '0', 'answer_99': 'A'}, {'revision': '0', 'answer_1': 'Z'},
            {'revision': '0', 'answer_1': ['A', 'B']}, {'revision': '0', 'answer_1': ''},
        ]
        for payload in invalid:
            response = self.client.post(self.url, payload)
            self.assertEqual(response.status_code, 400, payload)
            self.assertEqual(response.json()['status'], 'invalid')
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.draft_revision, 0)
        self.assertEqual(self.quiz.draft_answers, {})

    def test_owner_auth_and_post_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.force_login(self.other)
        self.assertEqual(self.save().status_code, 404)
        self.client.logout()
        self.assertEqual(self.save().status_code, 302)

    def test_save_after_submit_does_not_modify_answers_or_draft(self):
        self.save(answer_1='A')
        self.client.post(reverse('learning:quiz_submit', args=[self.quiz.pk]), self.final_answers() | {'draft_revision': '1'})
        self.quiz.refresh_from_db()
        final = self.quiz.answers.copy()
        response = self.save(revision=1, answer_1='D')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['status'], 'submitted')
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.answers, final)
        self.assertEqual(self.quiz.draft_answers, {'1': 'A'})
        self.assertEqual(self.quiz.draft_revision, 1)

    def test_abandoned_and_expired_quizzes_reject_drafts(self):
        VocabularyQuizSession.objects.filter(pk=self.quiz.pk).update(started_at=timezone.now() - timedelta(days=2))
        response = self.save(answer_1='A')
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()['status'], 'unavailable')
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.status, 'abandoned')
        self.assertEqual(self.quiz.draft_revision, 0)

    def test_unpublished_or_moved_exam_sources_reject_drafts(self):
        self.content.exam_type = 'IELTS'
        self.content.save(update_fields=['exam_type'])
        self.assertEqual(self.save(answer_1='A').status_code, 410)
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())

    def test_stale_final_submit_restores_posted_choices_with_conflict_lock(self):
        self.save(answer_1='A')
        posted = self.final_answers() | {'draft_revision': '0'}
        response = self.client.post(reverse('learning:quiz_submit', args=[self.quiz.pk]), posted)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.context['quiz_conflict'])
        self.assertEqual(response.context['quiz']['draft_revision'], 1)
        self.assertEqual(response.context['questions'][0]['selected_key'], posted['answer_1'])
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.status, 'in_progress')
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())

    def test_invalid_final_retains_valid_posted_choices_as_unsaved(self):
        response = self.client.post(reverse('learning:quiz_submit', args=[self.quiz.pk]), {'draft_revision': '0', 'answer_1': 'B'})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.context['quiz_has_unsaved'])
        self.assertFalse(response.context['quiz_conflict'])
        self.assertEqual(response.context['questions'][0]['selected_key'], 'B')

    def test_corrupt_stored_draft_never_escapes_allowlist(self):
        VocabularyQuizSession.objects.filter(pk=self.quiz.pk).update(draft_answers={'1': 'correct_key', '2': 'B', '999': 'A'})
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.saved_count, 1)
        play = self.client.get(reverse('learning:quiz_take', args=[self.quiz.pk]))
        self.assertEqual(play.context['questions'][0]['selected_key'], '')
        self.assertEqual(play.context['questions'][1]['selected_key'], 'B')
