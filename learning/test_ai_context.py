from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase

from .ai import answer_tutor_question, retrieve_learning_context
from .ai_context import pack_evidence
from .models import Flashcard, LearningContent


def question_evidence(stimulus='Long listening passage. ' * 90):
    return {
        'source': 'Research equipment booking update', 'kind': 'question',
        'text': 'Original complete source', 'source_id': 1206,
        'source_ref': {'kind': 'question', 'object_id': 1206, 'version': 'fixture-version'},
        'structured': {
            'prompt': 'Why does the speaker suggest a separate specialist consultation?',
            'passage': '', 'audio_script': stimulus, 'transcript': stimulus,
            'explanation': 'Book specialist support instead of making an incorrect adjustment.',
            'explanation_vi': 'Cần đặt lịch chuyên gia để tránh điều chỉnh sai.',
            'options': [
                {'id': index, 'label': label, 'text': text, 'is_correct': label == 'A',
                 'explanation_vi': f'Giải thích riêng phương án {label}.'}
                for index, (label, text) in enumerate([
                    ('A', 'Reserve specialist support.'), ('B', 'Repair a damaged sample.'),
                    ('C', 'Replace an expired booking.'), ('D', 'Train all laboratory staff.'),
                ], 1)
            ],
        },
    }


class EvidencePackingTests(SimpleTestCase):
    def test_long_question_preserves_key_and_each_distractor_before_stimulus(self):
        source = question_evidence()
        packed = pack_evidence([source])
        self.assertTrue(packed.sufficient)
        self.assertLessEqual(len(packed.text), 5400)
        self.assertIn('"is_correct":true', packed.text)
        for option in source['structured']['options']:
            self.assertIn(option['text'], packed.text)
            self.assertIn(option['explanation_vi'], packed.text)
        self.assertLess(packed.text.index('Cần đặt lịch'), packed.text.index('Stimulus for source'))
        self.assertEqual(packed.text.count('Long listening passage.'), 90)
        self.assertEqual(packed.evidence[0]['source_ref'], source['source_ref'])

    def test_all_question_essentials_precede_any_stimulus(self):
        first, second = question_evidence('FIRST STIMULUS'), question_evidence('SECOND STIMULUS')
        second['structured']['prompt'] = 'SECOND QUESTION ESSENTIALS'
        packed = pack_evidence([first, second])
        self.assertLess(packed.text.index('SECOND QUESTION ESSENTIALS'), packed.text.index('FIRST STIMULUS'))

    def test_excess_stimulus_is_explicitly_excerpted_within_total_budget(self):
        packed = pack_evidence([question_evidence('very long source ' * 1000)])
        self.assertTrue(packed.sufficient)
        self.assertLessEqual(len(packed.text), 5400)
        self.assertIn('Stimulus excerpt', packed.text)
        self.assertIn('Giải thích riêng phương án D.', packed.text)
        self.assertFalse(packed.evidence[0]['context_complete'])

    def test_oversized_or_incomplete_question_essentials_fail_closed(self):
        oversized = question_evidence()
        oversized['structured']['options'][3]['explanation_vi'] = 'x' * 6000
        incomplete = question_evidence()
        del incomplete['structured']['options'][0]['is_correct']
        for source in (oversized, incomplete):
            self.assertFalse(pack_evidence([source]).sufficient)

    def test_generic_legacy_excerpt_only_cites_included_sources(self):
        sources = [{'source': 'First', 'text': 'a' * 7000, 'kind': 'flashcard'},
                   {'source': 'Second', 'text': 'not included', 'kind': 'flashcard'}]
        packed = pack_evidence(sources)
        self.assertLessEqual(len(packed.text), 5400)
        self.assertEqual([source['source'] for source in packed.evidence], ['First'])
        self.assertIn('remaining text omitted', packed.text)
        self.assertFalse(packed.evidence[0]['context_complete'])
        self.assertEqual(packed.evidence[0]['context_format'], 'legacy_text')

    def test_legacy_question_never_silently_loses_unknown_essentials(self):
        self.assertFalse(pack_evidence([{'source': 'Legacy', 'kind': 'question', 'text': 'x' * 6000}]).sufficient)

    def test_malformed_explicit_structured_question_never_reserves_or_calls_model(self):
        for malformed in (None, [], 'broken'):
            source = {'source': 'Broken question', 'kind': 'question',
                      'text': 'Stem without answer key', 'structured': malformed}
            with self.subTest(structured=malformed), \
                    patch('learning.ai.retrieve_learning_context', return_value=[source]), \
                    patch('learning.ai.tutor_ai_available', return_value=True), \
                    patch('learning.ai.reserve_tutor_call') as reserve, \
                    patch('learning.ai.OpenAI') as openai, \
                    patch('learning.ai.generate_cloudflare_answer') as cloudflare:
                self.assertFalse(pack_evidence([source]).sufficient)
                self.assertEqual(answer_tutor_question('Explain', use_ai=True)['mode'], 'context_insufficient')
                reserve.assert_not_called()
                openai.assert_not_called()
                cloudflare.assert_not_called()

    @patch('learning.ai.tutor_ai_available', return_value=True)
    @patch('learning.ai.reserve_tutor_call', return_value=(True, 'allowed'))
    def test_oversized_question_does_not_reserve_or_call_either_provider(self, reserve, available):
        source = question_evidence()
        source['structured']['prompt'] = 'x' * 6000
        with patch('learning.ai.retrieve_learning_context', return_value=[source]), \
                patch('learning.ai.OpenAI') as openai, patch('learning.ai.generate_cloudflare_answer') as cloudflare:
            result = answer_tutor_question('Explain', use_ai=True)
        self.assertEqual(result['mode'], 'context_insufficient')
        self.assertEqual(result['generation']['provider'], 'none')
        self.assertEqual(result['evidence_sources'][0]['source_ref'], source['source_ref'])
        reserve.assert_not_called()
        openai.assert_not_called()
        cloudflare.assert_not_called()

    @patch('learning.ai.tutor_ai_available', return_value=True)
    @patch('learning.ai.reserve_tutor_call', return_value=(True, 'allowed'))
    def test_mock_cloudflare_receives_complete_essential_payload(self, reserve, available):
        source = question_evidence()
        with patch('learning.ai.retrieve_learning_context', return_value=[source]), \
                patch('learning.ai.provider_name', return_value='cloudflare'), \
                patch('learning.ai.generate_cloudflare_answer', return_value='Answer') as generate:
            result = answer_tutor_question('Explain each option', use_ai=True)
        payload = generate.call_args.args[1]
        self.assertIn('Giải thích riêng phương án D.', payload)
        self.assertLessEqual(len(payload), 5400)
        self.assertEqual(result['evidence_sources'][0]['source_ref'], source['source_ref'])
        self.assertEqual(result['generation']['provider'], 'cloudflare')

    def test_every_answer_branch_has_generation_metadata_and_provenance(self):
        source = question_evidence()
        with patch('learning.ai.retrieve_learning_context', return_value=[source]):
            lookup = answer_tutor_question('Explain')
            with patch('learning.ai.tutor_ai_available', return_value=True), \
                    patch('learning.ai.reserve_tutor_call', return_value=(False, 'global_daily_limit')):
                limited = answer_tutor_question('Explain', use_ai=True)
            with patch('learning.ai.tutor_ai_available', return_value=True), \
                    patch('learning.ai.reserve_tutor_call', return_value=(True, 'allowed')), \
                    patch('learning.ai.provider_name', return_value='cloudflare'), \
                    patch('learning.ai.generate_cloudflare_answer', side_effect=RuntimeError('private')):
                fallback = answer_tutor_question('Explain', use_ai=True)
        with patch('learning.ai.retrieve_learning_context', return_value=[]):
            absent = answer_tutor_question('Unknown')
        for result in (lookup, limited, fallback, absent):
            self.assertEqual(set(result['generation']) & {'provider', 'model', 'prompt_version', 'context_version', 'generated_at'},
                             {'provider', 'model', 'prompt_version', 'context_version', 'generated_at'})
        for result in (lookup, limited, fallback):
            self.assertEqual(result['evidence_sources'][0]['source_ref'], source['source_ref'])
        self.assertEqual(fallback['generation']['attempted_provider'], 'cloudflare')

    def test_clarification_preserves_each_choice_source_reference(self):
        choice = {'title': 'Bank meanings', 'href': '/cards', 'meaning_vi': 'ngân hàng',
                  'review_status': 'language_checked', 'source_ref': {'version': 'choice-version'}}
        source = {'ambiguous': True, 'term': 'bank', 'sense_options': [choice]}
        with patch('learning.ai.retrieve_learning_context', return_value=[source]):
            result = answer_tutor_question('bank')
        self.assertEqual(result['evidence_sources'][0]['source_ref'], choice['source_ref'])
        self.assertEqual(result['generation']['provider'], 'none')


class KnowledgeRoutingTests(TestCase):
    def setUp(self):
        content = LearningContent.objects.create(title='Vocabulary', exam_type='TOEIC',
            skill='vocabulary', content_type='vocabulary', is_published=True, review_status='language_checked')
        Flashcard.objects.create(content=content, term='reading', meaning_vi='chỉ số đo')

    def test_multi_topic_lookup_returns_both_notes_and_sources(self):
        result = answer_tutor_question('Compare present perfect and passive voice')
        self.assertEqual(result['mode'], 'retrieval_only')
        self.assertEqual(len(result['evidence_sources']), 2)
        self.assertIn('have/has', result['answer'])
        self.assertIn('be (chia theo thì)', result['answer'])
        self.assertTrue(all(source.get('source_ref') for source in result['evidence_sources']))

    def test_incidental_skill_and_quoted_vocabulary_do_not_force_strategy_note(self):
        incidental = retrieve_learning_context('What is the reading on this thermometer?')
        self.assertFalse(any(item['kind'] == 'knowledge' for item in incidental))
        explicit = retrieve_learning_context('Giải thích từ “reading”.')
        self.assertEqual(explicit[0]['kind'], 'flashcard')
        self.assertEqual(explicit[0]['term'], 'reading')

    def test_explicit_learning_strategy_still_returns_note(self):
        evidence = retrieve_learning_context('How can I improve reading speed?')
        self.assertEqual(evidence[0]['source_id'], 'reading-strategy')

    def test_explicit_question_id_always_preserves_authorization_boundary(self):
        with patch('learning.retrieval.retrieve_context', return_value=[]) as retrieve:
            self.assertEqual(retrieve_learning_context('present perfect passive voice', question_id='invalid'), [])
        self.assertEqual(retrieve.call_args.kwargs['question_id'], 'invalid')
