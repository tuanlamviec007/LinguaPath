import copy
from collections import Counter
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from learning.management.commands.seed_toeic_workplace import load_pack, validate_pack
from learning.models import AnswerOption, Flashcard, LearningContent, Question
from learning.vocabulary_catalog import answer_pattern


class WorkplaceValidationTests(SimpleTestCase):
    def test_pack_is_balanced_and_every_blank_matches_one_word_in_context(self):
        rows = load_pack()
        self.assertEqual(len({row['term'].casefold() for row in rows}), 40)
        self.assertEqual(set(Counter(row['topic'] for row in rows).values()), {10})
        for row in rows:
            with self.subTest(term=row['term']):
                sentence = answer_pattern(row['cloze_answer']).sub('_____', row['example_en'], count=1)
                self.assertEqual(sentence.count('_____'), 1)
                self.assertEqual(sentence.replace('_____', row['cloze_answer']), row['example_en'])
                self.assertIn(row['term'], row['example_en'])
                self.assertNotIn(row['meaning_vi'], row['meaning_distractors'])
                self.assertTrue(row['explanation_vi'].strip())

    def test_rejects_duplicate_answers_missing_translations_and_invalid_blanks(self):
        mutations = [
            lambda rows: rows[0].update(cloze_distractors=[rows[0]['cloze_answer'], 'attend', 'recruit']),
            lambda rows: rows[0].update(example_vi=''),
            lambda rows: rows[0].update(cloze_answer='nonexistent'),
            lambda rows: rows[0].update(example_en=rows[0]['example_en'] + ' We also meet another deadline.'),
            lambda rows: rows[1].update(term=rows[0]['term']),
            lambda rows: rows[1].update(id=rows[0]['id']),
            lambda rows: rows[0].update(cefr_level='C2'),
        ]
        for mutate in mutations:
            rows = copy.deepcopy(load_pack())
            mutate(rows)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                validate_pack(rows)


class WorkplaceSeedTests(TestCase):
    def seed(self, **kwargs):
        call_command('seed_toeic_workplace', stdout=StringIO(), **kwargs)

    def test_default_creates_draft_content_without_publishing(self):
        self.seed()
        self.assertEqual(LearningContent.objects.count(), 12)
        self.assertEqual(Flashcard.objects.count(), 40)
        self.assertEqual(Question.objects.count(), 80)
        self.assertFalse(LearningContent.objects.filter(is_published=True).exists())
        self.assertEqual(set(LearningContent.objects.values_list('review_status', flat=True)), {'draft'})

    def test_provisional_pack_has_correct_counts_explanations_and_one_answer(self):
        self.seed(publish_provisional=True)
        self.assertEqual(AnswerOption.objects.count(), 320)
        for content in LearningContent.objects.prefetch_related('questions', 'flashcards'):
            with self.subTest(content=content.question_type):
                self.assertEqual(content.publication_issues(), [])
                self.assertTrue(content.is_published)
                self.assertEqual(content.review_status, 'language_checked')
                if content.question_type.endswith('-deck'):
                    self.assertEqual(content.flashcards.count(), 10)
                    self.assertEqual(content.questions.count(), 0)
                else:
                    self.assertEqual(content.questions.count(), 10)
                    self.assertEqual(content.flashcards.count(), 0)
        for question in Question.objects.prefetch_related('options'):
            choices = list(question.options.all())
            self.assertEqual(len(choices), 4)
            self.assertEqual(len({choice.text for choice in choices}), 4)
            self.assertEqual(sum(choice.is_correct for choice in choices), 1)
            self.assertTrue(all(choice.explanation_vi for choice in choices))
            if question.content.question_type.endswith('-cloze'):
                self.assertEqual(question.passage.count('_____'), 1)

    def test_rerun_preserves_teacher_edits_titles_answers_and_review_status(self):
        self.seed(publish_provisional=True)
        card = Flashcard.objects.first()
        card.meaning_vi = 'Nghĩa đã được giáo viên chỉnh sửa'
        card.save(update_fields=['meaning_vi'])
        content = card.content
        content.title = 'Tên bộ được biên tập lại'
        content.review_status = 'teacher_approved'
        content.is_published = False
        content.save(update_fields=['title', 'review_status', 'is_published'])
        question = Question.objects.first()
        question.explanation_vi = 'Lời giải được người biên tập chỉnh sửa'
        question.save(update_fields=['explanation_vi'])
        self.seed(publish_provisional=True)
        card.refresh_from_db()
        content.refresh_from_db()
        question.refresh_from_db()
        self.assertEqual(card.meaning_vi, 'Nghĩa đã được giáo viên chỉnh sửa')
        self.assertEqual(content.title, 'Tên bộ được biên tập lại')
        self.assertEqual(content.review_status, 'teacher_approved')
        self.assertFalse(content.is_published)
        self.assertEqual(question.explanation_vi, 'Lời giải được người biên tập chỉnh sửa')
        self.assertEqual((LearningContent.objects.count(), Flashcard.objects.count(), Question.objects.count()), (12, 40, 80))

    def test_draft_rerun_does_not_silently_publish_existing_content(self):
        self.seed()
        self.seed(publish_provisional=True)
        self.assertFalse(LearningContent.objects.filter(is_published=True).exists())

    def test_collision_with_existing_card_rolls_back_whole_import(self):
        content = LearningContent.objects.create(title='Teacher deck', content_type='vocabulary', skill='vocabulary')
        term = load_pack()[0]['term']
        Flashcard.objects.create(content=content, term=term.upper(), meaning_vi='Bản do giáo viên soạn')
        with self.assertRaises(CommandError):
            self.seed(publish_provisional=True)
        self.assertEqual(LearningContent.objects.count(), 1)
        self.assertEqual(Flashcard.objects.get().meaning_vi, 'Bản do giáo viên soạn')
        self.assertFalse(Question.objects.exists())

    def test_dry_run_does_not_write_anything(self):
        self.seed(dry_run=True)
        self.assertFalse(LearningContent.objects.exists())
