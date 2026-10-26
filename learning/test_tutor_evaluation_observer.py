from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .ai import answer_tutor_question
from .models import AnswerOption, AttemptAnswer, LearningContent, PracticeAttempt, Question


class TutorEvaluationObserverTests(TestCase):
    def test_public_evaluation_excludes_even_the_quota_principals_own_questions(self):
        user = get_user_model().objects.create_user(username='staff-with-private-history', is_staff=True)
        content = LearningContent.objects.create(title='Own submitted lesson', content_type='reading',
            skill='reading', is_published=True, review_status='language_checked')
        question = Question.objects.create(content=content, prompt='PRIVATE distinctive question',
            passage='PRIVATE source material', explanation='PRIVATE rationale')
        option = AnswerOption.objects.create(question=question, label='A', text='PRIVATE key', is_correct=True)
        AnswerOption.objects.create(question=question, label='B', text='Other option')
        attempt = PracticeAttempt.objects.create(user=user, content=content, status='submitted', question_ids=[question.pk])
        AttemptAnswer.objects.create(attempt=attempt, question=question, selected_option=option, is_correct=True)
        ordinary = answer_tutor_question('Explain the question.', question_id=question.pk, user=user)
        self.assertEqual(ordinary['mode'], 'retrieval_only')
        observed = []
        public = answer_tutor_question('Explain the question.', question_id=question.pk, user=user,
            public_context_only=True, evidence_observer=lambda *args: observed.append(args))
        self.assertEqual(public['mode'], 'no_match')
        self.assertEqual(observed, [([], None)])

    @override_settings(AI_TUTOR_ENABLED=True)
    def test_observer_cannot_mutate_model_input_and_packing_is_reused(self):
        from .ai_context import pack_evidence
        seen = []
        def observe(evidence, packed):
            seen.append((evidence, packed.text))
            evidence[0]['text'] = 'MODIFIED BY OBSERVER'
            evidence[0]['source_ref']['version'] = 'bad'
            packed.text = 'MODIFIED PACKED CONTEXT'
        with patch('learning.ai.tutor_ai_available', return_value=True), \
             patch('learning.ai.reserve_tutor_call', return_value=(True, 'allowed')) as quota, \
             patch('learning.ai.provider_name', return_value='cloudflare'), \
             patch('learning.ai.pack_evidence', wraps=pack_evidence) as pack, \
             patch('learning.ai.generate_cloudflare_answer', return_value={'answer':'A model answer','model':'test-model'}) as generate:
            result = answer_tutor_question('despite và although', user=object(), use_ai=True,
                public_context_only=True, evidence_observer=observe)
        self.assertEqual(len(seen), 1)
        pack.assert_called_once()
        quota.assert_called_once()
        self.assertEqual(generate.call_args.args[1], seen[0][1])
        self.assertNotIn('MODIFIED', generate.call_args.args[1])
        self.assertNotEqual(result['evidence_sources'][0]['source_ref']['version'], 'bad')

    def test_offline_snapshot_is_exact_without_provider_or_quota(self):
        seen = []
        with patch('learning.ai.OpenAI') as openai, patch('learning.ai.generate_cloudflare_answer') as cloudflare, \
             patch('learning.ai.reserve_tutor_call') as quota:
            result = answer_tutor_question('despite và although', public_context_only=True,
                evidence_observer=lambda *args: seen.append(args))
        self.assertEqual(result['mode'], 'retrieval_only')
        self.assertTrue(seen[0][1].sufficient)
        self.assertEqual(result['answer'], seen[0][0][0]['text'])
        openai.assert_not_called(); cloudflare.assert_not_called(); quota.assert_not_called()

    def test_ordinary_call_remains_unchanged_when_observer_is_omitted(self):
        ordinary = answer_tutor_question('despite và although')
        observed = answer_tutor_question('despite và although', evidence_observer=lambda *args: None)
        for key in ('answer', 'sources', 'evidence_sources', 'mode'):
            self.assertEqual(ordinary[key], observed[key])
