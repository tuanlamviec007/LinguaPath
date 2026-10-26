from types import SimpleNamespace
from unittest.mock import Mock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TestCase
from django.utils import timezone

from .admin import FlashcardAdmin, LearningContentAdmin, QuestionAdmin
from .models import AnswerOption, AttemptAnswer, AttemptDraftAnswer, Flashcard, LearningContent, PracticeAttempt, Question
from .practice_sessions import PracticeUnavailableError, save_draft, start_or_resume
from .vocabulary_import import import_vocabulary_csv


class ReviewInvalidationAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='content-admin', email='admin@example.test', password='audit-password-123',
        )
        self.factory = RequestFactory()
        self.request = self.factory.post('/admin/')
        self.request.user = self.user
        self.message_items = []

        class MessageStore:
            def add(_, level, message, extra_tags='', fail_silently=False):
                self.message_items.append((level, str(message)))

        self.request._messages = MessageStore()
        self.content = LearningContent.objects.create(
            title='Reviewed set', exam_type='TOEIC', content_type='reading', skill='reading',
            review_status='teacher_approved', reviewer='Lecturer', reviewed_at=timezone.now(),
            review_note='Checked all answers.', is_published=True,
        )
        self.question = Question.objects.create(
            content=self.content, prompt='Where is the meeting?', explanation='The notice says Room 2.',
        )
        self.correct = AnswerOption.objects.create(question=self.question, label='A', text='Room 2', is_correct=True)
        self.wrong = AnswerOption.objects.create(question=self.question, label='B', text='Room 3')

    def assert_content_requires_review(self, content=None):
        content = content or self.content
        content.refresh_from_db()
        self.assertFalse(content.is_published)
        self.assertEqual(content.review_status, 'draft')
        self.assertEqual(content.reviewer, '')
        self.assertIsNone(content.reviewed_at)
        self.assertEqual(content.review_note, '')

    def test_question_admin_invalidates_parent_when_answers_change(self):
        self.correct.is_correct = False
        form = SimpleNamespace(instance=self.question, changed_data=[], save_m2m=Mock())
        formset = SimpleNamespace(
            has_changed=lambda: True,
            save=lambda: self.correct.save(update_fields=['is_correct']),
        )
        model_admin = QuestionAdmin(Question, admin.site)
        model_admin.save_related(self.request, form, [formset], change=True)

        self.assert_content_requires_review()
        self.correct.refresh_from_db()
        self.assertFalse(self.correct.is_correct)
        self.assertTrue(any('cần rà soát lại' in message for _, message in self.message_items))

    def test_question_delete_invalidates_parent_after_successful_delete(self):
        model_admin = QuestionAdmin(Question, admin.site)
        model_admin.delete_model(self.request, self.question)
        self.assert_content_requires_review()
        self.assertFalse(Question.objects.filter(pk=self.question.pk).exists())

    def test_moving_question_invalidates_both_content_sets(self):
        destination = LearningContent.objects.create(
            title='Second reviewed set', exam_type='TOEIC', content_type='reading', skill='reading',
            review_status='teacher_approved', reviewer='Lecturer', reviewed_at=timezone.now(),
            review_note='Checked.', is_published=True,
        )
        self.question.content = destination
        form = SimpleNamespace(instance=self.question, changed_data=['content'], save_m2m=Mock())
        model_admin = QuestionAdmin(Question, admin.site)
        model_admin.save_model(self.request, self.question, form, change=True)
        formset = SimpleNamespace(has_changed=lambda: False, save=Mock())
        model_admin.save_related(self.request, form, [formset], change=True)

        self.assert_content_requires_review(self.content)
        self.assert_content_requires_review(destination)

    def test_protected_question_delete_keeps_parent_published(self):
        learner = get_user_model().objects.create_user(username='learner', password='learner-password-123')
        attempt = PracticeAttempt.objects.create(
            user=learner, content=self.content, status='submitted', question_count=1,
            question_ids=[self.question.pk], submitted_at=timezone.now(),
        )
        AttemptAnswer.objects.create(attempt=attempt, question=self.question, is_correct=False)

        model_admin = QuestionAdmin(Question, admin.site)
        with self.assertRaises(ProtectedError):
            model_admin.delete_model(self.request, self.question)

        self.content.refresh_from_db()
        self.assertTrue(self.content.is_published)
        self.assertEqual(self.content.review_status, 'teacher_approved')

    def test_draft_does_not_block_admin_question_deletion(self):
        learner = get_user_model().objects.create_user(username='draft-learner')
        attempt, _ = start_or_resume(learner, self.content)
        AttemptDraftAnswer.objects.create(attempt=attempt, question=self.question, selected_option=self.correct)
        QuestionAdmin(Question, admin.site).delete_model(self.request, self.question)
        self.assert_content_requires_review()
        self.assertFalse(attempt.draft_answers.exists())
        with self.assertRaises(PracticeUnavailableError):
            save_draft(learner, attempt.id, {})
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'abandoned')
        self.assertFalse(attempt.answers.exists())

    def test_draft_does_not_block_inline_option_deletion(self):
        learner = get_user_model().objects.create_user(username='draft-option-learner')
        attempt, _ = start_or_resume(learner, self.content)
        AttemptDraftAnswer.objects.create(attempt=attempt, question=self.question, selected_option=self.correct)
        form = SimpleNamespace(instance=self.question, changed_data=[], save_m2m=Mock())
        formset = SimpleNamespace(has_changed=lambda: True, save=lambda: self.correct.delete())
        QuestionAdmin(Question, admin.site).save_related(self.request, form, [formset], change=True)
        self.assert_content_requires_review()
        self.assertFalse(attempt.draft_answers.exists())
        with self.assertRaises(PracticeUnavailableError):
            save_draft(learner, attempt.id, {})
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'abandoned')
        self.assertFalse(attempt.answers.exists())

    def test_flashcard_edit_invalidates_parent(self):
        vocab = LearningContent.objects.create(
            title='Approved words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary',
            review_status='teacher_approved', reviewer='Lecturer', reviewed_at=timezone.now(),
            review_note='Checked.', is_published=True,
        )
        card = Flashcard.objects.create(content=vocab, term='schedule', meaning_vi='lịch trình')
        card.meaning_vi = 'thời gian biểu'
        model_admin = FlashcardAdmin(Flashcard, admin.site)
        model_admin.save_model(self.request, card, form=SimpleNamespace(changed_data=['meaning_vi']), change=True)

        self.assert_content_requires_review(vocab)

    def test_saving_unchanged_flashcard_preserves_parent_publication_and_review(self):
        vocab = LearningContent.objects.create(
            title='Unchanged approved words', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary',
            review_status='teacher_approved', reviewer='Lecturer', reviewed_at=timezone.now(),
            review_note='Checked.', is_published=True,
        )
        card = Flashcard.objects.create(content=vocab, term='schedule', meaning_vi='lịch trình')
        reviewed_at = vocab.reviewed_at
        FlashcardAdmin(Flashcard, admin.site).save_model(
            self.request, card, form=SimpleNamespace(changed_data=[]), change=True,
        )
        vocab.refresh_from_db()
        self.assertTrue(vocab.is_published)
        self.assertEqual(vocab.review_status, 'teacher_approved')
        self.assertEqual(vocab.reviewer, 'Lecturer')
        self.assertEqual(vocab.reviewed_at, reviewed_at)
        self.assertEqual(vocab.review_note, 'Checked.')
        self.assertFalse(self.message_items)

    def test_learning_content_inline_edits_invalidate_parent(self):
        form = SimpleNamespace(instance=self.content, changed_data=[], save_m2m=Mock())
        formset = SimpleNamespace(has_changed=lambda: True, save=Mock())
        model_admin = LearningContentAdmin(LearningContent, admin.site)
        model_admin.save_related(self.request, form, [formset], change=True)

        self.assert_content_requires_review()


class VocabularyImportReviewResetTests(TestCase):
    def test_merge_import_retains_omitted_words_and_clears_stale_review(self):
        content = LearningContent.objects.create(
            title='Imported set', exam_type='TOEIC', content_type='vocabulary', skill='vocabulary',
            review_status='teacher_approved', reviewer='Lecturer', reviewed_at=timezone.now(),
            review_note='Previously approved.', is_published=True,
        )
        Flashcard.objects.create(content=content, term='existing', meaning_vi='từ cũ', cefr_level='A1')
        Flashcard.objects.create(content=content, term='omitted', meaning_vi='vẫn giữ', cefr_level='A1')
        csv_text = 'term,meaning_vi,cefr_level\nexisting,từ đã sửa,A2\nnew,từ mới,B1\n'

        imported, created, updated = import_vocabulary_csv(
            csv_text, title='Imported set', topic='Work', source_name='Self-authored',
            rights_note='Original content.',
        )

        self.assertEqual((created, updated), (1, 1))
        self.assertEqual(imported.flashcards.count(), 3)
        self.assertTrue(imported.flashcards.filter(term='omitted').exists())
        imported.refresh_from_db()
        self.assertFalse(imported.is_published)
        self.assertEqual(imported.review_status, 'draft')
        self.assertEqual(imported.reviewer, '')
        self.assertIsNone(imported.reviewed_at)
        self.assertEqual(imported.review_note, '')

