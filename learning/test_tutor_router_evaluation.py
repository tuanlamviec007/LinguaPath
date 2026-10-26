from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from .management.commands.evaluate_tutor_router import DEFAULT_CASES, evaluate, load_cases
from .models import Flashcard, LearningContent


class TutorRouterMetricTests(SimpleTestCase):
    def test_multisource_coverage_requires_all_notes_and_counts_extra_sources(self):
        cases = [
            {'id': 'comparison', 'category': 'multi', 'query': 'compare', 'expected': [
                {'kind': 'knowledge', 'knowledge_id': 'present-perfect'},
                {'kind': 'knowledge', 'knowledge_id': 'passive'}]},
            {'id': 'negative', 'category': 'no_match', 'query': 'negative', 'expected': []},
            {'id': 'abstained', 'category': 'no_match', 'query': 'empty', 'expected': []},
        ]

        def retrieve(query, **kwargs):
            return [] if query == 'empty' else [{'kind': 'knowledge', 'source_id': 'passive'}]

        report = evaluate(cases, retrieve, exam='TOEIC', limit=3)
        self.assertEqual(report['overall']['positive_coverage'], .5)
        self.assertEqual(report['overall']['exact_matches'], 1)
        self.assertEqual(report['overall']['negative_abstention_rate'], .5)
        self.assertEqual(report['overall']['omissions'], 1)
        self.assertEqual(report['overall']['false_positives'], 1)
        self.assertEqual(report['cases'][0]['omissions'], [('knowledge', 'present-perfect')])
        self.assertEqual(report['by_category']['multi']['expected_sources'], 2)

    def test_unknown_retrieved_kind_cannot_disappear_as_abstention(self):
        cases = [{'id': 'negative', 'category': 'no_match', 'query': 'none', 'expected': []}]
        report = evaluate(cases, lambda *args, **kwargs: [{'kind': 'question', 'source_id': 123}], exam='TOEIC', limit=3)
        self.assertEqual(report['overall']['negative_abstention_rate'], 0)
        self.assertEqual(report['overall']['false_positives'], 1)

    def test_default_fixture_declares_editorial_status_and_all_note_ids(self):
        fixture = load_cases(DEFAULT_CASES)
        self.assertIn('not independent holdout', fixture['provenance'])
        ids = {item['knowledge_id'] for row in fixture['cases'] for item in row['expected'] if item['kind'] == 'knowledge'}
        self.assertEqual(ids, {'despite-although', 'responsible-for', 'subject-verb', 'present-perfect',
                              'passive', 'word-forms', 'listening-strategy', 'reading-strategy'})


class TutorRouterCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        content = LearningContent.objects.create(title='Router test vocabulary', exam_type='TOEIC',
            content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
        Flashcard.objects.create(content=content, term='reading', meaning_vi='số đo hiển thị',
                                 part_of_speech='noun', example_en='The reading is accurate.')

    def run_report(self, directory, cases):
        path = Path(directory) / 'cases.json'
        target = Path(directory) / 'report.json'
        path.write_text(json.dumps({'version': 'test', 'provenance': 'AI-editorial regression; not independent holdout',
                                    'cases': cases}), encoding='utf-8')
        output = StringIO()
        call_command('evaluate_tutor_router', cases=str(path), output=str(target), stdout=output)
        return json.loads(target.read_text()), output.getvalue()

    def test_production_router_compares_notes_and_quotes_reading_lexically_without_inference_or_db_writes(self):
        cases = [
            {'id': 'comparison', 'category': 'multi', 'query': 'Compare present perfect and passive voice',
             'expected': [{'kind': 'knowledge', 'knowledge_id': 'present-perfect'}, {'kind': 'knowledge', 'knowledge_id': 'passive'}]},
            {'id': 'incidental', 'category': 'negative', 'query': 'Why is the thermometer reading inaccurate?', 'expected': []},
            {'id': 'quoted', 'category': 'lexical', 'query': 'Define the word “reading”',
             'expected': [{'kind': 'flashcard', 'term': 'reading'}]},
        ]
        with TemporaryDirectory() as directory, CaptureQueriesContext(connection) as queries, \
             patch('learning.ai.OpenAI') as openai, patch('learning.ai.generate_cloudflare_answer') as bridge:
            report, output = self.run_report(directory, cases)
        self.assertEqual(report['overall']['exact_matches'], 3)
        self.assertEqual(report['overall']['positive_coverage'], 1)
        self.assertEqual(report['overall']['negative_abstention_rate'], 1)
        self.assertEqual(report['visible_card_count'], 1)
        self.assertEqual(report['cases'][2]['actual'], [['flashcard', 'reading']])
        self.assertIn('not an independent holdout', output)
        self.assertEqual(set(report['router_sha256']), {'ai.py', 'retrieval.py'})
        for name in ('fixture_sha256', 'corpus_sha256', 'knowledge_sha256'):
            self.assertRegex(report[name], r'^[0-9a-f]{64}$')
        openai.assert_not_called()
        bridge.assert_not_called()
        mutations = [query['sql'] for query in queries if query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'ALTER', 'CREATE', 'DROP'))]
        self.assertEqual(mutations, [])

    def test_invalid_fixture_and_limit_are_command_errors(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'cases.json'
            for data in ([], {'cases': []}, {'provenance': 'editorial', 'cases': [
                {'id': 'x', 'category': 'test', 'query': 'hello', 'expected': [{'kind': 'question', 'question_id': 1}]}]}):
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(CommandError):
                    call_command('evaluate_tutor_router', cases=str(path), stdout=StringIO())
            with self.assertRaisesMessage(CommandError, '--limit'):
                call_command('evaluate_tutor_router', limit=0, stdout=StringIO())

    def test_report_cannot_overwrite_fixture(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'cases.json'
            original = json.dumps({'version': 'test', 'provenance': 'AI-editorial regression', 'cases': [
                {'id': 'negative', 'category': 'no_match', 'query': 'xyzzynonexistenttoken', 'expected': []}]})
            path.write_text(original, encoding='utf-8')
            with self.assertRaisesMessage(CommandError, 'separate JSON'):
                call_command('evaluate_tutor_router', cases=str(path), output=str(path), stdout=StringIO())
            self.assertEqual(path.read_text(), original)
