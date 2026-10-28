from unittest.mock import patch
from uuid import uuid4
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .ai import _lookup
from .ai import answer_tutor_question
from .chat_views import current_memory
from .models import Flashcard, LearningContent, TutorTurn
from .retrieval import _card_result
from .semantic_retrieval import retrieve_semantic_context
from .management.commands.index_tutor_vectors import public_documents


class ChatTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('chat-student', password='test-password')
        self.other = get_user_model().objects.create_user('other-chat-student', password='test-password')
        self.client.force_login(self.user)
        self.url = reverse('learning:chat')
        self.content = LearningContent.objects.create(title='Visible vocabulary', exam_type='TOEIC', content_type='vocabulary',
            skill='vocabulary', review_status='language_checked', is_published=True)
        self.card = Flashcard.objects.create(content=self.content, term='consistent', meaning_vi='đều đặn', cefr_level='A1')

    def send(self, page=None, **kwargs):
        page = page or self.client.get(self.url)
        data = {'token': page.context['token'], 'question': 'consistent', 'tool': 'question'}
        data.update(kwargs)
        return self.client.post(self.url, data)

    def test_requires_login_and_does_not_create_turn_on_get(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertFalse(TutorTurn.objects.exists())

    def test_same_send_token_cannot_repeat_ai_or_create_duplicate_turn(self):
        page = self.client.get(self.url)
        with patch('learning.chat_views.answer_tutor_question', return_value={'answer':'Hi', 'sources':[], 'mode':'retrieval_only'}) as answer:
            first = self.send(page)
            self.send(page)
        self.assertEqual(answer.call_count, 1)
        self.assertEqual(TutorTurn.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.client.get(first.url).status_code, 200)

    def test_busy_inference_returns_lookup_instead_of_waiting_or_spending_a_second_call(self):
        entered, release = Event(), Event()
        def generate(*args, **kwargs):
            entered.set(); release.wait(2)
            return {'answer':'Explanation', 'model':'test-model'}
        with patch('learning.ai.tutor_ai_available',return_value=True), patch('learning.ai.provider_name',return_value='cloudflare'), \
             patch('learning.ai.reserve_tutor_call',return_value=(True,'')) as budget, \
             patch('learning.ai.generate_cloudflare_answer',side_effect=generate) as provider:
            with ThreadPoolExecutor(max_workers=1) as pool:
                first=pool.submit(answer_tutor_question,'despite và although',use_ai=True)
                self.assertTrue(entered.wait(1))
                try:
                    second=answer_tutor_question('despite và although',use_ai=True)
                    self.assertEqual(second['mode'],'retrieval_only')
                    self.assertIn('yêu cầu AI khác',second['answer'])
                    self.assertEqual(budget.call_count,1)
                finally:
                    release.set()
                self.assertEqual(first.result()['mode'],'llm_rag')
                self.assertEqual(provider.call_count,1)

    def test_interrupted_pending_turn_does_not_lock_the_thread_forever(self):
        page = self.client.get(self.url)
        turn = TutorTurn.objects.create(user=self.user, question='Interrupted', result={
            'chat_thread':page.context['thread'], 'mode':'chat_pending', 'answer':'Pending', 'sources':[]})
        with patch('learning.chat_views.answer_tutor_question') as answer:
            self.send(page)
            answer.assert_not_called()
        TutorTurn.objects.filter(pk=turn.pk).update(created_at=timezone.now()-timedelta(seconds=100))
        page = self.client.get(self.url+'?thread='+page.context['thread'])
        self.assertContains(page, 'Lượt trước chưa hoàn thành')
        with patch('learning.chat_views.answer_tutor_question',return_value={'answer':'Recovered','sources':[],'mode':'retrieval_only'}) as answer:
            self.send(page)
            answer.assert_called_once()

    def test_other_user_cannot_read_thread_or_reuse_signed_send_token(self):
        page = self.client.get(self.url)
        response = self.send(page)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(response.url).status_code, 404)
        self.assertEqual(self.send(page).status_code, 400)
        self.assertFalse(TutorTurn.objects.filter(user=self.other).exists())

    def test_edited_or_held_source_is_not_replayed_as_model_memory(self):
        result = _lookup([_card_result(self.card, 1, 'exact')])
        turn = TutorTurn.objects.create(user=self.user, question='consistent', result=result)
        memory, previous = current_memory([turn], self.user, 'TOEIC')
        self.assertEqual(len(memory), 2)
        self.assertEqual(previous, 'consistent')
        self.card.meaning_vi='nhất quán';self.card.save()
        self.assertEqual(current_memory([turn], self.user, 'TOEIC'), ([], ''))
        self.content.is_published=False;self.content.save()
        self.assertEqual(current_memory([turn], self.user, 'TOEIC'), ([], ''))

    def test_progress_and_private_question_results_never_become_model_memory(self):
        progress = TutorTurn.objects.create(user=self.user, question='My progress', result={'mode':'learning_data', 'answer':'Private stats'})
        result = _lookup([_card_result(self.card, 1, 'exact')])
        result['evidence_sources'][0]['kind']='question'
        private = TutorTurn.objects.create(user=self.user, question='Exam answer', result=result)
        self.assertEqual(current_memory([progress, private], self.user, 'TOEIC'), ([], ''))

    def test_followup_retrieves_previous_topic_but_stays_inside_this_thread(self):
        first = self.send()
        page = self.client.get(first.url)
        with patch('learning.chat_views.answer_tutor_question', return_value={'answer':'Example','mode':'retrieval_only','sources':[]}) as answer:
            self.send(page, question='Cho mình ví dụ khác')
        self.assertIn('consistent', answer.call_args.kwargs['retrieval_query'])
        self.assertTrue(answer.call_args.kwargs['public_context_only'])
        new = self.client.get(self.url)
        with patch('learning.chat_views.answer_tutor_question', return_value={'answer':'No context','mode':'no_match','sources':[]}) as answer:
            self.send(new, question='Cho mình ví dụ khác')
        self.assertEqual(answer.call_args.kwargs['retrieval_query'], 'Cho mình ví dụ khác')

    def test_clear_requires_second_step_and_preserves_other_threads(self):
        response = self.send()
        page = self.client.get(response.url)
        other_turn = TutorTurn.objects.create(user=self.user, question='Keep', result={'chat_thread':str(uuid4())})
        self.send(page, tool='clear')
        self.assertEqual(TutorTurn.objects.filter(user=self.user).count(), 2)
        self.send(page, tool='confirm_clear')
        self.assertEqual(list(TutorTurn.objects.filter(user=self.user).values_list('id',flat=True)), [other_turn.pk])

    @override_settings(AI_SEMANTIC_SEARCH_ENABLED=True)
    def test_vector_match_requires_current_version_and_published_visible_source(self):
        ref = _card_result(self.card,1,'exact')['source_ref']
        match = {'id':f'flashcard:{self.card.pk}', 'version':ref['version'], 'score':.9}
        with patch('learning.semantic_retrieval.provider_name',return_value='cloudflare'), patch('learning.semantic_retrieval.cloudflare_rag_request',return_value={'matches':[match]}):
            self.assertEqual(len(retrieve_semantic_context('a regular habit')),1)
            self.card.is_available=False;self.card.save()
            self.assertEqual(retrieve_semantic_context('a regular habit'),[])
            self.card.is_available=True;self.card.meaning_vi='changed';self.card.save()
            self.assertEqual(retrieve_semantic_context('a regular habit'),[])

    @override_settings(AI_SEMANTIC_SEARCH_ENABLED=True)
    def test_vector_outage_and_unknown_source_fail_closed(self):
        with patch('learning.semantic_retrieval.provider_name',return_value='cloudflare'), patch('learning.semantic_retrieval.cloudflare_rag_request',side_effect=TimeoutError):
            self.assertEqual(retrieve_semantic_context('habit'),[])

    @override_settings(AI_SEMANTIC_SEARCH_ENABLED=True)
    def test_close_vector_ties_and_weak_matches_ask_for_more_context(self):
        ref = _card_result(self.card,1,'exact')['source_ref']
        first = {'id':f'flashcard:{self.card.pk}', 'version':ref['version'], 'score':.53}
        second = {'id':'knowledge:passive', 'version':'a'*64, 'score':.52}
        with patch('learning.semantic_retrieval.provider_name',return_value='cloudflare'), patch('learning.semantic_retrieval.cloudflare_rag_request',return_value={'matches':[first,second]}):
            self.assertEqual(retrieve_semantic_context('vague request'),[])

    def test_index_is_public_and_dry_by_default(self):
        documents = public_documents(1)
        self.assertTrue(any(d['id']==f'flashcard:{self.card.pk}' for d in documents))
        self.assertTrue(all(d['id'].startswith(('knowledge:', 'flashcard:')) for d in documents))
        self.content.is_published=False;self.content.save()
        self.assertFalse(any(d['id'].startswith('flashcard:') for d in public_documents(1)))
