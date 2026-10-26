from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from .management.commands.seed_demo import Command as DemoSeedCommand
from .management.commands.seed_starter_content import Command as StarterSeedCommand
from .models import LearningContent


class SeedReviewMetadataTests(TestCase):
    def make_teacher_approved_content(self, title):
        return LearningContent.objects.create(
            title=title,
            description='Original description',
            exam_type='TOEIC',
            content_type='vocabulary',
            skill='vocabulary',
            review_status='teacher_approved',
            reviewer='Teacher reviewer',
            reviewed_at=timezone.now() - timedelta(days=20),
            review_note='Human approval of the previous version.',
            source_checked_on=date.today() - timedelta(days=20),
            is_published=True,
        )

    def assert_ai_provisional(self, content, reviewer, note):
        content.refresh_from_db()
        self.assertEqual(content.review_status, 'language_checked')
        self.assertEqual(content.reviewer, reviewer)
        self.assertEqual(content.review_note, note)
        self.assertIsNotNone(content.reviewed_at)
        self.assertIsNone(content.source_checked_on)

    def test_starter_refresh_demotes_human_approval_and_is_idempotent(self):
        title = 'Seeded vocabulary for metadata test'
        content = self.make_teacher_approved_content(title)
        defaults = {
            'description': 'Original description',
            'exam_type': 'TOEIC',
            'content_type': 'vocabulary',
            'skill': 'vocabulary',
            'topic': 'Work',
            'difficulty': 1,
            'estimated_minutes': 8,
            'source_name': 'Original content',
            'source_url': '',
            'rights_note': 'Self-authored content',
            'is_published': True,
        }
        note = 'AI checked provisionally; a teacher must review.'
        command = StarterSeedCommand()

        refreshed = command._upsert_content(title, defaults, note)

        self.assertEqual(refreshed.pk, content.pk)
        self.assert_ai_provisional(
            refreshed, 'AI language QA (chưa được giáo viên duyệt)', note,
        )
        first_reviewed_at = refreshed.reviewed_at
        self.assertEqual(LearningContent.objects.filter(title=title).count(), 1)

        repeated = command._upsert_content(title, defaults, note)

        self.assertEqual(repeated.pk, content.pk)
        self.assertEqual(repeated.reviewed_at, first_reviewed_at)
        self.assertEqual(LearningContent.objects.filter(title=title).count(), 1)

    def test_demo_refresh_demotes_human_approval_and_is_idempotent(self):
        content = self.make_teacher_approved_content('Demo vocab for metadata test')
        command = DemoSeedCommand()
        note = command.vocab_review_note

        command._refresh_review_metadata(content, note)

        self.assert_ai_provisional(content, command.ai_reviewer, note)
        first_reviewed_at = content.reviewed_at
        defaults = command._review_defaults(note)
        self.assertIsNone(defaults['source_checked_on'])

        command._refresh_review_metadata(content, note)

        content.refresh_from_db()
        self.assertEqual(content.reviewed_at, first_reviewed_at)
        self.assertEqual(content.review_status, 'language_checked')
        self.assertEqual(content.reviewer, command.ai_reviewer)
        self.assertIsNone(content.source_checked_on)
