"""Frozen vocabulary-only reference for the pre-normalization retriever.

The benchmark calls both retrievers without a user, so only public flashcards
are eligible. This baseline does not call a model or expose question answers.
"""
import re

from django.db.models import Q

from .models import Flashcard


STOP_WORDS = {
    'the', 'is', 'are', 'was', 'were', 'what', 'when', 'where', 'why', 'how',
    'for', 'and', 'or', 'to', 'of', 'in', 'on', 'a', 'an', 'it', 'this',
    'that', 'cua', 'la', 'gi', 'tai', 'sao', 'nao', 'theo', 'bai', 'cau',
}


def _terms(text):
    return {word for word in re.findall(r'[a-zA-ZÀ-ỹ]{2,}', text.lower()) if word not in STOP_WORDS}


def retrieve_context(query, exam='TOEIC', limit=3):
    query_terms = _terms(query[:500])
    if not query_terms:
        return []
    condition = Q()
    for term in sorted(query_terms)[:12]:
        for field in ('term', 'meaning_vi', 'example_en', 'example_vi', 'content__topic'):
            condition |= Q(**{f'{field}__icontains': term})
    cards = Flashcard.objects.filter(is_available=True,
        content__is_published=True,
        content__review_status__in=['language_checked', 'teacher_approved'],
        content__exam_type=exam,
    ).filter(condition).select_related('content').order_by('id')[:100]
    matches = []
    for card in cards:
        text = ' '.join([card.term, card.meaning_vi, card.example_en, card.example_vi, card.content.topic])
        matched = query_terms & _terms(text)
        score = len(matched) / max(len(query_terms), 1)
        if len(matched) >= 2 or (len(query_terms) == 1 and len(query_terms & _terms(card.term)) == 1):
            matches.append({
                'score': score, 'source': card.content.title, 'term': card.term,
                'kind': 'flashcard', 'source_id': card.id,
            })
    matches.sort(key=lambda item: (-item['score'], item['source']))
    return matches[:limit]
