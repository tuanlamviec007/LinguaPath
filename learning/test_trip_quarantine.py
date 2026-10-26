from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import RequestFactory, TestCase

from .admin import FlashcardAdmin
from .content_coverage import content_coverage
from .content_review import build_review_packet
from .management.commands.repair_starter_trip import (
    DERIVED_NEW, DERIVED_OLD, DERIVED_PARENT, HOLD_NOTE, OLD_MATCH, PARENT_MATCH, REPAIRED_VALUES)
from .models import AnswerOption, Flashcard, LearningContent, Question
from .review_validation import validate_review_packet


class TripQuarantineTests(TestCase):
    def setUp(self):
        self.parent = LearningContent.objects.create(**PARENT_MATCH, skill='vocabulary',
            is_published=True, review_status='language_checked')
        self.card = Flashcard.objects.create(content=self.parent, **OLD_MATCH)
        self.other = Flashcard.objects.create(content=self.parent, term='untouched', meaning_vi='giữ nguyên')
        self.derived = LearningContent.objects.create(**DERIVED_PARENT, skill='vocabulary',
            is_published=True, review_status='language_checked')
        self.question = Question.objects.create(content=self.derived, **DERIVED_OLD)
        for label, text, correct in [('A','địa danh nổi bật',False),('B','chuyến đi',True),
                ('C','nhân viên lễ tân',False),('D','tài liệu điện tử',False)]:
            AnswerOption.objects.create(question=self.question,label=label,text=text,is_correct=correct)

    def apply(self, **extra):
        call_command('repair_starter_trip', quarantine_card=True, apply=True, stdout=StringIO(), **extra)

    def test_preview_does_not_change_any_source_or_publication(self):
        before=list(Flashcard.objects.values()); sources=list(LearningContent.objects.values())
        output=StringIO(); call_command('repair_starter_trip',quarantine_card=True,stdout=output)
        self.assertEqual(list(Flashcard.objects.values()),before)
        self.assertEqual(list(LearningContent.objects.values()),sources)
        self.assertIn('DRY RUN',output.getvalue())

    def test_repairs_card_and_derivative_but_only_holds_card_and_small_question_set(self):
        before=LearningContent.objects.values().get(pk=self.parent.pk)
        self.apply()
        self.card.refresh_from_db(); self.question.refresh_from_db(); self.derived.refresh_from_db()
        self.assertEqual(self.card.example_vi,REPAIRED_VALUES['example_vi'])
        self.assertEqual(self.card.topic,'Travel')
        self.assertFalse(self.card.is_available); self.assertEqual(self.card.availability_note,HOLD_NOTE)
        self.assertEqual(self.question.explanation_vi,DERIVED_NEW)
        self.assertEqual((self.derived.review_status,self.derived.is_published),('draft',False))
        self.assertEqual(LearningContent.objects.values().get(pk=self.parent.pk),before)
        self.assertEqual(list(Flashcard.objects.learner_visible().values_list('pk',flat=True)),[self.other.pk])
        after=list(Flashcard.objects.values()); content_after=list(LearningContent.objects.values())
        self.apply()
        self.assertEqual(list(Flashcard.objects.values()),after)
        self.assertEqual(list(LearningContent.objects.values()),content_after)

    def test_previously_edited_derivative_aborts_entire_repair(self):
        Question.objects.filter(pk=self.question.pk).update(explanation_vi='A human edited this.')
        with self.assertRaises(CommandError): self.apply()
        self.card.refresh_from_db(); self.derived.refresh_from_db()
        self.assertTrue(self.card.is_available)
        self.assertEqual(self.card.example_vi,OLD_MATCH['example_vi'])
        self.assertTrue(self.derived.is_published)

    def test_human_approved_parent_or_derivative_is_never_overwritten(self):
        for parent in (self.parent,self.derived):
            parent.review_status='teacher_approved'; parent.save(update_fields=['review_status'])
            with self.assertRaises(CommandError): self.apply()
            self.card.refresh_from_db(); self.assertTrue(self.card.is_available)
            parent.review_status='language_checked'; parent.save(update_fields=['review_status'])

    def test_held_card_is_retained_in_inventory_and_prioritized_in_v2_review_sample(self):
        self.apply()
        coverage=content_coverage()
        self.assertEqual(coverage['totals']['cards'],2)
        self.assertEqual(coverage['totals']['visible_cards'],1)
        self.assertEqual(coverage['totals']['held_cards'],1)
        packet=build_review_packet([self.parent.pk],max_items=1)
        self.assertEqual(packet['schema_version'],'linguapath-content-review-v2')
        card=packet['contents'][0]['flashcards'][0]
        self.assertEqual(card['id'],self.card.pk)
        self.assertFalse(card['is_available'])
        self.assertEqual(validate_review_packet(packet)['status'],'current')
        Flashcard.objects.filter(pk=self.card.pk).update(availability_note='A later review note')
        self.assertEqual(validate_review_packet(packet)['status'],'stale')


class FlashcardHoldAdminTests(TestCase):
    def setUp(self):
        self.parent=LearningContent.objects.create(title='Provisional deck',skill='vocabulary',
            content_type='vocabulary',review_status='language_checked',is_published=True)
        self.card=Flashcard.objects.create(content=self.parent,term='word',meaning_vi='từ')
        self.admin=FlashcardAdmin(Flashcard,admin.site)
        self.admin.message_user=Mock()
        self.request=RequestFactory().post('/admin/')
        self.request.user=get_user_model().objects.create_superuser(username='hold-admin')

    def test_hold_only_keeps_parent_publication_but_release_requires_review(self):
        self.card.is_available=False
        self.card.availability_note='Review this example'
        self.admin.save_model(self.request,self.card,SimpleNamespace(changed_data=['is_available','availability_note']),True)
        self.parent.refresh_from_db(); self.assertTrue(self.parent.is_published)
        self.card.is_available=True
        self.admin.save_model(self.request,self.card,SimpleNamespace(changed_data=['is_available']),True)
        self.parent.refresh_from_db(); self.assertFalse(self.parent.is_published)
        self.assertEqual(self.parent.review_status,'draft')

    def test_source_edit_alongside_hold_still_invalidates_parent(self):
        self.card.is_available=False; self.card.meaning_vi='edited'
        self.admin.save_model(self.request,self.card,SimpleNamespace(changed_data=['is_available','meaning_vi']),True)
        self.parent.refresh_from_db(); self.assertFalse(self.parent.is_published)
