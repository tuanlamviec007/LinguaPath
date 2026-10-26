from django.conf import settings
from django.db import models


class SavedWord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_words')
    flashcard = models.ForeignKey('learning.Flashcard', on_delete=models.CASCADE, related_name='saved_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['user', 'flashcard'], name='one_saved_word_per_user_card')]
