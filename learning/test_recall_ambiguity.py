"""Typed prompts must distinguish a single bank lemma before exact-key grading."""
from copy import deepcopy
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .models import Flashcard, LearningContent, SavedWord, VocabularyQuizDailyReward, VocabularyQuizSession
from .quiz_answers import quiz_answer_is_correct, recall_prompt_signature
from .quiz_recall import RecallPromptIndex
from .quiz_views import _available, _retry_candidates
from .quiz_weak_words import weak_word_summary


class RecallPromptSignatureTests(SimpleTestCase):
    def card(self, term, meaning='khách hàng', pos='noun', **extra):
        return {'term': term, 'meaning_vi': meaning, 'part_of_speech': pos, **extra}

    def test_same_visible_cues_collide_across_level_topic_and_card_id(self):
        a = self.card('client', id=1, cefr_level='A1', topic='Office')
        b = self.card('customer', id=2, cefr_level='C1', topic='Shop')
        self.assertEqual(recall_prompt_signature(a), recall_prompt_signature(b))
        index = RecallPromptIndex([a, b])
        self.assertFalse(index.allows(a))
        self.assertFalse(index.allows(b))
        self.assertEqual(index.eligible_ids, set())

    def test_different_pos_initial_and_word_count_really_distinguish_prompts(self):
        for a, b in ((self.card('client', pos='noun'), self.card('customer', pos='verb')),
                     (self.card('client'), self.card('buyer')),
                     (self.card('client'), self.card('customer service'))):
            with self.subTest(a=a, b=b):
                index = RecallPromptIndex([a, b])
                self.assertTrue(index.allows(a))
                self.assertTrue(index.allows(b))

    def test_nfkc_whitespace_case_pos_and_short_hidden_initials(self):
        a = self.card('ＳＰＥＡＫ', meaning='  NÓI  ', pos='ＶＥＲＢ')
        b = self.card('say', meaning='nói', pos='verb')
        self.assertFalse(RecallPromptIndex([a, b]).allows(a))
        # Terms shorter than three characters do not show an initial at all.
        a, b = self.card('an', meaning='một'), self.card('or', meaning='một')
        self.assertEqual(recall_prompt_signature(a), recall_prompt_signature(b))
        self.assertFalse(RecallPromptIndex([a, b]).allows(a))

    def test_duplicate_normalized_lemma_is_not_a_collision_or_synonym_expansion(self):
        a, b = self.card('client', id=1), self.card(' ＣＬＩＥＮＴ ', id=2)
        index = RecallPromptIndex([a, b])
        self.assertEqual(index.eligible_ids, {1, 2})
        self.assertTrue(quiz_answer_is_correct(a, 'CLIENT', 'recall'))
        self.assertFalse(quiz_answer_is_correct(a, 'customer', 'recall'))


class RecallAmbiguityJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='ambiguity-owner')
        cls.other = get_user_model().objects.create_user(username='ambiguity-other')
        LearnerProfile.objects.create(user=cls.user, exam_goal='TOEIC', onboarding_complete=True)
        LearnerProfile.objects.create(user=cls.other, exam_goal='TOEIC', onboarding_complete=True)
        cls.content = LearningContent.objects.create(title='Visible exam bank', exam_type='TOEIC',
            content_type='vocabulary', skill='vocabulary', is_published=True, review_status='teacher_approved')
        cls.safe = [Flashcard.objects.create(content=cls.content, term=term, meaning_vi=meaning,
            part_of_speech='noun', cefr_level='A1', topic='Safe') for term, meaning in (
            ('apple', 'quả táo'), ('book', 'quyển sách'), ('chair', 'ghế tựa'), ('desk', 'bàn làm việc'), ('envelope', 'phong bì'))]

    def setUp(self):
        self.client.force_login(self.user)

    def card(self, term, meaning='khách hàng', **kwargs):
        data = {'content': self.content, 'term': term, 'meaning_vi': meaning,
                'part_of_speech': 'noun', 'cefr_level': 'A1', 'topic': 'Target'}
        data.update(kwargs)
        return Flashcard.objects.create(**data)

    def pair(self):
        return self.card('client'), self.card('customer', cefr_level='B2', topic='Other')

    def question(self, card, number=1):
        return {'number': number, 'card_id': card.pk, 'term': card.term, 'meaning_vi': card.meaning_vi,
                'part_of_speech': card.part_of_speech, 'cefr_level': card.cefr_level, 'example_en': '',
                'example_vi': '', 'source_url': '', 'options': [{'key': 'A', 'text': card.meaning_vi},
                {'key': 'B', 'text': 'khác nghĩa'}, {'key': 'C', 'text': 'một đáp án khác'},
                {'key': 'D', 'text': 'lựa chọn cuối'}], 'correct_key': 'A'}

    def session(self, cards, mode='recall', status='submitted', wrong=True, **kwargs):
        snapshot = [self.question(card, i) for i, card in enumerate(cards, start=1)]
        if mode == 'recall':
            for q in snapshot:
                q['options'], q['correct_key'] = [], ''
        answers = {str(q['number']): ('wrong' if wrong else q['term']) if mode == 'recall' else ('B' if wrong else 'A') for q in snapshot}
        data = {'user': self.user, 'mode': mode, 'exam_type': 'TOEIC', 'status': status,
                'snapshot': snapshot, 'question_count': len(cards),
                'correct_count': 0 if wrong else len(cards), 'answers': answers if status == 'submitted' else {},
                'submitted_at': timezone.now() if status == 'submitted' else None}
        data.update(kwargs)
        return VocabularyQuizSession.objects.create(**data)

    def test_dynamic_four_collision_groups_are_excluded_from_counts_and_start_only_in_recall(self):
        blocked = []
        for left, right, meaning, pos in (('speak', 'say', 'nói', 'verb'), ('client', 'customer', 'khách hàng', 'noun'),
                                          ('connect', 'contact', 'liên hệ', 'verb'), ('protect', 'preserve', 'bảo vệ', 'verb')):
            blocked.extend([self.card(left, meaning, part_of_speech=pos), self.card(right, meaning, part_of_speech=pos)])
        hub = self.client.get(reverse('learning:quiz_hub'), {'mode': 'recall', 'count': '15'})
        self.assertEqual(hub.context['available_count'], 5)
        self.assertEqual(hub.context['selected_count'], 15)
        self.client.post(reverse('learning:quiz_start'), {'mode': 'recall', 'count': '15'})
        quiz = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertEqual({q['card_id'] for q in quiz.snapshot}, {card.pk for card in self.safe})
        self.client.post(reverse('learning:quiz_abandon', args=[quiz.pk]), {'confirm_abandon':'yes', 'revision': VocabularyQuizSession.objects.get(pk=quiz.pk).draft_revision})
        meaning = self.client.get(reverse('learning:quiz_hub'), {'mode': 'meaning', 'count': 'bogus'})
        self.assertEqual((meaning.context['available_count'], meaning.context['selected_count']), (13, 10))
        self.client.post(reverse('learning:quiz_start'), {'mode': 'meaning', 'count': '15'})
        quiz = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertEqual({q['card_id'] for q in quiz.snapshot}, {c.pk for c in [*blocked, *self.safe]})

    def test_saved_subset_and_level_topic_do_not_hide_full_bank_ambiguity(self):
        a, b = self.pair()
        for card in [a, *self.safe]:
            SavedWord.objects.create(user=self.user, flashcard=card)
        hub = self.client.get(reverse('learning:quiz_hub'), {'mode': 'recall', 'source': 'saved'})
        self.assertEqual(hub.context['available_count'], 5)
        self.client.post(reverse('learning:quiz_start'), {'mode': 'recall', 'source': 'saved', 'count': '15'})
        quiz = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertNotIn(a.pk, {q['card_id'] for q in quiz.snapshot})
        self.client.post(reverse('learning:quiz_abandon', args=[quiz.pk]), {'confirm_abandon':'yes', 'revision': VocabularyQuizSession.objects.get(pk=quiz.pk).draft_revision})
        response = self.client.post(reverse('learning:quiz_start'),
            {'mode': 'recall', 'count': '5', 'level': 'A1', 'topic': 'Target'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(VocabularyQuizSession.objects.filter(user=self.user, status='in_progress').exists())
        self.assertIn('gợi ý rõ', ' '.join(str(m) for m in get_messages(response.wsgi_request)))

    def test_hidden_draft_other_exam_and_nonvocabulary_cards_do_not_create_collisions(self):
        target = self.card('client')
        for updates in ({'is_published': False}, {'review_status': 'draft'}, {'exam_type': 'IELTS'},
                        {'content_type': 'reading', 'skill': 'reading'}):
            values = {'title': 'Invisible distractor', 'exam_type': 'TOEIC', 'content_type': 'vocabulary',
                      'skill': 'vocabulary', 'is_published': True, 'review_status': 'teacher_approved'}
            values.update(updates)
            content = LearningContent.objects.create(**values)
            self.card('customer', content=content)
        with self.assertNumQueries(1):
            index = RecallPromptIndex.for_exam('TOEIC')
        self.assertTrue(index.allows(self.question(target)))
        self.assertIn(target.pk, index.eligible_ids)

    def test_existing_active_draft_new_collision_is_abandoned_without_grading_or_xp(self):
        target = self.card('client')
        active = self.session([target], status='in_progress')
        self.assertTrue(_available(active))
        self.card('customer')
        response = self.client.post(reverse('learning:quiz_submit', args=[active.pk]), {'answer_1': 'customer'})
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, 'khớp với nhiều từ tiếng Anh', status_code=410)
        active.refresh_from_db()
        self.assertEqual((active.status, active.answers, active.correct_count, active.xp_earned), ('abandoned', {}, 0, 0))
        self.assertFalse(VocabularyQuizDailyReward.objects.filter(user=self.user).exists())

    def test_get_and_autosave_expire_ambiguous_recall_but_leave_meaning_quiz_valid(self):
        a, b = self.pair()
        active = self.session([a], status='in_progress')
        response = self.client.get(reverse('learning:quiz_take', args=[active.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn('nhiều từ', ' '.join(str(m) for m in get_messages(response.wsgi_request)))
        active = self.session([a], status='in_progress')
        response = self.client.post(reverse('learning:quiz_draft', args=[active.pk]), {'revision': '0', 'answer_1': 'client'})
        self.assertEqual(response.status_code, 410)
        self.assertIn('nhiều từ', response.json()['message'])
        active = self.session([a], mode='meaning', status='in_progress')
        self.assertTrue(_available(active))
        response = self.client.post(reverse('learning:quiz_submit', args=[active.pk]), {'answer_1': 'A'})
        self.assertEqual(response.status_code, 302)
        active.refresh_from_db()
        self.assertEqual((active.status, active.correct_count), ('submitted', 1))

    def test_ambiguous_recall_retries_are_filtered_and_original_result_is_immutable(self):
        a, b = self.pair()
        parent = self.session([a, self.safe[0]])
        before = deepcopy(parent.snapshot)
        response = self.client.get(reverse('learning:quiz_result', args=[parent.pk]))
        self.assertEqual(response.context['retry_available_count'], 1)
        self.assertEqual(response.context['quiz'].correct_count, 0)
        self.client.post(reverse('learning:quiz_retry', args=[parent.pk]))
        retry = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertEqual([q['card_id'] for q in retry.snapshot], [self.safe[0].pk])
        self.assertEqual((retry.mode, retry.is_retry, retry.xp_earned), ('recall', True, 0))
        parent.refresh_from_db()
        self.assertEqual((parent.snapshot, parent.correct_count), (before, 0))
        self.assertEqual(len(_retry_candidates(self.session([a], mode='meaning'))), 1)

    def test_retry_with_only_ambiguous_words_does_not_create_a_new_attempt(self):
        a, b = self.pair()
        parent = self.session([a])
        before = VocabularyQuizSession.objects.filter(user=self.user).count()
        response = self.client.post(reverse('learning:quiz_retry', args=[parent.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(VocabularyQuizSession.objects.filter(user=self.user).count(), before)
        self.assertIn('gợi ý rõ', ' '.join(str(m) for m in get_messages(response.wsgi_request)))

    def test_weak_meaning_evidence_survives_ambiguous_recall_answers_and_recall_pool_excludes_it(self):
        a, b = self.pair()
        self.session([a], mode='meaning', submitted_at=timezone.now() - timedelta(minutes=5))
        self.session([a], mode='recall', wrong=False)
        summary = weak_word_summary(self.user)
        self.assertEqual([w['card'].pk for w in summary['words']], [a.pk])
        self.assertEqual(summary['words'][0]['wrong_count'], 1)
        hub = self.client.get(reverse('learning:quiz_hub'), {'mode': 'recall', 'source': 'weak'})
        self.assertEqual(hub.context['available_count'], 0)
        self.client.post(reverse('learning:quiz_start'), {'mode': 'recall', 'source': 'weak', 'count': '5'})
        self.assertFalse(VocabularyQuizSession.objects.filter(user=self.user, status='in_progress').exists())
        self.client.post(reverse('learning:quiz_start'), {'mode': 'meaning', 'source': 'weak', 'count': '5'})
        active = VocabularyQuizSession.objects.get(user=self.user, status='in_progress')
        self.assertEqual([q['card_id'] for q in active.snapshot], [a.pk])

    def test_ambiguous_recall_mistake_does_not_open_weak_entry_and_other_owner_stays_private(self):
        a, b = self.pair()
        parent = self.session([a])
        self.assertEqual(weak_word_summary(self.user)['count'], 0)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('learning:quiz_result', args=[parent.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('learning:quiz_retry', args=[parent.pk])).status_code, 404)

    def test_recall_validation_and_weak_rebuild_have_bounded_query_counts(self):
        a, b = self.pair()
        cards = [*self.safe, a, b]
        for _ in range(8):
            self.session(cards)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with self.assertNumQueries(5), CaptureQueriesContext(connection) as queries:
            summary = weak_word_summary(self.user, 'TOEIC')
        for query in queries:
            self.assertNotIn('"snapshot"', query['sql'])
            self.assertNotIn('"answers"', query['sql'])
        self.assertEqual(summary['count'], 5)
        active = self.session(self.safe, status='in_progress')
        with self.assertNumQueries(1):
            self.assertTrue(_available(active))
