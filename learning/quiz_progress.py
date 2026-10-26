"""Keep first-try quiz evidence separate from targeted practice repetitions."""
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from .models import VocabularyQuizSession


MIN_STRATUM_QUESTIONS = 5


def quiz_progress_summary(user, exam_type):
    now = timezone.now()
    start_day = timezone.localdate(now) - timedelta(days=29)
    sessions = VocabularyQuizSession.objects.filter(
        user=user, exam_type=exam_type, status='submitted',
        submitted_at__date__gte=start_day, submitted_at__lte=now,
    )
    first_tries = sessions.filter(is_retry=False)
    totals = first_tries.aggregate(
        completed=Count('pk'), questions=Sum('question_count'), correct=Sum('correct_count'),
    )
    questions, correct = totals['questions'] or 0, totals['correct'] or 0
    mode_labels = dict(VocabularyQuizSession._meta.get_field('mode').choices)
    source_labels = dict(VocabularyQuizSession._meta.get_field('vocabulary_source').choices)
    strata = []
    # Aggregate metadata in SQL rather than hydrating immutable answer payloads.
    # A selected CEFR filter describes the quiz configuration, not a measured
    # level of competence. Blank levels deliberately remain a mixed group.
    for row in first_tries.values('mode', 'cefr_level', 'vocabulary_source').annotate(
        completed=Count('pk'), questions=Sum('question_count'), correct=Sum('correct_count'),
    ).order_by('mode', 'cefr_level', 'vocabulary_source'):
        row_questions, row_correct = row['questions'] or 0, row['correct'] or 0
        strata.append({
            **row, 'questions': row_questions, 'correct': row_correct,
            'mode_label': mode_labels.get(row['mode'], 'Cách luyện khác'),
            'level_label': row['cefr_level'] or 'Mọi mức (trộn)',
            'source_label': source_labels.get(row['vocabulary_source'], 'Nguồn khác'),
            'accuracy': round(100 * row_correct / row_questions) if row_questions else None,
            'sufficient': row_questions >= MIN_STRATUM_QUESTIONS,
        })
    return {
        'completed': totals['completed'], 'questions': questions, 'correct': correct,
        'accuracy': round(100 * correct / questions) if questions else None,
        'strata': strata, 'minimum_stratum_questions': MIN_STRATUM_QUESTIONS,
        'retry_count': sessions.filter(is_retry=True).count(),
        'recent': list(sessions.select_related('parent_quiz').defer(
            'snapshot', 'answers', 'draft_answers',
            'parent_quiz__snapshot', 'parent_quiz__answers', 'parent_quiz__draft_answers',
        ).order_by('-submitted_at', '-pk')[:6]),
    }
