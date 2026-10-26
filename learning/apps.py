from django.apps import AppConfig


class LearningConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'learning'

    def ready(self):
        from django.db.models.signals import post_delete, post_save
        from .models import VocabularyQuizSession
        from .weak_word_outcomes import quiz_outcomes_deleted, quiz_outcomes_saved
        post_save.connect(quiz_outcomes_saved, sender=VocabularyQuizSession,
                          dispatch_uid='learning.quiz_weak_word_outcomes_saved')
        post_delete.connect(quiz_outcomes_deleted, sender=VocabularyQuizSession,
                            dispatch_uid='learning.quiz_weak_word_outcomes_deleted')
