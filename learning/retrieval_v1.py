"""Small, deterministic lexical retrieval for learner-visible TOEIC/IELTS content."""

import re
import unicodedata
from urllib.parse import urlencode

from django.urls import reverse

from .models import Flashcard, Question


MAX_FLASHCARDS_SCANNED = 10_000
MAX_RESULTS = 10
MAX_SIGNED_BIGINT = (2 ** 63) - 1
VISIBLE_REVIEW_STATUSES = ('language_checked', 'teacher_approved')

# These words occur in common learner questions but carry little search intent.
# A learner can still request a stopword as a vocabulary item by quoting it.
STOP_WORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'been', 'being', 'but', 'by',
    'can', 'could', 'did', 'do', 'does', 'for', 'from', 'had', 'has', 'have',
    'he', 'her', 'here', 'hers', 'him', 'his', 'how', 'i', 'if', 'in', 'into',
    'is', 'it', 'its', 'me', 'my', 'of', 'on', 'or', 'our', 'please', 'she',
    'should', 'so', 'that', 'the', 'their', 'them', 'then', 'there', 'these',
    'they', 'this', 'those', 'to', 'us', 'was', 'we', 'were', 'what', 'when',
    'where', 'which', 'who', 'why', 'will', 'with', 'would', 'you', 'your',
    'ban', 'bai', 'cach', 'cau', 'cho', 'co', 'cua', 'dung', 'gi', 'giai',
    'hay', 'hoi', 'la', 'lam', 'nao', 'nghia', 'noi', 'sao', 'the', 'theo',
    'thi', 'tu', 've', 'voi', 'y',
}

_WORD_RE = re.compile(r'[a-z0-9]+')
_QUOTED_RE = re.compile(r'["“”‘’\']([^"“”‘’\']+)["“”‘’\']')


def _fold(text):
    """Normalize accents and Vietnamese đ for matching, never for evidence."""
    text = unicodedata.normalize('NFKD', str(text or '').lower())
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return text.replace('đ', 'd')


def _tokens(text):
    return _WORD_RE.findall(_fold(text))


def _query_terms(query):
    folded = _fold(query)
    terms = {word for word in _WORD_RE.findall(folded) if word not in STOP_WORDS}
    # Quoting explicitly marks a target term, including common words such as
    # "how" or "can" that would otherwise be discarded as question wording.
    for quoted in _QUOTED_RE.findall(str(query or '').lower()):
        terms.update(_tokens(quoted))
    return terms


def _phrase_in(phrase, text):
    phrase_tokens = _tokens(phrase)
    text_tokens = _tokens(text)
    if not phrase_tokens or len(phrase_tokens) > len(text_tokens):
        return False
    width = len(phrase_tokens)
    return any(text_tokens[index:index + width] == phrase_tokens for index in range(len(text_tokens) - width + 1))


def _score_card(query, query_terms, card):
    term_tokens = _tokens(card.term)
    if not term_tokens:
        return None
    quoted_targets = _QUOTED_RE.findall(str(query or '').lower())
    explicitly_quoted = any(_phrase_in(card.term, target) for target in quoted_targets)
    is_stopword_term = all(token in STOP_WORDS for token in term_tokens)
    if any(_tokens(target) == term_tokens for target in quoted_targets):
        return (140.0, 'exact_term')
    if _tokens(query) == term_tokens and (not is_stopword_term or explicitly_quoted):
        return (120.0, 'exact_term')
    if len(term_tokens) > 1 and _phrase_in(card.term, query) and (not is_stopword_term or explicitly_quoted):
        return (100.0, 'phrase')

    matched_term_tokens = set(term_tokens) & query_terms
    if matched_term_tokens:
        coverage = len(matched_term_tokens) / len(set(term_tokens))
        return (70.0 + 10.0 * coverage, 'token')

    meaning_tokens = set(_tokens(card.meaning_vi)) - STOP_WORDS
    meaning_hits = len(query_terms & meaning_tokens)
    if meaning_hits >= 2:
        return (40.0 + min(meaning_hits, 5), 'token')

    example_tokens = (
        set(_tokens(card.example_en)) | set(_tokens(card.example_vi))
    ) - STOP_WORDS
    example_hits = len(query_terms & example_tokens)
    if example_hits >= 2:
        return (15.0 + min(example_hits, 5), 'token')
    return None


def _card_result(card, score, match_type):
    evidence = (
        f'Bài: {card.content.title}\nTừ: {card.term} ({card.part_of_speech})\n'
        f'Nghĩa: {card.meaning_vi}\nVí dụ: {card.example_en}\nDịch: {card.example_vi}'
    )
    return {
        'score': score,
        'text': evidence,
        'source': card.content.title,
        'kind': 'flashcard',
        'source_id': card.pk,
        'href': f"{reverse('learning:flashcards')}?{urlencode({'q': card.term, 'all': '1'})}",
        'match_type': match_type,
        'review_status': card.content.review_status,
        'term': card.term,
    }


def _question_result(question, score, match_type):
    evidence = (
        f'Bài: {question.content.title}\nCâu hỏi: {question.prompt}\n'
        f'Đoạn văn: {question.passage}\n'
        f'Kịch bản nghe: {question.audio_script}\nBản chép lời: {question.transcript}\n'
        f'Lời giải tham khảo trong học liệu: {question.explanation_vi or question.explanation}'
    )
    options = list(question.options.all())
    if options:
        evidence += '\nPhương án: ' + '; '.join(
            f'{option.label}. {option.text} (đúng)' if option.is_correct
            else f'{option.label}. {option.text}'
            for option in options
        )
    return {
        'score': score,
        'text': evidence,
        'source': question.content.title,
        'kind': 'question',
        'source_id': question.pk,
        'href': f'/tutor/?question_id={question.pk}',
        'match_type': match_type,
        'review_status': question.content.review_status,
        'term': None,
    }


def _submitted_questions(exam, user):
    if user is None or not getattr(user, 'is_authenticated', False):
        return Question.objects.none()
    return Question.objects.filter(
        content__is_published=True,
        content__review_status__in=VISIBLE_REVIEW_STATUSES,
        content__exam_type=exam,
        attemptanswer__attempt__user=user,
        attemptanswer__attempt__status='submitted',
    ).select_related('content').distinct()


def retrieve_context(query, exam='TOEIC', limit=3, question_id=None, user=None):
    """Retrieve matched context while preserving learner visibility boundaries.

    Flashcards are shared, published study material. Question answers are
    private to a learner until that learner has submitted an attempt containing
    the question. Query matching is performed on normalized in-memory text so
    Vietnamese accent variants work without changing original evidence.
    """
    query = str(query or '')[:500]
    try:
        limit = max(0, int(limit))
    except (TypeError, ValueError):
        limit = 3
    limit = min(limit, MAX_RESULTS)
    if limit == 0:
        return []

    # An explicit question ID is an authorization-sensitive lookup. Invalid or
    # inaccessible IDs never fall through to generic retrieval.
    if question_id is not None:
        try:
            if isinstance(question_id, bool):
                return []
            exact_id = int(question_id)
        except (TypeError, ValueError, OverflowError):
            return []
        if exact_id < 1 or exact_id > MAX_SIGNED_BIGINT:
            return []
        question = _submitted_questions(exam, user).filter(pk=exact_id).first()
        if question is None:
            return []
        return [_question_result(question, 1.0, 'exact_term')]

    query_terms = _query_terms(query)
    if not query_terms:
        return []

    candidates = []
    cards = Flashcard.objects.filter(is_available=True,
        content__is_published=True,
        content__review_status__in=VISIBLE_REVIEW_STATUSES,
        content__exam_type=exam,
    ).select_related('content').only(
        'id', 'term', 'part_of_speech', 'meaning_vi', 'example_en', 'example_vi',
        'content__id', 'content__title', 'content__review_status',
    ).order_by('id')[:MAX_FLASHCARDS_SCANNED]
    for card in cards:
        scored = _score_card(query, query_terms, card)
        if scored:
            score, match_type = scored
            candidates.append(_card_result(card, score, match_type))

    # Learner question history is usually small; scan the eligible set so
    # accent-folded queries are not lost to database collation behavior.
    questions = _submitted_questions(exam, user).only(
        'id', 'prompt', 'passage', 'audio_script', 'transcript',
        'explanation', 'explanation_vi',
        'content__id', 'content__title', 'content__review_status',
    ).order_by('id')
    for question in questions:
        searchable = ' '.join((
            question.prompt, question.passage, question.audio_script,
            question.transcript, question.explanation_vi, question.explanation,
        ))
        matched = query_terms & (set(_tokens(searchable)) - STOP_WORDS)
        if len(matched) < 2:
            continue
        score = 25.0 + 10.0 * len(matched) / max(len(query_terms), 1)
        candidates.append({
            'score': score,
            'kind': 'question',
            'source_id': question.pk,
            'question': question,
            'match_type': 'token',
        })

    # Deterministic ties make benchmark results repeatable.
    candidates.sort(key=lambda item: (-item['score'], item['kind'], item['source_id']))
    selected = candidates[:limit]
    return [
        _question_result(item['question'], item['score'], item['match_type'])
        if item['kind'] == 'question' else item
        for item in selected
    ]
