from datetime import timedelta
from unittest.mock import patch
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Flashcard, LearningContent, VocabularyQuizDailyReward, VocabularyQuizSession


class VocabularyQuizTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='quiz-owner', password='test-pass')
        cls.other = get_user_model().objects.create_user(username='quiz-other', password='test-pass')
        cls.content = LearningContent.objects.create(title='Quiz words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
        cls.cards = [Flashcard.objects.create(content=cls.content, term=f'word{i}', meaning_vi=f'nghĩa {i}', cefr_level='A2', topic='Business', example_en=f'Example {i} hidden until submission.', example_vi=f'Bản dịch {i}.') for i in range(15)]

    def setUp(self):
        self.client.force_login(self.user)

    def start(self, **data):
        response = self.client.post(reverse('learning:quiz_start'), {'level': 'A2', 'topic': 'Business', 'count': '5'} | data)
        self.assertEqual(response.status_code, 302)
        return VocabularyQuizSession.objects.get(user=self.user, status='in_progress')

    def answers(self, quiz):
        return {f'answer_{q["number"]}': q['correct_key'] for q in quiz.snapshot}

    def test_empty_source_allows_retry_and_explains_server_validation(self):
        page = self.client.get(reverse('learning:quiz_hub'), {'source': 'saved', 'mode': 'recall'})
        self.assertEqual(page.context['available_count'], 0)
        self.assertContains(page, 'trước bộ lọc')
        self.assertNotContains(page, 'class="button primary lp-quiz-start" type="submit" disabled')
        response = self.client.post(reverse('learning:quiz_start'),
                                    {'source': 'saved', 'mode': 'recall', 'count': '5'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Chưa đủ từ có gợi ý rõ')
        self.assertFalse(VocabularyQuizSession.objects.filter(user=self.user).exists())

    def test_authentication_and_post_only_start(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('learning:quiz_hub')).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('learning:quiz_start')).status_code, 405)

    def test_start_honors_filters_and_four_unique_shuffled_options(self):
        quiz = self.start(count='10')
        self.assertEqual(quiz.question_count, 10)
        self.assertEqual(len({q['term'] for q in quiz.snapshot}), 10)
        for question in quiz.snapshot:
            self.assertEqual(question['cefr_level'], 'A2')
            self.assertEqual(len({o['text'].casefold() for o in question['options']}), 4)
            self.assertIn(question['correct_key'], ['A', 'B', 'C', 'D'])

    def test_play_explicitly_excludes_answers_and_examples(self):
        quiz = self.start()
        response = self.client.get(reverse('learning:quiz_take', args=[quiz.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['quiz'], dict)
        self.assertNotIn('snapshot', response.context['quiz'])
        for question in response.context['questions']:
            self.assertNotIn('correct_key', question)
            self.assertNotIn('meaning_vi', question)
            self.assertIn('example_en', question)
            self.assertNotIn('example_vi', question)
        self.assertNotContains(response, 'Bản dịch')
        self.assertEqual(response.headers['Cache-Control'].find('no-store') >= 0, True)

    def test_result_is_not_visible_before_submission(self):
        quiz = self.start()
        response = self.client.get(reverse('learning:quiz_result', args=[quiz.pk]))
        self.assertRedirects(response, reverse('learning:quiz_take', args=[quiz.pk]), fetch_redirect_response=False)

    def test_server_scores_and_repeated_submit_is_idempotent(self):
        quiz = self.start()
        url = reverse('learning:quiz_submit', args=[quiz.pk])
        response = self.client.post(url, self.answers(quiz) | {'correct_count': '999', 'xp_earned': '999'})
        self.assertEqual(response.status_code, 302)
        quiz.refresh_from_db()
        self.assertEqual(quiz.correct_count, 5)
        self.assertEqual(quiz.xp_earned, 30)
        self.assertEqual(quiz.accuracy, 100)
        self.client.post(url, {})
        quiz.refresh_from_db()
        self.assertEqual(quiz.correct_count, 5)
        self.assertEqual(VocabularyQuizDailyReward.objects.filter(user=self.user).count(), 1)
        result = self.client.get(reverse('learning:quiz_result', args=[quiz.pk]))
        self.assertEqual(result.context['results'][0]['correct_text'], quiz.snapshot[0]['meaning_vi'])
        self.assertTrue(result.context['results'][0]['is_correct'])

    def test_wrong_answers_are_not_correct(self):
        quiz = self.start()
        answers = {f'answer_{q["number"]}': next(o['key'] for o in q['options'] if o['key'] != q['correct_key']) for q in quiz.snapshot}
        self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), answers)
        quiz.refresh_from_db()
        self.assertEqual(quiz.correct_count, 0)
        self.assertEqual(quiz.question_count, 5)
        self.assertEqual(quiz.xp_earned, 20)

    def test_second_quiz_same_day_does_not_farm_xp(self):
        first = self.start()
        self.client.post(reverse('learning:quiz_submit', args=[first.pk]), self.answers(first))
        second = self.start()
        self.client.post(reverse('learning:quiz_submit', args=[second.pk]), self.answers(second))
        second.refresh_from_db()
        self.assertEqual(second.xp_earned, 0)
        self.assertEqual(VocabularyQuizDailyReward.objects.get(user=self.user).xp, 30)

    def test_user_cannot_read_submit_or_get_other_users_result(self):
        quiz = self.start()
        self.client.force_login(self.other)
        for route in ('quiz_take', 'quiz_result'):
            self.assertEqual(self.client.get(reverse('learning:' + route, args=[quiz.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), self.answers(quiz)).status_code, 404)
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())

    def test_invalid_option_unknown_question_and_multiple_values_do_not_submit(self):
        quiz = self.start()
        url = reverse('learning:quiz_submit', args=[quiz.pk])
        for answers in ({'answer_1': 'Z'}, {'answer_99': 'A'}, {'answer_1': ['A', 'B']}):
            self.assertEqual(self.client.post(url, answers).status_code, 400)
            quiz.refresh_from_db()
            self.assertEqual(quiz.status, 'in_progress')
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())

    def test_invalid_filters_create_no_quiz(self):
        for data in ({'level': 'C9'}, {'count': '-1'}, {'count': '30000'}, {'topic': 'x' * 81}):
            self.assertEqual(self.client.post(reverse('learning:quiz_start'), data).status_code, 400)
        self.assertFalse(VocabularyQuizSession.objects.exists())

    def test_replace_requires_confirmation_and_starts_selected_new_quiz(self):
        old = self.start()
        old.draft_answers = {'1': old.snapshot[0]['options'][0]['key']}
        old.draft_revision = 1
        old.save(update_fields=['draft_answers', 'draft_revision'])
        params = {'replace_quiz': str(old.pk), 'count': '10', 'level': 'A2', 'topic': 'Business', 'mode': 'meaning'}
        page = self.client.get(reverse('learning:quiz_hub'))
        self.assertContains(page, 'Tạo quiz mới')
        confirmation = self.client.post(reverse('learning:quiz_start'), params)
        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, 'Dừng bài đang làm?')
        old.refresh_from_db()
        self.assertEqual(old.status, 'in_progress')
        response = self.client.post(reverse('learning:quiz_start'), params | {'confirm_replace': 'yes', 'replace_revision': '1'})
        new = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        old.refresh_from_db()
        self.assertEqual(old.status, 'abandoned')
        self.assertEqual(old.draft_revision, 1)
        self.assertNotEqual(new.pk, old.pk)
        self.assertEqual((new.question_count, new.cefr_level, new.topic), (10, 'A2', 'Business'))
        self.assertRedirects(response, reverse('learning:quiz_take', args=[new.pk]), fetch_redirect_response=False)
        repeated = self.client.post(reverse('learning:quiz_start'), params | {'confirm_replace': 'yes', 'replace_revision': '1'})
        self.assertRedirects(repeated, reverse('learning:quiz_hub'), fetch_redirect_response=False)
        self.assertEqual(VocabularyQuizSession.objects.filter(user=self.user, status='in_progress').count(), 1)

    def test_replace_keeps_old_quiz_when_selection_is_empty_or_draft_changed(self):
        old = self.start()
        params = {'replace_quiz': str(old.pk), 'confirm_replace': 'yes', 'replace_revision': '0', 'count': '5'}
        self.client.post(reverse('learning:quiz_start'), params | {'topic': 'Missing topic'})
        old.refresh_from_db()
        self.assertEqual(old.status, 'in_progress')
        old.draft_revision = 1
        old.save(update_fields=['draft_revision'])
        response = self.client.post(reverse('learning:quiz_start'), params)
        self.assertRedirects(response, reverse('learning:quiz_hub'), fetch_redirect_response=False)
        old.refresh_from_db()
        self.assertEqual(old.status, 'in_progress')
        self.assertEqual(VocabularyQuizSession.objects.filter(user=self.user).count(), 1)

    def test_replace_rolls_back_old_quiz_if_new_creation_fails(self):
        old = self.start()
        with patch('learning.quiz_views.VocabularyQuizSession.objects.create', side_effect=IntegrityError('synthetic')):
            response = self.client.post(reverse('learning:quiz_start'), {
                'replace_quiz': str(old.pk), 'confirm_replace': 'yes',
                'replace_revision': '0', 'count': '5',
            })
        old.refresh_from_db()
        self.assertEqual(old.status, 'in_progress')
        self.assertRedirects(response, reverse('learning:quiz_take', args=[old.pk]), fetch_redirect_response=False)

    def test_replace_cannot_target_another_users_quiz(self):
        old = self.start()
        self.client.force_login(self.other)
        response = self.client.post(reverse('learning:quiz_start'), {'replace_quiz': str(old.pk), 'count': '5'})
        self.assertRedirects(response, reverse('learning:quiz_hub'), fetch_redirect_response=False)
        old.refresh_from_db()
        self.assertEqual(old.status, 'in_progress')
        self.assertFalse(VocabularyQuizSession.objects.filter(user=self.other).exists())

    def test_duplicate_start_resumes_existing_session(self):
        first = self.start()
        response = self.client.post(reverse('learning:quiz_start'), {'count': '15'})
        self.assertRedirects(response, reverse('learning:quiz_take', args=[first.pk]), fetch_redirect_response=False)
        self.assertEqual(VocabularyQuizSession.objects.filter(user=self.user).count(), 1)

    def test_less_than_requested_available_reports_actual_count(self):
        Flashcard.objects.filter(content=self.content).exclude(pk__in=[c.pk for c in self.cards[:7]]).delete()
        quiz = self.start(count='15')
        self.assertEqual(quiz.question_count, 7)

    def test_fewer_than_four_distinct_meanings_prevents_quiz(self):
        Flashcard.objects.filter(content=self.content).update(meaning_vi='same meaning')
        response = self.client.post(reverse('learning:quiz_start'), {'count': '5'})
        self.assertRedirects(response, reverse('learning:quiz_hub'), fetch_redirect_response=False)
        self.assertFalse(VocabularyQuizSession.objects.exists())

    def test_unpublished_and_draft_cards_cannot_start_quiz(self):
        self.content.review_status = 'draft'
        self.content.save(update_fields=['review_status'])
        response = self.client.post(reverse('learning:quiz_start'), {'count': '5'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(VocabularyQuizSession.objects.exists())

    def test_unpublishing_content_blocks_grading_and_awards(self):
        quiz = self.start()
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        response = self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), self.answers(quiz))
        self.assertEqual(response.status_code, 410)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, 'abandoned')
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())

    def test_snapshot_is_used_when_source_word_is_edited(self):
        quiz = self.start()
        Flashcard.objects.filter(pk=quiz.snapshot[0]['card_id']).update(meaning_vi='Edited meaning')
        self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), self.answers(quiz))
        result = self.client.get(reverse('learning:quiz_result', args=[quiz.pk]))
        self.assertEqual(result.context['results'][0]['meaning_vi'], quiz.snapshot[0]['meaning_vi'])
        self.assertNotEqual(result.context['results'][0]['meaning_vi'], 'Edited meaning')

    def test_expired_quiz_does_not_award_points(self):
        quiz = self.start()
        VocabularyQuizSession.objects.filter(pk=quiz.pk).update(started_at=timezone.now() - timedelta(days=2))
        response = self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), self.answers(quiz))
        self.assertEqual(response.status_code, 410)
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())

    def test_equivalent_meanings_for_same_term_never_become_distractors(self):
        Flashcard.objects.create(content=self.content, term='word0', meaning_vi='cách diễn đạt tương đương', cefr_level='A2', topic='Business')
        quiz = self.start(count='15')
        for q in quiz.snapshot:
            if q['term'] == 'word0':
                texts = [o['text'] for o in q['options']]
                self.assertEqual(sum(text in texts for text in ('nghĩa 0', 'cách diễn đạt tương đương')), 1)

    def test_substring_synonym_meanings_are_excluded(self):
        from .quiz_views import _too_similar
        self.assertTrue(_too_similar('mua', 'mua hàng'))
        self.assertTrue(_too_similar('sửa chữa', 'sửa chữa thứ bị hỏng'))
        self.assertFalse(_too_similar('hóa đơn', 'đi du lịch'))

    def test_missing_answer_does_not_award_and_restores_selections(self):
        quiz = self.start()
        answers = self.answers(quiz)
        answers.pop('answer_5')
        response = self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), answers)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.context['quiz_error'])
        self.assertEqual(response.context['questions'][0]['selected_key'], answers['answer_1'])
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, 'in_progress')
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())

    def test_abandon_is_user_owned_post_only_and_allows_new_quiz(self):
        quiz = self.start()
        url = reverse('learning:quiz_abandon', args=[quiz.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url).status_code, 302)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, 'abandoned')
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())
        next_quiz = self.start()
        self.assertNotEqual(quiz.pk, next_quiz.pk)

    def test_abandon_submitted_quiz_does_not_delete_result_or_reward(self):
        quiz = self.start()
        self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), self.answers(quiz))
        self.client.post(reverse('learning:quiz_abandon', args=[quiz.pk]))
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, 'submitted')
        self.assertEqual(quiz.xp_earned, 30)
        self.assertEqual(VocabularyQuizDailyReward.objects.filter(user=self.user).count(), 1)

    def test_filter_with_fewer_than_five_valid_cards_creates_no_session(self):
        Flashcard.objects.filter(content=self.content).exclude(pk__in=[c.pk for c in self.cards[:4]]).delete()
        response = self.client.post(reverse('learning:quiz_start'), {'count': '5'})
        self.assertRedirects(response, reverse('learning:quiz_hub'), fetch_redirect_response=False)
        self.assertFalse(VocabularyQuizSession.objects.exists())
