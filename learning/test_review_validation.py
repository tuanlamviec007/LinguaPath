"""Read-only validation never turns editor notes into professional approval."""
from copy import deepcopy
from datetime import timedelta
from io import BytesIO, StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .content_review import build_review_packet, CHECKLIST_TEMPLATE, HUMAN_REVIEW_TEMPLATE, _hash
from .models import AnswerOption, Flashcard, LearningContent, Question
from .review_validation import load_review_packet, ReviewPacketLoadError, validate_review_packet


class ReviewValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.content = LearningContent.objects.create(title='Editorial sample', exam_type='TOEIC',
            skill='reading', content_type='reading', cefr_level='B1',
            review_status='language_checked', is_published=True)
        cls.cards = [Flashcard.objects.create(content=cls.content, order=index, term=f'word{index}',
            meaning_vi=f'nghĩa {index}', example_en='A source example.', example_vi='Một ví dụ.') for index in range(1, 3)]
        cls.question = Question.objects.create(content=cls.content, prompt='SECRET SOURCE PROMPT',
            passage='SECRET SOURCE PASSAGE', explanation='SECRET SOURCE EXPLANATION')
        for label in 'AB':
            AnswerOption.objects.create(question=cls.question, label=label, text=f'SECRET OPTION {label}',
                is_correct=label == 'A', explanation_vi='SECRET DISTRACTOR EXPLANATION')

    def packet(self, maximum=1):
        return build_review_packet([self.content.pk], max_items=maximum)

    def complete(self, packet, *, conclusion='pass', result='pass'):
        for record in packet['contents']:
            for item in [*record['flashcards'], *record['questions']]:
                item['human_review'].update(reviewer_name='Named reviewer', qualifications='Relevant qualification, self-declared',
                    reviewed_at='2026-10-25', conclusion=conclusion, notes='Reviewer notes for this decision.')
                for entry in item['checklist'].values():
                    entry.update(result=result, notes='Reviewer evidence for this check.')
        return packet

    def test_blank_current_draft_is_valid_pending_and_not_approved(self):
        report = validate_review_packet(self.packet())
        self.assertEqual(report['status'], 'current')
        self.assertTrue(report['source_matches'])
        self.assertFalse(report['annotations_complete'])
        self.assertFalse(report['approval_allowed'])
        self.assertFalse(report['sample_covers_all_selected_sources'])
        self.assertEqual(report['summary']['items_total'], 2)
        self.assertEqual(report['summary']['items_pending'], 2)
        self.assertEqual(report['summary']['conclusions']['pending'], 2)
        self.assertEqual(report['problems'], [])

    def test_complete_per_item_annotations_allow_optional_shared_header(self):
        packet = self.complete(self.packet(2))
        report = validate_review_packet(packet)
        self.assertEqual(report['status'], 'current')
        self.assertTrue(report['annotations_complete'])
        self.assertTrue(report['sample_covers_all_selected_sources'])
        self.assertFalse(report['summary']['packet_reviewer_complete'])
        self.assertEqual(report['summary']['items_complete'], 3)
        self.assertEqual(report['summary']['checklist_completed'], 18)
        self.assertEqual(report['summary']['conclusions']['pass'], 3)
        self.assertTrue(all(item['complete'] for item in report['items']))

    def test_shared_header_never_supplies_missing_per_item_identity(self):
        packet = self.complete(self.packet())
        packet['human_review'] = deepcopy(packet['contents'][0]['flashcards'][0]['human_review'])
        packet['contents'][0]['flashcards'][0]['human_review']['reviewer_name'] = ''
        report = validate_review_packet(packet)
        self.assertTrue(report['summary']['packet_reviewer_complete'])
        self.assertFalse(report['annotations_complete'])
        self.assertEqual(report['summary']['items_pending'], 1)

    def test_failed_and_not_applicable_checks_require_notes_for_completeness(self):
        packet = self.complete(self.packet(), conclusion='needs_changes', result='fail')
        item = packet['contents'][0]['questions'][0]
        item['checklist']['audio_and_accessibility'].update(result='not_applicable', notes='')
        report = validate_review_packet(packet)
        self.assertEqual(report['status'], 'current')
        self.assertFalse(report['annotations_complete'])
        self.assertIn('missing_check_notes', {problem['code'] for problem in report['problems']})
        item['checklist']['audio_and_accessibility']['notes'] = 'No audio is supplied for this reading item.'
        self.assertTrue(validate_review_packet(packet)['annotations_complete'])
        item['human_review']['notes'] = ''
        report = validate_review_packet(packet)
        self.assertFalse(report['annotations_complete'])
        self.assertIn('missing_conclusion_notes', {problem['code'] for problem in report['problems']})

    def test_pass_conflicting_with_failure_or_item_needing_changes_is_invalid(self):
        packet = self.complete(self.packet())
        packet['contents'][0]['questions'][0]['checklist']['answer_key']['result'] = 'fail'
        self.assertEqual(validate_review_packet(packet)['status'], 'invalid')
        packet = self.complete(self.packet(), conclusion='needs_changes')
        packet['human_review']['conclusion'] = 'pass'
        report = validate_review_packet(packet)
        self.assertEqual(report['status'], 'invalid')
        self.assertIn('conflicting_conclusion', {problem['code'] for problem in report['problems']})

    def test_annotation_enums_limits_dates_and_unknown_keys_are_invalid(self):
        packet = self.complete(self.packet())
        mutations = (
            lambda p: p['human_review'].update(reviewer_name='x' * 201),
            lambda p: p['human_review'].update(qualifications='x' * 2001),
            lambda p: p['human_review'].update(notes='x' * 4001),
            lambda p: p['human_review'].update(conclusion='approved'),
            lambda p: p['human_review'].update(conclusion=[]),
            lambda p: p['human_review'].update(reviewed_at='2026-02-30'),
            lambda p: p['human_review'].update(reviewed_at='2026-10-25T12:00:00'),
            lambda p: p['human_review'].update(extra='unrecognized'),
            lambda p: p['contents'][0]['questions'][0]['checklist']['answer_key'].update(result=True),
            lambda p: p['contents'][0]['questions'][0]['checklist']['answer_key'].update(result='approved'),
            lambda p: p['contents'][0]['questions'][0]['checklist']['answer_key'].update(notes=12),
            lambda p: p['contents'][0]['questions'][0]['checklist'].update(unknown={'result': 'pass', 'notes': ''}),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = deepcopy(packet)
                mutate(changed)
                self.assertEqual(validate_review_packet(changed)['status'], 'invalid')
        for valid_date in ('2026-10-25', '2026-10-25T12:00:00+07:00', '2026-10-25T05:00:00Z'):
            packet['human_review']['reviewed_at'] = valid_date
            self.assertEqual(validate_review_packet(packet)['status'], 'current')

    def test_original_evidence_selection_and_hash_tampering_is_rejected_before_db(self):
        packet = self.packet()
        mutations = (
            lambda p: p.update(approval_allowed=True),
            lambda p: p.update(scope='full_approval'),
            lambda p: p.update(fingerprint='0' * 64),
            lambda p: p['contents'][0]['content'].update(title='Modified title'),
            lambda p: p['contents'][0]['questions'][0].update(prompt='Modified prompt'),
            lambda p: p['contents'][0]['questions'][0]['options'][0].update(is_correct=False),
            lambda p: p['contents'][0]['questions'][0]['options'][0].update(text='Modified option'),
            lambda p: p['contents'][0]['flashcards'][0].update(version_hash='0' * 64),
            lambda p: p['selection'].update(max_items_per_kind_per_content=2),
            lambda p: p['checklist_template']['answer_key'].update(notes='Unexpected template change'),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = deepcopy(packet)
                mutate(changed)
                with CaptureQueriesContext(connection) as queries:
                    report = validate_review_packet(changed)
                self.assertEqual(report['status'], 'invalid')
                self.assertEqual(len(queries), 0)

    def test_recomputed_hashes_do_not_make_edited_evidence_match_current_bank(self):
        packet = self.packet()
        item = packet['contents'][0]['questions'][0]
        item['prompt'] = 'Locally edited source evidence'
        source_item = {key: value for key, value in item.items() if key not in ('version_hash', 'human_review', 'checklist')}
        item['version_hash'] = _hash(source_item)
        normalized = deepcopy(packet)
        normalized.pop('fingerprint')
        normalized.pop('generated_at')
        normalized['human_review'] = deepcopy(HUMAN_REVIEW_TEMPLATE)
        for record in normalized['contents']:
            for source in [*record['flashcards'], *record['questions']]:
                source['human_review'] = deepcopy(HUMAN_REVIEW_TEMPLATE)
                source['checklist'] = deepcopy(CHECKLIST_TEMPLATE)
        packet['fingerprint'] = _hash(normalized)
        report = validate_review_packet(packet)
        self.assertEqual(report['status'], 'stale')
        self.assertFalse(report['source_matches'])
        self.assertIn('do not verify reviewer identity', report['notice'])

    def test_problem_list_is_bounded_without_discarding_incomplete_state(self):
        packet = self.complete(self.packet(), result='not_applicable')
        for record in packet['contents']:
            for item in [*record['flashcards'], *record['questions']]:
                for check in item['checklist'].values():
                    check['notes'] = ''
        with patch('learning.review_validation.MAX_PROBLEMS', 1):
            report = validate_review_packet(packet)
        self.assertEqual(report['status'], 'current')
        self.assertEqual(len(report['problems']), 1)
        self.assertTrue(report['problems_truncated'])
        self.assertFalse(report['annotations_complete'])

    def test_changed_unsampled_item_marks_snapshot_stale(self):
        packet = self.complete(self.packet())
        Flashcard.objects.filter(pk=self.cards[1].pk).update(example_en='Changed outside exported sample.')
        report = validate_review_packet(packet)
        self.assertEqual(report['status'], 'stale')
        self.assertFalse(report['source_matches'])
        self.assertTrue(report['annotations_complete'])
        self.assertIn('source_changed', {problem['code'] for problem in report['problems']})

    def test_changed_sampled_key_metadata_or_deleted_parent_is_stale(self):
        packet = self.packet()
        AnswerOption.objects.filter(question=self.question, label='B').update(explanation_vi='New explanation')
        self.assertEqual(validate_review_packet(packet)['status'], 'stale')
        packet = self.packet()
        LearningContent.objects.filter(pk=self.content.pk).update(rights_note='Changed provenance')
        self.assertEqual(validate_review_packet(packet)['status'], 'stale')
        packet = self.packet()
        self.content.delete()
        report = validate_review_packet(packet)
        self.assertEqual(report['status'], 'stale')
        self.assertIn('source_unavailable', {problem['code'] for problem in report['problems']})

    def test_updated_at_and_valid_generation_date_do_not_change_source_status(self):
        packet = self.packet()
        LearningContent.objects.filter(pk=self.content.pk).update(updated_at=timezone.now() + timedelta(days=1))
        packet['generated_at'] = '2026-10-24T00:00:00+07:00'
        self.assertEqual(validate_review_packet(packet)['status'], 'current')

    def test_read_only_four_queries_no_models_or_personal_records_in_report(self):
        packet = self.complete(self.packet())
        before = LearningContent.objects.values().get(pk=self.content.pk)
        with patch('learning.ai.OpenAI') as openai, patch('learning.ai.generate_cloudflare_answer') as cloudflare:
            with CaptureQueriesContext(connection) as queries:
                report = validate_review_packet(packet)
        self.assertEqual(len(queries), 4)
        for query in queries:
            # PostgreSQL iterator() declares a read-only server-side SELECT cursor.
            self.assertRegex(query['sql'].lstrip().upper(), r'^(?:SELECT\b|DECLARE "[^"]+"(?: NO SCROLL| SCROLL)? CURSOR(?: WITH HOLD)? FOR SELECT\b)')
        self.assertEqual(before, LearningContent.objects.values().get(pk=self.content.pk))
        text = json.dumps(report)
        for private_text in ('SECRET SOURCE', 'SECRET OPTION', 'SECRET DISTRACTOR', 'Named reviewer', 'Relevant qualification', 'Reviewer notes'):
            self.assertNotIn(private_text, text)
        openai.assert_not_called()
        cloudflare.assert_not_called()

    def test_malformed_values_cycles_nonfinite_and_deep_nesting_fail_safely(self):
        nested = []
        for unused in range(30):
            nested = [nested]
        cyclic = []
        cyclic.append(cyclic)
        for malformed in (None, [], {}, True, 'text', {'a': float('nan')}, {'a': float('inf')}, nested, cyclic, {1: 'non-string-key'}):
            with self.subTest(value=type(malformed).__name__), CaptureQueriesContext(connection) as queries:
                self.assertEqual(validate_review_packet(malformed)['status'], 'invalid')
            self.assertEqual(len(queries), 0)

    def test_loader_rejects_duplicate_keys_nonfinite_invalid_utf8_and_oversize(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":{"x":1,"x":2}}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'\xff', b'{', b'[' * 1500):
            with self.subTest(raw=raw[:30]), self.assertRaises(ReviewPacketLoadError):
                load_review_packet(BytesIO(raw))
        with patch('learning.review_validation.MAX_PACKET_BYTES', 10), self.assertRaises(ReviewPacketLoadError):
            load_review_packet(BytesIO(b' ' * 11))
        with patch('learning.review_validation.MAX_PACKET_BYTES', 10), self.assertRaises(ReviewPacketLoadError):
            load_review_packet(StringIO('"' + 'é' * 5 + '"'))
        packet = self.packet()
        self.assertEqual(load_review_packet(BytesIO(json.dumps(packet).encode())), packet)

    def test_malformed_identity_and_coverage_shapes_do_not_raise(self):
        packet = self.packet()
        mutations = (
            lambda p: p['selection'].update(content_ids=[True]),
            lambda p: p['selection'].update(content_ids=[[]]),
            lambda p: p['selection'].update(max_items_per_kind_per_content=True),
            lambda p: p['contents'][0].update(coverage=[]),
            lambda p: p['contents'][0]['coverage']['flashcards'].update(total='one'),
            lambda p: p['contents'][0]['questions'][0].update(id=[]),
            lambda p: p['contents'][0]['questions'][0]['options'][0].update(id=[]),
            lambda p: p['contents'][0]['questions'][0].update(human_review=[]),
            lambda p: p['contents'][0]['questions'][0].update(checklist=[]),
        )
        for mutate in mutations:
            changed = deepcopy(packet)
            mutate(changed)
            with self.subTest(mutation=mutate):
                self.assertEqual(validate_review_packet(changed)['status'], 'invalid')

    def test_cli_current_pending_prints_report_without_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'packet.json'
            source.write_text(json.dumps(self.packet()))
            stdout = StringIO()
            call_command('validate_review_packet', input=source, stdout=stdout)
            self.assertEqual(json.loads(stdout.getvalue())['status'], 'current')
            self.assertFalse(json.loads(stdout.getvalue())['annotations_complete'])

    def test_cli_stale_writes_report_then_nonzero_preserves_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'packet.json', Path(directory) / 'report.json'
            source.write_text(json.dumps(self.packet()))
            original = source.read_bytes()
            Flashcard.objects.filter(pk=self.cards[1].pk).update(meaning_vi='Revised outside sample')
            with self.assertRaises(CommandError):
                call_command('validate_review_packet', input=source, output=output, stdout=StringIO())
            self.assertEqual(json.loads(output.read_text())['status'], 'stale')
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob('.review-validation-*')), [])

    def test_cli_overwrite_guard_invalid_file_and_input_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'packet.json', Path(directory) / 'report.json'
            source.write_text(json.dumps(self.packet()))
            output.write_text('KEEP')
            with self.assertRaises(CommandError):
                call_command('validate_review_packet', input=source, output=output, stdout=StringIO())
            self.assertEqual(output.read_text(), 'KEEP')
            call_command('validate_review_packet', input=source, output=output, overwrite=True, stdout=StringIO())
            self.assertEqual(json.loads(output.read_text())['status'], 'current')
            with self.assertRaises(CommandError):
                call_command('validate_review_packet', input=source, output=source, overwrite=True, stdout=StringIO())
            source.write_text('{"a":1,"a":2}')
            with self.assertRaises(CommandError):
                call_command('validate_review_packet', input=source, output=Path(directory) / 'missing.json', stdout=StringIO())
            self.assertFalse((Path(directory) / 'missing.json').exists())

    def test_cli_concurrent_destination_creation_never_overwrites_it(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'packet.json', Path(directory) / 'report.json'
            source.write_text(json.dumps(self.packet()))
            def collision(*unused):
                output.write_text('CONCURRENT')
                raise FileExistsError
            with patch('learning.management.commands.validate_review_packet.os.link', side_effect=collision), self.assertRaises(CommandError):
                call_command('validate_review_packet', input=source, output=output, stdout=StringIO())
            self.assertEqual(output.read_text(), 'CONCURRENT')
            self.assertEqual(list(Path(directory).glob('.review-validation-*')), [])
