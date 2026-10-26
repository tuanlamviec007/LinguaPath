"""Editorial regressions for lookup intent and conservative sense clarification."""
from unittest.mock import patch

from django.test import TestCase

from .ai import answer_tutor_question
from .models import Flashcard, LearningContent, TutorUsageBudget
from .retrieval import retrieve_context
from .retrieval_evaluation import evaluate_cases


class RetrievalIntentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.content = LearningContent.objects.create(title='Synthetic editorial source',exam_type='TOEIC',
            content_type='vocabulary',skill='vocabulary',is_published=True,review_status='language_checked')

    def card(self, term, meaning='nghĩa mẫu', **fields):
        return Flashcard.objects.create(content=self.content,term=term,meaning_vi=meaning,**fields)

    def test_english_quoted_definition_subject_is_lookup(self):
        card=self.card('algorithm','thuật toán')
        for query in ('What is an “algorithm” in computing?', "What is an 'algorithm'?", 'What is “algorithm”?'):
            with self.subTest(query=query):
                self.assertEqual(retrieve_context(query)[0]['source_id'],card.pk)

    def test_english_unquoted_definition_subject_must_be_complete(self):
        card=self.card('consent form','phiếu đồng ý')
        for query in ('What is a consent form?', 'What is a consent form in research?'):
            self.assertEqual(retrieve_context(query)[0]['source_id'],card.pk)
        for query in ('What is the best consent form for my clinic?', 'What is a consent formality?'):
            self.assertEqual(retrieve_context(query),[])

    def test_vietnamese_definition_supports_unaccented_input(self):
        card=self.card('bandwidth','băng thông')
        for query in ('“bandwidth” là gì?', 'Trong ket noi mang, “bandwidth” la gi?', 'Trong mạng, “bandwidth” là đại lượng nào?'):
            self.assertEqual(retrieve_context(query)[0]['source_id'],card.pk)

    def test_quoted_example_sentence_does_not_compete_with_requested_subject(self):
        self.card('bank transfer','chuyển khoản')
        card=self.card('bank','ngân hàng')
        results=retrieve_context('In “bank transfer”, what does “bank” mean?')
        self.assertEqual([item['source_id'] for item in results],[card.pk])

    def test_adjacent_quoted_subjects_can_both_be_requested(self):
        first=self.card('invoice','hóa đơn');second=self.card('receipt','biên lai')
        results=retrieve_context('Giải thích “invoice” và “receipt” nghĩa là gì?')
        self.assertEqual({item['source_id'] for item in results},{first.pk,second.pk})

    def test_unknown_quoted_subject_cannot_fall_through_to_context_headword(self):
        self.card('finance','tài chính');self.card('bank','ngân hàng',topic='finance')
        self.assertEqual(retrieve_context('What does “unlistedword” mean in finance?'),[])

    def test_multiword_subject_does_not_match_one_known_fragment(self):
        self.card('scope creep','phạm vi tăng thêm')
        self.assertEqual(retrieve_context('Explain scope'),[])
        self.assertEqual(retrieve_context('Define “scope”'),[])
        self.assertEqual(retrieve_context('scope creep')[0]['term'],'scope creep')

    def test_apostrophes_in_bare_or_quoted_headword_remain_part_of_subject(self):
        card=self.card("manager's agenda",'lịch của quản lý')
        for query in ("manager's agenda", 'Define “manager’s agenda”', "Define 'manager's agenda'"):
            with self.subTest(query=query):
                self.assertEqual(retrieve_context(query)[0]['source_id'],card.pk)

    def test_declarative_setup_followed_by_advice_does_not_search_examples(self):
        self.card('charger','bộ sạc',example_en='The laptop needs repair before the class project presentation.')
        self.card('laptop','máy tính xách tay')
        self.assertEqual(retrieve_context('My laptop needs repair before class. How should I organize the project files for my presentation?'),[])

    def test_descriptive_request_does_not_search_meaning_or_topic(self):
        self.card('consent','agreement risks participants',topic='research process')
        self.assertEqual(retrieve_context('The research process needs improvement. Draft a checklist explaining risks to participants.'),[])

    def test_short_library_search_keeps_example_fallback(self):
        card=self.card('receipt','biên lai',example_en='Deposit transaction appears here.')
        self.assertEqual(retrieve_context('deposit transaction')[0]['source_id'],card.pk)

    def test_quoted_instruction_not_reinterpreted_as_lookup_verb(self):
        self.card('bank','ngân hàng')
        self.assertEqual(retrieve_context('Why was “define bank” printed on the wall?'),[])

    def test_generic_example_overlap_cannot_choose_one_sense(self):
        first=self.card('bank','ngân hàng',example_en='A bank near the office.')
        second=self.card('bank','bờ sông',example_en='A bank near a tree.')
        result=retrieve_context('What does “bank” mean near the office?')
        self.assertTrue(result[0]['ambiguous'])
        self.assertEqual({s['source_id'] for s in result[0]['sense_options']},{first.pk,second.pk})
        self.assertNotIn('_sense_support',result[0])

    def test_domain_meaning_support_can_resolve_sense(self):
        first=self.card('bank','ngân hàng',topic='finance')
        self.card('bank','bờ sông',topic='geography')
        result=retrieve_context('What does “bank” mean in finance?')
        self.assertEqual(result[0]['source_id'],first.pk)
        self.assertFalse(result[0]['ambiguous'])
        self.assertEqual(len(result),1)

    def test_shared_domain_word_does_not_hide_sense_ambiguity(self):
        self.card('charge','khoản phí',topic='business',example_en='The charge is shown on the invoice.')
        self.card('charge','buộc tội',topic='business')
        result=retrieve_context('What does “charge” mean in business on the invoice?')
        self.assertTrue(result[0]['ambiguous'])

    def test_uncertain_sense_never_reserves_quota_or_calls_provider(self):
        self.card('bank','ngân hàng',example_en='The bank is near the office.')
        self.card('bank','bờ sông')
        with patch('learning.ai.tutor_ai_available',return_value=True), patch('learning.ai.reserve_tutor_call') as quota, \
             patch('learning.ai.OpenAI') as provider, patch('learning.ai.generate_cloudflare_answer') as bridge:
            result=answer_tutor_question('What does “bank” mean near the office?',use_ai=True)
        self.assertEqual(result['mode'],'needs_context')
        quota.assert_not_called();provider.assert_not_called();bridge.assert_not_called()
        self.assertFalse(TutorUsageBudget.objects.exists())

    def test_clarification_prompt_selects_literal_meaning(self):
        self.card('bank','ngân hàng',example_en='The bank is near the office.')
        self.card('bank','bờ sông')
        result=answer_tutor_question('What does “bank” mean near the office?')
        for prompt,source in zip(result['clarification_prompts'],result['evidence_sources']):
            chosen=answer_tutor_question(prompt)
            self.assertEqual(chosen['mode'],'retrieval_only')
            self.assertEqual(chosen['evidence_sources'][0]['meaning_vi'],source['meaning_vi'])

    def test_optional_sense_evaluation_is_literal_and_separate_from_headwords(self):
        self.card('bank','ngân hàng',topic='finance');self.card('bank','bờ sông',topic='geography')
        cases=[{'id':'ambiguous','split':'dev','category':'sense','query':'bank','expected_terms':['bank'],
            'expected_senses':[{'term':'bank','meaning_vi':'ngân hàng'},{'term':'bank','meaning_vi':'bờ sông'}], 'ambiguity_required':True}]
        report=evaluate_cases(cases,retrieve_context)
        self.assertEqual(report['overall']['sense_recall_at_3'],1)
        self.assertEqual(report['overall']['ambiguity_accuracy'],1)

    def test_distinct_vietnamese_meanings_are_not_merged_by_accent_folding(self):
        self.card('testword','ma');self.card('testword','má')
        results=retrieve_context('testword')
        self.assertEqual(len(results),2)
        self.assertTrue(results[0]['ambiguous'])
        self.assertEqual(results[0]['sense_count'],2)

    def test_clarification_literal_meaning_preserves_accents(self):
        self.card('testword','ma');self.card('testword','má')
        result=answer_tutor_question('testword')
        for prompt,source in zip(result['clarification_prompts'],result['evidence_sources']):
            chosen=answer_tutor_question(prompt)
            self.assertEqual(chosen['mode'],'retrieval_only')
            self.assertEqual(chosen['evidence_sources'][0]['meaning_vi'],source['meaning_vi'])

    def test_incidental_quoted_headword_in_long_advice_request_is_not_lookup(self):
        self.card('budget','ngân sách');self.card('consent form','phiếu đồng ý');self.card('afternoon','buổi chiều')
        for query in (
            "My team mentioned 'budget'. Can you plan tomorrow's meeting?",
            "Our organization needs a 'consent form'. Please draft a checklist for the project.",
            "I saw 'afternoon' in a weather notice. Should I take an umbrella tomorrow?",
        ):
            with self.subTest(query=query): self.assertEqual(retrieve_context(query),[])
        self.assertEqual(retrieve_context('Please define “budget” for my English lesson.')[0]['term'],'budget')
