from django.test import SimpleTestCase

from .retrieval_evaluation import BENCHMARK_PATH, evaluate_cases, load_benchmark


class RetrievalMetricTests(SimpleTestCase):
    def test_metrics_count_rank_misses_and_false_abstentions(self):
        cases = [
            {'id': 'first', 'split': 'dev', 'category': 'word', 'query': 'one', 'expected_terms': ['target']},
            {'id': 'second', 'split': 'test', 'category': 'word', 'query': 'two', 'expected_terms': ['other']},
            {'id': 'negative', 'split': 'test', 'category': 'no_match', 'query': 'none', 'expected_terms': []},
        ]
        def fake(query, limit):
            return [{'term': 'wrong'}, {'term': 'target'}] if query == 'one' else []
        report = evaluate_cases(cases, fake)
        self.assertEqual(report['overall']['recall_at_3'], .5)
        self.assertEqual(report['overall']['mrr_at_3'], .25)
        self.assertEqual(report['overall']['negative_abstention_rate'], 1)
        self.assertEqual(report['overall']['abstention_precision'], .5)
        self.assertEqual(report['overall']['false_positive_negatives'], 0)

    def test_wrong_bank_sense_can_pass_headword_metric_but_fails_sense_metric(self):
        case = {'id': 'sense', 'split': 'dev', 'category': 'sense', 'query': 'bank finance',
                'expected_terms': ['bank'],
                'expected_senses': [{'term': 'bank', 'meaning_vi': 'ngân hàng'}]}
        result = evaluate_cases([case], lambda query, limit: [{'term': 'bank', 'meaning_vi': 'bờ sông'}])
        overall = result['overall']
        self.assertEqual(overall['recall_at_3'], 1)
        self.assertEqual(overall['sense_labeled_queries'], 1)
        self.assertEqual(overall['sense_recall_at_3'], 0)
        self.assertEqual(overall['sense_mrr_at_3'], 0)
        self.assertEqual(result['cases'][0]['retrieved_senses'], [{'term': 'bank', 'meaning_vi': 'bờ sông'}])

    def test_strict_sense_recall_and_rank_use_distinct_labeled_pairs(self):
        case = {'id': 'senses', 'split': 'dev', 'category': 'sense', 'query': 'two terms',
                'expected_terms': ['bank', 'charge'], 'expected_senses': [
                    {'term': 'bank', 'meaning_vi': 'ngân hàng'}, {'term': 'charge', 'meaning_vi': 'khoản phí'}]}
        retrieved = [{'term': 'bank', 'meaning_vi': 'bờ sông'},
                     {'term': 'charge', 'meaning_vi': 'khoản phí'},
                     {'term': 'charge', 'meaning_vi': 'khoản phí'}]
        overall = evaluate_cases([case], lambda query, limit: retrieved)['overall']
        self.assertEqual(overall['recall_at_3'], 1)
        self.assertEqual(overall['sense_recall_at_3'], .5)
        self.assertEqual(overall['sense_hit_at_3'], 1)
        self.assertEqual(overall['sense_mrr_at_3'], .5)

    def test_sense_normalization_accepts_unicode_form_case_spacing_but_keeps_accents(self):
        import unicodedata
        case = {'id': 'unicode', 'split': 'dev', 'category': 'sense', 'query': 'unicode',
                'expected_terms': ['bank'], 'expected_senses': [{'term': 'bank', 'meaning_vi': 'Má  thờ'}]}
        for meaning, expected in [(unicodedata.normalize('NFD', ' MÁ\tTHỜ '), 1), ('Ma tho', 0), ('Má thờ.', 0)]:
            with self.subTest(meaning=meaning):
                result = evaluate_cases([case], lambda query, limit: [{'term': ' BANK ', 'meaning_vi': meaning}])
                self.assertEqual(result['overall']['sense_recall_at_3'], expected)

    def test_ambiguity_is_separate_top_result_decision_not_sense_correctness(self):
        cases = [{'id': str(required), 'split': 'dev', 'category': 'sense', 'query': str(required),
                  'expected_terms': ['bank'], 'expected_senses': [{'term': 'bank', 'meaning_vi': 'ngân hàng'}],
                  'ambiguity_required': required} for required in (True, False)]
        def fake(query, limit):
            return [{'term': 'bank', 'meaning_vi': 'bờ sông', 'ambiguous': query == 'True'},
                    {'term': 'other', 'meaning_vi': 'khác', 'ambiguous': True}]
        result = evaluate_cases(cases, fake)
        self.assertEqual(result['overall']['ambiguity_labeled_queries'], 2)
        self.assertEqual(result['overall']['ambiguity_accuracy'], 1)
        self.assertEqual(result['overall']['sense_recall_at_3'], 0)
        cases[0]['ambiguity_required'] = False
        self.assertEqual(evaluate_cases(cases, fake)['overall']['ambiguity_accuracy'], .5)

    def test_missing_top_result_is_not_a_correct_no_ambiguity_decision(self):
        case = {'id':'empty', 'split':'dev', 'category':'sense', 'query':'bank',
                'expected_terms':['bank'], 'ambiguity_required':False}
        report = evaluate_cases([case], lambda query,limit: [])
        self.assertEqual(report['overall']['ambiguity_accuracy'],0)

    def test_optional_labels_report_no_denominator_or_accuracy_when_absent(self):
        cases = [{'id': 'legacy', 'split': 'dev', 'category': 'word', 'query': 'bank', 'expected_terms': ['bank']}]
        overall = evaluate_cases(cases, lambda query, limit: [{'term': 'bank'}])['overall']
        self.assertEqual((overall['recall_at_3'], overall['mrr_at_3']), (1, 1))
        self.assertEqual(overall['sense_labeled_queries'], 0)
        self.assertEqual(overall['ambiguity_labeled_queries'], 0)
        for key in ('sense_recall_at_3', 'sense_hit_at_3', 'sense_mrr_at_3', 'ambiguity_accuracy'):
            self.assertIsNone(overall[key])

    def test_load_validates_sense_labels_and_ambiguity_types(self):
        valid = {'id': 'valid', 'split': 'dev', 'category': 'sense', 'query': 'bank', 'expected_terms': ['bank'],
                 'expected_senses': [{'term': ' BANK ', 'meaning_vi': 'ngân hàng'}], 'ambiguity_required': False}
        invalid_updates = [
            {'expected_senses': []}, {'expected_senses': None}, {'expected_senses': 'bank'},
            {'expected_senses': ['bank']}, {'expected_senses': [{'term': 'bank'}]},
            {'expected_senses': [{'term': 'bank', 'meaning_vi': ''}]},
            {'expected_senses': [{'term': 'bank', 'meaning_vi': 5}]},
            {'expected_senses': [{'term': 'bank', 'meaning_vi': 'ngân hàng', 'other': 'unknown'}]},
            {'expected_senses': [{'term': 'charge', 'meaning_vi': 'khoản phí'}]},
            {'expected_senses': [{'term': 'bank', 'meaning_vi': 'ngân hàng'}, {'term': ' BANK ', 'meaning_vi': 'NGÂN  HÀNG'}]},
            {'ambiguity_required': 1}, {'ambiguity_required': 'false'}, {'ambiguity_required': None},
            {'expected_terms': []}, {'expected_terms': ['bank', ' BANK ']}, {'category': ''},
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'benchmark.json'
            path.write_text(json.dumps({'cases': [valid]}))
            self.assertEqual(load_benchmark(path)['cases'][0], valid)
            for update in invalid_updates:
                with self.subTest(update=update):
                    path.write_text(json.dumps({'cases': [{**valid, **update}]}))
                    with self.assertRaises(ValueError):
                        load_benchmark(path)

            for first, second in [('bank', ' BANK '), ('café', 'cafe\u0301')]:
                aliases=[{'id':str(i),'split':split,'category':'word','query':term,'expected_terms':[term]}
                    for i,(split,term) in enumerate([('dev',first),('test',second)])]
                path.write_text(json.dumps({'cases':aliases}))
                with self.assertRaisesMessage(ValueError, 'dev và test'):
                    load_benchmark(path)

    def test_load_rejects_non_object_duplicate_keys_and_nonfinite_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'benchmark.json'
            for raw in ('[]', 'null', '5', '{"cases":[],"cases":[]}', '{"cases":[],"number":NaN}'):
                with self.subTest(raw=raw):
                    path.write_text(raw)
                    with self.assertRaises(ValueError):
                        load_benchmark(path)

    def test_fixed_benchmark_has_disjoint_term_groups_and_balanced_splits(self):
        benchmark = load_benchmark()
        self.assertEqual(len(benchmark['cases']), 96)
        for split in ('dev', 'test'):
            rows = [case for case in benchmark['cases'] if case['split'] == split]
            self.assertEqual(len(rows), 48)
            self.assertEqual(sum(not c['expected_terms'] for c in rows), 8)


    def test_v2_has_new_target_groups_and_balanced_frozen_splits(self):
        original = load_benchmark()
        benchmark = load_benchmark(BENCHMARK_PATH.with_name('retrieval_benchmark_v2.json'))
        old_terms = {term.casefold() for case in original['cases'] for term in case['expected_terms']}
        new_terms = {term.casefold() for case in benchmark['cases'] for term in case['expected_terms']}
        self.assertEqual(len(new_terms), 20)
        self.assertFalse(old_terms & new_terms)
        self.assertEqual(len(benchmark['cases']), 96)
        for split in ('dev', 'test'):
            rows = [case for case in benchmark['cases'] if case['split'] == split]
            self.assertEqual(len(rows), 48)
            self.assertEqual(sum(not c['expected_terms'] for c in rows), 8)


from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase


class RetrievalEvaluationCommandTests(TestCase):
    def test_default_hides_test_feedback_and_final_report_excludes_case_gold(self):
        benchmark = {'version': 'test', 'cases': [
            {'id': 'd', 'split': 'dev', 'category': 'no_match', 'query': 'development', 'expected_terms': []},
            {'id': 't', 'split': 'test', 'category': 'no_match', 'query': 'held-out', 'expected_terms': []},
        ]}
        with TemporaryDirectory() as directory, \
             patch('learning.management.commands.evaluate_retrieval.load_benchmark', return_value=benchmark), \
             patch('learning.management.commands.evaluate_retrieval.baseline_retrieve', return_value=[]) as baseline, \
             patch('learning.retrieval.retrieve_context', return_value=[]) as improved:
            target = Path(directory) / 'metrics.json'
            output = StringIO()
            call_command('evaluate_retrieval', output=str(target), stdout=output)
            self.assertNotIn(' test:', output.getvalue())
            self.assertEqual([call.args[0] for call in improved.call_args_list], ['development'])
            self.assertEqual([call.args[0] for call in baseline.call_args_list], ['development'])
            report = json.loads(target.read_text())
            self.assertEqual(set(report['improved']['by_split']), {'dev'})
            baseline.reset_mock()
            improved.reset_mock()
            call_command('evaluate_retrieval', include_test=True, output=str(target), overwrite=True, stdout=StringIO())
            report = json.loads(target.read_text())
            self.assertEqual(set(report['improved']['by_split']), {'dev', 'test'})
            self.assertTrue(report['includes_test'])
            self.assertNotIn('cases', report['baseline'])
            self.assertNotIn('cases', report['improved'])
            self.assertNotIn('held-out', target.read_text())

    def test_dev_run_does_not_validate_or_reveal_missing_test_gold(self):
        benchmark = {'version': 'test', 'cases': [
            {'id': 'd', 'split': 'dev', 'category': 'no_match', 'query': 'development', 'expected_terms': []},
            {'id': 't', 'split': 'test', 'category': 'word', 'query': 'hidden', 'expected_terms': ['unseen-test-only-term']},
        ]}
        with patch('learning.management.commands.evaluate_retrieval.load_benchmark', return_value=benchmark):
            output = StringIO()
            call_command('evaluate_retrieval', stdout=output)
            self.assertNotIn('unseen-test-only-term', output.getvalue())
            from django.core.management.base import CommandError
            with self.assertRaisesMessage(CommandError, 'unseen-test-only-term'):
                call_command('evaluate_retrieval', include_test=True, stdout=StringIO())
