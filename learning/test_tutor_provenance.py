from copy import deepcopy

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile
from .ai import answer_tutor_question
from .models import (
    AnswerOption, AttemptAnswer, Flashcard, LearningContent, PracticeAttempt,
    Question, TutorTurn,
)
from .retrieval import retrieve_context
from .tutor_provenance import revalidate_tutor_history


class TutorProvenanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='history-owner')
        self.other = get_user_model().objects.create_user(username='other-reader')
        LearnerProfile.objects.create(user=self.user, current_cefr='A1')
        self.content = LearningContent.objects.create(
            title='Public vocabulary', exam_type='TOEIC', content_type='vocabulary',
            skill='vocabulary', is_published=True, review_status='language_checked',
        )
        self.card = Flashcard.objects.create(content=self.content, term='deadline', meaning_vi='hạn chót')
        self.result = answer_tutor_question('deadline', user=self.user)
        self.now = timezone.now()

    def revalidate(self, result=Ellipsis, user=None, exam='TOEIC'):
        return revalidate_tutor_history(self.result if result is Ellipsis else result,
                                        user or self.user, exam, self.now)

    def make_question(self, prompt='Why was the shipment delayed?'):
        question = Question.objects.create(
            content=self.content, prompt=prompt, passage='The storm delayed shipment.',
            explanation='The passage identifies the storm.', explanation_vi='Bão gây chậm trễ.',
        )
        correct = AnswerOption.objects.create(
            question=question, label='A', text='A storm', is_correct=True,
            explanation_vi='Đoạn văn nêu rõ có bão.',
        )
        AnswerOption.objects.create(question=question, label='B', text='A strike',
                                    explanation_vi='Không có bằng chứng về đình công.')
        attempt = PracticeAttempt.objects.create(
            user=self.user, content=self.content, status='submitted',
            question_count=1, question_ids=[question.pk],
        )
        AttemptAnswer.objects.create(attempt=attempt, question=question, selected_option=correct)
        return question

    def test_new_sources_have_stable_refs_without_timestamp_noise(self):
        original = deepcopy(self.result)
        result, notice = self.revalidate()
        self.assertEqual(notice['state'], 'current')
        self.assertTrue(result['evidence_sources'][0]['link_available'])
        self.assertEqual(result['evidence_sources'][0]['current_review_status'], 'language_checked')
        self.content.description = 'An unrelated administrative description'
        self.content.save()
        self.assertEqual(self.revalidate()[1]['state'], 'current')
        self.assertEqual(self.result, original)

    def test_edit_marks_stale_preserves_snapshot_and_opens_current_material(self):
        self.card.meaning_vi = 'thời hạn mới'
        self.card.save(update_fields=['meaning_vi'])
        result, notice = self.revalidate()
        source = result['evidence_sources'][0]
        self.assertEqual(notice['state'], 'stale')
        self.assertEqual(result['answer'], self.result['answer'])
        self.assertEqual(source['meaning_vi'], 'hạn chót')
        self.assertEqual(source['review_status_as_of'], 'language_checked')
        self.assertEqual(source['review_status'], '')
        self.assertTrue(source['link_available'])

    def test_review_change_is_stale_and_old_badge_is_not_current(self):
        self.content.review_status = 'teacher_approved'
        self.content.save(update_fields=['review_status'])
        result, notice = self.revalidate()
        self.assertEqual(notice['state'], 'stale')
        self.assertEqual(result['evidence_sources'][0]['current_review_status'], '')
        self.assertEqual(result['evidence_sources'][0]['review_status_as_of'], 'language_checked')

    def test_unpublished_deleted_and_changed_exam_disable_links(self):
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        for label in ('unpublished', 'deleted'):
            with self.subTest(label=label):
                result, notice = self.revalidate()
                self.assertEqual(notice['state'], 'withdrawn')
                self.assertEqual(result['answer'], self.result['answer'])
                self.assertEqual(result['evidence_sources'][0]['href'], '')
                self.assertFalse(result['evidence_sources'][0]['link_available'])
            if label == 'unpublished':
                self.card.delete()
        self.assertEqual(self.revalidate(exam='IELTS')[1]['state'], 'withdrawn')

    def test_question_structured_evidence_keeps_all_answer_explanations(self):
        question = self.make_question()
        evidence = retrieve_context('irrelevant', question_id=question.pk, user=self.user)[0]
        self.assertEqual(evidence['source_ref']['kind'], 'question')
        self.assertEqual(evidence['structured']['prompt'], question.prompt)
        self.assertEqual(len(evidence['structured']['options']), 2)
        self.assertTrue(evidence['structured']['options'][0]['is_correct'])
        self.assertIn('Không có bằng chứng về đình công.', evidence['text'])
        self.assertEqual(evidence['structured']['options'][1]['explanation_vi'],
                         'Không có bằng chứng về đình công.')

    def test_question_history_requires_current_own_submitted_access(self):
        question = self.make_question()
        result = answer_tutor_question('why', question_id=question.pk, user=self.user)
        self.assertEqual(self.revalidate(result)[1]['state'], 'current')
        decorated, notice = self.revalidate(result, user=self.other)
        self.assertEqual(notice['state'], 'withdrawn')
        self.assertFalse(decorated['evidence_sources'][0]['link_available'])
        PracticeAttempt.objects.filter(user=self.user).update(status='abandoned')
        self.assertEqual(self.revalidate(result)[1]['state'], 'withdrawn')

    def test_question_key_or_distractor_edit_changes_version(self):
        question = self.make_question()
        result = answer_tutor_question('why', question_id=question.pk, user=self.user)
        AnswerOption.objects.filter(question=question, label='B').update(explanation_vi='New distractor explanation')
        self.assertEqual(self.revalidate(result)[1]['state'], 'stale')

    def test_legacy_and_malformed_json_fail_safely_without_unverified_links(self):
        legacy = {'answer': 'A legitimate historical answer', 'mode': 'retrieval_only',
                  'sources': ['Old source'], 'evidence_sources': [
                      {'title': 'Old source', 'href': 'javascript:alert(1)', 'review_status': 'teacher_approved'},
                  ], 'actions': [{'label': 'Old link', 'href': 'https://unverified.invalid'}]}
        decorated, notice = self.revalidate(legacy)
        self.assertEqual(notice['state'], 'legacy')
        self.assertEqual(decorated['answer'], legacy['answer'])
        self.assertEqual(decorated['evidence_sources'][0]['href'], '')
        self.assertEqual(decorated['actions'][0]['href'], '')
        self.assertEqual(legacy['evidence_sources'][0]['href'], 'javascript:alert(1)')
        for malformed in ([], None, 'string', {'answer': [], 'sources': {}, 'evidence_sources': [None, 8, {}]}):
            with self.subTest(malformed=malformed):
                result, notice = self.revalidate(malformed)
                self.assertIsInstance(result['answer'], str)
                self.assertIsInstance(result['sources'], list)
                self.assertEqual(notice['state'], 'legacy')

    def test_references_with_invalid_or_out_of_range_ids_are_unknown(self):
        for object_id in (True, -1, 2**63, [], '1'):
            result = deepcopy(self.result)
            result['evidence_sources'][0]['source_ref']['object_id'] = object_id
            self.assertEqual(self.revalidate(result)[1]['state'], 'legacy')

    def test_history_validation_batches_cards_and_question_options(self):
        questions = [self.make_question(f'Why was shipment {index} delayed?') for index in range(5)]
        evidence = [self.result['evidence_sources'][0]]
        for question in questions:
            evidence.extend(answer_tutor_question('why', question_id=question.pk, user=self.user)['evidence_sources'])
        saved = {'answer': 'Combined historical explanation', 'mode': 'llm_rag',
                 'sources': [], 'evidence_sources': evidence}
        with self.assertNumQueries(3):
            result, notice = self.revalidate(saved)
        self.assertEqual(notice['state'], 'current')
        self.assertEqual(len(result['evidence_sources']), 6)

    def test_retrieval_does_not_defer_provenance_fields_per_match(self):
        for index in range(12):
            Flashcard.objects.create(content=self.content, term='deadline', meaning_vi=f'hạn {index}')
        with CaptureQueriesContext(connection) as queries:
            result = retrieve_context('explain deadline', user=self.user, limit=10)
        self.assertEqual(len(result), 10)
        self.assertEqual(len(queries), 2)  # cards and submitted-question scan

    def test_saved_turn_get_is_owner_scoped_read_only_and_handles_bad_shapes(self):
        turn = TutorTurn.objects.create(user=self.user, question='deadline', result=self.result)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('tutor'), {'turn': turn.pk}).status_code, 404)
        self.client.force_login(self.user)
        self.card.meaning_vi = 'updated'
        self.card.save(update_fields=['meaning_vi'])
        page = self.client.get(reverse('tutor'), {'turn': turn.pk})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['history_notice']['state'], 'stale')
        self.assertContains(page, 'Nguồn đã thay đổi')
        self.assertContains(page, 'Câu trả lời đã lưu')
        turn.refresh_from_db()
        self.assertEqual(turn.result, self.result)
        malformed = TutorTurn.objects.create(user=self.user, question='old', result=['malformed'])
        page = self.client.get(reverse('tutor'), {'turn': malformed.pk})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['history_notice']['state'], 'legacy')

    def test_ambiguous_choices_each_keep_their_own_source_ref(self):
        Flashcard.objects.create(content=self.content, term='deadline', meaning_vi='thời điểm hết hạn khác')
        result = answer_tutor_question('deadline', user=self.user)
        self.assertEqual(result['mode'], 'needs_context')
        self.assertEqual(len(result['evidence_sources']), 2)
        self.assertEqual(len({source['source_ref']['object_id'] for source in result['evidence_sources']}), 2)

    def test_legacy_missing_or_malformed_source_fields_render_safely(self):
        self.client.force_login(self.user)
        result = {'answer': 'An old answer', 'sources': ['Old'], 'mode': 'retrieval_only',
                  'evidence_sources': [
                      {'title': 'Old source', 'label': 'A word', 'href': 'https://unverified.invalid'},
                      {'title': {}, 'kind': [], 'label': None, 'meaning_vi': ['invalid']},
                  ]}
        turn = TutorTurn.objects.create(user=self.user, question='old', result=result)
        page = self.client.get(reverse('tutor'), {'turn': turn.pk})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Old source')
        self.assertContains(page, 'Học liệu đã lưu')
        self.assertEqual(page.context['history_notice']['state'], 'legacy')
        for source in page.context['evidence_sources']:
            self.assertEqual(source['href'], '')
            self.assertTrue(all(isinstance(source[field], str) for field in ('title', 'kind', 'label', 'meaning_vi')))
        turn.refresh_from_db()
        self.assertEqual(turn.result, result)

    def test_personal_tool_snapshots_keep_only_valid_current_navigation(self):
        path = reverse('learning:flashcards_content', args=[self.content.pk])
        snapshot = {'answer': 'Old plan', 'mode': 'daily_plan', 'actions': [
            {'title': 'Valid current lesson', 'href': path + '?level=A1'},
            {'title': 'External', 'href': 'https://attacker.invalid' + path},
            {'title': 'Mutation', 'href': reverse('learning:review_flashcard', args=[self.card.pk])},
            {'title': 'Unsafe query', 'href': path + '?next=https://attacker.invalid'},
            {'title': 'Unsafe level', 'href': path + '?level=bad'},
        ]}
        result, notice = self.revalidate(snapshot)
        self.assertEqual(notice['state'], 'snapshot')
        self.assertEqual(result['actions'][0]['href'], path + '?level=A1')
        self.assertTrue(all(action['href'] == '' for action in result['actions'][1:]))
        self.content.is_published = False
        self.content.save(update_fields=['is_published'])
        self.assertEqual(self.revalidate(snapshot)[0]['actions'][0]['href'], '')
        progress = {'answer': 'Old totals', 'mode': 'learning_data', 'actions': [
            {'title': 'Progress', 'href': reverse('progress')},
            {'title': 'Errors', 'href': reverse('learning:mistake_notebook')},
            {'title': 'Other', 'href': '/accounts/logout/'},
        ]}
        links = self.revalidate(progress)[0]['actions']
        self.assertEqual(links[0]['href'], reverse('progress'))
        self.assertEqual(links[1]['href'], reverse('learning:mistake_notebook'))
        self.assertEqual(links[2]['href'], '')
