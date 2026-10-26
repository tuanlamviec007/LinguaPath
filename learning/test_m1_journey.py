from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from planner.models import LearnerProfile, StudyTask
from .models import Flashcard, LearningContent, PracticeAttempt, Question, UserFlashcardState


class StableLearningJourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='m1-owner')
        cls.other = get_user_model().objects.create_user(username='m1-other')
        cls.profile = LearnerProfile.objects.create(
            user=cls.user, onboarding_complete=True, current_cefr='A1',
            target_cefr='B1', target_score=750, daily_minutes=30,
        )
        cls.words = LearningContent.objects.create(
            title='Completed vocabulary', content_type='vocabulary', skill='vocabulary',
            review_status='language_checked', is_published=True, estimated_minutes=10,
        )
        Flashcard.objects.create(content=cls.words, term='desk', meaning_vi='bàn', cefr_level='A1')
        cls.reading = LearningContent.objects.create(
            title='Five minute reading', content_type='reading', skill='reading',
            review_status='language_checked', is_published=True, cefr_level='A1', estimated_minutes=5,
        )
        Question.objects.create(content=cls.reading, prompt='What is on the desk?')

    def setUp(self):
        self.client.force_login(self.user)

    def goal(self, **changes):
        return self.client.post(reverse('learning_goal'), {
            'current_cefr': 'A1', 'target_cefr': 'B1', 'daily_minutes': 30,
            'target_score': 750, 'target_date': '', **changes,
        })

    def completed_task(self):
        return StudyTask.objects.create(
            user=self.user, content=self.words, cefr_level='A1',
            scheduled_for=timezone.localdate(), status='done', estimated_minutes=10,
            completed_at=timezone.now(),
        )

    def test_noop_and_score_only_goal_save_keep_done_and_pending_task_ids(self):
        done = self.completed_task()
        pending = StudyTask.objects.create(
            user=self.user, content=self.reading, scheduled_for=timezone.localdate(),
            estimated_minutes=5, status='in_progress',
        )
        ids = set(StudyTask.objects.filter(user=self.user).values_list('pk', flat=True))
        for changes in ({}, {'target_score': 850}):
            self.assertRedirects(self.goal(**changes), reverse('dashboard'), fetch_redirect_response=False)
            self.assertEqual(set(StudyTask.objects.filter(user=self.user).values_list('pk', flat=True)), ids)
            done.refresh_from_db(); pending.refresh_from_db()
            self.assertEqual(done.status, 'done')
            self.assertEqual(pending.status, 'in_progress')

    def test_budget_change_keeps_done_work_and_uses_only_remaining_minutes(self):
        done = self.completed_task()
        self.assertEqual(self.goal(daily_minutes=15).status_code, 302)
        done.refresh_from_db()
        self.assertEqual(done.status, 'done')
        tasks = list(StudyTask.objects.filter(user=self.user, scheduled_for=timezone.localdate()))
        self.assertLessEqual(sum(t.estimated_minutes for t in tasks), 15)
        pending = [t for t in tasks if t.status != 'done']
        self.assertEqual([(t.content_id, t.estimated_minutes) for t in pending], [(self.reading.pk, 5)])
        stable_ids = {t.pk for t in tasks}
        for _ in range(2):
            self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(set(StudyTask.objects.filter(user=self.user).values_list('pk', flat=True)), stable_ids)

    def test_budget_below_completed_minutes_does_not_assign_extra_work(self):
        done = self.completed_task()
        self.assertEqual(self.goal(daily_minutes=5).status_code, 302)
        self.assertEqual(list(StudyTask.objects.filter(user=self.user).values_list('pk', flat=True)), [done.pk])

    def test_placement_apply_preserves_completed_tasks(self):
        done = self.completed_task()
        session = self.client.session
        session['placement_estimate'] = 'A2'
        session.save()
        self.assertEqual(self.client.post(reverse('learning:apply_placement_result')).status_code, 302)
        done.refresh_from_db()
        self.assertEqual(done.status, 'done')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_cefr, 'A2')
        self.assertLessEqual(sum(StudyTask.objects.filter(user=self.user).values_list('estimated_minutes', flat=True)), 30)

    def test_repeated_early_hard_posts_do_not_postpone_a_difficult_word(self):
        card = self.words.flashcards.get()
        url = reverse('learning:review_flashcard', args=[card.pk])
        self.assertEqual(self.client.post(url, {'rating': 'hard'}).status_code, 302)
        state = UserFlashcardState.objects.get(user=self.user, flashcard=card)
        original_due, original_interval = state.due_at, state.interval_days
        for _ in range(30):
            self.assertEqual(self.client.post(url, {'rating': 'hard'}).status_code, 302)
        state.refresh_from_db()
        self.assertEqual(state.due_at, original_due)
        self.assertEqual(state.interval_days, original_interval)

    def test_progress_orders_paginates_and_links_all_own_history_with_bounded_metadata(self):
        now = timezone.now()
        rows = PracticeAttempt.objects.bulk_create([
            PracticeAttempt(user=self.user, content=self.reading, status='submitted',
                            submitted_at=now-timedelta(minutes=30-i), question_count=2, correct_count=1)
            for i in range(25)
        ])
        PracticeAttempt.objects.create(user=self.user, content=self.reading, status='submitted', submitted_at=now+timedelta(days=1), question_count=99)
        PracticeAttempt.objects.create(user=self.other, content=self.reading, status='submitted', submitted_at=now, question_count=99)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('progress'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_attempts'], 25)
        self.assertEqual(response.context['total_questions'], 50)
        self.assertEqual(response.context['accuracy'], 50)
        self.assertEqual([a.pk for a in response.context['attempts']], [a.pk for a in reversed(rows[5:])])
        self.assertContains(response, reverse('learning:attempt_result', args=[rows[-1].pk]))
        self.assertContains(response, '?practice_page=2#history-title')
        metadata_sql = [q['sql'] for q in queries if 'learning_practiceattempt' in q['sql'] and 'LIMIT 20' in q['sql']]
        self.assertTrue(metadata_sql)
        self.assertNotIn('result_snapshot', metadata_sql[0])
        page2 = self.client.get(reverse('progress'), {'practice_page': 2})
        self.assertEqual([a.pk for a in page2.context['attempts']], [a.pk for a in reversed(rows[:5])])
        self.assertContains(page2, reverse('learning:attempt_result', args=[rows[0].pk]))
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual([a.pk for a in dashboard.context['recent_attempts']], [a.pk for a in reversed(rows[-4:])])
        self.assertContains(dashboard, reverse('learning:attempt_result', args=[rows[-1].pk]))
