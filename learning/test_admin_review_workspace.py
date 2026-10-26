"""Answer-bearing review packets require explicit staff content permissions."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import AnswerOption, Flashcard, LearningContent, Question


class AdminReviewWorkspaceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='pilot-editor', is_staff=True)
        permissions = Permission.objects.filter(content_type__app_label='learning', codename__in=[
            'view_learningcontent', 'view_question', 'view_answeroption', 'view_flashcard'])
        self.user.user_permissions.add(*permissions)
        self.content = LearningContent.objects.create(title='Pilot reading', exam_type='TOEIC',
            content_type='reading', skill='reading', cefr_level='B1', review_status='language_checked', is_published=True)
        self.question = Question.objects.create(content=self.content, prompt='When is the meeting?',
            passage='The meeting is on Friday.', explanation='It is on Friday.')
        AnswerOption.objects.create(question=self.question, label='A', text='Friday', is_correct=True, explanation_vi='Trong bài ghi thứ Sáu.')
        AnswerOption.objects.create(question=self.question, label='B', text='Monday', explanation_vi='Không phải thứ Hai.')
        Flashcard.objects.create(content=self.content, term='meeting', meaning_vi='cuộc họp', cefr_level='B1')
        self.url = reverse('admin:learning_learningcontent_review_workspace')
        self.client.force_login(self.user)

    def post(self, **extra):
        return self.client.post(self.url, {'exam': 'TOEIC', 'skill': '', 'level': '',
            'content_id': [str(self.content.pk)], 'max_items': '1', **extra})

    def test_get_is_readonly_and_does_not_expose_answer_key(self):
        with CaptureQueriesContext(connection) as queries:
            page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Chuẩn bị duyệt pilot')
        self.assertContains(page, 'Pilot reading')
        self.assertNotContains(page, 'Không phải thứ Hai.')
        self.assertIn('no-store', page['Cache-Control'])
        self.assertTrue(all(not query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for query in queries))

    def test_export_has_source_evidence_but_does_not_approve_or_publish(self):
        before = list(LearningContent.objects.values())
        with CaptureQueriesContext(connection) as queries:
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        packet = response.json()
        self.assertFalse(packet['approval_allowed'])
        self.assertEqual(packet['scope'], 'sample_for_human_review')
        self.assertIn('Không phải thứ Hai.', response.content.decode())
        self.assertEqual(list(LearningContent.objects.values()), before)
        self.assertTrue(all(not query['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for query in queries))

    def test_permissions_are_rechecked_when_role_is_revoked(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.user.user_permissions.remove(Permission.objects.get(content_type__app_label='learning', codename='view_answeroption'))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.post().status_code, 403)

    def test_learner_or_anonymous_cannot_open_answer_packet(self):
        learner = get_user_model().objects.create_user(username='pilot-learner')
        self.client.force_login(learner)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.post().status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_export_requires_csrf(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(self.url, {'exam': 'TOEIC','content_id':self.content.pk,'max_items':1}).status_code, 403)

    def test_invalid_or_cross_filter_selection_and_methods_are_rejected(self):
        for extra in ({'content_id': []}, {'content_id': ['9' * 5000]},
                      {'content_id': ['-1']}, {'content_id': [str(self.content.pk)] * 2},
                      {'exam': 'IELTS'}, {'max_items': '101'}, {'max_items': '0'}):
            with self.subTest(extra=str(extra)[:90]):
                self.assertEqual(self.post(**extra).status_code, 400)
        self.assertEqual(self.client.put(self.url).status_code, 405)
