"""A per-card editorial hold blocks new learning without rewriting evidence."""
from copy import deepcopy

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .ai import answer_tutor_question
from .models import Flashcard, LearningContent, SavedWord, VocabularyQuizSession
from .quiz_recall import RecallPromptIndex
from .quiz_views import _available, _retry_candidates
from .retrieval import retrieve_context
from .retrieval_v1 import retrieve_context as retrieve_v1
from .retrieval_baseline import retrieve_context as retrieve_baseline
from .saved_words import visible_cards, visible_saved_words
from .tutor_provenance import flashcard_source_ref, revalidate_tutor_history
from .weak_word_models import WeakWordOutcome, WeakWordQuizReceipt
from .weak_word_outcomes import materialized_weak_word_summary


class FlashcardAvailabilityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='availability-learner')
        LearnerProfile.objects.create(user=self.user, onboarding_complete=True)
        self.content = LearningContent.objects.create(title='Availability bank', content_type='vocabulary',
            skill='vocabulary', exam_type='TOEIC', is_published=True, review_status='language_checked')
        words = [('invoice','hóa đơn'),('printer','máy in'),('warehouse','nhà kho'),
            ('umbrella','ô dù'),('passenger','hành khách'),('currency','tiền tệ'),('baggage','hành lý'),('deadline','hạn chót')]
        self.cards = [Flashcard.objects.create(content=self.content, term=term, meaning_vi=meaning,
            part_of_speech='noun', cefr_level='B1', example_en=f'An example of {term}.', example_vi='Một ví dụ.')
            for term, meaning in words]
        self.card = self.cards[0]
        self.client.force_login(self.user)

    def hold(self, card=None):
        Flashcard.objects.filter(pk=(card or self.card).pk).update(
            is_available=False, availability_note='Chờ rà soát nguồn đã sửa.')

    def question(self, card=None):
        card = card or self.card
        return {'number':1,'card_id':card.pk,'term':card.term,'meaning_vi':card.meaning_vi,
            'part_of_speech':card.part_of_speech,'cefr_level':card.cefr_level,
            'example_en':card.example_en,'example_vi':card.example_vi,'source_url':'',
            'options':[{'key':'A','text':card.meaning_vi},{'key':'B','text':'nghĩa khác'}],'correct_key':'A'}

    def submitted(self, mode='meaning'):
        return VocabularyQuizSession.objects.create(user=self.user, mode=mode, status='submitted',
            question_count=1, submitted_at=timezone.now(), snapshot=[self.question()],
            answers={'1':'B' if mode=='meaning' else 'wrong'}, correct_count=0)

    def test_default_manager_and_parent_inventory_keep_held_card(self):
        self.hold()
        self.assertEqual(Flashcard.objects.count(),8)
        self.assertEqual(self.content.flashcards.count(),8)
        self.assertEqual(Flashcard.objects.learner_visible('TOEIC').count(),7)
        self.assertEqual(Flashcard.objects.learner_visible('IELTS').count(),0)
        self.content.is_published=False; self.content.save(update_fields=['is_published'])
        self.assertFalse(Flashcard.objects.learner_visible().exists())

    def test_hold_hides_bookmarks_but_the_owner_can_remove_their_existing_bookmark(self):
        SavedWord.objects.create(user=self.user,flashcard=self.card)
        self.hold()
        self.assertNotIn(self.card.pk, visible_cards(self.user).values_list('pk',flat=True))
        self.assertFalse(visible_saved_words(self.user).exists())
        url=reverse('learning:save_word',args=[self.card.pk])
        self.assertEqual(self.client.post(url,{'action':'save'}).status_code,404)
        self.assertTrue(SavedWord.objects.filter(user=self.user,flashcard=self.card).exists())
        self.assertEqual(self.client.post(url,{'action':'remove'}).status_code,302)
        self.assertFalse(SavedWord.objects.filter(user=self.user,flashcard=self.card).exists())

    def test_holding_one_card_does_not_hide_its_parent_or_siblings(self):
        self.hold()
        self.content.refresh_from_db()
        self.assertTrue(self.content.is_published)
        self.assertEqual(self.content.review_status,'language_checked')
        hub=self.client.get(reverse('learning:quiz_hub'))
        self.assertEqual(hub.context['available_count'],7)
        self.client.post(reverse('learning:quiz_start'),{'count':'5'})
        quiz=VocabularyQuizSession.objects.get(user=self.user,status='in_progress')
        self.assertNotIn(self.card.pk,{q['card_id'] for q in quiz.snapshot})

    def test_active_meaning_quiz_is_not_graded_after_a_source_card_is_held(self):
        self.client.post(reverse('learning:quiz_start'),{'count':'5'})
        quiz=VocabularyQuizSession.objects.get(user=self.user,status='in_progress')
        before=deepcopy(quiz.snapshot)
        held_id=quiz.snapshot[0]['card_id']
        Flashcard.objects.filter(pk=held_id).update(is_available=False)
        response=self.client.post(reverse('learning:quiz_submit',args=[quiz.pk]),
            {f'answer_{q["number"]}':q['correct_key'] for q in quiz.snapshot})
        self.assertEqual(response.status_code,410)
        quiz.refresh_from_db()
        self.assertEqual(quiz.status,'abandoned')
        self.assertEqual(quiz.snapshot,before)
        self.assertEqual(quiz.answers,{})
        self.assertEqual(quiz.xp_earned,0)

    def test_stale_recall_index_does_not_allow_held_card_in_active_or_retry_quiz(self):
        index=RecallPromptIndex.for_exam('TOEIC')
        quiz=VocabularyQuizSession.objects.create(user=self.user,mode='recall',question_count=1,snapshot=[self.question()])
        self.assertTrue(_available(quiz,index))
        self.hold()
        self.assertFalse(_available(quiz,index))
        quiz.status='submitted'; quiz.answers={'1':'wrong'}; quiz.submitted_at=timezone.now()
        quiz.save(update_fields=['status','answers','submitted_at'])
        self.assertEqual(_retry_candidates(quiz,index),[])

    def test_recall_ambiguity_index_uses_only_currently_available_cards(self):
        cost=Flashcard.objects.create(content=self.content,term='cost',meaning_vi='chi phí',part_of_speech='noun')
        charge=Flashcard.objects.create(content=self.content,term='charge',meaning_vi='chi phí',part_of_speech='noun')
        self.assertTrue(RecallPromptIndex.for_exam('TOEIC').ambiguous({'term':'cost','meaning_vi':'chi phí','part_of_speech':'noun'}))
        self.hold(charge)
        index=RecallPromptIndex.for_exam('TOEIC')
        self.assertIn(cost.pk,index.eligible_ids)
        self.assertNotIn(charge.pk,index.visible_ids)

    def test_tutor_retrievers_exclude_held_sources(self):
        self.assertTrue(retrieve_context('invoice'))
        self.hold()
        for retriever in (retrieve_context,retrieve_v1,retrieve_baseline):
            with self.subTest(retriever=retriever.__module__):
                self.assertEqual(retriever('invoice'),[])

    def test_tutor_history_withdraws_held_source_without_rewriting_or_hashing_availability(self):
        result=answer_tutor_question('invoice',user=self.user)
        before=deepcopy(result)
        version=flashcard_source_ref(self.card)
        self.hold()
        self.card.refresh_from_db()
        self.assertEqual(flashcard_source_ref(self.card),version)
        with CaptureQueriesContext(connection) as queries:
            decorated,notice=revalidate_tutor_history(result,self.user,'TOEIC',timezone.now())
        self.assertEqual(len(queries),1)
        self.assertEqual(notice['state'],'withdrawn')
        self.assertEqual(decorated['answer'],before['answer'])
        self.assertFalse(decorated['evidence_sources'][0]['link_available'])
        self.assertEqual(decorated['evidence_sources'][0]['href'],'')
        self.assertEqual(result,before)

    def test_submitted_results_keep_original_answers_but_disable_save_and_retry(self):
        quiz=self.submitted(); snapshot=deepcopy(quiz.snapshot); answers=deepcopy(quiz.answers)
        self.hold()
        page=self.client.get(reverse('learning:quiz_result',args=[quiz.pk]))
        self.assertEqual(page.status_code,200)
        self.assertContains(page,self.card.term)
        self.assertFalse(page.context['results'][0]['can_save'])
        self.assertEqual(page.context['retry_available_count'],0)
        self.client.post(reverse('learning:quiz_retry',args=[quiz.pk]))
        self.assertFalse(VocabularyQuizSession.objects.filter(user=self.user,status='in_progress').exists())
        quiz.refresh_from_db()
        self.assertEqual(quiz.snapshot,snapshot); self.assertEqual(quiz.answers,answers)

    def test_held_word_leaves_current_weak_queue_even_with_stale_supplied_bank(self):
        self.submitted()
        stale_bank=list(visible_cards(self.user))
        self.assertEqual(materialized_weak_word_summary(self.user,'TOEIC')['count'],1)
        projection=list(WeakWordOutcome.objects.values()); receipts=list(WeakWordQuizReceipt.objects.values())
        self.hold()
        self.assertEqual(materialized_weak_word_summary(self.user,'TOEIC')['count'],0)
        self.assertEqual(materialized_weak_word_summary(self.user,'TOEIC',visible_bank=stale_bank)['count'],0)
        self.assertEqual(list(WeakWordOutcome.objects.values()),projection)
        self.assertEqual(list(WeakWordQuizReceipt.objects.values()),receipts)

    def test_old_plan_links_disable_held_only_level_without_hiding_available_siblings(self):
        held=Flashcard.objects.create(content=self.content,term='advanced',meaning_vi='nâng cao',cefr_level='C1',is_available=False)
        url=reverse('learning:flashcards_content',args=[self.content.pk])
        raw={'answer':'An old plan','mode':'daily_plan','actions':[
            {'title':'Held level','href':url+'?level=C1'},
            {'title':'Available level','href':url+'?level=B1'},
            {'title':'Whole deck','href':url}]}
        decorated,_=revalidate_tutor_history(raw,self.user,'TOEIC',timezone.now())
        self.assertEqual([action['link_available'] for action in decorated['actions']],[False,True,True])
        Flashcard.objects.filter(content=self.content).update(is_available=False)
        decorated,_=revalidate_tutor_history(raw,self.user,'TOEIC',timezone.now())
        self.assertFalse(any(action['link_available'] for action in decorated['actions']))
