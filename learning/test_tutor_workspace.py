from datetime import timedelta
from unittest.mock import patch, Mock
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .ai import answer_tutor_question
from .models import Flashcard, LearningContent, TutorUsageBudget, UserFlashcardState


class TutorWorkspaceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='source-reader')
        self.profile = LearnerProfile.objects.create(user=self.user, current_cefr='A1')
        self.content = LearningContent.objects.create(
            title='Vocabulary source', exam_type='TOEIC', content_type='vocabulary',
            skill='vocabulary', is_published=True, review_status='language_checked',
        )
        self.card = Flashcard.objects.create(
            content=self.content, term='deadline', meaning_vi='hạn chót',
            example_en='The deadline is Friday.', cefr_level='A1',
        )
        self.client.force_login(self.user)

    def test_suggestions_use_current_level_exam_and_only_visible_content(self):
        Flashcard.objects.create(content=self.content, term='advanced', cefr_level='C1')
        hidden = LearningContent.objects.create(title='Draft', review_status='draft', is_published=True)
        Flashcard.objects.create(content=hidden, term='secret', cefr_level='A1')
        foreign = LearningContent.objects.create(title='IELTS terms', exam_type='IELTS', review_status='teacher_approved', is_published=True)
        Flashcard.objects.create(content=foreign, term='foreign', cefr_level='A1')
        page = self.client.get(reverse('tutor'))
        self.assertEqual(page.context['suggested_prompts'], ['Giải thích từ “deadline” và cho ví dụ.'])
        self.assertContains(page, 'data-prompt=')
        self.assertFalse(TutorUsageBudget.objects.exists())

    @patch.dict('os.environ', {'OPENAI_API_KEY': ''})
    def test_source_link_can_open_card_even_when_not_due(self):
        UserFlashcardState.objects.create(user=self.user, flashcard=self.card, last_rating='known', reviewed_at=timezone.now(), due_at=timezone.now() + timedelta(days=7))
        page = self.client.post(reverse('tutor'), {'question': 'Giải thích từ “deadline”.'}, follow=True)
        self.assertEqual(page.context['mode'], 'retrieval_only')
        sources = page.context['evidence_sources']
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['review_status'], 'language_checked')
        self.assertContains(page, 'chưa giảng viên duyệt')
        parts = urlsplit(sources[0]['href'])
        self.assertEqual(parts.path, reverse('learning:flashcards'))
        self.assertEqual(parse_qs(parts.query), {'q': ['deadline'], 'all': ['1']})
        source_page = self.client.get(sources[0]['href'])
        self.assertEqual([card.pk for card in source_page.context['cards']], [self.card.pk])
        self.assertFalse(TutorUsageBudget.objects.exists())

    @patch.dict('os.environ', {'OPENAI_API_KEY': ''})
    def test_invalid_explicit_question_id_does_not_fall_through_to_public_word(self):
        for question_id in ('invalid', '9' * 100, '-1'):
            with self.subTest(question_id=question_id):
                page = self.client.post(reverse('tutor'), {'question': 'deadline', 'question_id': question_id}, follow=True)
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context['mode'], 'no_match')
                self.assertEqual(page.context['evidence_sources'], [])
                self.assertNotContains(page, 'Nghĩa: hạn chót')

    def test_no_match_never_calls_external_service(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('learning.ai.OpenAI') as client:
            result = answer_tutor_question('quantum galaxies', user=self.user, use_ai=True)
        self.assertEqual(result['mode'], 'no_match')
        self.assertEqual(result['evidence_sources'], [])
        client.assert_not_called()
        self.assertFalse(TutorUsageBudget.objects.exists())

    @override_settings(AI_TUTOR_ENABLED=True)
    def test_llm_sources_match_context_and_fallback_only_lists_displayed_evidence(self):
        second = Flashcard.objects.create(content=self.content, term='project', meaning_vi='dự án')
        client = Mock()
        client.responses.create.return_value.output_text = 'A referenced explanation.'
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('learning.ai.OpenAI', return_value=client):
            result = answer_tutor_question('Giải thích từ deadline và project', user=self.user, use_ai=True)
        self.assertEqual(result['mode'], 'llm_rag')
        self.assertEqual({s['label'] for s in result['evidence_sources']}, {'deadline', second.term})
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('learning.ai.reserve_tutor_call', return_value=(False, 'daily_limit')):
            blocked = answer_tutor_question('Giải thích từ deadline và project', user=self.user, use_ai=True)
        self.assertEqual(blocked['mode'], 'budget_limited')
        self.assertEqual(len(blocked['evidence_sources']), 1)
        self.assertEqual(blocked['sources'], [blocked['evidence_sources'][0]['title']])

    def test_tutor_requires_authentication(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('tutor')).status_code, 302)


    def test_default_lookup_never_calls_external_service_even_when_configured(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('learning.ai.OpenAI') as client:
            result = answer_tutor_question('deadline', user=self.user)
            page = self.client.post(reverse('tutor'), {'question': 'deadline'}, follow=True)
        self.assertEqual(result['mode'], 'retrieval_only')
        self.assertEqual(page.context['mode'], 'retrieval_only')
        self.assertEqual(page.context['tutor_mode'], 'lookup')
        client.assert_not_called()
        self.assertFalse(TutorUsageBudget.objects.exists())

    @override_settings(AI_TUTOR_ENABLED=True)
    def test_only_explicit_ai_form_choice_can_reserve_call(self):
        client = Mock()
        client.responses.create.return_value.output_text = 'A referenced explanation.'
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('learning.ai.OpenAI', return_value=client) as factory:
            for response_mode in ('lookup', 'invalid'):
                page = self.client.post(reverse('tutor'), {'question': 'deadline', 'response_mode': response_mode}, follow=True)
                self.assertEqual(page.context['mode'], 'retrieval_only')
            factory.assert_not_called()
            self.assertFalse(TutorUsageBudget.objects.exists())
            page = self.client.post(reverse('tutor'), {'question': 'deadline', 'response_mode': 'ai'}, follow=True)
        self.assertEqual(page.context['mode'], 'llm_rag')
        self.assertEqual(page.context['tutor_mode'], 'ai')
        self.assertEqual(TutorUsageBudget.objects.get(user=self.user).day_count, 1)
        factory.assert_called_once()

    @override_settings(AI_TUTOR_ENABLED=True)
    def test_ai_controls_only_available_when_service_enabled(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            page = self.client.get(reverse('tutor'))
        self.assertNotContains(page, 'value="ai"')
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            page = self.client.get(reverse('tutor'))
        self.assertContains(page, 'value="ai"')
        self.assertContains(page, 'value="lookup"')

    def test_ambiguous_word_asks_for_context_before_any_external_call(self):
        self.card.term = 'bank'
        self.card.meaning_vi = 'ngân hàng'
        self.card.example_en = 'The bank manages money.'
        self.card.save()
        Flashcard.objects.create(content=self.content, term='bank', meaning_vi='bờ sông', example_en='The river bank is sandy.')
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), patch('learning.ai.OpenAI') as client:
            page = self.client.post(reverse('tutor'), {'question': 'Giải thích từ “bank”.', 'response_mode': 'ai'}, follow=True)
        self.assertEqual(page.context['mode'], 'needs_context')
        self.assertEqual(len(page.context['evidence_sources']), 2)
        self.assertContains(page, 'ngân hàng')
        self.assertContains(page, 'bờ sông')
        self.assertEqual(len(page.context['suggested_prompts']), 2)
        self.assertFalse(TutorUsageBudget.objects.exists())
        client.assert_not_called()
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            answer = self.client.post(reverse('tutor'), {'question': page.context['suggested_prompts'][1]}, follow=True)
        self.assertEqual(answer.context['mode'], 'retrieval_only')
        self.assertEqual(answer.context['evidence_sources'][0]['meaning_vi'], 'bờ sông')

    def test_unavailable_ai_choice_falls_back_to_selected_lookup_without_quota(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}), patch('learning.ai.OpenAI') as client:
            page = self.client.post(reverse('tutor'), {'question': 'deadline', 'response_mode': 'ai'}, follow=True)
        self.assertEqual(page.context['tutor_mode'], 'lookup')
        self.assertEqual(page.context['mode'], 'retrieval_only')
        self.assertContains(page, 'value="lookup" checked')
        self.assertFalse(TutorUsageBudget.objects.exists())
        client.assert_not_called()
