import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile, StudyTask
from .ai import answer_tutor_question
from .ai_provider import NoRedirect, generate_cloudflare_answer, tutor_ai_available
from .models import AnswerOption, LearningContent, PracticeAttempt, Question, TutorTurn, TutorUsageBudget
from .tutor_tools import daily_tasks, learner_progress


@override_settings(ALLOWED_HOSTS=['learn.example', 'testserver'], AI_TUTOR_ENABLED=True)
class CloudflareTransportTests(TestCase):
    def setUp(self):
        self.env = {'AI_TUTOR_PROVIDER': 'cloudflare', 'AI_BRIDGE_SECRET': 's' * 40,
                    'CLOUDFLARE_AI_ENDPOINT': 'https://learn.example/internal/tutor/infer'}
        self.user = get_user_model().objects.create_user(username='cloudflare-learner')

    def test_configuration_requires_exact_https_allowed_host_path_and_secret(self):
        with patch.dict('os.environ', self.env):
            self.assertTrue(tutor_ai_available())
            for endpoint in ['http://learn.example/internal/tutor/infer',
                             'https://attacker.example/internal/tutor/infer',
                             'https://learn.example/internal/tutor/infer?secret=bad',
                             'https://user:pass@learn.example/internal/tutor/infer',
                             'https://learn.example:8443/internal/tutor/infer',
                             'https://learn.example:bad/internal/tutor/infer',
                             'https://learn.example/other']:
                with self.subTest(endpoint=endpoint), patch.dict('os.environ', {'CLOUDFLARE_AI_ENDPOINT': endpoint}):
                    self.assertFalse(tutor_ai_available())
            with patch.dict('os.environ', {'AI_BRIDGE_SECRET': 'short'}):
                self.assertFalse(tutor_ai_available())
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.example'))

    def test_bridge_sends_only_bounded_question_and_sources_and_no_redirects(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'answer': 'Giải thích theo nguồn.'}).encode()
        opener = Mock()
        opener.open.return_value = response
        with patch.dict('os.environ', self.env), patch('learning.ai_provider.build_opener', return_value=opener) as factory:
            self.assertEqual(generate_cloudflare_answer('q' * 900, 'c' * 7000), 'Giải thích theo nguồn.')
        request = opener.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(set(payload), {'query', 'context'})
        self.assertEqual((len(payload['query']), len(payload['context'])), (500, 5400))
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + 's' * 40)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 25)
        self.assertIsInstance(factory.call_args.args[0], NoRedirect)

    def test_cloudflare_branch_uses_quota_and_falls_back_without_exception_details(self):
        with patch.dict('os.environ', self.env), patch('learning.ai.generate_cloudflare_answer', return_value='Giải thích.') as generate:
            result = answer_tutor_question('despite và although', user=self.user, use_ai=True)
        self.assertEqual(result['mode'], 'llm_rag')
        self.assertEqual(result['provider'], 'cloudflare')
        self.assertEqual(TutorUsageBudget.objects.get(user=self.user).day_count, 1)
        generate.assert_called_once()
        with patch.dict('os.environ', self.env), patch('learning.ai.generate_cloudflare_answer', side_effect=RuntimeError('private-token-value')):
            with self.assertLogs('learning.ai', level='WARNING') as captured:
                result = answer_tutor_question('despite và although', user=self.user, use_ai=True)
        self.assertEqual(result['mode'], 'retrieval_fallback')
        self.assertNotIn('private-token-value', result['answer'] + '\n'.join(captured.output))
        self.assertEqual(TutorUsageBudget.objects.get(user=self.user).day_count, 2)

    def test_bridge_metadata_reports_actual_worker_selection_and_tolerates_legacy(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        for extra, expected in [
            ({'model': '@cf/custom-model', 'prompt_version': 'cloudflare-explain-v1'},
             ('@cf/custom-model', 'cloudflare-explain-v1')),
            ({}, (None, None)),
            ({'model': {'bad': 'shape'}, 'prompt_version': 'x' * 101}, (None, None)),
        ]:
            response.read.return_value = json.dumps({'answer': ' Answer ', **extra}).encode()
            with self.subTest(extra=extra), patch.dict('os.environ', self.env), patch('learning.ai_provider.build_opener', return_value=opener):
                result = generate_cloudflare_answer('query', 'sources', include_metadata=True)
            self.assertEqual(result['answer'], 'Answer')
            self.assertEqual((result['model'], result['prompt_version']), expected)

    def test_tutor_saves_reported_worker_model_instead_of_local_environment_guess(self):
        generated = {'answer': 'Answer', 'model': '@cf/worker-selection', 'prompt_version': 'cloudflare-explain-v1'}
        with patch.dict('os.environ', {**self.env, 'AI_TUTOR_MODEL': '@cf/local-guess'}), patch('learning.ai.generate_cloudflare_answer', return_value=generated) as generate:
            result = answer_tutor_question('despite và although', user=self.user, use_ai=True)
        self.assertEqual(result['answer'], 'Answer')
        self.assertEqual(result['generation']['model'], '@cf/worker-selection')
        self.assertEqual(result['generation']['bridge_prompt_version'], 'cloudflare-explain-v1')
        self.assertTrue(generate.call_args.kwargs['include_metadata'])

    def test_no_match_and_disabled_service_do_not_invoke_cloudflare(self):
        with patch.dict('os.environ', self.env), patch('learning.ai.generate_cloudflare_answer') as generate:
            result = answer_tutor_question('quantum galaxy', user=self.user, use_ai=True)
            self.assertEqual(result['mode'], 'no_match')
            with override_settings(AI_TUTOR_ENABLED=False):
                result = answer_tutor_question('responsible for', user=self.user, use_ai=True)
                self.assertEqual(result['mode'], 'retrieval_only')
            generate.assert_not_called()
        self.assertFalse(TutorUsageBudget.objects.exists())

    def test_provider_rejects_invalid_and_oversized_responses(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.dict('os.environ', self.env), patch('learning.ai_provider.build_opener', return_value=opener):
            for raw in [b'[]', b'{"answer": 123}', b'{"answer": " "}', b'not-json', b'a' * 32769]:
                with self.subTest(raw=raw[:40]):
                    response.read.return_value = raw
                    with self.assertRaises(ValueError):
                        generate_cloudflare_answer('test', 'source')


class TutorLearningToolsTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.user = users.objects.create_user(username='learner-tools')
        self.other = users.objects.create_user(username='other-tools')
        self.profile = LearnerProfile.objects.create(user=self.user, current_cefr='A1', daily_minutes=30)
        self.content = LearningContent.objects.create(title='Entry reading', content_type='reading', skill='reading',
                                                     cefr_level='A1', review_status='language_checked', is_published=True)
        question = Question.objects.create(content=self.content, prompt='Where?', explanation='At the office.')
        AnswerOption.objects.create(question=question, label='A', text='Office', is_correct=True)
        AnswerOption.objects.create(question=question, label='B', text='Station')
        self.client.force_login(self.user)

    def test_redirect_get_does_not_repeat_inference_and_history_is_private(self):
        result = {'answer': '<script>bad()</script>', 'sources': [], 'evidence_sources': [], 'mode': 'retrieval_only'}
        with patch('learning.views.answer_tutor_question', return_value=result) as answer:
            response = self.client.post(reverse('tutor'), {'question': 'test'})
            self.assertEqual(response.status_code, 302)
            page = self.client.get(response['Location'])
            self.client.get(response['Location'])
            answer.assert_called_once()
        self.assertContains(page, '&lt;script&gt;bad()&lt;/script&gt;')
        self.assertNotContains(page, '<script>bad()')
        self.assertIn('no-store', page['Cache-Control'])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(response['Location']).status_code, 404)
        self.assertNotContains(self.client.get(reverse('tutor')), 'test</a>')

    def test_history_is_capped_and_deletion_affects_only_owner(self):
        TutorTurn.objects.bulk_create([TutorTurn(user=self.user, question=f'Old {i}', result={}) for i in range(55)])
        foreign = TutorTurn.objects.create(user=self.other, question='Other history', result={})
        self.client.post(reverse('tutor'), {'question': 'despite và although'})
        self.assertEqual(TutorTurn.objects.filter(user=self.user).count(), 50)
        self.client.post(reverse('tutor'), {'action': 'clear_history'})
        self.assertFalse(TutorTurn.objects.filter(user=self.user).exists())
        self.assertTrue(TutorTurn.objects.filter(pk=foreign.pk).exists())

    def test_clear_history_requires_login_and_csrf(self):
        from django.test import Client
        # A signed-in forged POST must not delete learner history.
        turn = TutorTurn.objects.create(user=self.user, question='Keep this', result={})
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(reverse('tutor'), {'action': 'clear_history'}).status_code, 403)
        self.assertTrue(TutorTurn.objects.filter(pk=turn.pk).exists())

    def test_progress_uses_only_own_submitted_exam_results(self):
        PracticeAttempt.objects.create(user=self.user, content=self.content, status='submitted', submitted_at=timezone.now(), correct_count=1, question_count=2)
        PracticeAttempt.objects.create(user=self.user, content=self.content, status='in_progress', correct_count=9, question_count=9)
        PracticeAttempt.objects.create(user=self.other, content=self.content, status='submitted', submitted_at=timezone.now(), correct_count=7, question_count=9)
        answer = learner_progress(self.user, self.profile)['answer']
        self.assertIn('1/2', answer)
        self.assertIn('50%', answer)
        self.assertNotIn('7/9', answer)
        with patch('learning.views.answer_tutor_question') as model:
            page = self.client.post(reverse('tutor'), {'action': 'progress'}, follow=True)
        self.assertEqual(page.context['mode'], 'learning_data')
        model.assert_not_called()
        self.assertFalse(TutorUsageBudget.objects.exists())

    def test_daily_plan_does_not_duplicate_tasks_or_consume_ai_and_links_work(self):
        first = daily_tasks(self.user, self.profile)
        second = daily_tasks(self.user, self.profile)
        self.assertEqual(first, second)
        self.assertEqual(StudyTask.objects.filter(user=self.user).count(), 1)
        page = self.client.post(reverse('tutor'), {'action': 'plan'}, follow=True)
        self.assertEqual(page.context['mode'], 'daily_plan')
        self.assertTrue(page.context['tutor_actions'])
        self.assertEqual(self.client.get(page.context['tutor_actions'][0]['href']).status_code, 200)
        self.assertFalse(TutorUsageBudget.objects.exists())

    def test_recommendations_hide_wrong_level_exam_and_drafts(self):
        for name, values in [('Draft', {'review_status': 'draft'}), ('Higher', {'cefr_level': 'C1'}), ('Other exam', {'exam_type': 'IELTS'})]:
            content = LearningContent.objects.create(title=name, content_type='reading', skill='reading', cefr_level=values.pop('cefr_level', 'A1'), is_published=True, review_status=values.pop('review_status', 'language_checked'), **values)
            Question.objects.create(content=content, prompt='Question', explanation='Answer')
        page = self.client.get(reverse('tutor'))
        self.assertEqual([item.pk for item in page.context['recommended_practice']], [self.content.pk])
        self.assertEqual(self.client.post(reverse('tutor'), {'action': 'execute_anything'}).status_code, 400)

    def test_knowledge_lookup_is_bilingual_and_explicit_question_id_cannot_bypass_access(self):
        response = answer_tutor_question('Khi nào dùng despite và although?', user=self.user)
        self.assertIn('Although + mệnh đề', response['answer'])
        self.assertEqual(response['mode'], 'retrieval_only')
        self.assertEqual(response['evidence_sources'][0]['review_status'], 'language_checked')
        response = answer_tutor_question('despite although', question_id='not-valid', user=self.user)
        self.assertEqual(response['mode'], 'no_match')


def valid_draft():
    return json.dumps({'questions': [{
        'prompt': f'Despite the delay, team {index} remained _____ throughout the meeting.',
        'options': {'A': 'calm', 'B': 'calmly', 'C': 'calmness', 'D': 'calmingly'},
        'correct_label': 'A',
        'explanation_vi': 'A là tính từ sau remained; B và D là trạng từ, C là danh từ. Cần người có chuyên môn rà soát toàn bộ câu.',
    } for index in range(3)]})


class AdminAIDraftTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username='draft-editor', email='test@example.test', password='test-only-password')
        self.client.force_login(self.admin)
        self.url = reverse('admin:learning_learningcontent_ai_draft')

    def test_only_complete_generation_saves_an_unpublished_unapproved_draft(self):
        with patch('learning.admin.provider_name', return_value='cloudflare'), patch('learning.admin.tutor_ai_available', return_value=True), patch('learning.admin.generate_cloudflare_answer', return_value=valid_draft()) as generate:
            response = self.client.post(self.url, {'topic': 'despite-although'})
        self.assertEqual(response.status_code, 302)
        content = LearningContent.objects.get()
        self.assertEqual((content.review_status, content.is_published, content.cefr_level), ('draft', False, ''))
        self.assertEqual(content.questions.count(), 3)
        content.review_status = 'language_checked'
        self.assertTrue(any('duyệt chuyên môn' in issue for issue in content.publication_issues()))
        for question in content.questions.all():
            self.assertEqual(question.options.count(), 4)
            self.assertEqual(question.options.filter(is_correct=True).count(), 1)
        self.assertEqual(TutorUsageBudget.objects.get(user=self.admin).day_count, 1)
        self.assertEqual(generate.call_args.kwargs, {'task': 'draft_part5'})
        self.assertNotIn(content, self.client.get(reverse('tutor')).context['recommended_practice'])

    def test_malformed_or_duplicate_output_rolls_back_and_never_publishes(self):
        payload = json.loads(valid_draft())
        payload['questions'][1]['options']['B'] = 'calm'
        with patch('learning.admin.provider_name', return_value='cloudflare'), patch('learning.admin.tutor_ai_available', return_value=True), patch('learning.admin.generate_cloudflare_answer', return_value=json.dumps(payload)):
            response = self.client.post(self.url, {'topic': 'despite-although'})
        self.assertContains(response, 'Không có học liệu mới được lưu')
        self.assertFalse(LearningContent.objects.exists())
        self.assertFalse(Question.objects.exists())
        self.assertEqual(TutorUsageBudget.objects.get(user=self.admin).day_count, 1)

    def test_unconfigured_provider_does_not_call_or_charge(self):
        with patch('learning.admin.tutor_ai_available', return_value=False), patch('learning.admin.generate_cloudflare_answer') as generate:
            self.client.post(self.url, {'topic': 'despite-although'})
        generate.assert_not_called()
        self.assertFalse(TutorUsageBudget.objects.exists())

    def test_staff_needs_question_and_answer_permissions_as_well_as_content(self):
        from django.contrib.auth.models import Permission
        staff = get_user_model().objects.create_user(username='partial-editor', is_staff=True)
        staff.user_permissions.add(Permission.objects.get(content_type__app_label='learning', codename='add_learningcontent'))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'topic': 'despite-although'}).status_code, 403)

    def test_invalid_schema_html_duplicate_prompts_and_extra_blanks_are_rejected(self):
        from .ai_drafts import validate_part5_draft
        mutations = [
            lambda p: p['questions'].pop(),
            lambda p: p['questions'][0].update(correct_label='E'),
            lambda p: p['questions'][0].update(prompt='<b>HTML</b> remains _____ in this long sentence.'),
            lambda p: p['questions'][0].update(prompt='The _____ invoice is waiting for _____ before delivery.'),
            lambda p: p['questions'][1].update(prompt=p['questions'][0]['prompt']),
        ]
        for mutate in mutations:
            payload = json.loads(valid_draft())
            mutate(payload)
            with self.assertRaises(ValueError):
                validate_part5_draft(json.dumps(payload))
