"""Review packets preserve original evidence without certifying source quality."""
from copy import deepcopy
from datetime import timedelta
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .content_review import build_review_packet, MAX_PACKET_BYTES
from .models import AnswerOption, Flashcard, LearningContent, Question, TutorTurn


class ContentReviewPacketTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.content = LearningContent.objects.create(title='Listening pilot', exam_type='TOEIC',
            skill='listening', content_type='listening', topic='Appointments', cefr_level='B1',
            source_name='Original material', rights_note='Written for practice', review_status='language_checked',
            reviewer='AI editorial draft, not teacher approval', reviewed_at=timezone.now(), is_published=True)
        cls.questions = []
        for index in range(3):
            question = Question.objects.create(content=cls.content, order=index + 1,
                prompt=f'Why does the speaker call? {index}', passage='Exact passage.',
                audio_script='Exact listening script.', transcript='Exact transcript.',
                explanation='Exact explanation.', explanation_vi='Lời giải nguyên gốc.')
            for label in ('A', 'B', 'C', 'D'):
                AnswerOption.objects.create(question=question, label=label, text=f'Option {label} {index}',
                    is_correct=label == 'C', explanation_vi=f'Lời giải riêng {label}.')
            cls.questions.append(question)
        cls.cards = [Flashcard.objects.create(content=cls.content, term=f'word-{index}',
            meaning_vi=f'nghĩa {index}', order=index+1, example_en='Exact example.', example_vi='Ví dụ nguyên gốc.')
            for index in range(3)]

    def test_exact_evidence_key_distractor_explanations_and_blank_human_review(self):
        packet = build_review_packet([self.content.pk])
        source = packet['contents'][0]
        question = source['questions'][0]
        self.assertEqual(question['prompt'], self.questions[0].prompt)
        self.assertEqual(question['passage'], 'Exact passage.')
        self.assertEqual(question['audio_script'], 'Exact listening script.')
        self.assertEqual(question['transcript'], 'Exact transcript.')
        self.assertEqual(question['explanation_vi'], 'Lời giải nguyên gốc.')
        self.assertEqual([option['label'] for option in question['options'] if option['is_correct']], ['C'])
        self.assertEqual([option['explanation_vi'] for option in question['options']], [f'Lời giải riêng {label}.' for label in 'ABCD'])
        self.assertIsNone(question['human_review']['conclusion'])
        self.assertTrue(all(entry['result'] is None for entry in question['checklist'].values()))
        self.assertFalse(packet['approval_allowed'])
        self.assertEqual(packet['scope'], 'sample_for_human_review')

    def test_sample_coverage_and_hash_include_unexported_evidence(self):
        packet = build_review_packet([self.content.pk], max_items=1)
        source = packet['contents'][0]
        self.assertEqual(source['coverage']['questions'], {'total': 3, 'exported': 1, 'complete': False})
        self.assertEqual(source['coverage']['flashcards'], {'total': 3, 'exported': 1, 'complete': False})
        self.assertEqual(source['questions'][0]['id'], self.questions[0].pk)
        AnswerOption.objects.filter(question=self.questions[-1], label='D').update(explanation_vi='Changed unsampled distractor.')
        changed = build_review_packet([self.content.pk], max_items=1)
        self.assertNotEqual(source['content_hash'], changed['contents'][0]['content_hash'])
        self.assertNotEqual(packet['fingerprint'], changed['fingerprint'])
        self.assertEqual(source['questions'][0]['version_hash'], changed['contents'][0]['questions'][0]['version_hash'])

    def test_source_metadata_and_selected_key_changes_are_versioned(self):
        old = build_review_packet([self.content.pk])
        LearningContent.objects.filter(pk=self.content.pk).update(rights_note='Revised rights provenance')
        updated = build_review_packet([self.content.pk])
        self.assertNotEqual(old['contents'][0]['content_hash'], updated['contents'][0]['content_hash'])
        AnswerOption.objects.filter(question=self.questions[0], label='A').update(is_correct=True)
        changed = build_review_packet([self.content.pk])
        self.assertNotEqual(updated['contents'][0]['questions'][0]['version_hash'], changed['contents'][0]['questions'][0]['version_hash'])
        self.assertIn('invalid_key_count', {item['code'] for item in changed['contents'][0]['structural_findings']})

    def test_updated_at_and_generation_time_do_not_invalidate_source_or_fingerprint(self):
        first = build_review_packet([self.content.pk])
        LearningContent.objects.filter(pk=self.content.pk).update(updated_at=timezone.now() + timedelta(days=2))
        second = build_review_packet([self.content.pk])
        self.assertEqual(first['contents'][0]['content_hash'], second['contents'][0]['content_hash'])
        self.assertEqual(first['fingerprint'], second['fingerprint'])
        self.assertNotEqual(first['generated_at'], second['generated_at'])
        data = deepcopy(first)
        fingerprint = data.pop('fingerprint')
        data.pop('generated_at')
        encoded = json.dumps(json.loads(json.dumps(data)), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(fingerprint, hashlib.sha256(encoded).hexdigest())

    def test_export_queries_are_four_selects_without_personal_tables_or_provider_calls(self):
        user = get_user_model().objects.create_user(username='private-learner')
        TutorTurn.objects.create(user=user, question='PRIVATE LEARNER QUESTION', result={'answer': 'PRIVATE LEARNER ANSWER'})
        before = LearningContent.objects.values('review_status', 'is_published', 'reviewer', 'reviewed_at').get(pk=self.content.pk)
        with patch('learning.ai.OpenAI') as openai, patch('learning.ai.generate_cloudflare_answer') as cloudflare:
            with CaptureQueriesContext(connection) as queries:
                packet = build_review_packet([self.content.pk])
        self.assertEqual(len(queries), 4)
        for query in queries:
            # PostgreSQL iterator() declares a read-only server-side SELECT cursor.
            self.assertRegex(query['sql'].lstrip().upper(), r'^(?:SELECT\b|DECLARE "[^"]+"(?: NO SCROLL| SCROLL)? CURSOR(?: WITH HOLD)? FOR SELECT\b)')
            self.assertNotIn('learning_tutorturn', query['sql'])
            self.assertNotIn('auth_user', query['sql'])
        self.assertNotIn('PRIVATE LEARNER', json.dumps(packet, ensure_ascii=False))
        self.assertEqual(before, LearningContent.objects.values('review_status', 'is_published', 'reviewer', 'reviewed_at').get(pk=self.content.pk))
        openai.assert_not_called()
        cloudflare.assert_not_called()

    def test_selection_is_strict_bounded_and_missing_ids_fail_without_partial_packet(self):
        for ids in ([], [self.content.pk, self.content.pk], [True], ['1'], [-1], [2**63], [self.content.pk, 999999], list(range(1, 12)), '1', None):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                build_review_packet(ids)
        for count in (0, 101, True, '2', None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                build_review_packet([self.content.pk], max_items=count)

    def test_deterministic_parent_order_and_independent_checklists(self):
        second = LearningContent.objects.create(title='Empty draft', skill='reading', content_type='reading')
        packet = build_review_packet([second.pk, self.content.pk])
        self.assertEqual(packet['selection']['content_ids'], [self.content.pk, second.pk])
        self.assertEqual(packet['contents'][-1]['structural_findings'][0]['code'], 'empty_content')
        packet['contents'][0]['questions'][0]['checklist']['answer_key']['notes'] = 'Reviewer comment'
        self.assertEqual(packet['contents'][0]['questions'][1]['checklist']['answer_key']['notes'], '')
        self.assertEqual(build_review_packet([self.content.pk])['contents'][0]['questions'][0]['checklist']['answer_key']['notes'], '')

    def test_size_guard_fails_without_truncating_source(self):
        self.assertGreater(MAX_PACKET_BYTES, 0)
        with patch('learning.content_review.MAX_PACKET_BYTES', 100), self.assertRaises(ValueError):
            build_review_packet([self.content.pk])

    def test_command_writes_complete_json_atomically_and_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'review.json'
            call_command('export_review_packet', content_ids=[self.content.pk], max_items=1, output=output, stdout=StringIO())
            packet = json.loads(output.read_text())
            self.assertFalse(packet['approval_allowed'])
            self.assertEqual(packet['contents'][0]['coverage']['questions']['exported'], 1)
            output.write_text('KEEP EXISTING REVIEW')
            with self.assertRaises(CommandError):
                call_command('export_review_packet', content_ids=[self.content.pk], output=output, stdout=StringIO())
            self.assertEqual(output.read_text(), 'KEEP EXISTING REVIEW')
            call_command('export_review_packet', content_ids=[self.content.pk], max_items=1, output=output, overwrite=True, stdout=StringIO())
            self.assertEqual(json.loads(output.read_text())['schema_version'], packet['schema_version'])
            self.assertEqual(list(Path(directory).glob('.review-packet-*')), [])

    def test_invalid_command_selection_or_destination_does_not_create_or_replace_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'review.json'
            with self.assertRaises(CommandError):
                call_command('export_review_packet', content_ids=[self.content.pk, 999999], output=output, stdout=StringIO())
            self.assertFalse(output.exists())
            with self.assertRaises(CommandError):
                call_command('export_review_packet', content_ids=[self.content.pk], output=Path(directory) / 'missing' / 'review.json', stdout=StringIO())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_concurrent_destination_creation_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'review.json'
            def collision(*args):
                output.write_text('CONCURRENT REVIEW')
                raise FileExistsError
            with patch('learning.management.commands.export_review_packet.os.link', side_effect=collision), self.assertRaises(CommandError):
                call_command('export_review_packet', content_ids=[self.content.pk], output=output, stdout=StringIO())
            self.assertEqual(output.read_text(), 'CONCURRENT REVIEW')
            self.assertEqual(list(Path(directory).glob('.review-packet-*')), [])
