"""A small, read-only welcome path derived from the learner's own activity."""
from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone

from .models import FlashcardReview, VocabularyQuizSession


def starter_progress(user, profile):
    now = timezone.now()
    activity = get_user_model().objects.filter(pk=user.pk).annotate(
        tried_word=Exists(FlashcardReview.objects.filter(user_id=OuterRef('pk'),
            flashcard__content__exam_type=profile.exam_goal, reviewed_at__lte=now)),
        tried_quiz=Exists(VocabularyQuizSession.objects.filter(user_id=OuterRef('pk'),
            exam_type=profile.exam_goal, status='submitted', submitted_at__lte=now)),
    ).values('tried_word', 'tried_quiz').get()
    steps = [
        {'title': 'Chọn nhịp học', 'description': 'Mục tiêu và thời gian phù hợp với bạn.',
         'done': profile.onboarding_complete, 'href': reverse('learning_goal'), 'action': 'Chọn nhịp học'},
        {'title': 'Thử một thẻ từ', 'description': 'Xem nghĩa, rồi tự đánh giá mức nhớ.',
         'done': activity['tried_word'], 'href': reverse('learning:flashcards'), 'action': 'Học từ đầu tiên'},
        {'title': 'Làm quiz đầu tiên', 'description': 'Trả lời câu hỏi và xem lời giải sau khi nộp.',
         'done': activity['tried_quiz'], 'href': reverse('learning:quiz_hub'), 'action': 'Thử quiz từ vựng'},
    ]
    completed = sum(step['done'] for step in steps)
    return {'steps': steps, 'completed': completed, 'total': len(steps),
        'percent': round(100 * completed / len(steps)), 'complete': completed == len(steps),
        'next': next((step for step in steps if not step['done']), None)}
