"""Typed vocabulary recall journeys, including drafts and existing quiz evidence."""
from copy import deepcopy
from datetime import timedelta
from urllib.parse import parse_qs

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .models import (
    Flashcard, FlashcardReview, LearningContent, SavedWord, UserFlashcardState,
    VocabularyQuizDailyReward, VocabularyQuizSession,
)
from .quiz_weak_words import weak_word_summary


class TypedRecallQuizJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='recall-owner')
        cls.other = get_user_model().objects.create_user(username='recall-other')
        for user in (cls.user, cls.other):
            LearnerProfile.objects.create(user=user, exam_goal='TOEIC', onboarding_complete=True)
        cls.content = LearningContent.objects.create(
            title='Recall vocabulary', content_type='vocabulary', skill='vocabulary',
            exam_type='TOEIC', is_published=True, review_status='teacher_approved',
        )
        words = [
            ('umbrella', 'ô dù'), ('baggage', 'hành lý'), ('printer', 'máy in'),
            ('currency', 'tiền tệ'), ('passenger', 'hành khách'),
            ('meet a deadline', 'đáp ứng đúng thời hạn'),
            ("manager's agenda", 'chương trình họp của người quản lý'),
            ('carry-on', 'hành lý xách tay'), ('applicant', 'người ứng tuyển'),
            ('warehouse', 'nhà kho'), ('invoice', 'hóa đơn'),
            ('shipment', 'lô hàng'), ('negotiate', 'thương lượng'),
            ('coordinate', 'phối hợp'), ('reimbursement', 'khoản hoàn trả'),
        ]
        cls.cards = [Flashcard.objects.create(
            content=cls.content, term=term, meaning_vi=meaning, cefr_level='B1',
            topic='Office', part_of_speech='noun',
            example_en=f'An example containing {term}.', example_vi=f'Bản dịch của {term}.',
        ) for term, meaning in words]

    def setUp(self):
        self.client.force_login(self.user)

    def start(self, **filters):
        response = self.client.post(reverse('learning:quiz_start'), {'count':'5', 'mode':'recall', **filters})
        self.assertEqual(response.status_code, 302)
        quiz = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertRedirects(response, reverse('learning:quiz_take', args=[quiz.pk]), fetch_redirect_response=False)
        return quiz

    def answers(self, quiz):
        return {f'answer_{q["number"]}':q['term'] for q in quiz.snapshot}

    def submit(self, quiz, answers=None, **extra):
        response = self.client.post(
            reverse('learning:quiz_submit', args=[quiz.pk]),
            {**(self.answers(quiz) if answers is None else answers), **extra},
        )
        self.assertRedirects(response, reverse('learning:quiz_result', args=[quiz.pk]), fetch_redirect_response=False)
        quiz.refresh_from_db()
        return response

    def test_default_quizzes_remain_multiple_choice_and_unknown_modes_are_rejected(self):
        legacy = VocabularyQuizSession.objects.create(user=self.other, question_count=1)
        self.assertEqual(legacy.mode, 'meaning')
        for mode in ('other', '', ['recall', 'meaning']):
            response = self.client.post(reverse('learning:quiz_start'), {'count':'5', 'mode':mode})
            self.assertEqual(response.status_code, 400)
        response = self.client.post(reverse('learning:quiz_start'), {'count':'5'})
        self.assertEqual(response.status_code, 302)
        quiz = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertEqual(quiz.mode, 'meaning')
        self.assertTrue(all(len(q['options']) == 4 for q in quiz.snapshot))

    def test_recall_does_not_require_four_distractor_meanings(self):
        for index in range(5):
            Flashcard.objects.create(content=self.content, term=f'{chr(97 + index)}compoundword', meaning_vi='một nghĩa chung', topic='Small bank', cefr_level='B2')
        quiz = self.start(topic='Small bank', level='B2')
        self.assertEqual((quiz.mode, quiz.question_count), ('recall', 5))
        self.assertEqual({q['meaning_vi'] for q in quiz.snapshot}, {'một nghĩa chung'})

    def test_play_contains_prompt_and_hint_but_no_target_or_answer_bearing_examples(self):
        quiz = self.start()
        response = self.client.get(reverse('learning:quiz_take', args=[quiz.pk]))
        self.assertEqual(response.context['quiz']['mode'], 'recall')
        self.assertNotIn('snapshot', response.context['quiz'])
        for original, safe in zip(quiz.snapshot, response.context['questions']):
            self.assertEqual(safe['meaning_vi'], original['meaning_vi'])
            self.assertIn('recall_hint', safe)
            self.assertEqual(safe['selected_answer'], '')
            for key in ('term', 'correct_key', 'options', 'example_en', 'example_vi'):
                self.assertNotIn(key, safe)
            self.assertNotContains(response, original['term'])
            self.assertNotContains(response, original['example_en'])
        self.assertContains(response, 'data-quiz-text-answer')
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_server_accepts_case_whitespace_unicode_and_curly_apostrophe_equivalents(self):
        quiz = self.start(count='15')
        answers = {}
        for q in quiz.snapshot:
            typed = '  ' + q['term'].upper().replace(' ', '   ').replace("'", '’') + '  '
            if q['term'] == 'printer':
                typed = 'ＰＲＩＮＴＥＲ'
            answers[f'answer_{q["number"]}'] = typed
        self.submit(quiz, answers, mode='meaning', correct_count='999', xp_earned='999')
        self.assertEqual((quiz.mode, quiz.correct_count, quiz.xp_earned), ('recall', 15, 50))
        before = deepcopy(quiz.answers)
        self.submit(quiz, {f'answer_{q["number"]}':'changed' for q in quiz.snapshot})
        self.assertEqual(quiz.answers, before)
        self.assertEqual(VocabularyQuizDailyReward.objects.filter(user=self.user).count(), 1)

    def test_grading_does_not_accept_typos_synonyms_inflections_or_removed_punctuation(self):
        quiz = self.start(count='15')
        variants = {'umbrella':'parasol', 'printer':'printers', 'carry-on':'carry on', "manager's agenda":'managers agenda'}
        answers = {f'answer_{q["number"]}':variants.get(q['term'], q['term'] + 'x') for q in quiz.snapshot}
        self.submit(quiz, answers)
        self.assertEqual(quiz.correct_count, 0)
        self.assertEqual(weak_word_summary(self.user)['count'], 15)
        result = self.client.get(reverse('learning:quiz_result', args=[quiz.pk]))
        self.assertTrue(all(not item['is_correct'] for item in result.context['results']))
        for item in result.context['results']:
            self.assertEqual(item['correct_text'], item['term'])

    def test_invalid_missing_duplicate_foreign_and_oversized_submission_never_grades(self):
        quiz = self.start()
        valid = self.answers(quiz)
        invalid_payloads = [
            {}, {**valid, 'answer_1':''}, {**valid, 'answer_1':'   '},
            {**valid, 'answer_1':['a','b']}, {**valid, 'answer_1':'x'*241},
            {**valid, 'answer_999':'extra'},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), payload)
                self.assertEqual(response.status_code, 400)
        quiz.refresh_from_db()
        self.assertEqual((quiz.status, quiz.correct_count, quiz.answers), ('in_progress', 0, {}))
        self.assertFalse(VocabularyQuizDailyReward.objects.filter(user=self.user).exists())

    def test_raw_draft_restores_own_text_without_scoring_and_counts_nonblank_answers(self):
        quiz = self.start()
        raw = '  My   Answer  '
        response = self.client.post(reverse('learning:quiz_draft', args=[quiz.pk]), {'revision':'0', 'answer_1':raw})
        self.assertEqual((response.status_code, response.json()['saved_count']), (200, 1))
        quiz.refresh_from_db()
        self.assertEqual(quiz.draft_answers, {'1':raw})
        self.assertEqual((quiz.saved_count, quiz.answers, quiz.correct_count, quiz.xp_earned), (1, {}, 0, 0))
        play = self.client.get(reverse('learning:quiz_take', args=[quiz.pk]))
        self.assertEqual(play.context['questions'][0]['selected_answer'], raw)
        self.assertNotIn('term', play.context['questions'][0])
        self.assertFalse(FlashcardReview.objects.exists())
        self.assertFalse(UserFlashcardState.objects.exists())
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())

    def test_full_draft_snapshot_supports_clearing_omitted_and_blank_text(self):
        quiz = self.start()
        url = reverse('learning:quiz_draft', args=[quiz.pk])
        self.assertEqual(self.client.post(url, {'revision':'0', 'answer_1':'one', 'answer_2':'two'}).status_code, 200)
        second = self.client.post(url, {'revision':'1', 'answer_2':'two'})
        self.assertEqual(second.json()['saved_count'], 1)
        quiz.refresh_from_db()
        self.assertEqual(quiz.draft_answers, {'2':'two'})
        cleared = self.client.post(url, {'revision':'2', 'answer_2':'   '})
        self.assertEqual((cleared.status_code, cleared.json()['saved_count']), (200, 0))
        quiz.refresh_from_db()
        self.assertEqual((quiz.draft_answers, quiz.saved_count), ({}, 0))
        noop = self.client.post(url, {'revision':'3'})
        self.assertEqual(noop.json()['revision'], 3)

    def test_invalid_drafts_and_stale_tab_leave_confirmed_text_untouched(self):
        quiz = self.start()
        url = reverse('learning:quiz_draft', args=[quiz.pk])
        self.client.post(url, {'revision':'0', 'answer_1':'confirmed'})
        for payload in ({'revision':'1','answer_1':['a','b']}, {'revision':'1','answer_1':'x'*241}, {'revision':'1','answer_90':'x'}):
            self.assertEqual(self.client.post(url, payload).status_code, 400)
        self.assertEqual(self.client.post(url, {'revision':'0','answer_1':'old tab'}).status_code, 409)
        posted = self.answers(quiz)
        response = self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), {**posted, 'draft_revision':'0'})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.context['quiz_conflict'])
        self.assertEqual(response.context['questions'][0]['selected_answer'], posted['answer_1'])
        quiz.refresh_from_db()
        self.assertEqual((quiz.draft_answers, quiz.draft_revision, quiz.status), ({'1':'confirmed'}, 1, 'in_progress'))

    def test_corrupt_draft_values_do_not_reach_play_context_or_saved_count(self):
        quiz = self.start()
        VocabularyQuizSession.objects.filter(pk=quiz.pk).update(draft_answers={'1':{'term':'hidden'}, '2':'x'*241, '3':'valid text', '999':'outside'})
        quiz.refresh_from_db()
        self.assertEqual(quiz.saved_count, 1)
        questions = self.client.get(reverse('learning:quiz_take', args=[quiz.pk])).context['questions']
        self.assertEqual([q['selected_answer'] for q in questions], ['', '', 'valid text', '', ''])

    def test_auth_csrf_ownership_and_source_publication_rules_still_apply(self):
        quiz = self.start()
        draft_url = reverse('learning:quiz_draft', args=[quiz.pk])
        submit_url = reverse('learning:quiz_submit', args=[quiz.pk])
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.user)
        self.assertEqual(guarded.post(draft_url, {'revision':'0','answer_1':'typed'}).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('learning:quiz_take', args=[quiz.pk])).status_code, 404)
        self.assertEqual(self.client.post(draft_url, {'revision':'0'}).status_code, 404)
        self.assertEqual(self.client.post(submit_url, self.answers(quiz)).status_code, 404)
        self.client.force_login(self.user)
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        self.assertEqual(self.client.post(draft_url, {'revision':'0','answer_1':'typed'}).status_code, 410)
        self.assertFalse(VocabularyQuizDailyReward.objects.exists())

    def test_source_edits_do_not_change_snapshotted_target_or_bookmark_revised_words(self):
        quiz = self.start()
        q = quiz.snapshot[0]
        Flashcard.objects.filter(pk=q['card_id']).update(term='completely revised word', meaning_vi='nghĩa mới')
        self.submit(quiz)
        self.assertEqual(quiz.correct_count, quiz.question_count)
        result = self.client.get(reverse('learning:quiz_result', args=[quiz.pk]))
        row = next(item for item in result.context['results'] if item['card_id'] == q['card_id'])
        self.assertEqual((row['term'], row['correct_text'], row['is_correct'], row['can_save']), (q['term'], q['term'], True, False))

    def test_retry_preserves_recall_mode_only_missed_terms_and_zero_xp(self):
        parent = self.start()
        answers = self.answers(parent)
        for q in parent.snapshot[:2]:
            answers[f'answer_{q["number"]}'] = 'incorrect term'
        self.submit(parent, answers)
        before = deepcopy(parent.snapshot)
        yesterday = timezone.localdate() - timedelta(days=1)
        VocabularyQuizDailyReward.objects.filter(quiz=parent).update(day=yesterday)
        VocabularyQuizSession.objects.filter(pk=parent.pk).update(submitted_at=timezone.now()-timedelta(days=1))
        response = self.client.post(reverse('learning:quiz_retry', args=[parent.pk]))
        self.assertEqual(response.status_code, 302)
        retry = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertEqual((retry.mode, retry.is_retry, retry.question_count, retry.parent_quiz_id), ('recall', True, 2, parent.pk))
        self.assertEqual({q['card_id'] for q in retry.snapshot}, {q['card_id'] for q in before[:2]})
        self.submit(retry)
        self.assertEqual(retry.xp_earned, 0)
        self.assertFalse(VocabularyQuizDailyReward.objects.filter(user=self.user, day=timezone.localdate()).exists())
        self.assertEqual(weak_word_summary(self.user)['count'], 0)
        parent.refresh_from_db()
        self.assertEqual(parent.snapshot, before)
        new_quiz = self.start()
        self.submit(new_quiz)
        self.assertEqual(new_quiz.xp_earned, 30)

    def test_weak_queue_combines_multiple_choice_and_typed_recall_evidence(self):
        parent = self.start(mode='meaning')
        answers = {f'answer_{q["number"]}':q['correct_key'] for q in parent.snapshot}
        missed = parent.snapshot[0]
        answers['answer_1'] = next(o['key'] for o in missed['options'] if o['key'] != missed['correct_key'])
        self.submit(parent, answers)
        self.assertEqual(weak_word_summary(self.user)['count'], 1)
        recall = self.start(source='weak')
        self.assertEqual((recall.mode, recall.is_retry, recall.question_count), ('recall', True, 1))
        self.assertEqual(recall.snapshot[0]['card_id'], missed['card_id'])
        self.submit(recall)
        self.assertEqual((recall.xp_earned, weak_word_summary(self.user)['count']), (0, 0))
        again = self.start(mode='recall')
        answers = {f'answer_{q["number"]}':'incorrect term' for q in again.snapshot}
        self.submit(again, answers)
        self.assertEqual(weak_word_summary(self.user)['count'], again.question_count)

    def test_saved_recall_questions_use_only_the_owners_visible_collection(self):
        for card in self.cards[:5]:
            SavedWord.objects.create(user=self.user, flashcard=card)
        SavedWord.objects.create(user=self.other, flashcard=self.cards[-1])
        quiz = self.start(source='saved')
        self.assertEqual({q['card_id'] for q in quiz.snapshot}, {card.pk for card in self.cards[:5]})
        self.assertEqual(quiz.mode, 'recall')

    def test_history_mode_filter_separates_attempts_and_survives_pagination(self):
        common = {'user':self.user, 'status':'submitted', 'submitted_at':timezone.now()-timedelta(minutes=1), 'question_count':5, 'correct_count':4}
        for _ in range(21):
            VocabularyQuizSession.objects.create(**common, mode='recall')
        VocabularyQuizSession.objects.create(**common)
        VocabularyQuizSession.objects.create(**{**common,'user':self.other}, mode='recall')
        response = self.client.get(reverse('learning:quiz_history'), {'mode':'recall','period':'all'})
        self.assertEqual((response.context['selected_mode'], response.context['filtered_count']), ('recall', 21))
        self.assertEqual(len(response.context['quizzes']), 20)
        self.assertTrue(all(q.mode == 'recall' for q in response.context['quizzes']))
        self.assertEqual(parse_qs(response.context['pagination_query'])['mode'], ['recall'])
        second = self.client.get(reverse('learning:quiz_history'), {'mode':'recall','period':'all','page':2})
        self.assertEqual(len(second.context['quizzes']), 1)
        old = self.client.get(reverse('learning:quiz_history'), {'mode':'meaning'})
        self.assertEqual(old.context['filtered_count'], 1)
        invalid = self.client.get(reverse('learning:quiz_history'), {'mode':'unknown'})
        self.assertEqual(invalid.context['selected_mode'], '')

    def test_recall_omits_embedded_answers_but_preserves_whole_word_boundaries_and_meaning_mode(self):
        words = [
            ('email', 'gửi EMAIL'), ('piano', 'đàn piano'), ('car', 'xe chuyên chở cargo'),
            ('violet', 'màu tím'), ('ledger', 'sổ cái'), ('frugal', 'tiết kiệm'),
            ('quartz', 'thạch anh'), ('sprout', 'chồi non'),
        ]
        cards = [Flashcard.objects.create(
            content=self.content, term=term, meaning_vi=meaning, topic='Prompt audit', cefr_level='B2',
        ) for term, meaning in words]
        recall = self.start(topic='Prompt audit', count='15')
        terms = {q['term'] for q in recall.snapshot}
        self.assertEqual(recall.question_count, 6)
        self.assertNotIn('email', terms)
        self.assertNotIn('piano', terms)
        self.assertIn('car', terms)
        self.client.post(reverse('learning:quiz_abandon', args=[recall.pk]))
        meaning = self.start(mode='meaning', topic='Prompt audit', count='15')
        self.assertEqual({q['card_id'] for q in meaning.snapshot}, {card.pk for card in cards})

    def test_unsafe_historical_recall_prompts_cannot_be_resumed_or_submitted(self):
        quiz = self.start()
        quiz.snapshot[0]['meaning_vi'] = f"đáp án là {quiz.snapshot[0]['term']}"
        quiz.save(update_fields=['snapshot'])
        response = self.client.get(reverse('learning:quiz_take', args=[quiz.pk]))
        self.assertRedirects(response, reverse('learning:quiz_hub'), fetch_redirect_response=False)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, 'abandoned')

        next_quiz = self.start()
        next_quiz.snapshot[0]['meaning_vi'] = f"đáp án là {next_quiz.snapshot[0]['term']}"
        next_quiz.save(update_fields=['snapshot'])
        response = self.client.post(reverse('learning:quiz_submit', args=[next_quiz.pk]), self.answers(next_quiz))
        self.assertEqual(response.status_code, 410)
        next_quiz.refresh_from_db()
        self.assertEqual((next_quiz.status, next_quiz.correct_count, next_quiz.answers), ('abandoned', 0, {}))
        self.assertFalse(VocabularyQuizDailyReward.objects.filter(user=self.user).exists())

    def test_recall_retries_omit_unsafe_historical_prompts_without_filling_from_the_bank(self):
        parent = self.start()
        self.submit(parent, {f'answer_{q["number"]}':'incorrect term' for q in parent.snapshot})
        unsafe_id = parent.snapshot[0]['card_id']
        parent.snapshot[0]['meaning_vi'] = f"một cách gọi {parent.snapshot[0]['term']}"
        parent.save(update_fields=['snapshot'])
        response = self.client.post(reverse('learning:quiz_retry', args=[parent.pk]))
        self.assertEqual(response.status_code, 302)
        retry = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertEqual((retry.mode, retry.question_count), ('recall', 4))
        self.assertNotIn(unsafe_id, {q['card_id'] for q in retry.snapshot})
        self.client.post(reverse('learning:quiz_abandon', args=[retry.pk]))
        for question in parent.snapshot:
            question['meaning_vi'] = f"một cách gọi {question['term']}"
        parent.save(update_fields=['snapshot'])
        before = VocabularyQuizSession.objects.filter(user=self.user).count()
        response = self.client.post(reverse('learning:quiz_retry', args=[parent.pk]))
        self.assertRedirects(response, reverse('learning:quiz_result', args=[parent.pk]), fetch_redirect_response=False)
        self.assertEqual(VocabularyQuizSession.objects.filter(user=self.user).count(), before)

    def test_malformed_legacy_options_do_not_break_or_clear_valid_recall_mistakes(self):
        quiz = self.start()
        self.submit(quiz, {f'answer_{q["number"]}':'incorrect term' for q in quiz.snapshot})
        question = deepcopy(quiz.snapshot[0])
        question.update(number=1, options=None, correct_key='A')
        VocabularyQuizSession.objects.create(
            user=self.user, mode='meaning', status='submitted', submitted_at=timezone.now(),
            question_count=1, snapshot=[question], answers={'1':'A'},
        )
        self.assertEqual(weak_word_summary(self.user)['count'], quiz.question_count)
        self.assertEqual(self.client.get(reverse('learning:quiz_hub')).status_code, 200)
