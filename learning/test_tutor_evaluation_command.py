"""Evaluation CLI is offline by default and validates destinations before calls."""
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .management.commands.evaluate_tutor_answers import ROOT, _atomic_report


COMMAND_MODULE = 'learning.management.commands.evaluate_tutor_answers'


class TutorEvaluationCommandTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'cases.json'
        self.output = Path(self.directory.name) / 'report.json'
        self.fixture = {'version': 'test-editorial-v1',
            'provenance': 'AI-editorial regression; not an independent holdout.',
            'cases': [{'id': 'grammar', 'category': 'grammar',
                'query': 'Giải thích despite và although',
                'expected': [{'kind': 'knowledge', 'knowledge_id': 'despite-although'}]}]}
        self.source.write_text(json.dumps(self.fixture, ensure_ascii=False), encoding='utf-8')

    def run_command(self, **options):
        defaults = {'cases': self.source, 'output': self.output, 'stdout': StringIO()}
        call_command('evaluate_tutor_answers', **{**defaults, **options})

    def test_offline_runs_real_tutor_without_model_quota_or_database_writes(self):
        with patch('learning.ai.OpenAI') as openai, \
             patch('learning.ai.generate_cloudflare_answer') as bridge, \
             patch('learning.ai.reserve_tutor_call') as reserve, \
             CaptureQueriesContext(connection) as queries:
            self.run_command()
        report = json.loads(self.output.read_text())
        self.assertEqual(report['summary']['errors'], 0)
        self.assertEqual(report['cases'][0]['result']['mode'], 'retrieval_only')
        self.assertIn('despite', report['cases'][0]['result']['answer'].lower())
        self.assertRegex(report['run_provenance']['fixture_file_sha256'], r'^[0-9a-f]{64}$')
        self.assertIn('learning/ai.py', report['run_provenance']['code_sha256'])
        openai.assert_not_called()
        bridge.assert_not_called()
        reserve.assert_not_called()
        self.assertTrue(all(not item['sql'].lstrip().upper().startswith(
            ('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP')) for item in queries))

    def test_existing_output_is_preserved_before_any_evaluation(self):
        self.output.write_text('keep existing report')
        with patch(f'{COMMAND_MODULE}.run_tutor_evaluation') as run:
            with self.assertRaisesMessage(CommandError, 'already exists'):
                self.run_command()
        self.assertEqual(self.output.read_text(), 'keep existing report')
        run.assert_not_called()

    def test_explicit_overwrite_replaces_report_but_preserves_fixture(self):
        original = self.source.read_bytes()
        self.output.write_text('old report')
        self.run_command(overwrite=True)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(json.loads(self.output.read_text())['summary']['errors'], 0)
        self.assertEqual(list(Path(self.directory.name).glob('.tutor-evaluation-*.tmp')), [])

    def test_malformed_fixture_cannot_replace_an_existing_report(self):
        self.output.write_text('keep report')
        self.source.write_text('{"cases":NaN}')
        with patch(f'{COMMAND_MODULE}.run_tutor_evaluation') as run:
            with self.assertRaises(CommandError):
                self.run_command(overwrite=True)
        self.assertEqual(self.output.read_text(), 'keep report')
        run.assert_not_called()

    def test_live_only_flags_are_rejected_in_offline_mode_before_evaluation(self):
        with patch(f'{COMMAND_MODULE}.run_tutor_evaluation') as run:
            for options in ({'user_id': 1}, {'max_live_calls': 1}, {'max_live_calls': -1}):
                with self.subTest(options=options), self.assertRaisesMessage(CommandError, 'require --live'):
                    self.run_command(**options)
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_live_requires_explicit_bounded_cap_and_existing_active_staff(self):
        users = get_user_model()
        learner = users.objects.create_user(username='not-staff')
        inactive = users.objects.create_user(username='inactive-staff', is_staff=True, is_active=False)
        with patch(f'{COMMAND_MODULE}.run_tutor_evaluation') as run:
            options = ({'live': True}, {'live': True, 'user_id': 1},
                {'live': True, 'user_id': 1, 'max_live_calls': 11},
                {'live': True, 'user_id': 0, 'max_live_calls': 1},
                {'live': True, 'user_id': 999999, 'max_live_calls': 1},
                {'live': True, 'user_id': learner.pk, 'max_live_calls': 1},
                {'live': True, 'user_id': inactive.pk, 'max_live_calls': 1})
            for values in options:
                with self.subTest(options=values), self.assertRaises(CommandError):
                    self.run_command(**values)
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_live_case_count_is_checked_before_any_request(self):
        staff = get_user_model().objects.create_user(username='eval-staff', is_staff=True)
        self.fixture['cases'].append({**self.fixture['cases'][0], 'id': 'grammar-two'})
        self.source.write_text(json.dumps(self.fixture))
        with patch(f'{COMMAND_MODULE}.run_tutor_evaluation') as run:
            with self.assertRaisesMessage(CommandError, 'exceeds --max-live-calls'):
                self.run_command(live=True, user_id=staff.pk, max_live_calls=1)
        run.assert_not_called()

    def test_explicit_live_mode_passes_staff_and_cap_without_calling_a_real_model(self):
        staff = get_user_model().objects.create_user(username='bounded-eval', is_staff=True)
        report = {'version': 'test', 'summary': {'errors': 0}, 'cases': []}
        with patch(f'{COMMAND_MODULE}.run_tutor_evaluation', return_value=report) as run:
            self.run_command(live=True, user_id=staff.pk, max_live_calls=1)
        kwargs = run.call_args.kwargs
        self.assertTrue(kwargs['live'])
        self.assertEqual(kwargs['max_live_calls'], 1)
        self.assertEqual(kwargs['user'].pk, staff.pk)
        self.assertTrue(self.output.exists())

    def test_fixture_cannot_be_replaced_via_same_path_symlink_or_hard_link(self):
        original = self.source.read_bytes()
        symlink = Path(self.directory.name) / 'symlink.json'
        hardlink = Path(self.directory.name) / 'hardlink.json'
        symlink.symlink_to(self.source)
        os.link(self.source, hardlink)
        with patch(f'{COMMAND_MODULE}.run_tutor_evaluation') as run:
            for target in (self.source, symlink, hardlink):
                with self.subTest(target=target), self.assertRaises(CommandError):
                    self.run_command(output=target, overwrite=True)
        self.assertEqual(self.source.read_bytes(), original)
        run.assert_not_called()

    def test_report_cannot_replace_code_or_json_in_source_directories(self):
        with patch(f'{COMMAND_MODULE}.run_tutor_evaluation') as run:
            for target in (ROOT / 'learning' / 'data' / 'retrieval_benchmark.json',
                           ROOT / 'learning' / 'would-be-report.json',
                           ROOT / 'learning' / 'ai.py'):
                with self.subTest(target=target), self.assertRaises(CommandError):
                    self.run_command(output=target, overwrite=True)
        run.assert_not_called()

    def test_unknown_directory_non_json_and_symbolic_output_are_rejected_before_calls(self):
        dangling = Path(self.directory.name) / 'dangling.json'
        dangling.symlink_to(Path(self.directory.name) / 'missing.json')
        with patch(f'{COMMAND_MODULE}.run_tutor_evaluation') as run:
            for target in (Path(self.directory.name) / 'missing' / 'report.json',
                           self.output.with_suffix('.txt'), dangling):
                with self.subTest(target=target), self.assertRaises(CommandError):
                    self.run_command(output=target)
        run.assert_not_called()

    def test_atomic_exclusive_write_preserves_racing_report_and_removes_temporary(self):
        link = os.link

        def race(source, target):
            self.output.write_text('another evaluator won')
            return link(source, target)

        with patch(f'{COMMAND_MODULE}.os.link', side_effect=race):
            with self.assertRaisesMessage(CommandError, 'destination was not replaced'):
                _atomic_report(self.output, b'{"new":true}', overwrite=False)
        self.assertEqual(self.output.read_text(), 'another evaluator won')
        self.assertEqual(list(Path(self.directory.name).glob('.tutor-evaluation-*.tmp')), [])

    def test_case_errors_are_saved_before_command_reports_failure(self):
        report = {'version': 'test', 'summary': {'errors': 1},
            'cases': [{'id': 'grammar', 'error': 'case_execution_failed', 'result': None}]}
        with patch(f'{COMMAND_MODULE}.run_tutor_evaluation', return_value=report):
            with self.assertRaisesMessage(CommandError, 'saved report records redacted'):
                self.run_command()
        self.assertEqual(json.loads(self.output.read_text())['cases'][0]['error'], 'case_execution_failed')

    def test_invalid_or_oversized_result_cannot_replace_existing_report(self):
        self.output.write_text('keep old report')
        for report in ({'summary': {'errors': 0}, 'bad': float('inf')},
                       {'summary': {'errors': 0}, 'answer': 'too large'}):
            with self.subTest(report=report), \
                 patch(f'{COMMAND_MODULE}.run_tutor_evaluation', return_value=report), \
                 patch(f'{COMMAND_MODULE}.MAX_REPORT_BYTES', 10):
                with self.assertRaises(CommandError):
                    self.run_command(overwrite=True)
        self.assertEqual(self.output.read_text(), 'keep old report')
