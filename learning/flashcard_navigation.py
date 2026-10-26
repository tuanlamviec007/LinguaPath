"""Keep rating redirects inside the learner's current flashcard workspace."""
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .models import CEFR_LEVELS


def flashcard_return_url(request, card):
    fallback = f"{reverse('learning:flashcards_content', args=[card.content_id])}?level={card.cefr_level}"
    destinations = request.POST.getlist('next')
    if len(destinations) != 1:
        return fallback
    value = destinations[0]
    if (len(value) > 2048 or not value.startswith('/') or value.startswith('//')
            or not url_has_allowed_host_and_scheme(value, {request.get_host()}, require_https=request.is_secure())):
        return fallback
    parsed = urlsplit(value)
    if parsed.netloc or parsed.scheme:
        return fallback
    try:
        match = resolve(parsed.path)
    except Resolver404:
        return fallback
    if match.view_name not in {'learning:flashcards', 'learning:flashcards_content'}:
        return fallback
    filters = parse_qs(parsed.query)
    query = {}
    if filters.get('all') == ['1']:
        query['all'] = '1'
    level = filters.get('level', [''])[0].upper()
    if level in dict(CEFR_LEVELS):
        query['level'] = level
    for key, limit in (('topic', 80), ('q', 80)):
        text = filters.get(key, [''])[0].strip()[:limit]
        if text:
            query[key] = text
    page = filters.get('page', [''])[0]
    if page.isascii() and page.isdecimal() and 0 < len(page) < 8 and int(page) > 0:
        query['page'] = str(int(page))
    fragment = parsed.fragment if re.fullmatch(r'flashcard-[1-9][0-9]{0,18}', parsed.fragment) else ''
    return parsed.path + ('?' + urlencode(query) if query else '') + ('#' + fragment if fragment else '')


def attach_rating_return_urls(page, *, path, show_all, level, topic, query):
    filters = {'page': page.number}
    if show_all:
        filters['all'] = '1'
    if level:
        filters['level'] = level
    if topic:
        filters['topic'] = topic
    if query:
        filters['q'] = query
    target = path + '?' + urlencode(filters)
    cards = list(page.object_list)
    for index, card in enumerate(cards):
        # Due cards leave the set after rating; continue at a neighboring card.
        neighbor = card if show_all else cards[min(index + 1, len(cards) - 1)]
        if not show_all and neighbor.pk == card.pk and index:
            neighbor = cards[index - 1]
        card.rating_return_url = f'{target}#flashcard-{neighbor.pk}'
    page.object_list = cards
