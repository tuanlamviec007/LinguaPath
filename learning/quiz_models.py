"""Durable, user-owned snapshots for the short vocabulary challenge."""
from django.conf import settings
from django.db import models
from .quiz_answers import quiz_answer_is_valid


class VocabularyQuizSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vocabulary_quizzes')
    status = models.CharField(max_length=12, default='in_progress', choices=[('in_progress', 'Đang làm'), ('submitted', 'Đã nộp'), ('abandoned', 'Đã dừng')])
    exam_type = models.CharField(max_length=10, default='TOEIC')
    cefr_level = models.CharField(max_length=2, blank=True)
    topic = models.CharField(max_length=80, blank=True)
    vocabulary_source = models.CharField(max_length=8, default='all', choices=[('all', 'Toàn bộ từ vựng'), ('saved', 'Sổ từ cá nhân'), ('weak', 'Từ cần ôn'), ('due', 'Gõ từ đến lịch ôn')])
    mode = models.CharField(max_length=8, default='meaning', choices=[('meaning', 'Chọn nghĩa'), ('recall', 'Gõ từ tiếng Anh')])
    question_count = models.PositiveSmallIntegerField()
    correct_count = models.PositiveSmallIntegerField(default=0)
    snapshot = models.JSONField(default=list)
    answers = models.JSONField(default=dict, blank=True)
    draft_answers = models.JSONField(default=dict, blank=True)
    last_saved_at = models.DateTimeField(null=True, blank=True)
    draft_revision = models.PositiveIntegerField(default=0)
    parent_quiz = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='retry_quizzes')
    is_retry = models.BooleanField(default=False)
    xp_earned = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        constraints = [models.UniqueConstraint(fields=['user'], condition=models.Q(status='in_progress'), name='one_active_vocabulary_quiz_per_user')]
        indexes = [models.Index(fields=['user', 'status', 'submitted_at'], name='vocab_quiz_user_status_idx')]

    @property
    def saved_count(self):
        if not isinstance(self.draft_answers, dict):
            return 0
        return sum(quiz_answer_is_valid(question, self.draft_answers.get(str(question['number'])), self.mode) for question in self.snapshot)

    @property
    def accuracy(self):
        return round(self.correct_count * 100 / self.question_count) if self.question_count else 0


class VocabularyQuizDailyReward(models.Model):
    """At most one quiz bonus per user/local day, independent of retries."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='quiz_daily_rewards')
    day = models.DateField()
    quiz = models.OneToOneField(VocabularyQuizSession, on_delete=models.CASCADE, related_name='daily_reward')
    xp = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'day'], name='one_quiz_reward_per_user_day')]


class DueRecallObservation(models.Model):
    """Prospective spacing observations, not a mastery or CEFR assessment.

    Source wording remains in the immutable quiz snapshot. A numeric card ID
    preserves the observation if a shared card is removed; deleting its owner
    cascades through the quiz. No historical self-rating is backfilled here.
    """
    quiz = models.ForeignKey(VocabularyQuizSession, on_delete=models.CASCADE, related_name='due_observations')
    card_id = models.PositiveBigIntegerField()
    baseline_reviewed_at = models.DateTimeField()
    checked_at = models.DateTimeField()
    is_correct = models.BooleanField()
    exclusion_reason = models.CharField(max_length=20, blank=True, choices=[
        ('review_changed', 'Đã tự đánh giá lại trong lúc làm'),
        ('source_changed', 'Nguồn đã đổi trong lúc làm'),
        ('invalid_baseline', 'Thiếu mốc hợp lệ'),
    ])

    class Meta:
        constraints = [models.UniqueConstraint(fields=['quiz', 'card_id'], name='unique_due_observation_card')]
        indexes = [models.Index(fields=['card_id', 'checked_at'], name='due_card_checked_idx')]
