from django.conf import settings
from django.db import models
from learning.models import CEFR_LEVELS


class LearnerProfile(models.Model):
    EXAMS = [('TOEIC', 'TOEIC'), ('IELTS', 'IELTS')]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='learner_profile')
    exam_goal = models.CharField(max_length=10, choices=EXAMS, default='TOEIC')
    target_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Điểm TOEIC mục tiêu (10–990).')
    current_cefr = models.CharField(max_length=2, choices=CEFR_LEVELS, default='A1')
    target_cefr = models.CharField(max_length=2, choices=CEFR_LEVELS, default='B1')
    daily_minutes = models.PositiveSmallIntegerField(default=30)
    target_date = models.DateField(null=True, blank=True)
    timezone = models.CharField(max_length=50, default='Asia/Ho_Chi_Minh')
    onboarding_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.username} – {self.exam_goal}'


class StudyTask(models.Model):
    STATUS = [('todo', 'Chưa làm'), ('in_progress', 'Đang học'), ('done', 'Hoàn thành'), ('skipped', 'Đã bỏ qua')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='study_tasks')
    content = models.ForeignKey('learning.LearningContent', on_delete=models.CASCADE, related_name='study_tasks')
    cefr_level = models.CharField(max_length=2, choices=CEFR_LEVELS, blank=True, help_text='Mức từ vựng cụ thể của nhiệm vụ, nếu có.')
    scheduled_for = models.DateField()
    estimated_minutes = models.PositiveSmallIntegerField(default=10)
    status = models.CharField(max_length=12, choices=STATUS, default='todo')
    reason = models.CharField(max_length=240, blank=True)
    recommendation_score = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    recommendation_version = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['status', 'id']
        constraints = [models.UniqueConstraint(fields=['user', 'content', 'scheduled_for', 'cefr_level'], name='unique_daily_content_task_level')]

    def __str__(self):
        return f'{self.user} – {self.content.title} – {self.scheduled_for}'
