from copy import deepcopy
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Flashcard, LearningContent, VocabularyQuizDailyReward, VocabularyQuizSession
from .quiz_views import active_quiz_for_user


class VocabularyQuizRetryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='retry-quiz-owner')
        cls.other = get_user_model().objects.create_user(username='retry-quiz-other')
        cls.content = LearningContent.objects.create(title='Retry words', content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
        for index in range(8):
            Flashcard.objects.create(content=cls.content, term=f'word{index}', meaning_vi=f'nghĩa {index}', example_en=f'Example {index}')

    def setUp(self):
        self.client.force_login(self.user)
        self.client.post(reverse('learning:quiz_start'), {'count': '5'})
        self.parent = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')

    def submit_parent(self, wrong_count=2):
        answers = {}
        for index, question in enumerate(self.parent.snapshot):
            answers[f'answer_{question["number"]}'] = next(o['key'] for o in question['options'] if o['key'] != question['correct_key']) if index < wrong_count else question['correct_key']
        self.client.post(reverse('learning:quiz_submit', args=[self.parent.pk]), answers)
        self.parent.refresh_from_db()

    def start_retry(self):
        response = self.client.post(reverse('learning:quiz_retry', args=[self.parent.pk]))
        self.assertEqual(response.status_code, 302)
        return VocabularyQuizSession.objects.get(user=self.user, status='in_progress')

    def test_retry_only_contains_missed_words_with_immutable_parent_snapshot(self):
        self.submit_parent(2)
        before = deepcopy(self.parent.snapshot)
        first_card = self.parent.snapshot[0]['card_id']
        Flashcard.objects.filter(pk=first_card).update(term='Edited source', meaning_vi='Edited meaning')
        retry = self.start_retry()
        self.assertEqual(retry.parent_quiz_id, self.parent.pk)
        self.assertTrue(retry.is_retry)
        self.assertEqual(retry.question_count, 2)
        self.assertEqual({q['card_id'] for q in retry.snapshot}, {q['card_id'] for q in before[:2]})
        for index, q in enumerate(retry.snapshot):
            self.assertEqual(q['number'], index + 1)
            original = before[index]
            self.assertEqual(q['term'], original['term'])
            self.assertEqual(q['meaning_vi'], original['meaning_vi'])
            self.assertCountEqual([o['text'] for o in q['options']], [o['text'] for o in original['options']])
            self.assertNotEqual([o['text'] for o in q['options']], [o['text'] for o in original['options']])
            self.assertEqual(next(o['text'] for o in q['options'] if o['key'] == q['correct_key']), original['meaning_vi'])
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.snapshot, before)

    def test_one_wrong_word_can_be_retried_without_normal_five_minimum(self):
        self.submit_parent(1)
        retry = self.start_retry()
        self.assertEqual(retry.question_count, 1)
        play = self.client.get(reverse('learning:quiz_take', args=[retry.pk]))
        self.assertTrue(play.context['quiz']['is_retry'])
        self.assertNotIn('correct_key', play.context['questions'][0])

    def test_retry_no_xp_and_does_not_consume_today_normal_quiz_reward(self):
        self.submit_parent(1)
        yesterday = timezone.localdate() - timedelta(days=1)
        VocabularyQuizDailyReward.objects.filter(quiz=self.parent).update(day=yesterday)
        VocabularyQuizSession.objects.filter(pk=self.parent.pk).update(submitted_at=timezone.now() - timedelta(days=1))
        retry = self.start_retry()
        answers = {f'answer_{q["number"]}': q['correct_key'] for q in retry.snapshot}
        self.client.post(reverse('learning:quiz_submit', args=[retry.pk]), answers)
        retry.refresh_from_db()
        self.assertEqual(retry.xp_earned, 0)
        self.assertFalse(VocabularyQuizDailyReward.objects.filter(user=self.user, day=timezone.localdate()).exists())
        self.client.post(reverse('learning:quiz_start'), {'count': '5'})
        normal = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.client.post(reverse('learning:quiz_submit', args=[normal.pk]), {f'answer_{q["number"]}': q['correct_key'] for q in normal.snapshot})
        normal.refresh_from_db()
        self.assertEqual(normal.xp_earned, 30)

    def test_hidden_or_wrong_exam_sources_are_omitted(self):
        self.submit_parent(2)
        hidden = LearningContent.objects.create(title='Hidden words', exam_type='IELTS', content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
        Flashcard.objects.filter(pk=self.parent.snapshot[0]['card_id']).update(content=hidden)
        retry = self.start_retry()
        self.assertEqual(retry.question_count, 1)
        self.assertEqual(retry.snapshot[0]['card_id'], self.parent.snapshot[1]['card_id'])

    def test_all_hidden_sources_or_all_correct_return_to_parent_result(self):
        self.submit_parent(2)
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        response = self.client.post(reverse('learning:quiz_retry', args=[self.parent.pk]))
        self.assertRedirects(response, reverse('learning:quiz_result', args=[self.parent.pk]), fetch_redirect_response=False)
        self.assertEqual(VocabularyQuizSession.objects.filter(user=self.user).count(), 1)

    def test_all_correct_has_no_retry_and_result_reports_counts(self):
        self.submit_parent(0)
        response = self.client.post(reverse('learning:quiz_retry', args=[self.parent.pk]))
        self.assertRedirects(response, reverse('learning:quiz_result', args=[self.parent.pk]), fetch_redirect_response=False)
        result = self.client.get(reverse('learning:quiz_result', args=[self.parent.pk]))
        self.assertEqual(result.context['missed_count'], 0)
        self.assertEqual(result.context['retry_available_count'], 0)
        self.assertEqual(VocabularyQuizSession.objects.filter(user=self.user).count(), 1)

    def test_retry_owner_post_only_and_submitted_parent_required(self):
        url = reverse('learning:quiz_retry', args=[self.parent.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        self.assertRedirects(response, reverse('learning:quiz_take', args=[self.parent.pk]), fetch_redirect_response=False)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.post(url).status_code, 302)

    def test_repeated_retry_start_resumes_one_active_and_preserves_draft(self):
        self.submit_parent(2)
        first = self.start_retry()
        self.client.post(reverse('learning:quiz_draft', args=[first.pk]), {'revision': '0', 'answer_1': 'A'})
        second = self.start_retry()
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.draft_answers, {'1': 'A'})
        self.assertEqual(VocabularyQuizSession.objects.filter(parent_quiz=self.parent).count(), 1)

    def test_result_reports_parent_and_missed_words(self):
        self.submit_parent(2)
        result = self.client.get(reverse('learning:quiz_result', args=[self.parent.pk]))
        self.assertEqual(result.context['missed_count'], 2)
        self.assertEqual(result.context['retry_available_count'], 2)
        retry = self.start_retry()
        self.client.post(reverse('learning:quiz_submit', args=[retry.pk]), {f'answer_{q["number"]}': q['correct_key'] for q in retry.snapshot})
        result = self.client.get(reverse('learning:quiz_result', args=[retry.pk]))
        self.assertEqual(result.context['original_parent'], self.parent)

    def test_retry_remains_zero_xp_even_if_parent_record_is_removed(self):
        self.submit_parent(1)
        retry = self.start_retry()
        self.parent.delete()
        retry.refresh_from_db()
        self.assertIsNone(retry.parent_quiz_id)
        self.assertTrue(retry.is_retry)
        self.client.post(reverse('learning:quiz_submit', args=[retry.pk]), {f'answer_{q["number"]}': q['correct_key'] for q in retry.snapshot})
        retry.refresh_from_db()
        self.assertEqual(retry.xp_earned, 0)
        self.assertFalse(VocabularyQuizDailyReward.objects.filter(user=self.user).exists())

    def test_active_helper_respects_exam_and_expires_unavailable(self):
        self.assertEqual(active_quiz_for_user(self.user).pk, self.parent.pk)
        self.assertIsNone(active_quiz_for_user(self.user, exam_type='IELTS'))
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        self.assertIsNone(active_quiz_for_user(self.user))
