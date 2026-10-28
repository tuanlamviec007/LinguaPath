from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from .chat_brain import answer_chat_question, intent_of, general_reply
from .chat_views import current_memory
from .models import TutorTurn


class ConversationalRoutingTests(SimpleTestCase):
    def test_motivation_handles_vietnamese_and_colloquial_typing_without_retrieval(self):
        for question in ('tôi ko muốn học nữa', 'tôi không muốn học nữa', 'em chán học quá', 'mình mất động lực'):
            with self.subTest(question=question), patch('learning.chat_brain.answer_tutor_question') as rag:
                answer = answer_chat_question(question, user=None, use_ai=False)
                self.assertEqual(intent_of(question), 'motivation')
                self.assertEqual(answer['mode'], 'conversation')
                self.assertNotIn('chưa tìm thấy bài học', answer['answer'])
                self.assertIn('không cần ép', answer['answer'])
                rag.assert_not_called()

    def test_repeat_is_acknowledged_instead_of_repeating_the_same_lookup_message(self):
        query = 'tôi ko muốn học nữa'
        first = answer_chat_question(query, user=None, use_ai=False)
        second = answer_chat_question(query, user=None, use_ai=False, chat_history=[
            {'role':'user', 'content':query}, {'role':'assistant', 'content':first['answer']}])
        self.assertNotEqual(first['answer'], second['answer'])
        self.assertIn('không ép', second['answer'])

    def test_general_english_can_use_model_without_inventing_retrieved_sources(self):
        with patch('learning.chat_brain.answer_tutor_question',return_value={'mode':'no_match'}) as rag, \
             patch('learning.chat_brain.tutor_ai_available',return_value=True), \
             patch('learning.chat_brain.provider_name',return_value='cloudflare'), \
             patch('learning.chat_brain.reserve_tutor_call',return_value=(True,'')), \
             patch('learning.chat_brain.generate_cloudflare_answer',return_value={'answer':'A natural translation.','model':'llama','prompt_version':'lumi-conversation-v1'}) as model:
            answer = answer_chat_question('Dịch giúp mình: hôm nay mình muốn nghỉ ngơi',user=None,use_ai=True)
            self.assertEqual(answer['mode'],'llm_chat')
            self.assertEqual(answer['evidence_sources'],[])
            self.assertEqual(model.call_args.kwargs['task'],'chat')

    def test_exhausted_budget_remains_supportive_and_honest_about_basic_mode(self):
        with patch('learning.chat_brain.tutor_ai_available',return_value=True), patch('learning.chat_brain.provider_name',return_value='cloudflare'), \
             patch('learning.chat_brain.reserve_tutor_call',return_value=(False,'daily_limit')), patch('learning.chat_brain.generate_cloudflare_answer') as model:
            answer = general_reply('tôi không muốn học nữa',user=None,use_ai=True,intent='motivation')
            self.assertEqual(answer['mode'],'conversation')
            self.assertIn('không cần ép',answer['answer'])
            self.assertIn('Lượt AI',answer['answer'])
            model.assert_not_called()

    def test_rag_hit_keeps_its_evidence_and_does_not_get_replaced_by_general_chat(self):
        result={'mode':'llm_rag','evidence_sources':[{'title':'Published note'}]}
        with patch('learning.chat_brain.answer_tutor_question',return_value=result), patch('learning.chat_brain.general_reply') as general:
            self.assertEqual(answer_chat_question('despite và although',user=None,use_ai=True),result)
            general.assert_not_called()


class ConversationMemoryTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('conversation-learner')
        self.client.force_login(self.user)

    def test_social_memory_is_kept_and_tool_data_excluded(self):
        social=TutorTurn.objects.create(user=self.user,question='tôi ko muốn học nữa',result={
            'answer':'Mình nghe bạn.', 'mode':'llm_chat','chat_intent':'motivation'})
        tool=TutorTurn.objects.create(user=self.user,question='Progress',result={
            'answer':'Private progress numbers','mode':'learning_data'})
        memory, previous=current_memory([tool,social],self.user,'TOEIC')
        self.assertEqual(len(memory),2)
        self.assertEqual(memory[0]['content'],'tôi ko muốn học nữa')
        self.assertNotIn('Private progress',str(memory))

    def test_new_and_legacy_threads_default_to_ai_but_explicit_opt_out_is_retained(self):
        url=reverse('learning:chat')
        with patch('learning.chat_views.tutor_ai_available',return_value=True):
            page=self.client.get(url)
            self.assertTrue(page.context['use_ai'])
            response=self.client.post(url,{'token':page.context['token'],'tool':'question','question':'tôi ko muốn học nữa'})
            page=self.client.get(response.url)
            self.assertFalse(page.context['use_ai'])
            turn=TutorTurn.objects.get(user=self.user)
            turn.result.pop('chat_ai_choice');turn.save()
            self.assertTrue(self.client.get(response.url).context['use_ai'])
