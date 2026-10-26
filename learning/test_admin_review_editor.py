"""Review forms expose answer evidence only to permitted staff and never import it."""
from copy import deepcopy
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .content_review import build_review_packet
from .models import AnswerOption, LearningContent, Question


class AdminReviewEditorTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='review-editor', is_staff=True)
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='learning',
            codename__in=['view_learningcontent', 'view_question', 'view_answeroption', 'view_flashcard']))
        self.content = LearningContent.objects.create(title='Read the notice', exam_type='TOEIC',
            content_type='reading', skill='reading', cefr_level='B1')
        self.question = Question.objects.create(content=self.content, prompt='Which date?',
            passage='The answer is Friday. </script><script>alert(1)</script>', explanation='Friday is explicit.')
        AnswerOption.objects.create(question=self.question, label='A', text='Friday',
            is_correct=True, explanation_vi='Bằng chứng: Friday.')
        AnswerOption.objects.create(question=self.question, label='B', text='Sunday',
            explanation_vi='Bài không nói Sunday.')
        self.packet = build_review_packet([self.content.pk], max_items=1)
        self.workspace = reverse('admin:learning_learningcontent_review_workspace')
        self.check = reverse('admin:learning_learningcontent_review_check')
        self.client.force_login(self.user)

    def upload(self, packet=None, action='check', client=None):
        raw = json.dumps(self.packet if packet is None else packet).encode()
        return (client or self.client).post(self.check, {'action': action,
            'packet': SimpleUploadedFile('review.json', raw, content_type='application/json')})

    def assert_readonly(self, queries):
        self.assertTrue(all(not item['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
            for item in queries))

    def test_editor_contains_safe_source_and_never_writes(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(self.workspace, {'exam': 'TOEIC', 'content_id': self.content.pk,
                'max_items': 1, 'action': 'editor'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'review-editor-root')
        self.assertEqual(response.context['packet']['contents'][0]['questions'][0]['options'][0]['explanation_vi'],
            'Bằng chứng: Friday.')
        self.assertNotContains(response, '</script><script>alert(1)</script>')
        self.assertContains(response, r'\u003C/script\u003E\u003Cscript\u003E')
        self.assertIn('no-store', response['Cache-Control'])
        self.assert_readonly(queries)

    def test_check_get_does_not_embed_any_source(self):
        response = self.client.get(self.check)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Bằng chứng: Friday.')
        self.assertIn('no-store', response['Cache-Control'])

    def test_current_draft_can_reopen_with_annotations_preserved(self):
        packet = deepcopy(self.packet)
        packet['contents'][0]['questions'][0]['human_review']['notes'] = 'Reviewer note to keep.'
        with CaptureQueriesContext(connection) as queries:
            response = self.upload(packet, action='reopen')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'review-editor-root')
        self.assertContains(response, 'Reviewer note to keep.')
        self.assert_readonly(queries)

    def test_stale_source_cannot_reopen_or_write(self):
        LearningContent.objects.filter(pk=self.content.pk).update(title='Revised notice')
        with CaptureQueriesContext(connection) as queries:
            response = self.upload(action='reopen')
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, 'review-editor-root', status_code=409)
        self.assertContains(response, 'Nguồn hoặc phiên bản đã thay đổi', status_code=409)
        self.assert_readonly(queries)

    def test_report_download_omits_source_and_keys(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.upload(action='report')
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        report = response.json()
        self.assertEqual(report['status'], 'current')
        self.assertFalse(report['approval_allowed'])
        self.assertNotIn('Bằng chứng: Friday.', response.content.decode())
        self.assert_readonly(queries)

    def test_malformed_or_missing_upload_fails_cleanly(self):
        for raw in (b'{', b'{"schema_version":NaN}', b'{"a":1,"a":2}', b'[]'):
            with self.subTest(raw=raw):
                response = self.client.post(self.check, {'packet': SimpleUploadedFile('bad.json', raw)})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(self.check, {}).status_code, 400)
        self.assertEqual(self.upload(action='approve').status_code, 400)
        self.assertEqual(self.client.put(self.check).status_code, 405)

    def test_tampered_source_cannot_reopen(self):
        packet = deepcopy(self.packet)
        packet['contents'][0]['questions'][0]['options'][0]['is_correct'] = False
        response = self.upload(packet, action='reopen')
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, 'review-editor-root', status_code=400)

    def test_revoked_role_and_learners_cannot_upload(self):
        self.assertEqual(self.client.get(self.check).status_code, 200)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='learning', codename='view_answeroption'))
        self.assertEqual(self.client.get(self.check).status_code, 403)
        self.assertEqual(self.upload().status_code, 403)
        learner = get_user_model().objects.create_user(username='not-reviewer')
        self.client.force_login(learner)
        self.assertEqual(self.upload().status_code, 302)
        self.client.logout()
        self.assertEqual(self.upload().status_code, 302)

    def test_upload_requires_csrf_and_accepts_valid_token(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(self.upload(client=strict).status_code, 403)
        strict.get(self.check)
        response = strict.post(self.check, {'csrfmiddlewaretoken': strict.cookies['csrftoken'].value,
            'packet': SimpleUploadedFile('review.json', json.dumps(self.packet).encode())})
        self.assertEqual(response.status_code, 200)
