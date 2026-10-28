"""Vector matches are pointers only. The database remains the authority."""
import logging
import re
from django.conf import settings
from .ai_provider import cloudflare_rag_request, provider_name
from .models import Flashcard
from .retrieval import _card_result
from .tutor_knowledge import KNOWLEDGE
from .tutor_provenance import knowledge_source_ref

logger = logging.getLogger(__name__)
_ID = re.compile(r'(knowledge:[a-z0-9-]{1,55}|flashcard:[1-9][0-9]{0,8})\Z')


def note_evidence(note):
    return {'source': note['title'], 'text': note['text'], 'kind': 'knowledge', 'source_id': note['id'],
            'source_ref': knowledge_source_ref(note['id'], note), 'href': '/tutor/#knowledge-' + note['id'],
            'review_status': 'language_checked', 'match_type': 'semantic'}


def retrieve_semantic_context(query, exam='TOEIC'):
    if not getattr(settings, 'AI_SEMANTIC_SEARCH_ENABLED', False) or provider_name() != 'cloudflare':
        return []
    try:
        response = cloudflare_rag_request('search', {'query': query[:500]})
        matches = response.get('matches', [])
        if not isinstance(matches, list):
            return []
        matches = [m for m in matches[:6] if isinstance(m, dict) and isinstance(m.get('id'), str)
                   and _ID.fullmatch(m['id']) and type(m.get('score')) in (int, float) and 0 <= m['score'] <= 1.01]
        matches.sort(key=lambda match: match['score'], reverse=True)
        # Conservative single-source fallback. Similarity is not calibrated
        # confidence; a close tie asks for a more specific question instead.
        if not matches or matches[0]['score'] < .5 or (len(matches) > 1 and matches[0]['score'] - matches[1]['score'] < .05):
            return []
        matches = matches[:1]
        ids = [int(m['id'].split(':')[1]) for m in matches if m['id'].startswith('flashcard:')]
        cards = {card.pk: card for card in Flashcard.objects.learner_visible(exam).filter(pk__in=ids).select_related('content')}
        notes = {n['id']: n for n in KNOWLEDGE} if exam == 'TOEIC' else {}
        evidence, seen = [], set()
        for match in matches:
            kind, key = match['id'].split(':', 1)
            if match['id'] in seen:
                continue
            seen.add(match['id'])
            if kind == 'knowledge' and key in notes:
                item = note_evidence(notes[key])
            elif kind == 'flashcard' and int(key) in cards:
                item = _card_result(cards[int(key)], match['score'], 'semantic')
            else:
                continue
            if item['source_ref']['version'] == match.get('version'):
                evidence.append(item)
        return evidence[:3]
    except Exception:
        logger.warning('Semantic retrieval unavailable; keeping local lookup.')
        return []
