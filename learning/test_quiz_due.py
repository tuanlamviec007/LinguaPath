"""Prospective due-card observations and their deliberately narrow claims."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .models import DueRecallObservation, Flashcard, LearningContent, UserFlashcardState, VocabularyQuizSession
from .privacy import personal_data_response
from .quiz_due import due_states, due_summary, record_due_observations, selection_is_current


class DueRecallTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='due-owner')
        cls.other = get_user_model().objects.create_user(username='due-other')
        cls.profile = LearnerProfile.objects.create(user=cls.user, exam_goal='TOEIC', current_cefr='A2', onboarding_complete=True)
        LearnerProfile.objects.create(user=cls.other, exam_goal='TOEIC', onboarding_complete=True)
        cls.content = LearningContent.objects.create(title='Due source', content_type='vocabulary', skill='vocabulary', exam_type='TOEIC', is_published=True, review_status='language_checked')
        cls.cards = [Flashcard.objects.create(content=cls.content, term=term, meaning_vi=meaning, cefr_level='A2', part_of_speech='noun', topic='Travel') for term, meaning in [
            ('umbrella', 'ô dù'), ('baggage', 'hành lý'), ('printer', 'máy in'), ('currency', 'tiền tệ'), ('passenger', 'hành khách'), ('invoice', 'hóa đơn'),
        ]]

    def setUp(self):
        self.client.force_login(self.user)
        self.now = timezone.now()

    def state(self, card=None, user=None, gap=48, due=-1, **extra):
        return UserFlashcardState.objects.create(user=user or self.user, flashcard=card or self.cards[0],
            reviewed_at=self.now-timedelta(hours=gap), due_at=self.now+timedelta(hours=due), last_rating='known', **extra)

    def start(self, **data):
        response = self.client.post(reverse('learning:quiz_start'), {'source':'due','mode':'recall','count':'5', **data})
        self.assertEqual(response.status_code, 302)
        return VocabularyQuizSession.objects.get(user=self.user, status='in_progress')

    def submit(self, quiz, correct=True):
        response = self.client.post(reverse('learning:quiz_submit', args=[quiz.pk]),
            {f'answer_{q["number"]}':q['term'] if correct else 'wrongword' for q in quiz.snapshot})
        self.assertEqual(response.status_code, 302)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status, 'submitted')

    def test_candidate_boundary_exact_24_hours_due_now_and_user_isolation(self):
        yes = self.state(gap=24, due=0)
        self.state(self.cards[1], gap=23.99)
        self.state(self.cards[2], gap=48, due=.01)
        self.state(self.cards[3], user=self.other)
        with self.assertNumQueries(1):
            self.assertEqual(list(due_states(self.user, 'TOEIC', self.now).values_list('pk', flat=True)), [yes.pk])

    def test_visible_vocabulary_exam_only(self):
        for card in self.cards: self.state(card)
        self.cards[0].is_available=False; self.cards[0].save(update_fields=['is_available'])
        foreign=LearningContent.objects.create(title='IELTS', exam_type='IELTS', content_type='vocabulary', is_published=True, review_status='language_checked')
        self.cards[1].content=foreign; self.cards[1].save(update_fields=['content'])
        hidden=LearningContent.objects.create(title='Hidden', exam_type='TOEIC', content_type='vocabulary', is_published=False)
        self.cards[2].content=hidden; self.cards[2].save(update_fields=['content'])
        self.assertEqual(set(due_states(self.user,'TOEIC').values_list('flashcard_id', flat=True)), {c.pk for c in self.cards[3:]})

    def test_hub_forces_recall_even_without_js_and_server_rejects_meaning(self):
        self.state()
        page=self.client.get(reverse('learning:quiz_hub'), {'source':'due','mode':'meaning'})
        self.assertEqual(page.context['selected_mode'], 'recall')
        self.assertEqual(page.context['available_count'], 1)
        self.assertContains(page, '24 giờ')
        response=self.client.post(reverse('learning:quiz_start'), {'source':'due','mode':'meaning','count':'5'})
        self.assertEqual(response.status_code,400)
        self.assertFalse(VocabularyQuizSession.objects.exists())

    def test_start_stamps_baseline_and_only_due_cards_without_padding(self):
        state=self.state()
        quiz=self.start()
        self.assertEqual((quiz.mode,quiz.vocabulary_source,quiz.question_count,quiz.is_retry),('recall','due',1,False))
        self.assertEqual(quiz.snapshot[0]['card_id'],state.flashcard_id)
        meta=quiz.snapshot[0]['due_check']
        self.assertEqual(meta['baseline_reviewed_at'],state.reviewed_at.isoformat())
        self.assertEqual(len(meta['source_version']),64)
        page=self.client.get(reverse('learning:quiz_take',args=[quiz.pk]))
        for field in ('term','due_check','correct_key','example_en'):
            self.assertNotIn(field,page.context['questions'][0])
        self.assertIn('no-store',page.headers['Cache-Control'])

    def test_filters_cannot_add_new_cards_or_another_exam(self):
        self.state()
        response=self.client.post(reverse('learning:quiz_start'), {'source':'due','mode':'recall','count':'5','level':'B2'})
        self.assertEqual(response.status_code,302)
        self.assertFalse(VocabularyQuizSession.objects.exists())

    def test_ambiguous_cue_is_not_added_even_if_only_one_duplicate_due(self):
        self.state()
        Flashcard.objects.create(content=self.content,term='unrelated',meaning_vi=self.cards[0].meaning_vi,part_of_speech='noun',cefr_level='A2')
        # Different first letters are distinguishable; make same first letter+length.
        Flashcard.objects.create(content=self.content,term='universe',meaning_vi=self.cards[0].meaning_vi,part_of_speech='noun',cefr_level='A2')
        response=self.client.post(reverse('learning:quiz_start'), {'source':'due','mode':'recall','count':'5'})
        self.assertEqual(response.status_code,302)
        self.assertFalse(VocabularyQuizSession.objects.exists())

    def test_submit_records_once_consumes_baseline_preserves_srs_and_cefr(self):
        state=self.state(review_count=7, interval_days=3)
        before=UserFlashcardState.objects.values().get(pk=state.pk)
        quiz=self.start(); self.submit(quiz)
        observation=DueRecallObservation.objects.get()
        self.assertTrue(observation.is_correct)
        self.assertEqual(observation.exclusion_reason,'')
        self.assertFalse(due_states(self.user,'TOEIC').exists())
        self.submit(quiz)
        self.assertEqual(DueRecallObservation.objects.count(),1)
        self.assertEqual(UserFlashcardState.objects.values().get(pk=state.pk),before)
        self.profile.refresh_from_db();self.assertEqual(self.profile.current_cefr,'A2')
        self.assertEqual(quiz.xp_earned,22)
        new_time=timezone.now()
        UserFlashcardState.objects.filter(pk=state.pk).update(reviewed_at=new_time,due_at=new_time)
        self.assertFalse(due_states(self.user,'TOEIC').exists())
        self.assertTrue(due_states(self.user,'TOEIC',new_time+timedelta(hours=24)).exists())

    def test_review_during_quiz_excludes_observation_but_snapshot_grade_remains(self):
        state=self.state();quiz=self.start()
        UserFlashcardState.objects.filter(pk=state.pk).update(reviewed_at=timezone.now())
        self.submit(quiz)
        self.assertEqual(DueRecallObservation.objects.get().exclusion_reason,'review_changed')
        self.assertEqual(quiz.correct_count,1)
        summary=due_summary(self.user,'TOEIC')
        self.assertEqual((summary['questions'],summary['excluded']),(0,1))

    def test_source_edit_during_quiz_excludes_observation(self):
        self.state();quiz=self.start()
        Flashcard.objects.filter(pk=self.cards[0].pk).update(example_vi='Đã đổi ví dụ')
        self.submit(quiz)
        self.assertEqual(DueRecallObservation.objects.get().exclusion_reason,'source_changed')

    def test_held_card_aborts_submit_without_observation(self):
        self.state();quiz=self.start()
        Flashcard.objects.filter(pk=self.cards[0].pk).update(is_available=False)
        response=self.client.post(reverse('learning:quiz_submit',args=[quiz.pk]),{'answer_1':quiz.snapshot[0]['term']})
        self.assertEqual(response.status_code,410)
        self.assertFalse(DueRecallObservation.objects.exists())

    def test_retry_is_not_a_second_due_observation_and_clears_metadata(self):
        self.state();quiz=self.start();self.submit(quiz,correct=False)
        response=self.client.post(reverse('learning:quiz_retry',args=[quiz.pk]))
        self.assertEqual(response.status_code,302)
        retry=VocabularyQuizSession.objects.get(parent_quiz=quiz)
        self.assertTrue(retry.is_retry)
        self.assertNotIn('due_check',retry.snapshot[0])
        self.submit(retry)
        self.assertEqual((DueRecallObservation.objects.count(),retry.xp_earned),(1,0))

    def test_draft_conflict_or_invalid_answers_do_not_record(self):
        self.state();quiz=self.start()
        endpoint=reverse('learning:quiz_submit',args=[quiz.pk])
        self.assertEqual(self.client.post(endpoint,{'revision':'1','answer_1':quiz.snapshot[0]['term']}).status_code,409)
        self.assertEqual(self.client.post(endpoint,{}).status_code,400)
        self.assertFalse(DueRecallObservation.objects.exists())

    def test_failure_rolls_back_grade_reward_and_observations(self):
        self.state();quiz=self.start()
        with patch('learning.quiz_views.record_due_observations',side_effect=RuntimeError('rollback')):
            with self.assertRaises(RuntimeError): self.submit(quiz)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status,'in_progress')
        self.assertFalse(DueRecallObservation.objects.exists())
        self.assertFalse(self.user.quiz_daily_rewards.exists())

    def test_invalid_or_missing_metadata_never_becomes_valid_observation(self):
        self.state();quiz=self.start()
        for bad in ({}, {'baseline_reviewed_at':'bad'}, {'baseline_reviewed_at':self.now.replace(tzinfo=None).isoformat()}):
            snap=deepcopy(quiz.snapshot);snap[0]['due_check']=bad
            quiz.snapshot=snap;quiz.status='submitted';quiz.submitted_at=timezone.now();quiz.answers={'1':snap[0]['term']}
            with transaction.atomic(): record_due_observations(quiz)
            self.assertEqual(DueRecallObservation.objects.get().exclusion_reason,'invalid_baseline')
            DueRecallObservation.objects.all().delete()

    def test_other_modes_or_retries_never_generate_observations(self):
        self.state();quiz=self.start();quiz.status='submitted';quiz.submitted_at=timezone.now()
        quiz.vocabulary_source='all'
        record_due_observations(quiz)
        quiz.vocabulary_source='due';quiz.is_retry=True
        record_due_observations(quiz)
        self.assertFalse(DueRecallObservation.objects.exists())

    def test_summary_aggregates_without_quiz_snapshot_and_has_minimum_sample(self):
        for card in self.cards: self.state(card)
        quiz=self.start(count='5');self.submit(quiz)
        with self.assertNumQueries(1): result=due_summary(self.user,'TOEIC')
        self.assertEqual((result['questions'],result['correct'],result['accuracy']),(5,5,100))
        self.assertEqual(due_summary(self.other,'TOEIC')['questions'],0)
        self.assertEqual(due_summary(self.user,'IELTS')['questions'],0)
        DueRecallObservation.objects.filter(quiz=quiz).first().delete()
        self.assertIsNone(due_summary(self.user,'TOEIC')['accuracy'])

    def test_history_source_filter_and_privacy_include_owned_observations(self):
        self.state();quiz=self.start();self.submit(quiz)
        page=self.client.get(reverse('learning:quiz_history'),{'source':'due'})
        self.assertEqual([q.pk for q in page.context['quizzes']],[quiz.pk])
        export=json.loads(personal_data_response(self.user).content)
        self.assertEqual(export['due_recall_observations'][0]['quiz_id'],quiz.pk)
        self.assertEqual(json.loads(personal_data_response(self.other).content)['due_recall_observations'],[])
        self.user.delete()
        self.assertFalse(DueRecallObservation.objects.exists())

    def test_progress_links_due_quiz_without_certifying_mastery(self):
        page=self.client.get(reverse('progress'))
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.context['due_summary']['questions'],0)
        self.assertContains(page,'source=due')

    def test_stale_prepared_selection_cannot_reuse_consumed_baseline(self):
        self.state();quiz=self.start();prepared=deepcopy(quiz.snapshot)
        self.submit(quiz)
        with transaction.atomic():
            self.assertFalse(selection_is_current(self.user,'TOEIC',prepared))

    def test_creation_rechecks_under_owner_lock_before_insert(self):
        self.state()
        with patch('learning.quiz_views.selection_is_current',return_value=False) as recheck:
            response=self.client.post(reverse('learning:quiz_start'),{'source':'due','mode':'recall','count':'5'})
        self.assertEqual(response.status_code,302)
        self.assertIn('source=due',response.url)
        recheck.assert_called_once()
        self.assertFalse(VocabularyQuizSession.objects.exists())

    def test_card_move_excludes_observation_even_when_wording_unchanged(self):
        self.state();quiz=self.start()
        destination=LearningContent.objects.create(title='Moved',content_type='vocabulary',skill='vocabulary',exam_type='TOEIC',is_published=True,review_status='language_checked')
        Flashcard.objects.filter(pk=self.cards[0].pk).update(content=destination)
        self.submit(quiz)
        self.assertEqual(DueRecallObservation.objects.get().exclusion_reason,'source_changed')

    def test_hold_during_source_lock_aborts_before_grade_or_reward(self):
        self.state();quiz=self.start()
        from .quiz_due import lock_due_cards
        def hold_then_lock(questions):
            Flashcard.objects.filter(pk=self.cards[0].pk).update(is_available=False)
            return lock_due_cards(questions)
        with patch('learning.quiz_views.lock_due_cards',side_effect=hold_then_lock):
            response=self.client.post(reverse('learning:quiz_submit',args=[quiz.pk]),{'answer_1':quiz.snapshot[0]['term']})
        self.assertEqual(response.status_code,410)
        quiz.refresh_from_db();self.assertEqual(quiz.status,'abandoned')
        self.assertFalse(DueRecallObservation.objects.exists())
        self.assertFalse(self.user.quiz_daily_rewards.exists())
