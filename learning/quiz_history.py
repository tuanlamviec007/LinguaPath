"""Private, filtered quiz archive with first-try scores kept separate from reviews."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import QueryDict
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from planner.models import LearnerProfile
from .models import CEFR_LEVELS, VocabularyQuizSession


def submitted_quizzes(user, exam_type, now=None):
    """A shared evidence boundary for the archive and hub's recent results."""
    return VocabularyQuizSession.objects.filter(
        user=user, exam_type=exam_type, status='submitted',
        submitted_at__lte=now if now is not None else timezone.now(),
    ).order_by('-submitted_at', '-pk')


@login_required
@require_GET
@never_cache
def quiz_history(request):
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    now = timezone.now()
    history = submitted_quizzes(request.user, profile.exam_goal, now)
    levels = [key for key, _ in CEFR_LEVELS]
    topics = list(history.exclude(topic='').order_by('topic').values_list('topic', flat=True).distinct())

    source = request.GET.get('source', '')
    source = source if source in ('all', 'saved', 'weak', 'due') else ''
    kind = request.GET.get('kind', '')
    kind = kind if kind in ('new', 'review') else ''
    mode = request.GET.get('mode', '')
    mode = mode if mode in ('meaning', 'recall') else ''
    period = request.GET.get('period', '30')
    period = period if period in ('7', '30', 'all') else '30'
    level = request.GET.get('level', '').strip().upper()
    level = level if level in levels else ''
    topic = request.GET.get('topic', '').strip()
    topic = topic if topic in topics else ''

    quizzes = history
    if period != 'all':
        start_day = timezone.localdate(now) - timedelta(days=int(period) - 1)
        quizzes = quizzes.filter(submitted_at__date__gte=start_day)
    if source:
        quizzes = quizzes.filter(vocabulary_source=source)
    if kind:
        quizzes = quizzes.filter(is_retry=kind == 'review')
    if mode:
        quizzes = quizzes.filter(mode=mode)
    if level:
        quizzes = quizzes.filter(cefr_level=level)
    if topic:
        quizzes = quizzes.filter(topic=topic)

    first_try = Q(is_retry=False)
    summary = quizzes.aggregate(
        new_count=Count('pk', filter=first_try),
        review_count=Count('pk', filter=Q(is_retry=True)),
        questions=Sum('question_count', filter=first_try),
        correct=Sum('correct_count', filter=first_try),
    )
    summary['questions'] = summary['questions'] or 0
    summary['correct'] = summary['correct'] or 0
    summary['accuracy'] = round(summary['correct'] * 100 / summary['questions']) if summary['questions'] else None
    # Archive rows need only metadata; answer snapshots can be large.
    page = Paginator(quizzes.defer('snapshot', 'answers', 'draft_answers'), 20).get_page(request.GET.get('page'))
    pagination_query = QueryDict(mutable=True)
    for key, value in (('period', period), ('source', source), ('kind', kind), ('mode', mode), ('level', level), ('topic', topic)):
        if value:
            pagination_query[key] = value
    return render(request, 'learning/quiz_history.html', {
        'profile': profile, 'quizzes': page, 'page_obj': page,
        'history_count': history.count(), 'filtered_count': page.paginator.count,
        'summary': summary, 'levels': levels, 'topics': topics,
        'selected_source': source, 'selected_kind': kind, 'selected_period': period,
        'selected_mode': mode,
        'selected_level': level, 'selected_topic': topic,
        'period_label': {'7': '7 ngày gần nhất', '30': '30 ngày gần nhất', 'all': 'Toàn bộ thời gian'}[period],
        'has_filters': bool(source or kind or mode or level or topic or period != '30'),
        'pagination_query': pagination_query.urlencode(),
    })
