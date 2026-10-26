"""Current quiz mistakes derived from each learner's submitted answer history.

A correct answer clears a word until a later incorrect answer. Evidence belongs
to the exact card/term/meaning combination seen in that attempt, so a teacher's
revision cannot accidentally transfer a mistake to a different word.
"""
import unicodedata

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from planner.models import LearnerProfile
from .models import CEFR_LEVELS


def _normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split()) if isinstance(value, str) else ''


def weak_word_summary(user, exam_type=None, *, visible_bank=None, recall_index=None):
    """Read compact outcomes; history backfill is an explicit release step."""
    if exam_type is None:
        profile, _ = LearnerProfile.objects.get_or_create(user=user)
        exam_type = profile.exam_goal
    from .weak_word_outcomes import materialized_weak_word_summary
    return materialized_weak_word_summary(
        user, exam_type, visible_bank=visible_bank, recall_index=recall_index,
    )

@login_required
@require_GET
@never_cache
def weak_words(request):
    summary = weak_word_summary(request.user)
    all_words = summary['words']
    topics = sorted({word['topic'] for word in all_words if word['topic']})
    level = request.GET.get('level', '').strip().upper()
    level = level if level in dict(CEFR_LEVELS) else ''
    topic = request.GET.get('topic', '').strip()
    topic = topic if topic in topics else ''
    query = request.GET.get('q', '').strip()[:80]
    query_key = _normalized(query)
    words = [word for word in all_words if (
        (not level or word['cefr_level'] == level)
        and (not topic or word['topic'] == topic)
        and (not query_key or any(query_key in _normalized(value) for value in (
            word['term'], word['meaning_vi'], word['card'].example_en,
        )))
    )]
    page = Paginator(words, 20).get_page(request.GET.get('page'))
    return render(request, 'learning/weak_words.html', {
        'words': page, 'page_obj': page, 'weak_word_count': summary['count'],
        'weak_words_ready': summary.get('ready', True),
        'filtered_count': len(words), 'selected_level': level, 'selected_topic': topic,
        'search_term': query, 'levels': CEFR_LEVELS, 'topics': topics,
        'has_filters': bool(level or topic or query),
    })
