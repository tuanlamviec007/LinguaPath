"""Private bookmarks over learner-visible vocabulary; bookmarks never award XP."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Exists, F, OuterRef, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from planner.models import LearnerProfile
from .models import CEFR_LEVELS, Flashcard, LEARNER_REVIEW_STATUSES, SavedWord


def visible_cards(user):
    profile, _ = LearnerProfile.objects.get_or_create(user=user)
    return Flashcard.objects.filter(is_available=True,
        content__exam_type=profile.exam_goal, content__content_type='vocabulary',
        content__is_published=True, content__review_status__in=LEARNER_REVIEW_STATUSES,
    ).exclude(term='').exclude(meaning_vi='')


def with_saved_flags(cards, user):
    return cards.annotate(is_saved=Exists(SavedWord.objects.filter(user=user, flashcard_id=OuterRef('pk'))))


def visible_saved_words(user):
    return visible_cards(user).filter(saved_by__user=user).annotate(saved_at=F('saved_by__created_at'))


@login_required
@require_GET
@never_cache
def saved_words(request):
    all_cards = visible_saved_words(request.user)
    topics = list(all_cards.exclude(topic='').order_by('topic').values_list('topic', flat=True).distinct())
    level = request.GET.get('level', '').upper()
    level = level if level in dict(CEFR_LEVELS) else ''
    topic = request.GET.get('topic', '').strip()
    topic = topic if topic in topics else ''
    query = request.GET.get('q', '').strip()[:80]
    cards = all_cards
    if level:
        cards = cards.filter(cefr_level=level)
    if topic:
        cards = cards.filter(topic=topic)
    if query:
        cards = cards.filter(Q(term__icontains=query) | Q(meaning_vi__icontains=query) | Q(example_en__icontains=query))
    page = Paginator(cards.select_related('content').order_by('-saved_at', '-pk'), 20).get_page(request.GET.get('page'))
    return render(request, 'learning/saved_words.html', {
        'cards': page, 'page_obj': page, 'saved_count': all_cards.count(),
        'filtered_count': cards.count(), 'selected_level': level, 'selected_topic': topic,
        'search_term': query, 'levels': CEFR_LEVELS, 'topics': topics,
        'has_filters': bool(level or topic or query),
    })


@login_required
@require_POST
@never_cache
def save_word(request, card_id):
    actions = request.POST.getlist('action')
    wants_json = 'application/json' in request.headers.get('Accept', '')
    if len(actions) != 1 or actions[0] not in ('save', 'remove'):
        if wants_json:
            return JsonResponse({'ok': False, 'message': 'Thao tác lưu từ không hợp lệ.'}, status=400)
        return HttpResponseBadRequest('Thao tác lưu từ không hợp lệ.')
    action = actions[0]
    if action == 'save':
        card = get_object_or_404(visible_cards(request.user), pk=card_id)
        SavedWord.objects.get_or_create(user=request.user, flashcard=card)
    else:
        # The caller may remove a private bookmark even after its lesson is hidden.
        # This does not confirm whether any public/other-user card exists.
        SavedWord.objects.filter(user=request.user, flashcard_id=card_id).delete()
    count = visible_saved_words(request.user).count()
    if wants_json:
        return JsonResponse({'ok': True, 'saved': action == 'save', 'saved_count': count, 'card_id': card_id})
    messages.success(request, 'Đã lưu từ vào sổ cá nhân.' if action == 'save' else 'Đã bỏ từ khỏi sổ cá nhân.')
    destination = request.POST.get('next', '')
    if not destination.startswith('/') or destination.startswith('//') or not url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        destination = reverse('learning:saved_words')
    return redirect(destination)
