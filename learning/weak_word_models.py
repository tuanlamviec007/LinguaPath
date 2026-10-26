"""Compact, rebuildable projections; quiz snapshots remain the source of truth."""
from django.conf import settings
from django.db import models


class WeakWordProjectionState(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='weak_word_projection')
    version = models.PositiveSmallIntegerField(default=1)
    ready = models.BooleanField(default=False)
    needs_rebuild = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class WeakWordOutcome(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='weak_word_outcomes')
    exam_type = models.CharField(max_length=10)
    # Deliberately not a Flashcard FK: revisions/deletions do not rewrite the
    # evidence identity; visibility is checked against the current bank on read.
    card_id = models.PositiveBigIntegerField()
    identity_hash = models.CharField(max_length=64)
    group_key = models.CharField(max_length=64)
    mode = models.CharField(max_length=8)
    term = models.TextField()
    meaning_vi = models.TextField()
    part_of_speech = models.TextField(blank=True)
    last_attempt_at = models.DateTimeField()
    last_quiz_id = models.PositiveBigIntegerField()
    is_wrong = models.BooleanField()
    wrong_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['user', 'exam_type', 'card_id', 'identity_hash', 'group_key'],
            name='unique_weak_word_outcome_group',
        )]


class WeakWordQuizReceipt(models.Model):
    quiz = models.OneToOneField('learning.VocabularyQuizSession', on_delete=models.CASCADE, related_name='weak_word_receipt')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='weak_word_quiz_receipts')
    fingerprint = models.CharField(max_length=64)


class WeakWordPendingOutcome(models.Model):
    """Future-dated imported evidence, never folded into current counters early."""
    quiz = models.ForeignKey('learning.VocabularyQuizSession', on_delete=models.CASCADE, related_name='pending_weak_word_outcomes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pending_weak_word_outcomes')
    exam_type = models.CharField(max_length=10)
    card_id = models.PositiveBigIntegerField()
    identity_hash = models.CharField(max_length=64)
    group_key = models.CharField(max_length=64)
    mode = models.CharField(max_length=8)
    term = models.TextField()
    meaning_vi = models.TextField()
    part_of_speech = models.TextField(blank=True)
    submitted_at = models.DateTimeField()
    is_wrong = models.BooleanField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['quiz', 'card_id'], name='unique_pending_weak_word_quiz_card')]
        indexes = [models.Index(fields=['user', 'exam_type', 'submitted_at'], name='weak_pending_user_exam_time')]
