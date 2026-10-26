from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase

from .tutor_scoring import build_tutor_scorecard, canonical_hash, score_tutor_run


def sample_run(mode='offline', answer_mode='retrieval_only'):
    return {'version': 'linguapath-tutor-evaluation-v1',
        'execution': {'mode': mode, 'public_context_only': True},
        'cases': [{'id': 'sample', 'query': 'Explain despite.', 'error': None,
            'result': {'mode': answer_mode, 'answer': 'An explanation.'}}]}


def fill_card(card):
    for review in card['reviews']:
        review['reviewer'].update(name='Test reviewer', qualifications='Test declaration only', reviewed_at='2026-10-25')
        for entry in review['criteria'].values():
            entry.update(result='pass', notes='Test evidence.')
    return card


class TutorScoringTests(SimpleTestCase):
    def test_blank_card_is_pending_and_no_model_quality_is_invented(self):
        run = sample_run()
        before = deepcopy(run)
        card = build_tutor_scorecard(run)
        report = score_tutor_run(run, card)
        self.assertEqual(run, before)
        self.assertEqual(report['summary']['pending_reviews'], 1)
        self.assertEqual(report['summary']['model_answers']['total'], 0)
        self.assertFalse(report['release_approval'])
        self.assertFalse(report['reviewer_identity_verified'])
        self.assertFalse(report['independent_holdout_verified'])

    def test_fully_assessed_failure_is_complete_but_remains_a_failure(self):
        run = sample_run('live', 'llm_rag')
        card = fill_card(build_tutor_scorecard(run))
        card['reviews'][0]['criteria']['grounding'].update(result='fail', notes='Unsupported claim in test.')
        report = score_tutor_run(run, card)
        self.assertEqual(report['summary']['completed_reviews'], 1)
        self.assertEqual(report['summary']['cases_with_failures'], 1)
        self.assertEqual(report['summary']['model_answers'], {'total':1,'reviewed':1,'with_failures':1})
        self.assertFalse(report['release_approval'])
        self.assertNotIn('Test reviewer', json.dumps(report))
        self.assertNotIn('Unsupported claim', json.dumps(report))

    def test_changed_run_answer_or_execution_does_not_reuse_old_scorecard(self):
        run = sample_run()
        card = fill_card(build_tutor_scorecard(run))
        for mutate in (lambda x:x['cases'][0]['result'].update(answer='Changed'),
                       lambda x:x['execution'].update(mode='live'),
                       lambda x:x.update(generated_at='new run')):
            changed = deepcopy(run); mutate(changed)
            with self.assertRaises(ValueError): score_tutor_run(changed, card)

    def test_evidence_snapshot_hash_is_verified_before_creating_scorecard(self):
        run = sample_run()
        evidence = {'retrieved': [{'text': 'Original source'}], 'packed': None}
        run['cases'][0]['evidence_snapshot'] = {**evidence, 'sha256': canonical_hash(evidence)}
        build_tutor_scorecard(run)
        run['cases'][0]['evidence_snapshot']['retrieved'][0]['text'] = 'Changed source'
        with self.assertRaises(ValueError): build_tutor_scorecard(run)

    def test_missing_reordered_duplicate_or_changed_rubric_is_rejected(self):
        run = sample_run()
        card = build_tutor_scorecard(run)
        changes = [lambda x:x['reviews'].clear(),
            lambda x:x['reviews'][0].update(case_id='other'),
            lambda x:x['criteria_template']['correctness'].update(result='pass'),
            lambda x:x['reviews'][0]['criteria'].pop('grounding'),
            lambda x:x['reviews'][0]['reviewer'].update(extra='forbidden')]
        for mutate in changes:
            changed = deepcopy(card); mutate(changed)
            with self.assertRaises(ValueError): score_tutor_run(run, changed)

    def test_dates_enums_and_text_bounds_are_checked(self):
        run = sample_run(); card = fill_card(build_tutor_scorecard(run))
        changes = [lambda x:x['reviews'][0]['reviewer'].update(reviewed_at='2026-02-30'),
            lambda x:x['reviews'][0]['reviewer'].update(reviewed_at='2026-10-25T12:00:00'),
            lambda x:x['reviews'][0]['reviewer'].update(name='a'*201),
            lambda x:x['reviews'][0]['criteria']['correctness'].update(result=[]),
            lambda x:x['reviews'][0]['criteria']['correctness'].update(result='approved'),
            lambda x:x['reviews'][0]['criteria']['correctness'].update(notes='x'*4001)]
        for mutate in changes:
            changed = deepcopy(card); mutate(changed)
            with self.assertRaises(ValueError): score_tutor_run(run, changed)

    def test_failed_or_not_applicable_checks_need_explanation(self):
        run = sample_run(); card = fill_card(build_tutor_scorecard(run))
        card['reviews'][0]['criteria']['injection_resistance'].update(result='not_applicable', notes='')
        self.assertEqual(score_tutor_run(run, card)['summary']['pending_reviews'], 1)
        card['reviews'][0]['criteria']['injection_resistance']['notes'] = 'No injection scenario in this case.'
        self.assertEqual(score_tutor_run(run, card)['summary']['completed_reviews'], 1)
        card['reviews'][0]['criteria']['correctness']['result'] = 'not_applicable'
        with self.assertRaises(ValueError): score_tutor_run(run, card)

    def test_model_grounding_cannot_be_marked_not_applicable(self):
        run = sample_run('live','llm_rag'); card = fill_card(build_tutor_scorecard(run))
        card['reviews'][0]['criteria']['grounding'].update(result='not_applicable', notes='A reason')
        with self.assertRaises(ValueError): score_tutor_run(run, card)

    def test_execution_errors_cannot_be_graded_as_successful_answers(self):
        run = sample_run(); run['cases'][0].update(result=None,error='case_execution_failed')
        card = fill_card(build_tutor_scorecard(run))
        report = score_tutor_run(run, card)
        self.assertEqual(report['summary']['unreviewable_cases'], 1)
        self.assertEqual(report['summary']['completed_reviews'], 0)
        self.assertFalse(report['cases'][0]['reviewable'])

    def test_command_exports_then_scores_without_model_or_db_access(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'run.json'; cardpath=Path(directory)/'card.json'; reportpath=Path(directory)/'score.json'
            source.write_text(json.dumps(sample_run()))
            with patch('learning.ai.OpenAI') as openai, patch('learning.ai.generate_cloudflare_answer') as cloudflare:
                call_command('review_tutor_answers', run=source,output=cardpath,stdout=StringIO())
                card=json.loads(cardpath.read_text()); fill_card(card); cardpath.write_text(json.dumps(card))
                call_command('review_tutor_answers', run=source,scorecard=cardpath,output=reportpath,stdout=StringIO())
            self.assertEqual(json.loads(reportpath.read_text())['summary']['completed_reviews'],1)
            openai.assert_not_called(); cloudflare.assert_not_called()

    def test_command_preserves_inputs_existing_outputs_and_rejects_duplicate_json(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'run.json'; output=Path(directory)/'output.json'
            original=json.dumps(sample_run()); source.write_text(original); output.write_text('KEEP')
            for kwargs in ({'output':source,'overwrite':True},{'output':output}):
                with self.assertRaises(CommandError): call_command('review_tutor_answers',run=source,stdout=StringIO(),**kwargs)
            self.assertEqual(source.read_text(),original); self.assertEqual(output.read_text(),'KEEP')
            source.write_text('{"version":1,"version":2}')
            with self.assertRaises(CommandError): call_command('review_tutor_answers',run=source,output=output,overwrite=True,stdout=StringIO())
            self.assertEqual(output.read_text(),'KEEP')
