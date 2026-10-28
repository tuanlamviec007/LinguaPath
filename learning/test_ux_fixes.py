from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile, StudyTask
from .models import Flashcard, FlashcardReview, LearningContent, VocabularyQuizSession, Question, AnswerOption, PracticeAttempt, AttemptDraftAnswer


class References(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids = []; self.references = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'): self.ids.append(attrs['id'])
        self.references.extend(attrs.get('aria-describedby', '').split())


class UXFixTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='ux-owner',password='synthetic-test-password')
        self.profile = LearnerProfile.objects.create(user=self.user,onboarding_complete=True,current_cefr='B1',daily_minutes=30)
        self.content = LearningContent.objects.create(title='Small daily step',content_type='vocabulary',skill='vocabulary',estimated_minutes=16,is_published=True,review_status='language_checked')
        meanings = ['hóa đơn','biên lai','cuộc họp','hợp đồng','nhân viên','cửa sổ','giám đốc','máy tính','điện thoại','văn phòng']
        self.cards = Flashcard.objects.bulk_create([Flashcard(content=self.content,term=f'word{i}',meaning_vi=meanings[i%10],cefr_level='B1',topic='Office') for i in range(285)])
        self.client.force_login(self.user)

    def test_daily_goal_is_bounded_distinct_and_counts_honest_self_ratings(self):
        page = self.client.get(reverse('dashboard'))
        self.assertEqual((page.context['due_cards'],page.context['new_cards']),(0,285))
        task = StudyTask.objects.get(user=self.user)
        self.assertEqual(task.vocabulary_goal,10)
        for card in self.cards[:9]:
            self.client.post(reverse('learning:review_flashcard',args=[card.pk]),{'rating':'again'})
        # Repeating one card is not another completed card.
        self.client.post(reverse('learning:review_flashcard',args=[self.cards[0].pk]),{'rating':'again'})
        task.refresh_from_db();self.assertEqual(task.status,'todo')
        page=self.client.get(reverse('learning:flashcards_content',args=[self.content.pk]),{'level':'B1'})
        self.assertEqual(page.context['vocabulary_task'].vocabulary_reviewed,9)
        self.client.post(reverse('learning:review_flashcard',args=[self.cards[9].pk]),{'rating':'again'})
        task.refresh_from_db();self.assertEqual(task.status,'done')
        self.assertEqual(self.user.flashcard_states.count(),10)
        self.assertEqual(self.client.get(reverse('dashboard')).context['completed_task_count'],1)

    def test_legacy_goal_recognizes_work_already_done_today(self):
        task=StudyTask.objects.create(user=self.user,content=self.content,cefr_level='B1',scheduled_for=timezone.localdate(),estimated_minutes=16)
        for card in self.cards[:10]:
            FlashcardReview.objects.create(user=self.user,flashcard=card,rating='hard',due_at=timezone.now())
        self.client.get(reverse('dashboard'))
        task.refresh_from_db();self.assertEqual((task.vocabulary_goal,task.status),(10,'done'))

    def test_stale_resume_is_not_offered_and_dashboard_preserves_its_draft(self):
        content=LearningContent.objects.create(title='Reading',content_type='reading',skill='reading',is_published=True,review_status='language_checked')
        question=Question.objects.create(content=content,prompt='Original?',explanation='Evidence')
        option=AnswerOption.objects.create(question=question,label='A',text='Yes',is_correct=True)
        self.client.post(reverse('learning:practice',args=[content.pk]))
        attempt=PracticeAttempt.objects.get(user=self.user)
        AttemptDraftAnswer.objects.create(attempt=attempt,question=question,selected_option=option)
        question.prompt='Revised?';question.save(update_fields=['prompt'])
        page=self.client.get(reverse('dashboard'))
        self.assertFalse(page.context['resume_attempts'])
        self.assertEqual(page.context['stale_attempt_count'],1)
        attempt.refresh_from_db();self.assertEqual(attempt.status,'in_progress')
        self.assertTrue(attempt.draft_answers.exists())
        page=self.client.get(reverse('learning:practice',args=[content.pk]))
        self.assertTrue(page.context['changed_attempt']);self.assertIsNone(page.context['active_attempt'])
        self.assertContains(page,'Bắt đầu bài luyện')

    def quiz(self):
        self.client.post(reverse('learning:quiz_start'),{'count':'5'})
        return VocabularyQuizSession.objects.get(user=self.user,status='in_progress')

    def test_cancel_confirmation_keeps_draft_and_detects_newer_tab(self):
        quiz=self.quiz();url=reverse('learning:quiz_abandon',args=[quiz.pk])
        self.assertEqual(self.client.post(url).status_code,200)
        self.client.post(reverse('learning:quiz_draft',args=[quiz.pk]),{'revision':'0','answer_1':quiz.snapshot[0]['correct_key']})
        self.assertEqual(self.client.post(url,{'confirm_abandon':'yes','revision':'0'}).status_code,409)
        quiz.refresh_from_db();self.assertEqual((quiz.status,quiz.saved_count),('in_progress',1))
        self.assertEqual(self.client.post(url,{'confirm_abandon':'yes','revision':quiz.draft_revision}).status_code,302)
        quiz.refresh_from_db();self.assertEqual(quiz.status,'abandoned')

    def test_quiz_html_reflects_saved_progress_and_discloses_expiry(self):
        quiz=self.quiz()
        self.client.post(reverse('learning:quiz_draft',args=[quiz.pk]),{'revision':'0','answer_1':quiz.snapshot[0]['correct_key']})
        page=self.client.get(reverse('learning:quiz_take',args=[quiz.pk]))
        self.assertContains(page,'1/5 câu đã chọn');self.assertContains(page,'aria-valuenow="1" data-quiz-progress')
        self.assertContains(page,'24 giờ từ lúc bắt đầu');self.assertNotContains(page,'Không có giới hạn thời gian.')
        self.assertEqual(page.context['quiz']['expires_at'],quiz.started_at+timedelta(days=1))

    def test_insufficient_pool_preserves_every_filter_and_missing_topic_option(self):
        response=self.client.post(reverse('learning:quiz_start'),{'source':'saved','mode':'meaning','level':'C1','topic':'Office & Travel','count':'5'})
        query=parse_qs(urlsplit(response.url).query)
        self.assertEqual(query,{'source':['saved'],'mode':['meaning'],'level':['C1'],'topic':['Office & Travel'],'count':['5']})
        page=self.client.get(response.url)
        self.assertEqual(page.context['selected_count'],5)
        self.assertContains(page,'Office &amp; Travel · hiện chưa có từ')
        self.assertFalse(VocabularyQuizSession.objects.filter(user=self.user).exists())

    def assert_references(self,page):
        parser=References();parser.feed(page.content.decode())
        self.assertEqual(len(parser.ids),len(set(parser.ids)))
        self.assertFalse(set(parser.references)-set(parser.ids))

    def test_form_guidance_and_errors_have_resolving_ids(self):
        page=self.client.get(reverse('learning_goal'));self.assert_references(page)
        self.assertContains(page,'min="5"');self.assertContains(page,'max="240"')
        self.assertContains(page,'A1 · Mới bắt đầu')
        page=self.client.post(reverse('learning_goal'),{'current_cefr':'B1','target_cefr':'A1','daily_minutes':'0','target_score':'9999'})
        self.assertEqual(page.status_code,200);self.assert_references(page)
        self.client.logout();self.assert_references(self.client.get(reverse('register')))
        page=self.client.post(reverse('register'),{'username':'x','password1':'a','password2':'b'})
        self.assertEqual(page.status_code,200);self.assert_references(page)

    def placement(self):
        for level in ('A1','A2','B2','C1'):
            for i in range(3):
                Flashcard.objects.create(content=self.content,term=f'{level}item{i}',meaning_vi=f'meaning {level} {i}',cefr_level=level)
        self.client.get(reverse('learning:placement_test'))
        return self.client.session['placement_token']

    def test_placement_refresh_save_and_explicit_restart(self):
        token=self.placement();url=reverse('learning:placement_test')
        questions=self.client.session['placement_questions']
        self.client.get(url);self.assertEqual(self.client.session['placement_questions'],questions)
        self.client.post(url,{'placement_token':token,'action':'save_draft','q_0':'A'})
        page=self.client.get(url);self.assertEqual(page.context['questions'][0]['selected'],'A')
        self.assertContains(page,'value="A" checked required')
        self.assertEqual(self.client.post(url,{'placement_token':token,'action':'restart'}).status_code,200)
        self.assertEqual(self.client.session['placement_questions'],questions)
        self.client.post(url,{'placement_token':token,'action':'confirm_restart'})
        self.client.get(url);self.assertNotEqual(self.client.session['placement_token'],token)
        current=self.client.session['placement_questions']
        self.client.post(url,{'placement_token':token,'q_0':'B'})
        self.assertEqual(self.client.session['placement_questions'],current)
        self.assertNotIn('placement_estimate',self.client.session)
