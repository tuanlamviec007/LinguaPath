"""Local description candidates remain choices, not generated definitions."""
from copy import copy
from types import SimpleNamespace
from unittest.mock import patch
import json

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from planner.models import LearnerProfile
from .ai import answer_tutor_question, retrieve_learning_context
from .models import Flashcard, LearningContent, TutorTurn, TutorUsageBudget
from .privacy import personal_data_response
from .retrieval import retrieve_context
from .retrieval_description import _features, rank_description


def card(pk,term,meaning,example=''):
    return SimpleNamespace(pk=pk,term=term,meaning_vi=meaning,example_vi=example)


class DescriptionRankTests(SimpleTestCase):
    def test_meaning_overlap_produces_ranked_suggestions(self):
        a=card(1,'voucher','phiếu thanh toán mua hàng')
        b=card(2,'invoice','hóa đơn mua hàng')
        result=rank_description([a,b],'phiếu thanh toán')
        self.assertEqual(result[0][0].pk,1)
        self.assertGreater(result[0][1],0)

    def test_topic_or_example_only_cannot_produce_match(self):
        a=card(1,'voucher','phiếu thanh toán','Máy in hóa đơn mua hàng ở văn phòng.')
        self.assertEqual(rank_description([a],'máy in hóa đơn văn phòng'),[])

    def test_single_unreinforced_definition_token_is_insufficient(self):
        self.assertEqual(rank_description([card(1,'voucher','phiếu thanh toán')],'phiếu'),[])

    def test_example_phrase_may_reinforce_a_rare_definition_token(self):
        a=card(1,'voucher','phiếu thanh toán','Hãy xuất phiếu giảm giá cho khách.')
        result=rank_description([a,card(2,'invoice','hóa đơn')],'phiếu giảm giá')
        self.assertEqual(result[0][0].pk,1)

    def test_pairs_are_raw_adjacent_not_glued_across_stopwords(self):
        terms,pairs=_features('thanh và toán')
        self.assertEqual(set(terms),{'thanh','toan'})
        self.assertNotIn(('thanh','toan'),pairs)
        self.assertIn(('thanh','toan'),_features('thanh toán')[1])

    def test_duplicate_rows_do_not_change_idf_or_rank(self):
        a=card(1,'voucher','phiếu thanh toán')
        b=card(2,'invoice','hóa đơn thanh toán')
        baseline=rank_description([a,b],'phiếu thanh toán')
        duplicates=[]
        for i in range(100):
            duplicate=copy(a);duplicate.pk=i+3;duplicates.append(duplicate)
        self.assertEqual([(c.pk,s) for c,s in baseline],[(c.pk,s) for c,s in rank_description([a,b,*duplicates],'phiếu thanh toán')])

    def test_repeated_query_words_do_not_raise_score(self):
        a=card(1,'voucher','phiếu thanh toán')
        self.assertEqual(rank_description([a],'phiếu thanh toán'),rank_description([a],'phiếu phiếu thanh toán thanh toán'))

    def test_accented_unaccented_and_decomposed_queries_keep_original_source(self):
        import unicodedata
        a=card(1,'voucher','phiếu thanh toán')
        for query in ('phiếu thanh toán','phieu thanh toan',unicodedata.normalize('NFD','phiếu thanh toán')):
            self.assertEqual(rank_description([a],query)[0][0].meaning_vi,'phiếu thanh toán')

    def test_empty_generic_numeric_or_nonsense_queries_abstain(self):
        a=card(1,'voucher','phiếu thanh toán')
        for query in ('','và của một loại nào','123456','xyzzypqr'):
            self.assertEqual(rank_description([a],query),[])

    def test_limit_three_and_deterministic_ties(self):
        cards=[card(i,f'term{i}','phiếu thanh toán') for i in range(10,0,-1)]
        result=rank_description(sorted(cards,key=lambda c:c.pk),'phiếu thanh toán',100)
        self.assertEqual([c.pk for c,_ in result],[1,2,3])
        self.assertEqual(rank_description(cards,'phiếu thanh toán',0),[])

    def test_query_after_character_bound_cannot_add_match(self):
        a=card(1,'voucher','phiếu thanh toán')
        self.assertEqual(rank_description([a],'x '*250+'phiếu thanh toán'),[])


class DescriptionTutorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=get_user_model().objects.create_user(username='description-owner')
        cls.other=get_user_model().objects.create_user(username='description-other')
        LearnerProfile.objects.create(user=cls.user,exam_goal='TOEIC',onboarding_complete=True)
        LearnerProfile.objects.create(user=cls.other,exam_goal='TOEIC',onboarding_complete=True)
        cls.content=LearningContent.objects.create(title='Lexical QA source',exam_type='TOEIC',content_type='vocabulary',skill='vocabulary',is_published=True,review_status='language_checked')
        cls.card=Flashcard.objects.create(content=cls.content,term='voucher',meaning_vi='phiếu thanh toán',example_vi='Hãy xuất phiếu thanh toán cho khách.')

    def setUp(self): self.client.force_login(self.user)

    def test_description_search_is_explicit_and_one_public_card_query(self):
        with self.assertNumQueries(1):
            results=retrieve_context('phiếu thanh toán',user=self.user,retrieval_mode='description')
        self.assertEqual(results[0]['match_type'],'description')
        self.assertEqual(results[0]['source_id'],self.card.pk)
        self.assertLess(results[0]['score'],80)
        self.assertEqual(retrieve_context('voucher',retrieval_mode='unknown'),[])

    def test_public_visibility_and_exam_boundaries_refresh_on_each_request(self):
        result=retrieve_context('phiếu thanh toán',retrieval_mode='description')
        self.assertEqual(len(result),1)
        self.assertEqual(retrieve_context('phiếu thanh toán',exam='IELTS',retrieval_mode='description'),[])
        Flashcard.objects.filter(pk=self.card.pk).update(is_available=False)
        self.assertEqual(retrieve_context('phiếu thanh toán',retrieval_mode='description'),[])
        Flashcard.objects.filter(pk=self.card.pk).update(is_available=True)
        LearningContent.objects.filter(pk=self.content.pk).update(is_published=False)
        self.assertEqual(retrieve_context('phiếu thanh toán',retrieval_mode='description'),[])

    def test_draft_or_nonvocabulary_source_is_not_description_candidate(self):
        LearningContent.objects.filter(pk=self.content.pk).update(review_status='draft')
        self.assertEqual(retrieve_context('phiếu thanh toán',retrieval_mode='description'),[])
        LearningContent.objects.filter(pk=self.content.pk).update(review_status='language_checked',content_type='reading')
        self.assertEqual(retrieve_context('phiếu thanh toán',retrieval_mode='description'),[])

    def test_invalid_question_id_never_falls_back_to_description(self):
        self.assertEqual(retrieve_context('phiếu thanh toán',question_id='wrong',user=self.user,retrieval_mode='description'),[])
        self.assertEqual(retrieve_context('phiếu thanh toán',question_id=True,user=self.user,retrieval_mode='description'),[])

    def test_description_bypasses_grammar_router_and_private_question_scan(self):
        with patch('learning.tutor_knowledge.find_knowledge') as knowledge,CaptureQueriesContext(connection) as queries:
            results=retrieve_learning_context('phiếu thanh toán',user=self.user,retrieval_mode='description')
        self.assertEqual(results[0]['source_id'],self.card.pk)
        knowledge.assert_not_called()
        self.assertEqual(len(queries),1)
        self.assertFalse(any('learning_question' in q['sql'] for q in queries))

    def test_candidates_never_pack_context_reserve_quota_or_call_provider(self):
        observed=[]
        with patch('learning.ai.pack_evidence') as packing,patch('learning.ai.reserve_tutor_call') as quota, \
             patch('learning.ai.OpenAI') as model,patch('learning.ai.generate_cloudflare_answer') as bridge:
            result=answer_tutor_question('phiếu thanh toán',user=self.user,use_ai=True,retrieval_mode='description',
                evidence_observer=lambda evidence,packed: observed.append((evidence,packed)))
        self.assertEqual(result['mode'],'needs_context')
        self.assertEqual(result['retrieval_mode'],'description')
        self.assertIsNone(result['generation']['model'])
        self.assertIsNone(observed[0][1])
        self.assertEqual(len(result['clarification_prompts']),1)
        for mock in (packing,quota,model,bridge):mock.assert_not_called()
        self.assertFalse(TutorUsageBudget.objects.exists())

    def test_candidate_choice_returns_current_literal_lookup(self):
        result=answer_tutor_question('phiếu thanh toán',retrieval_mode='description')
        chosen=answer_tutor_question(result['clarification_prompts'][0])
        self.assertEqual(chosen['mode'],'retrieval_only')
        self.assertEqual(chosen['evidence_sources'][0]['label'],'voucher')

    def test_post_ignores_paid_mode_and_history_preserves_description_mode(self):
        with patch('learning.views.tutor_ai_available',return_value=True),patch('learning.ai.reserve_tutor_call') as quota:
            page=self.client.post(reverse('tutor'),{'question':'phiếu thanh toán','query_mode':'description','response_mode':'ai'},follow=True)
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.context['query_mode'],'description')
        turn=TutorTurn.objects.get(user=self.user)
        self.assertEqual(turn.response_mode,'lookup')
        self.assertEqual(turn.result['retrieval_mode'],'description')
        self.assertContains(page,'name="query_mode" value="auto"')
        self.assertContains(page,'Chọn voucher')
        quota.assert_not_called()
        self.assertIn('no-store',page.headers['Cache-Control'])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('tutor'),{'turn':turn.pk}).status_code,404)

    def test_unknown_or_duplicate_query_modes_are_rejected(self):
        for mode in ('other',['auto','description']):
            response=self.client.post(reverse('tutor'),{'question':'phiếu thanh toán','query_mode':mode})
            self.assertEqual(response.status_code,400)
        self.assertFalse(TutorTurn.objects.exists())

    def test_export_includes_owned_retrieval_mode_and_not_other_history(self):
        self.client.post(reverse('tutor'),{'question':'phiếu thanh toán','query_mode':'description'})
        export=json.loads(personal_data_response(self.user).content)
        self.assertEqual(export['tutor_history'][0]['result']['retrieval_mode'],'description')
        self.assertEqual(json.loads(personal_data_response(self.other).content)['tutor_history'],[])

    def test_no_match_preserves_description_ui_without_model_call(self):
        with patch('learning.ai.reserve_tutor_call') as quota:
            page=self.client.post(reverse('tutor'),{'question':'unrelatedunknown','query_mode':'description'},follow=True)
        self.assertEqual(page.context['query_mode'],'description')
        self.assertEqual(page.context['mode'],'no_match')
        quota.assert_not_called()

    def test_stale_history_cannot_offer_candidate_post_button(self):
        self.client.post(reverse('tutor'),{'question':'phiếu thanh toán','query_mode':'description'})
        turn=TutorTurn.objects.get(user=self.user)
        Flashcard.objects.filter(pk=self.card.pk).update(is_available=False)
        page=self.client.get(reverse('tutor'),{'turn':turn.pk})
        self.assertEqual(page.context['history_notice']['state'],'withdrawn')
        self.assertNotContains(page,'Chọn voucher')
        self.assertEqual(page.context['suggested_prompts'],[])

    def test_description_with_question_id_is_public_only_even_for_valid_shaped_id(self):
        with patch('learning.retrieval._submitted_questions') as private,patch('learning.ai.reserve_tutor_call') as quota:
            result=answer_tutor_question('phiếu thanh toán',question_id='1',user=self.user,use_ai=True,retrieval_mode='description')
        self.assertEqual(result['mode'],'no_match')
        private.assert_not_called();quota.assert_not_called()

    def test_pinned_candidate_selection_is_free_and_ignores_forged_prompt(self):
        result=answer_tutor_question('phiếu thanh toán',retrieval_mode='description')
        ref=result['evidence_sources'][0]['source_ref']
        with patch('learning.ai.reserve_tutor_call') as quota:
            page=self.client.post(reverse('tutor'),{'action':'select_candidate','query_mode':'auto','response_mode':'ai',
                'question':'forged prompt','candidate_id':ref['object_id'],'candidate_version':ref['version']},follow=True)
        self.assertEqual(page.context['mode'],'retrieval_only')
        self.assertEqual(page.context['query_mode'],'auto')
        self.assertEqual(page.context['evidence_sources'][0]['source_ref']['object_id'],self.card.pk)
        self.assertNotIn('forged',TutorTurn.objects.get(user=self.user).question)
        self.assertEqual(TutorTurn.objects.get(user=self.user).response_mode,'lookup')
        quota.assert_not_called()

    def test_pinned_candidate_cannot_fall_through_to_another_sense_after_hold(self):
        from .ai import answer_description_candidate
        result=answer_tutor_question('phiếu thanh toán',retrieval_mode='description')
        ref=result['evidence_sources'][0]['source_ref']
        Flashcard.objects.create(content=self.content,term='voucher',meaning_vi='nghĩa khác')
        Flashcard.objects.filter(pk=self.card.pk).update(is_available=False)
        selected=answer_description_candidate(ref['object_id'],ref['version'])
        self.assertEqual(selected['mode'],'no_match')
        self.assertEqual(selected['evidence_sources'],[])

    def test_pinned_candidate_rejects_edited_source_wrong_exam_or_bad_fields(self):
        from .ai import answer_description_candidate
        result=answer_tutor_question('phiếu thanh toán',retrieval_mode='description')
        ref=result['evidence_sources'][0]['source_ref']
        self.assertEqual(answer_description_candidate(ref['object_id'],ref['version'],'IELTS')['mode'],'no_match')
        for pk,version in [(True,ref['version']),('abc',ref['version']),('9'*50,ref['version']),(-1,ref['version']),
                (ref['object_id'],'invalid'),(ref['object_id'],'0'*64)]:
            self.assertEqual(answer_description_candidate(pk,version)['mode'],'no_match')
        Flashcard.objects.filter(pk=self.card.pk).update(meaning_vi='phiếu đã thay đổi')
        self.assertEqual(answer_description_candidate(ref['object_id'],ref['version'])['mode'],'no_match')

    def test_candidate_form_cannot_mix_question_context_or_duplicate_source_ids(self):
        result=answer_tutor_question('phiếu thanh toán',retrieval_mode='description')
        ref=result['evidence_sources'][0]['source_ref']
        base={'action':'select_candidate','candidate_id':ref['object_id'],'candidate_version':ref['version']}
        for extra in ({'question_id':'bad'},{'candidate_id':[str(ref['object_id']),str(ref['object_id'])]}):
            self.assertEqual(self.client.post(reverse('tutor'),{**base,**extra}).status_code,400)
        from django.test import Client
        protected=Client(enforce_csrf_checks=True);protected.force_login(self.user)
        protected.get(reverse('tutor'))
        self.assertEqual(protected.post(reverse('tutor'),base).status_code,403)
