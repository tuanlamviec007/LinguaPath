"""Learner journeys for the private quiz mistake queue and targeted practice."""
from copy import deepcopy
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .models import (
    Flashcard, LearningContent, SavedWord, VocabularyQuizDailyReward,
    VocabularyQuizSession,
)
from .quiz_progress import quiz_progress_summary
from .quiz_weak_words import weak_word_summary


class WeakWordsJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='weak-words-owner')
        cls.other = get_user_model().objects.create_user(username='weak-words-other')
        for user in (cls.user, cls.other):
            LearnerProfile.objects.create(user=user, exam_goal='TOEIC', onboarding_complete=True)
        cls.content = LearningContent.objects.create(
            title='Work and travel words', content_type='vocabulary', skill='vocabulary',
            exam_type='TOEIC', is_published=True, review_status='teacher_approved',
        )
        terms = [
            ('umbrella', 'ô dù'), ('cloud', 'đám mây'), ('ticket', 'vé tàu'),
            ('bank', 'ngân hàng'), ('baggage', 'hành lý'), ('passenger', 'hành khách'),
            ('printer', 'máy in'), ('currency', 'tiền tệ'),
        ]
        cls.cards = [Flashcard.objects.create(
            content=cls.content, term=term, meaning_vi=meaning,
            cefr_level='B1' if index < 5 else 'B2',
            topic='Travel' if index < 5 else 'Work',
            example_en=f'This example uses {term}.', example_vi=f'Ví dụ về {meaning}.',
        ) for index, (term, meaning) in enumerate(terms)]

    def setUp(self):
        self.client.force_login(self.user)

    def completed(self, cards=None, correct=False, **overrides):
        """Write old submitted evidence without consuming today's reward slot."""
        cards = self.cards[:1] if cards is None else cards
        flags = correct if isinstance(correct, list) else [correct] * len(cards)
        snapshot = [{
            'number': number, 'card_id': card.pk, 'term': card.term,
            'meaning_vi': card.meaning_vi, 'cefr_level': card.cefr_level,
            'topic': card.topic, 'part_of_speech': card.part_of_speech,
            'example_en': card.example_en, 'example_vi': card.example_vi,
            'source_url': card.source_url, 'correct_key': 'A',
            'options': [
                {'key': 'A', 'label': 'A', 'text': card.meaning_vi},
                {'key': 'B', 'label': 'B', 'text': 'phương án sai'},
                {'key': 'C', 'label': 'C', 'text': 'một phương án khác'},
                {'key': 'D', 'label': 'D', 'text': 'phương án cuối'},
            ],
        } for number, card in enumerate(cards, start=1)]
        values = {
            'user': self.user, 'exam_type': 'TOEIC', 'status': 'submitted',
            'submitted_at': timezone.now() - timedelta(minutes=1),
            'question_count': len(cards), 'correct_count': sum(flags),
            'snapshot': snapshot,
            'answers': {str(number): 'A' if flag else 'B' for number, flag in enumerate(flags, start=1)},
        }
        values.update(overrides)
        return VocabularyQuizSession.objects.create(**values)

    def start(self, source='weak', **filters):
        response = self.client.post(reverse('learning:quiz_start'), {'source': source, 'count': '5', **filters})
        self.assertEqual(response.status_code, 302)
        return VocabularyQuizSession.objects.get(user=self.user, status='in_progress')

    def submit(self, quiz, correct=True):
        answers = {
            f'answer_{question["number"]}': question['correct_key'] if correct else next(
                option['key'] for option in question['options'] if option['key'] != question['correct_key']
            ) for question in quiz.snapshot
        }
        result = self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), answers)
        self.assertRedirects(result, reverse('learning:quiz_result', args=[quiz.pk]), fetch_redirect_response=False)
        quiz.refresh_from_db()

    def test_latest_submitted_outcome_clears_then_reopens_word_including_retries(self):
        old = self.completed(submitted_at=timezone.now() - timedelta(days=2))
        recent = self.completed(is_retry=True, parent_quiz=old)
        summary = weak_word_summary(self.user)
        self.assertEqual(summary['count'], 1)
        self.assertEqual(summary['words'][0]['wrong_count'], 2)
        self.assertEqual(summary['words'][0]['last_quiz_id'], recent.pk)
        self.completed(correct=True, is_retry=True, submitted_at=timezone.now() - timedelta(seconds=30))
        self.assertEqual(weak_word_summary(self.user)['count'], 0)
        latest = self.completed(submitted_at=timezone.now() - timedelta(seconds=10))
        word = weak_word_summary(self.user)['words'][0]
        self.assertEqual((word['card'].pk, word['last_quiz_id']), (self.cards[0].pk, latest.pk))

    def test_submission_time_then_primary_key_decides_latest_not_start_order(self):
        same_time = timezone.now() - timedelta(minutes=1)
        self.completed(submitted_at=same_time)
        self.completed(correct=True, submitted_at=same_time)
        self.assertEqual(weak_word_summary(self.user)['count'], 0)
        latest = self.completed(cards=self.cards[1:2], submitted_at=same_time)
        self.completed(cards=self.cards[1:2], correct=True, submitted_at=same_time - timedelta(minutes=1))
        self.assertEqual(weak_word_summary(self.user)['words'][0]['last_quiz_id'], latest.pk)

    def test_drafts_abandoned_future_and_missing_submission_do_not_change_queue(self):
        self.completed()
        self.completed(correct=True, status='in_progress', submitted_at=None)
        self.completed(correct=True, status='abandoned')
        self.completed(correct=True, submitted_at=timezone.now() + timedelta(days=1))
        self.completed(correct=True, submitted_at=None)
        self.assertEqual(weak_word_summary(self.user)['count'], 1)

    def test_queue_is_private_and_scoped_to_current_exam_and_visible_sources(self):
        self.completed(cards=self.cards[:3])
        self.completed(cards=self.cards[3:4], user=self.other)
        foreign = self.completed(cards=self.cards[4:5], exam_type='IELTS')
        self.assertEqual(weak_word_summary(self.user)['count'], 3)
        hidden = LearningContent.objects.create(
            title='Hidden vocabulary', content_type='vocabulary', skill='vocabulary',
            exam_type='TOEIC', is_published=False, review_status='teacher_approved',
        )
        Flashcard.objects.filter(pk=self.cards[0].pk).update(content=hidden)
        draft = LearningContent.objects.create(
            title='Unreviewed vocabulary', content_type='vocabulary', skill='vocabulary',
            exam_type='TOEIC', is_published=True, review_status='draft',
        )
        Flashcard.objects.filter(pk=self.cards[1].pk).update(content=draft)
        other_exam = LearningContent.objects.create(
            title='IELTS vocabulary', content_type='vocabulary', skill='vocabulary',
            exam_type='IELTS', is_published=True, review_status='teacher_approved',
        )
        Flashcard.objects.filter(pk=self.cards[2].pk).update(content=other_exam)
        self.assertEqual(weak_word_summary(self.user)['count'], 0)
        self.assertEqual(weak_word_summary(self.other)['count'], 1)
        # Merely changing the profile cannot make a TOEIC submission become IELTS evidence.
        LearnerProfile.objects.filter(user=self.user).update(exam_goal='IELTS')
        self.assertEqual(weak_word_summary(self.user)['count'], 0)
        self.assertEqual(foreign.exam_type, 'IELTS')

    def test_teacher_revisions_do_not_attach_old_mistakes_to_a_different_word(self):
        self.completed(cards=self.cards[:3])
        Flashcard.objects.filter(pk=self.cards[0].pk).update(term='a completely different term')
        Flashcard.objects.filter(pk=self.cards[1].pk).update(meaning_vi='nghĩa hoàn toàn mới')
        self.cards[2].delete()
        self.assertEqual(weak_word_summary(self.user)['count'], 0)

    def test_cosmetic_case_and_whitespace_edits_keep_same_word_identity(self):
        self.completed()
        card = self.cards[0]
        Flashcard.objects.filter(pk=card.pk).update(term=f'  {card.term.upper()}  ', meaning_vi='  Ô   DÙ  ')
        summary = weak_word_summary(self.user)
        self.assertEqual(summary['count'], 1)
        self.assertEqual(summary['words'][0]['card'].pk, card.pk)

    def test_correct_retry_of_old_snapshot_does_not_clear_revised_word_evidence(self):
        old = self.completed(submitted_at=timezone.now() - timedelta(days=2))
        card = self.cards[0]
        card.term, card.meaning_vi = 'deadline', 'hạn chót'
        card.save(update_fields=['term', 'meaning_vi'])
        current = self.completed(cards=[card], submitted_at=timezone.now() - timedelta(minutes=2))
        self.completed(
            cards=[card], correct=True, snapshot=deepcopy(old.snapshot),
            is_retry=True, parent_quiz=old,
        )
        summary = weak_word_summary(self.user)
        self.assertEqual(summary['count'], 1)
        self.assertEqual(summary['words'][0]['term'], 'deadline')
        self.assertEqual(summary['words'][0]['last_quiz_id'], current.pk)
        self.assertEqual(summary['words'][0]['wrong_count'], 1)

    def test_notebook_filters_bookmarks_auth_and_private_cache(self):
        self.completed(cards=self.cards)
        SavedWord.objects.create(user=self.user, flashcard=self.cards[2])
        page = self.client.get(reverse('learning:weak_words'), {'q': 'ticket', 'level': 'B1', 'topic': 'Travel'})
        self.assertEqual(page.status_code, 200)
        self.assertEqual((page.context['weak_word_count'], page.context['filtered_count']), (8, 1))
        self.assertEqual(page.context['words'][0]['card'].pk, self.cards[2].pk)
        self.assertTrue(page.context['words'][0]['card'].is_saved)
        self.assertContains(page, 'ticket')
        self.assertIn('no-store', page.headers['Cache-Control'])
        by_example = self.client.get(reverse('learning:weak_words'), {'q': 'example uses printer'})
        self.assertEqual(by_example.context['filtered_count'], 1)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('learning:weak_words')).context['weak_word_count'], 0)
        self.assertEqual(self.client.post(reverse('learning:weak_words')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('learning:weak_words')).status_code, 302)

    def test_notebook_paginates_twenty_without_overlap_and_handles_bad_filters(self):
        cards = [Flashcard.objects.create(
            content=self.content, term=f'pending-{index}', meaning_vi=f'nghĩa riêng {index}',
            cefr_level='B1', topic='Travel',
        ) for index in range(23)]
        self.completed(cards=cards)
        first = self.client.get(reverse('learning:weak_words'))
        second = self.client.get(reverse('learning:weak_words'), {'page': '2'})
        self.assertEqual((len(first.context['words']), len(second.context['words'])), (20, 3))
        self.assertFalse({row['card'].pk for row in first.context['words']} & {row['card'].pk for row in second.context['words']})
        invalid = self.client.get(reverse('learning:weak_words'), {'level': 'invalid', 'topic': 'missing', 'page': 'invalid'})
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(invalid.context['selected_level'], '')
        self.assertEqual(invalid.context['selected_topic'], '')
        self.assertEqual(invalid.context['filtered_count'], 23)

    def test_dashboard_and_progress_counts_are_current_and_private(self):
        self.completed(cards=self.cards[:2])
        for url in (reverse('dashboard'), reverse('progress')):
            self.assertEqual(self.client.get(url).context['weak_word_count'], 2)
        self.completed(cards=self.cards[:1], correct=True, submitted_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(reverse('dashboard')).context['weak_word_count'], 1)
        self.client.force_login(self.other)
        for url in (reverse('dashboard'), reverse('progress')):
            self.assertEqual(self.client.get(url).context['weak_word_count'], 0)

    def test_single_weak_word_quiz_uses_only_own_queue_and_hides_answer_metadata(self):
        self.completed()
        self.completed(cards=self.cards[1:2], user=self.other)
        hub = self.client.get(reverse('learning:quiz_hub'), {'source': 'weak'})
        self.assertEqual((hub.context['selected_source'], hub.context['available_count'], hub.context['weak_word_count']), ('weak', 1, 1))
        quiz = self.start()
        self.assertEqual((quiz.vocabulary_source, quiz.is_retry, quiz.question_count), ('weak', True, 1))
        self.assertIsNone(quiz.parent_quiz_id)
        self.assertEqual([q['card_id'] for q in quiz.snapshot], [self.cards[0].pk])
        self.assertEqual(len({o['text'] for o in quiz.snapshot[0]['options']}), 4)
        play = self.client.get(reverse('learning:quiz_take', args=[quiz.pk]))
        self.assertNotIn('snapshot', play.context['quiz'])
        self.assertNotIn('correct_key', play.context['questions'][0])
        self.assertNotIn('meaning_vi', play.context['questions'][0])
        self.assertNotIn('example_vi', play.context['questions'][0])

    def test_weak_submission_clears_queue_no_xp_and_preserves_normal_daily_bonus(self):
        self.completed()
        quiz = self.start()
        self.submit(quiz)
        self.assertEqual(quiz.xp_earned, 0)
        self.assertEqual(weak_word_summary(self.user)['count'], 0)
        self.assertFalse(VocabularyQuizDailyReward.objects.filter(user=self.user).exists())
        progress = quiz_progress_summary(self.user, 'TOEIC')
        self.assertEqual((progress['completed'], progress['retry_count']), (1, 1))
        normal = self.start(source='all')
        self.submit(normal)
        self.assertEqual(normal.xp_earned, 30)
        self.assertEqual(VocabularyQuizDailyReward.objects.filter(user=self.user).count(), 1)

    def test_wrong_weak_submission_stays_pending_and_later_normal_miss_reopens(self):
        self.completed()
        quiz = self.start()
        before = deepcopy(quiz.snapshot)
        self.submit(quiz, correct=False)
        self.assertEqual(weak_word_summary(self.user)['count'], 1)
        again = self.start()
        self.submit(again)
        self.assertEqual(weak_word_summary(self.user)['count'], 0)
        self.completed(submitted_at=timezone.now() - timedelta(microseconds=1))
        self.assertEqual(weak_word_summary(self.user)['count'], 1)
        quiz.refresh_from_db()
        self.assertEqual(quiz.snapshot, before)

    def test_empty_or_filtered_weak_pool_never_falls_back_and_tampering_rejected(self):
        response = self.client.post(reverse('learning:quiz_start'), {'source': 'weak', 'count': '5'})
        self.assertRedirects(response, reverse('learning:quiz_hub') + '?source=weak&mode=meaning&level=&topic=&count=5')
        self.assertFalse(VocabularyQuizSession.objects.exists())
        self.completed()
        response = self.client.post(reverse('learning:quiz_start'), {'source': 'weak', 'count': '5', 'level': 'C2'})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(reverse('learning:quiz_start'), {'source': 'weak', 'count': '5', 'level': 'B2'})
        self.assertRedirects(response, reverse('learning:quiz_hub') + '?source=weak&mode=meaning&level=B2&topic=&count=5')
        self.assertFalse(VocabularyQuizSession.objects.filter(status='in_progress').exists())
        for source in (['weak', 'all'], 'someone-else'):
            self.assertEqual(self.client.post(reverse('learning:quiz_start'), {'source': source, 'count': '5'}).status_code, 400)

    def test_hiding_source_after_weak_start_expires_quiz_without_grading_or_credit(self):
        self.completed()
        quiz = self.start()
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        response = self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]), {'answer_1': quiz.snapshot[0]['correct_key']})
        self.assertEqual(response.status_code, 410)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, 'abandoned')
        self.assertEqual(quiz.xp_earned, 0)
        self.assertFalse(VocabularyQuizDailyReward.objects.filter(user=self.user).exists())
