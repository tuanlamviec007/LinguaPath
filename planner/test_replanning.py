from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone

from learning.models import Flashcard, LearningContent, Question
from .models import LearnerProfile, StudyTask
from .services import generate_daily_plan, replan_daily_plan


class DailyPlanReplanningTests(TestCase):
    today = date(2026, 10, 23)

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='replanning-test')
        self.profile = LearnerProfile.objects.create(user=self.user, daily_minutes=30)
        self.make_content('reading')
        self.make_content('listening')
        self.make_content('vocabulary')

    def make_content(self, kind, exam='TOEIC', level='A1'):
        content = LearningContent.objects.create(
            title=f'{exam} {kind} {level}', exam_type=exam, content_type=kind, skill=kind,
            cefr_level=level, estimated_minutes=10, review_status='language_checked', is_published=True,
        )
        if kind == 'vocabulary':
            Flashcard.objects.create(content=content, term=f'{exam}-{level}', meaning_vi='từ mẫu', cefr_level=level)
        else:
            Question.objects.create(content=content, prompt='Question?', audio_script='Original script' if kind == 'listening' else '')
        return content

    def tasks(self):
        return StudyTask.objects.filter(user=self.user, scheduled_for=self.today)

    def initial_plan(self):
        return list(generate_daily_plan(self.user, self.profile, self.today))

    def complete(self, task):
        task.status = 'done'
        task.completed_at = timezone.now()
        task.save(update_fields=['status', 'completed_at'])

    def test_noop_and_tracking_only_changes_preserve_all_task_ids(self):
        tasks = self.initial_plan()
        self.complete(tasks[0])
        original_ids = set(self.tasks().values_list('pk', flat=True))
        for changed_fields in ([], ['target_score'], ['target_date'], ['target_score', 'target_date']):
            with self.subTest(changed_fields=changed_fields):
                replan_daily_plan(self.user, self.profile, changed_fields, self.today)
                self.assertEqual(set(self.tasks().values_list('pk', flat=True)), original_ids)

    def test_relevant_change_preserves_completed_task_and_only_uses_remaining_budget(self):
        tasks = self.initial_plan()
        self.complete(tasks[0])
        done_id, completed_at = tasks[0].pk, tasks[0].completed_at
        old_unfinished = {task.pk for task in tasks[1:]}
        self.profile.daily_minutes = 20
        replan_daily_plan(self.user, self.profile, ['daily_minutes'], self.today)
        done = self.tasks().get(pk=done_id)
        self.assertEqual(done.status, 'done')
        self.assertEqual(done.completed_at, completed_at)
        self.assertFalse(self.tasks().filter(pk__in=old_unfinished).exists())
        self.assertEqual(self.tasks().aggregate(total=Sum('estimated_minutes'))['total'], 20)

    def test_reduced_budget_below_completed_work_adds_nothing(self):
        tasks = self.initial_plan()
        self.complete(tasks[0])
        self.profile.daily_minutes = 5
        replan_daily_plan(self.user, self.profile, ['daily_minutes'], self.today)
        self.assertEqual(list(self.tasks().values_list('pk', flat=True)), [tasks[0].pk])

    def test_all_done_dashboard_does_not_refill_plan(self):
        tasks = self.initial_plan()
        for task in tasks:
            self.complete(task)
        self.make_content('reading', level='A2')
        result = generate_daily_plan(self.user, self.profile, self.today)
        self.assertEqual(set(result.values_list('pk', flat=True)), {task.pk for task in tasks})
        self.assertEqual(self.tasks().count(), 3)

    def test_hidden_completed_work_still_consumes_budget(self):
        tasks = self.initial_plan()
        self.complete(tasks[0])
        tasks[0].content.is_published = False
        tasks[0].content.save(update_fields=['is_published'])
        self.profile.daily_minutes = 20
        visible = replan_daily_plan(self.user, self.profile, ['daily_minutes'], self.today)
        self.assertEqual(visible.count(), 1)
        self.assertEqual(self.tasks().aggregate(total=Sum('estimated_minutes'))['total'], 20)
        self.assertTrue(self.tasks().filter(pk=tasks[0].pk, status='done').exists())

    def test_exam_switch_keeps_old_completed_work_and_charges_shared_budget(self):
        tasks = self.initial_plan()
        self.complete(tasks[0])
        new_content = self.make_content('reading', exam='IELTS')
        self.profile.exam_goal = 'IELTS'
        self.profile.daily_minutes = 20
        visible = replan_daily_plan(self.user, self.profile, ['exam_goal', 'daily_minutes'], self.today)
        self.assertEqual(list(visible.values_list('content_id', flat=True)), [new_content.pk])
        self.assertTrue(self.tasks().filter(pk=tasks[0].pk, status='done').exists())
        self.assertEqual(self.tasks().aggregate(total=Sum('estimated_minutes'))['total'], 20)
        self.assertFalse(self.tasks().filter(status='todo', content__exam_type='TOEIC').exists())

    def test_level_change_invalidates_old_level_tasks(self):
        self.initial_plan()
        old_ids = set(self.tasks().values_list('pk', flat=True))
        a2 = self.make_content('vocabulary', level='A2')
        self.profile.current_cefr = 'A2'
        self.profile.target_cefr = 'B1'
        result = replan_daily_plan(self.user, self.profile, ['current_cefr'], self.today)
        self.assertFalse(self.tasks().filter(pk__in=old_ids).exists())
        self.assertEqual(list(result.filter(content__content_type='vocabulary').values_list('content_id', 'cefr_level')), [(a2.pk, 'A2')])

    def test_other_users_and_other_days_are_untouched(self):
        self.initial_plan()
        other_user = get_user_model().objects.create_user(username='other-plan-owner')
        content = LearningContent.objects.first()
        other_task = StudyTask.objects.create(user=other_user, content=content, scheduled_for=self.today)
        old_task = StudyTask.objects.create(user=self.user, content=content, scheduled_for=date(2026, 10, 22))
        replan_daily_plan(self.user, self.profile, ['target_cefr'], self.today)
        self.assertTrue(StudyTask.objects.filter(pk=other_task.pk).exists())
        self.assertTrue(StudyTask.objects.filter(pk=old_task.pk).exists())
