import copy
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from learning.models import AnswerOption, Flashcard, LearningContent, Question
from learning.vocabulary_catalog import balanced_batches, cloze_sentence, load_catalog, validate_rows
from planner.models import LearnerProfile


def sample_rows():
    words = [
        ('binder', 'bìa còng', 'Keep the loose pages together inside this ring binder.'),
        ('stapler', 'dụng cụ dập ghim', 'Use the stapler to fasten these pages with a metal staple.'),
        ('shredder', 'máy hủy giấy', 'The shredder cuts confidential papers into tiny strips.'),
        ('clipboard', 'bảng kẹp giấy', 'Clip the checklist onto a clipboard while inspecting the room.'),
    ]
    return [{
        'term': term, 'cefr_level': 'A2', 'part_of_speech': 'noun',
        'meaning_vi': meaning, 'example_en': example,
        'example_vi': f'Câu ví dụ tự biên soạn cho {meaning}.', 'topic': 'Office',
        'cloze_answer': term,
        **{f'distractor_{i}': other[0] for i, other in enumerate([word for word in words if word[0] != term], 1)},
    } for term, meaning, example in words]


class CatalogValidationTests(SimpleTestCase):
    def test_batches_cover_all_items_without_a_tiny_remainder(self):
        batches = list(balanced_batches(list(range(54))))
        self.assertEqual([len(batch) for batch in batches], [18, 18, 18])
        self.assertEqual([item for batch in batches for item in batch], list(range(54)))

    def test_catalog_has_2000_distinct_complete_rows(self):
        rows = load_catalog()
        self.assertEqual(len(rows), 2000)
        self.assertEqual(len({row['term'].casefold() for row in rows}), 2000)

    def test_cloze_replaces_one_whole_word_without_altering_other_words(self):
        row = sample_rows()[0]
        self.assertIn('ring _____.', cloze_sentence(row))
        row.update(cloze_answer='pen', example_en='A pen is useful when opening a parcel.')
        self.assertEqual(cloze_sentence(row), 'A _____ is useful when opening a parcel.')

    def test_rejects_incomplete_duplicate_and_ambiguous_structures(self):
        mutations = [
            lambda rows: rows[0].update(cefr_level='C2'),
            lambda rows: rows[0].update(meaning_vi=''),
            lambda rows: rows[0].update(distractor_1=rows[0]['cloze_answer']),
            lambda rows: rows[0].update(example_en='A binder and another binder hold the paper.'),
            lambda rows: rows[1].update(term='  BINDER  '),
            lambda rows: rows[0].update(example_en='<b>Keep a binder near your desk.</b>'),
        ]
        for change in mutations:
            rows = copy.deepcopy(sample_rows())
            change(rows)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_rows(rows)


class CatalogSeedTests(TestCase):
    def seed(self, **kwargs):
        with patch('learning.management.commands.seed_vocabulary_3000.load_catalog', return_value=sample_rows()):
            call_command('seed_vocabulary_3000', stdout=StringIO(), **kwargs)

    def test_default_is_draft_and_provisional_publication_is_explicit(self):
        self.seed()
        self.assertEqual(Flashcard.objects.count(), 4)
        self.assertFalse(LearningContent.objects.filter(is_published=True).exists())
        self.assertEqual(set(LearningContent.objects.values_list('review_status', flat=True)), {'draft'})

    def test_creates_two_exercise_types_with_four_options_and_keeps_teacher_edits(self):
        self.seed(publish_provisional=True)
        self.assertEqual(Question.objects.count(), 8)
        self.assertEqual(AnswerOption.objects.count(), 32)
        for content in LearningContent.objects.all():
            self.assertEqual(content.publication_issues(), [])
            self.assertEqual(content.review_status, 'language_checked')
        for question in Question.objects.all():
            self.assertEqual(question.options.filter(is_correct=True).count(), 1)
            self.assertEqual(question.options.values('text').distinct().count(), 4)
        card = Flashcard.objects.first()
        card.meaning_vi = 'Nghĩa do giáo viên đã sửa'
        card.save(update_fields=['meaning_vi'])
        content = card.content
        content.review_status = 'teacher_approved'
        content.save(update_fields=['review_status'])
        before = (Flashcard.objects.count(), Question.objects.count(), AnswerOption.objects.count())
        self.seed(publish_provisional=True)
        card.refresh_from_db()
        content.refresh_from_db()
        self.assertEqual(card.meaning_vi, 'Nghĩa do giáo viên đã sửa')
        self.assertEqual(content.review_status, 'teacher_approved')
        self.assertEqual(before, (Flashcard.objects.count(), Question.objects.count(), AnswerOption.objects.count()))

    def test_dry_run_writes_nothing(self):
        self.seed(dry_run=True)
        self.assertFalse(LearningContent.objects.exists())

    def test_external_term_collision_fails_without_changing_existing_cards(self):
        existing = LearningContent.objects.create(title='Teacher collection', content_type='vocabulary', skill='vocabulary')
        Flashcard.objects.create(content=existing, term='binder', meaning_vi='Nghĩa của giáo viên')
        with self.assertRaises(CommandError):
            self.seed(publish_provisional=True)
        self.assertEqual(LearningContent.objects.count(), 1)
        self.assertEqual(Flashcard.objects.get().meaning_vi, 'Nghĩa của giáo viên')

    def test_filters_distinguish_context_and_meaning(self):
        self.seed(publish_provisional=True)
        user = get_user_model().objects.create_user(username='catalog-learner')
        LearnerProfile.objects.create(user=user, exam_goal='TOEIC', onboarding_complete=True)
        self.client.force_login(user)
        for mode, suffix in [('meaning', 'meaning'), ('cloze', 'cloze')]:
            response = self.client.get(reverse('learning:practice_list'), {'mode': mode})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['selected_mode'], mode)
            self.assertEqual(response.context['filtered_count'], 1)
            self.assertTrue(all(item.question_type.endswith(suffix) for item in response.context['content_list']))

    def test_pagination_keeps_selected_exercise_type(self):
        self.seed(publish_provisional=True)
        for index in range(12):
            content = LearningContent.objects.create(
                title=f'Extra cloze {index:02d}', content_type='vocabulary', skill='vocabulary',
                exam_type='TOEIC', question_type='lp3000-v1-cloze',
                review_status='language_checked', is_published=True,
            )
            Question.objects.create(content=content, prompt='A sample question', explanation='Sample explanation')
        user = get_user_model().objects.create_user(username='catalog-pagination')
        LearnerProfile.objects.create(user=user, exam_goal='TOEIC', onboarding_complete=True)
        self.client.force_login(user)
        response = self.client.get(reverse('learning:practice_list'), {'mode': 'cloze'})
        self.assertEqual(response.context['filtered_count'], 13)
        self.assertContains(response, 'page=2&amp;mode=cloze')
