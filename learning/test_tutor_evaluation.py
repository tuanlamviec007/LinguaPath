from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from .ai_context import PackedContext
from .models import Flashcard, LearningContent, TutorUsageBudget
from .tutor_evaluation import (
    DEFAULT_CASES, MAX_FIXTURE_BYTES, load_evaluation_cases,
    run_tutor_evaluation, validate_evaluation_cases,
)


def fixture(*cases):
    return {'version': 'test-v1', 'provenance': 'Known editorial regression; not an independent holdout.',
        'cases': list(cases) or [{'id': 'note', 'category': 'grammar', 'query': 'despite và although',
            'expected': [{'kind': 'knowledge', 'knowledge_id': 'despite-although'}]}]}


def answer(mode='retrieval_only', sources=None):
    return {'answer': 'Response based on the source.', 'mode': mode, 'sources': ['Knowledge note'],
        'evidence_sources': [{'kind': 'knowledge', 'label': 'Kiến thức TOEIC',
            'source_ref': {'kind': 'knowledge', 'object_id': 'despite-although'}}] if sources is None else sources,
        'generation': {'provider': 'none' if mode != 'llm_rag' else 'openai', 'model': None,
            'prompt_version': 'test', 'context_version': 'test', 'generated_at': '2026-10-25T00:00:00Z'}}


class TutorEvaluationCoreTests(SimpleTestCase):
    def setUp(self):
        self.staff = SimpleNamespace(pk=1, is_active=True, is_staff=True, is_authenticated=True)

    def test_default_fixture_retains_editorial_provenance_and_sixteen_cases(self):
        data = load_evaluation_cases(DEFAULT_CASES)
        self.assertEqual(len(data['cases']), 16)
        self.assertIn('not independent holdout', data['provenance'])

    def test_loader_rejects_duplicate_nonfinite_utf8_and_oversized_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            for raw in (b'{"version":"a","version":"b"}', b'{"n":NaN}',
                        b'{"n":Infinity}', b'{"n":1e999}', b'\xff', b'[]', b'{',
                        b' ' * (MAX_FIXTURE_BYTES + 1)):
                with self.subTest(raw=raw[:30]):
                    path.write_bytes(raw)
                    with self.assertRaises(ValueError):
                        load_evaluation_cases(path)

    def test_loader_returns_original_data_and_prohibits_question_ids(self):
        data = fixture()
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_text(json.dumps(data))
            self.assertEqual(load_evaluation_cases(path), data)
        for mutation in (
            lambda d: d['cases'][0].update(question_id=1),
            lambda d: d['cases'][0].update(query='q' * 501),
            lambda d: d['cases'][0].update(category='c' * 81),
            lambda d: d['cases'][0]['expected'].append({'kind': 'question', 'question_id': 1}),
            lambda d: d['cases'][0]['expected'].append(d['cases'][0]['expected'][0]),
            lambda d: d['cases'].append(deepcopy(d['cases'][0])),
            lambda d: d.update(provenance=''),
            lambda d: d.update(version=''),
        ):
            changed = deepcopy(data)
            mutation(changed)
            with self.assertRaises(ValueError):
                validate_evaluation_cases(changed)

    def test_all_cases_and_live_caps_validate_before_first_answer(self):
        answerer = Mock(return_value=answer())
        bad = fixture()
        bad['cases'].append({'id': 'late-invalid', 'query': 'x', 'category': 'c', 'expected': 'wrong'})
        with self.assertRaises(ValueError):
            run_tutor_evaluation(bad, answerer=answerer)
        for cap in (0, -1, 11, True, 1.0, None):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                run_tutor_evaluation(fixture(), live=True, user=self.staff, max_live_calls=cap, answerer=answerer)
        many = fixture(*[{**fixture()['cases'][0], 'id': str(i)} for i in range(3)])
        with self.assertRaises(ValueError):
            run_tutor_evaluation(many, live=True, user=self.staff, max_live_calls=2, answerer=answerer)
        answerer.assert_not_called()

    def test_live_principal_and_offline_options_fail_closed(self):
        for field in ('is_active', 'is_staff', 'is_authenticated'):
            user = deepcopy(self.staff)
            setattr(user, field, False)
            with self.assertRaises(ValueError):
                run_tutor_evaluation(fixture(), live=True, user=user, max_live_calls=1)
        for user in (None, SimpleNamespace(is_active=True, is_staff=True, is_authenticated=True, pk=True)):
            with self.assertRaises(ValueError):
                run_tutor_evaluation(fixture(), live=True, user=user, max_live_calls=1)
        for options in ({'max_live_calls': 1}, {'live': 'true'}, {'exam': 'UNKNOWN'}):
            with self.assertRaises(ValueError):
                run_tutor_evaluation(fixture(), **options)

    def test_offline_ignores_user_and_always_requests_public_context(self):
        answerer = Mock(return_value=answer())
        report = run_tutor_evaluation(fixture(), user=self.staff, answerer=answerer)
        kwargs = answerer.call_args.kwargs
        self.assertIsNone(kwargs['user'])
        self.assertFalse(kwargs['use_ai'])
        self.assertTrue(kwargs['public_context_only'])
        self.assertTrue(callable(kwargs['evidence_observer']))
        self.assertEqual(report['execution']['mode'], 'offline')
        self.assertEqual(report['execution']['use_ai_requests'], 0)
        self.assertEqual(report['summary']['source_coverage'], 1)
        self.assertEqual(report['cases'][0]['snapshot_notice'], 'not_observed')
        self.assertIsNone(report['cases'][0]['evidence_snapshot'])

    def test_live_requests_are_bounded_no_retries_and_mode_counts_are_honest(self):
        data = fixture(*[{**fixture()['cases'][0], 'id': str(i)} for i in range(3)])
        answerer = Mock(side_effect=[answer('llm_rag'), answer('retrieval_fallback'), answer('budget_limited')])
        report = run_tutor_evaluation(data, live=True, user=self.staff, max_live_calls=3, answerer=answerer)
        self.assertEqual(answerer.call_count, 3)
        self.assertTrue(all(call.kwargs['use_ai'] and call.kwargs['user'] is self.staff for call in answerer.call_args_list))
        self.assertEqual(report['execution']['model_attempts_inferred_from_mode'], 2)
        self.assertEqual(report['execution']['model_answers'], 1)
        self.assertEqual(report['summary']['latency_ms']['model_answers']['count'], 1)
        self.assertIn('not provider usage or cost', report['execution']['notice'])

    def test_errors_are_counted_and_exception_details_never_escape(self):
        data = fixture({'id': 'bad', 'category': 'negative', 'query': 'unknown', 'expected': []})
        callback = Mock(side_effect=RuntimeError('API_TOKEN_SECRET_DO_NOT_EXPORT'))
        report = run_tutor_evaluation(data, answerer=callback)
        self.assertEqual(callback.call_count, 1)
        self.assertEqual(report['summary']['errors'], 1)
        self.assertEqual(report['summary']['source_exact_matches'], 0)
        self.assertEqual(report['summary']['negative_abstentions'], 0)
        self.assertEqual(report['cases'][0]['error'], 'case_execution_failed')
        self.assertNotIn('API_TOKEN_SECRET', json.dumps(report))

    def test_unknown_source_is_a_false_positive_not_abstention(self):
        data = fixture({'id': 'negative', 'category': 'negative', 'query': 'unknown', 'expected': []})
        report = run_tutor_evaluation(data, answerer=lambda *a, **kw: answer('no_match', [{'kind': 'unknown'}]))
        self.assertEqual(report['summary']['negative_abstention_rate'], 0)
        self.assertEqual(report['cases'][0]['false_positives'], [('unknown', 'unrecognized-source-0')])

    def test_headword_coverage_does_not_claim_sense_or_answer_quality(self):
        data = fixture({'id': 'term', 'category': 'lexical', 'query': 'Define “charge”',
            'expected': [{'kind': 'flashcard', 'term': 'charge'}]})
        value = answer('needs_context', [{'kind': 'flashcard', 'label': 'CHARGE', 'meaning_vi': 'one possible sense'}])
        report = run_tutor_evaluation(data, answerer=lambda *a, **kw: value)
        self.assertEqual(report['summary']['source_coverage'], 1)
        self.assertEqual(report['execution']['model_attempts_inferred_from_mode'], 0)
        self.assertIn('not semantic quality', report['scope'])

    def test_latency_splits_model_answers_from_all_local_work(self):
        data = fixture(*[{**fixture()['cases'][0], 'id': str(i)} for i in range(2)])
        callback = Mock(side_effect=[answer(), answer('llm_rag')])
        with patch('learning.tutor_evaluation.perf_counter', side_effect=[1, 1.01, 2, 2.03]):
            report = run_tutor_evaluation(data, answerer=callback)
        latency = report['summary']['latency_ms']
        self.assertEqual(latency['all'], {'count': 2, 'median': 20.0, 'p95': 30.0})
        self.assertEqual(latency['model_answers'], {'count': 1, 'median': 30.0, 'p95': 30.0})

    def test_response_allowlist_strips_unknown_adapter_fields(self):
        value = answer()
        value.update(headers={'Authorization': 'DO_NOT_EXPORT'}, user_email='private@example.invalid')
        value['generation']['api_key'] = 'DO_NOT_EXPORT'
        report = run_tutor_evaluation(fixture(), answerer=lambda *a, **kw: value)
        raw = json.dumps(report)
        self.assertNotIn('DO_NOT_EXPORT', raw)
        self.assertNotIn('private@example.invalid', raw)

    def test_malformed_response_becomes_redacted_error(self):
        for value in (None, [], {'answer': 'x', 'mode': 'unknown'}, {**answer(), 'answer': ''},
                      {**answer(), 'generation': {'model': float('nan')}}):
            report = run_tutor_evaluation(fixture(), answerer=lambda *a, **kw: value)
            self.assertEqual(report['summary']['errors'], 1)
            self.assertEqual(report['cases'][0]['error'], 'invalid_result')

    def test_observer_captures_exact_snapshot_hash_and_detaches_mutation(self):
        source = {'kind': 'knowledge', 'text': 'Original evidence.',
            'source_ref': {'kind': 'knowledge', 'object_id': 'despite-although'}}
        packed = PackedContext('Exact model context.', [source], True)

        def callback(*args, **kwargs):
            kwargs['evidence_observer']([source], packed)
            source['text'] = 'Later changed.'
            return answer()

        report = run_tutor_evaluation(fixture(), answerer=callback)
        snapshot = report['cases'][0]['evidence_snapshot']
        self.assertEqual(snapshot['retrieved'][0]['text'], 'Original evidence.')
        self.assertEqual(snapshot['packed']['text'], 'Exact model context.')
        self.assertRegex(snapshot['sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(report['cases'][0]['snapshot_notice'], 'observed')

    def test_repeated_or_invalid_observer_capture_is_failed_case(self):
        for evidence, repeat in (([{'text': 'x' * (513 * 1024)}], False), ([], True)):
            def callback(*args, **kwargs):
                kwargs['evidence_observer'](evidence, None)
                if repeat:
                    kwargs['evidence_observer'](evidence, None)
                return answer()
            report = run_tutor_evaluation(fixture(), answerer=callback)
            self.assertEqual(report['cases'][0]['error'], 'invalid_evidence_snapshot')
            self.assertIsNone(report['cases'][0]['result'])

    def test_fixture_fingerprint_changes_with_expected_sources_or_query(self):
        original = fixture()
        report = run_tutor_evaluation(original, answerer=lambda *a, **kw: answer())
        changed = deepcopy(original)
        changed['cases'][0]['query'] += '?'
        altered = run_tutor_evaluation(changed, answerer=lambda *a, **kw: answer())
        self.assertNotEqual(report['fixture']['sha256'], altered['fixture']['sha256'])
        self.assertEqual(original, fixture())


class TutorEvaluationProductionTests(TestCase):
    def test_ambiguous_public_headword_keeps_all_senses_and_shared_references(self):
        content = LearningContent.objects.create(title='Ambiguous public words', exam_type='TOEIC',
            content_type='vocabulary', skill='vocabulary', review_status='language_checked', is_published=True)
        for meaning in ('phí dịch vụ', 'sạc điện'):
            Flashcard.objects.create(content=content, term='charge', meaning_vi=meaning)
        data = fixture({'id': 'ambiguous', 'category': 'lexical', 'query': 'Define “charge”',
            'expected': [{'kind': 'flashcard', 'term': 'charge'}]})
        with patch('learning.ai.OpenAI') as openai, patch('learning.ai.reserve_tutor_call') as quota:
            report = run_tutor_evaluation(data)
        row = report['cases'][0]
        self.assertIsNone(row['error'])
        self.assertEqual(row['result']['mode'], 'needs_context')
        self.assertEqual(len(row['result']['evidence_sources']), 2)
        self.assertEqual(row['evidence_snapshot']['retrieved'][0]['sense_count'], 2)
        self.assertEqual(len(row['evidence_snapshot']['retrieved'][0]['sense_options']), 2)
        self.assertIsNone(row['evidence_snapshot']['packed'])
        self.assertEqual(report['execution']['model_attempts_inferred_from_mode'], 0)
        openai.assert_not_called()
        quota.assert_not_called()

    def test_real_offline_pipeline_uses_no_models_quota_or_database_writes(self):
        with CaptureQueriesContext(connection) as queries, patch('learning.ai.OpenAI') as openai, \
                patch('learning.ai.generate_cloudflare_answer') as bridge, \
                patch('learning.ai.reserve_tutor_call') as reserve:
            report = run_tutor_evaluation(fixture())
        self.assertEqual(report['summary']['errors'], 0)
        self.assertEqual(report['summary']['source_exact_matches'], 1)
        self.assertEqual(report['summary']['mode_counts'], {'retrieval_only': 1})
        self.assertEqual(report['execution']['model_answers'], 0)
        self.assertIsNotNone(report['cases'][0]['evidence_snapshot'])
        self.assertTrue(all(not query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for query in queries))
        openai.assert_not_called()
        bridge.assert_not_called()
        reserve.assert_not_called()

    @override_settings(AI_TUTOR_ENABLED=True, AI_TUTOR_MINUTE_LIMIT=1, AI_TUTOR_DAILY_LIMIT=20,
                       AI_TUTOR_GLOBAL_MINUTE_LIMIT=20, AI_TUTOR_GLOBAL_DAILY_LIMIT=200)
    def test_live_pipeline_obeys_production_budget_without_real_provider_calls(self):
        staff = get_user_model().objects.create_user(username='evaluation-staff', is_staff=True)
        data = fixture(*[{**fixture()['cases'][0], 'id': str(i)} for i in range(2)])
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(output_text='Mock provider answer.', model='mock-model')
        with patch.dict('os.environ', {'AI_TUTOR_PROVIDER': 'openai', 'OPENAI_API_KEY': 'test-only'}), \
                patch('learning.ai.OpenAI', return_value=client) as provider:
            report = run_tutor_evaluation(data, live=True, user=staff, max_live_calls=2)
        self.assertEqual(report['summary']['errors'], 0)
        self.assertEqual(report['summary']['mode_counts'], {'budget_limited': 1, 'llm_rag': 1})
        self.assertEqual(report['execution']['model_answers'], 1)
        self.assertEqual(TutorUsageBudget.objects.get(user=staff).day_count, 1)
        provider.assert_called_once()
