"""Per-card holds change new learning, never erase a learner's prior activity."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile, StudyTask
from planner.services import generate_daily_plan
from .locking import nonkey_row_lock
from .management.commands.seed_starter_content import Command as StarterCommand
from .models import Flashcard, FlashcardReview, LearningContent, Question, UserFlashcardState
from .tutor_tools import daily_tasks


class CardHoldLearnerViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='card-hold-learner')
        self.profile = LearnerProfile.objects.create(user=self.user, onboarding_complete=True)
        self.content = LearningContent.objects.create(title='Available and held words',
            content_type='vocabulary', skill='vocabulary', exam_type='TOEIC',
            is_published=True, review_status='language_checked')
        self.available = Flashcard.objects.create(content=self.content, term='publicword',
            meaning_vi='nghĩa khả dụng', topic='Public topic', cefr_level='A1')
        self.held = Flashcard.objects.create(content=self.content, term='heldword',
            meaning_vi='nghĩa đang chờ duyệt', topic='Held-only topic', cefr_level='A1',
            is_available=False, availability_note='Chờ người biên tập kiểm tra.')
        self.client.force_login(self.user)

    def test_held_card_is_absent_from_flashcards_topics_dashboard_and_tutor_suggestions(self):
        page = self.client.get(reverse('learning:flashcards'), {'all':'1'})
        self.assertEqual(page.context['card_count'], 1)
        self.assertNotContains(page, 'heldword')
        self.assertNotIn('Held-only topic', page.context['available_topics'])
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.context['due_cards'], 0)
        self.assertEqual(dashboard.context['new_cards'], 1)
        tutor = self.client.get(reverse('tutor'))
        self.assertTrue(any('publicword' in prompt for prompt in tutor.context['suggested_prompts']))
        self.assertTrue(all('heldword' not in prompt for prompt in tutor.context['suggested_prompts']))

    def test_held_card_is_not_in_current_progress_or_due_counts_but_history_survives(self):
        now = timezone.now()
        for card in (self.available, self.held):
            UserFlashcardState.objects.create(user=self.user, flashcard=card,
                last_rating='known', reviewed_at=now, due_at=now-timedelta(days=1))
        event = FlashcardReview.objects.create(user=self.user, flashcard=self.held,
            rating='known', due_at=now)
        page = self.client.get(reverse('progress'))
        a1 = next(row for row in page.context['cefr_progress'] if row['level']=='A1')
        self.assertEqual((a1['total'], a1['known']), (1,1))
        self.assertEqual(page.context['upcoming_reviews'][0]['count'], 1)
        self.assertEqual(page.context['activity']['review_events'], 1)
        self.assertTrue(FlashcardReview.objects.filter(pk=event.pk).exists())

    def test_rating_a_held_card_is_rejected_without_srs_or_task_changes(self):
        task = StudyTask.objects.create(user=self.user, content=self.content, cefr_level='A1',
            scheduled_for=timezone.localdate(), status='todo')
        response = self.client.post(reverse('learning:review_flashcard', args=[self.held.pk]), {'rating':'known'})
        self.assertEqual(response.status_code,404)
        self.assertFalse(UserFlashcardState.objects.exists())
        self.assertFalse(FlashcardReview.objects.exists())
        task.refresh_from_db(); self.assertEqual(task.status,'todo')

    def test_rating_rechecks_hold_after_initial_card_lookup_before_any_state_write(self):
        def hold_before_lock(queryset):
            Flashcard.objects.filter(pk=self.available.pk).update(is_available=False)
            return nonkey_row_lock(queryset)
        with patch('learning.views.nonkey_row_lock', side_effect=hold_before_lock):
            response = self.client.post(reverse('learning:review_flashcard', args=[self.available.pk]), {'rating':'known'})
        self.assertEqual(response.status_code,404)
        self.assertFalse(UserFlashcardState.objects.exists())
        self.assertFalse(FlashcardReview.objects.exists())

    def test_existing_held_only_level_tasks_are_hidden_without_refilling_or_erasing_done(self):
        self.available.cefr_level = 'A2'; self.available.save(update_fields=['cefr_level'])
        pending = StudyTask.objects.create(user=self.user, content=self.content, cefr_level='A1',
            scheduled_for=timezone.localdate(), status='todo')
        done = StudyTask.objects.create(user=self.user, content=self.content, cefr_level='B1',
            scheduled_for=timezone.localdate(), status='done', estimated_minutes=15)
        visible = list(generate_daily_plan(self.user,self.profile))
        self.assertEqual([item.pk for item in visible], [done.pk])
        self.assertEqual(StudyTask.objects.count(),2)
        pending.refresh_from_db(); self.assertEqual(pending.status,'todo')
        self.assertEqual(daily_tasks(self.user,self.profile)['actions'],[])

    def test_held_known_states_do_not_unlock_next_level(self):
        next_level = Flashcard.objects.create(content=self.content, term='nextword',
            meaning_vi='từ mức tiếp theo', cefr_level='A2')
        now=timezone.now()
        for index in range(4):
            card = Flashcard.objects.create(content=self.content, term=f'held-known-{index}',
                meaning_vi=f'nghĩa {index}', cefr_level='A1', is_available=False)
            UserFlashcardState.objects.create(user=self.user, flashcard=card,
                last_rating='known', reviewed_at=now, due_at=now-timedelta(days=1))
        tasks=list(generate_daily_plan(self.user,self.profile))
        self.assertTrue(tasks)
        self.assertNotIn('A2',[item.cefr_level for item in tasks])
        self.assertTrue(Flashcard.objects.filter(pk=next_level.pk).exists())

    def test_starter_does_not_create_new_questions_from_held_cards(self):
        for index in range(3):
            Flashcard.objects.create(content=self.content, term=f'public-{index}', meaning_vi=f'nghĩa riêng {index}', cefr_level='A1')
        StarterCommand()._vocabulary_quizzes(self.content)
        self.assertEqual(Question.objects.count(),4)
        self.assertFalse(Question.objects.filter(prompt__contains='heldword').exists())
        self.assertFalse(Question.objects.filter(options__text=self.held.meaning_vi).exists())

    def test_starter_hold_does_not_shift_later_twenty_item_deck_boundaries(self):
        source = LearningContent.objects.create(title='Stable seed batches', content_type='vocabulary', skill='vocabulary')
        for index in range(21):
            Flashcard.objects.create(content=source, term=f'word{index:02d}', meaning_vi=f'nghĩa riêng biệt {index}',
                cefr_level='A1', order=index+1, is_available=index!=0)
        StarterCommand()._vocabulary_quizzes(source)
        second = LearningContent.objects.get(title='Vocabulary A1: Chọn nghĩa đúng · Bộ 02')
        self.assertEqual(list(second.questions.values_list('prompt',flat=True)), ['“word20” có nghĩa gần nhất là gì?'])
        self.assertFalse(Question.objects.filter(prompt__contains='“word00”').exists())
        self.assertEqual(Question.objects.count(),20)


class CardHoldPlacementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='placement-hold-learner')
        self.profile = LearnerProfile.objects.create(user=self.user, onboarding_complete=True)
        self.content = LearningContent.objects.create(title='Placement hold fixture', content_type='vocabulary',
            skill='vocabulary', is_published=True, review_status='language_checked')
        for level in ('A1','A2','B1','B2','C1'):
            for index in range(4):
                Flashcard.objects.create(content=self.content,term=f'{level}-word-{index}',
                    meaning_vi=f'nhóm {level} nghĩa {index}',cefr_level=level)
        self.client.force_login(self.user)
        self.url=reverse('learning:placement_test')

    def prepare(self):
        page=self.client.get(self.url)
        self.assertEqual(len(page.context['questions']),15)
        return deepcopy(self.client.session['placement_questions'])

    def post_answers(self,questions):
        return self.client.post(self.url,{'placement_token': self.client.session.get('placement_token',''), **{f'q_{index}':question['correct'] for index,question in enumerate(questions)}})

    def test_current_versioned_placement_still_scores_without_updating_profile(self):
        questions=self.prepare()
        self.assertTrue(all(len(question['source_versions'])==4 for question in questions))
        response=self.post_answers(questions)
        self.assertRedirects(response,reverse('learning:placement_result'))
        self.assertEqual(self.client.session['placement_estimate'],'C1')
        self.profile.refresh_from_db(); self.assertEqual(self.profile.current_cefr,'A1')

    def test_hold_after_get_invalidates_target_or_distractor_before_scoring(self):
        for choose in ('target','distractor'):
            questions=self.prepare()
            question=questions[0]
            card_id=question['target_id'] if choose=='target' else next(source['id'] for source in question['source_versions'] if source['id']!=question['target_id'])
            Flashcard.objects.filter(pk=card_id).update(is_available=False)
            response=self.post_answers(questions)
            self.assertRedirects(response,self.url,fetch_redirect_response=False)
            self.assertNotIn('placement_questions',self.client.session)
            self.assertNotIn('placement_estimate',self.client.session)
            Flashcard.objects.filter(pk=card_id).update(is_available=True)

    def test_source_meaning_edit_invalidates_placement(self):
        questions=self.prepare()
        Flashcard.objects.filter(pk=questions[0]['target_id']).update(meaning_vi='Nghĩa đã sửa')
        self.assertRedirects(self.post_answers(questions),self.url,fetch_redirect_response=False)
        self.assertNotIn('placement_estimate',self.client.session)

    def test_legacy_or_malformed_sessions_expire_but_prior_results_remain(self):
        valid=self.prepare()
        variants=[[{'level':item['level'],'correct':item['correct']} for item in valid],
            [{**item,'level':[]} if index==0 else item for index,item in enumerate(valid)]]
        for questions in variants:
            session=self.client.session
            session['placement_questions']=questions
            session['placement_scores']={'A1':1}; session['placement_estimate']='A1'; session.save()
            response=self.post_answers(valid)
            self.assertRedirects(response,self.url,fetch_redirect_response=False)
            self.assertNotIn('placement_questions',self.client.session)
            self.assertEqual(self.client.session['placement_scores'],{'A1':1})
