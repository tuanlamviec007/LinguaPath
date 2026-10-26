"""Imported history must not silently look like an empty mistake queue."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .models import VocabularyQuizSession


class ProjectionReadinessUITests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='projection-import')
        LearnerProfile.objects.create(user=self.user, onboarding_complete=True)
        # Bulk imports intentionally skip the normal submit signal.
        VocabularyQuizSession.objects.bulk_create([VocabularyQuizSession(
            user=self.user, status='submitted', submitted_at=timezone.now(),
            question_count=1, snapshot=[], answers={},
        )])
        self.client.force_login(self.user)

    def test_private_pages_distinguish_pending_projection_from_no_mistakes(self):
        for route in ('dashboard', 'progress', 'learning:quiz_hub', 'learning:weak_words'):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context['weak_words_ready'])
                self.assertContains(response, 'Danh sách từ cần ôn đang chờ đồng bộ')
                self.assertIn('no-store', response['Cache-Control'])
                if route == 'learning:weak_words':
                    self.assertNotContains(response, 'Chưa có từ nào đang cần ôn')

    def test_cannot_start_partial_weak_word_quiz_until_backfill(self):
        response = self.client.post(reverse('learning:quiz_start'), {'source': 'weak', 'count': '5'})
        self.assertRedirects(response, reverse('learning:weak_words'), fetch_redirect_response=False)
        self.assertFalse(VocabularyQuizSession.objects.filter(status='in_progress').exists())

    def test_release_gate_rejects_import_then_accepts_explicit_backfill_without_payload_reads(self):
        from io import StringIO
        from django.core.management import call_command, CommandError
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command('check_weak_word_outcomes', stdout=output)
        call_command('backfill_weak_word_outcomes', apply=True, stdout=output)
        with CaptureQueriesContext(connection) as queries:
            call_command('check_weak_word_outcomes', stdout=output)
        for query in queries:
            self.assertNotIn('"snapshot"', query['sql'])
            self.assertNotIn('"answers"', query['sql'])
            self.assertTrue(query['sql'].lstrip().upper().startswith('SELECT'))
