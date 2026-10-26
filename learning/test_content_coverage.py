import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .content_coverage import content_coverage
from .models import AnswerOption, Flashcard, LearningContent, Question, TutorTurn


class ContentCoverageTests(TestCase):
    def content(self, **values):
        defaults = dict(title='Editorial content', exam_type='TOEIC', skill='reading', content_type='reading',
                        cefr_level='B1', review_status='language_checked', is_published=True)
        defaults.update(values)
        return LearningContent.objects.create(**defaults)

    def question(self, parent, **values):
        defaults = dict(prompt='A source prompt', explanation='Source explanation')
        defaults.update(values)
        question = Question.objects.create(content=parent, **defaults)
        AnswerOption.objects.create(question=question, label='A', text='First', is_correct=True, explanation_vi='Reason A')
        AnswerOption.objects.create(question=question, label='B', text='Second', explanation_vi='Reason B')
        return question

    def test_parent_card_question_counts_do_not_multiply_each_other(self):
        parent = self.content()
        for _ in range(3):
            self.question(parent)
        for index in range(4):
            Flashcard.objects.create(content=parent, term=f'term-{index}', meaning_vi=f'nghĩa {index}', cefr_level='A2')
        result = content_coverage()
        self.assertEqual(result['totals']['contents'], 1)
        self.assertEqual(result['totals']['cards'], 4)
        self.assertEqual(result['totals']['questions'], 3)
        self.assertEqual(result['content_groups'][0]['cards'], 4)
        self.assertEqual(result['content_groups'][0]['questions'], 3)
        self.assertEqual(result['card_levels'], [{'cefr_level': 'A2', 'cards': 4, 'visible_cards': 4}])
        self.assertFalse(any(row['skill'] == 'reading' and row['cefr_level'] == 'B1' for row in result['gaps']))

    def test_exam_review_and_publication_scopes_are_explicit(self):
        for values in ({}, {'review_status': 'draft'}, {'is_published': False},
                       {'exam_type': 'IELTS'}, {'review_status': 'teacher_approved'}):
            parent = self.content(**values)
            self.question(parent)
        result = content_coverage()
        self.assertEqual(result['totals']['contents'], 4)
        self.assertEqual(result['totals']['visible_contents'], 2)
        self.assertEqual(result['totals']['visible_questions'], 2)
        self.assertEqual(result['totals']['published_contents'], 3)
        self.assertEqual(result['totals']['teacher_approved_contents'], 1)
        self.assertEqual(result['structural']['content']['teacher_approval_missing_reviewer_or_time'], 1)
        self.assertEqual(content_coverage('IELTS')['totals']['questions'], 1)
        with self.assertRaises(ValueError):
            content_coverage('INVALID')

    def test_structural_flags_and_missing_metadata_do_not_invent_judgment(self):
        parent = self.content(skill='listening', content_type='listening', cefr_level='', question_type='',
                              source_name=' ', rights_note='')
        broken = Question.objects.create(content=parent, prompt=' ', explanation='', audio_url='', audio_script=' ')
        AnswerOption.objects.create(question=broken, label='A', text=' ', explanation_vi='')
        Flashcard.objects.create(content=parent, term=' ', meaning_vi='', cefr_level='C2',
                                 source_name='', rights_note='', example_en='', example_vi='')
        result = content_coverage()
        flags = result['structural']['question']
        for key in ('blank_prompt', 'fewer_than_two_options', 'not_exactly_one_correct_option',
                    'missing_explanation', 'listening_without_audio_or_script', 'has_blank_option_text',
                    'has_missing_option_explanation'):
            self.assertEqual(flags[key], 1, key)
        self.assertEqual(result['structural']['flashcard']['blank_term_or_meaning'], 1)
        self.assertEqual(result['metadata']['contents_without_cefr'], 1)
        self.assertEqual(result['metadata']['cards_with_unrecognized_cefr'], 1)
        self.assertEqual(result['question_types'], [{'question_type': '', 'contents': 1, 'questions': 1, 'visible_questions': 1}])
        self.assertIn('not teacher approval', result['scope'])

    def test_raw_question_type_labels_remain_raw_and_empty_gaps_are_explicit(self):
        parent = self.content(question_type='Internal label, not inferred Part')
        self.question(parent)
        result = content_coverage()
        self.assertEqual(result['question_types'][0]['question_type'], parent.question_type)
        empty = content_coverage('IELTS')
        self.assertEqual(empty['totals']['contents'], 0)
        self.assertEqual(len(empty['gaps']), 10)
        self.assertEqual(empty['structural']['question']['missing_explanation'], 0)

    def test_read_path_uses_three_selects_and_never_reads_learner_models(self):
        parent = self.content()
        for _ in range(12):
            self.question(parent)
        user = get_user_model().objects.create_user(username='PRIVATE_LEARNER_IDENTIFIER')
        TutorTurn.objects.create(user=user, question='PRIVATE_LEARNER_PROMPT', result={'answer': 'PRIVATE_REPLY'})
        with CaptureQueriesContext(connection) as queries:
            report = content_coverage()
        self.assertEqual(len(queries), 3)
        for query in queries:
            # PostgreSQL iterator() declares a read-only server-side SELECT cursor.
            self.assertRegex(query['sql'].lstrip().upper(), r'^(?:SELECT\b|DECLARE "[^"]+"(?: NO SCROLL| SCROLL)? CURSOR(?: WITH HOLD)? FOR SELECT\b)')
            for forbidden in ('learning_tutorturn', 'auth_user', 'practiceattempt', 'vocabularyquizsession'):
                self.assertNotIn(forbidden, query['sql'].lower())
        encoded = json.dumps(report)
        self.assertNotIn('PRIVATE_', encoded)
        self.assertNotIn('A source prompt', encoded)

    def test_command_stdout_json_and_atomic_no_overwrite(self):
        self.content()
        output = StringIO()
        call_command('audit_content_coverage', stdout=output)
        self.assertEqual(json.loads(output.getvalue())['totals']['contents'], 1)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'reports' / 'coverage.json'
            call_command('audit_content_coverage', output=path, stdout=StringIO())
            original = path.read_bytes()
            with self.assertRaises(CommandError):
                call_command('audit_content_coverage', output=path, stdout=StringIO())
            self.assertEqual(path.read_bytes(), original)
            call_command('audit_content_coverage', output=path, overwrite=True, exam='IELTS', stdout=StringIO())
            self.assertEqual(json.loads(path.read_text())['totals']['contents'], 0)
            self.assertEqual(list(path.parent.iterdir()), [path])
