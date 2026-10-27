"""Small, deterministic lexical retrieval for learner-visible TOEIC/IELTS content."""

import re
import unicodedata
from urllib.parse import urlencode

from django.urls import reverse
from django.db.models import Count, prefetch_related_objects

from .models import Flashcard, Question
from .tutor_provenance import (
    CARD_FIELDS, CONTENT_FIELDS, QUESTION_FIELDS, flashcard_source_ref,
    option_prefetch, question_source_ref, question_structured,
)


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
    'thi', 'tu', 've', 'voi', 'y', 'mean', 'means', 'meaning', 'meanings',
    'word', 'words', 'term', 'terms', 'explain', 'explanation', 'translate',
    'translation', 'definition', 'define', 'use', 'using', 'pronunciation',
    'thich', 'va', 'vi', 'du',
}

_WORD_RE = re.compile(r'[a-z0-9]+')
_QUOTED_RE = re.compile(r'(?<!\w)(?:"([^"\n]+)"|“([^”\n]+)”|‘(.+?)’|\'(.+?)\')(?!\w)')
_QUOTE_REQUEST_BEFORE = re.compile(
    r'(?:what\s+does|what\s+(?:is|are)\s*(?:(?:a|an|the)\s+)?|'
    r'define|explain|translate|meaning\s+of|pronunciation\s+of|'
    r'(?:how\s+(?:to|do\s+you)\s+pronounce)|giai\s+thich|dich|phat\s+am|cach\s+dung)'
    r'\s*(?:(?:the\s+)?(?:word|term)|tu|cum\s+tu)?\s*$', re.I)
_QUOTE_REQUEST_AFTER = re.compile(r'^\s*(?:means?\b|nghia\s+(?:la|gi)\b|la\s+gi\b|la\s+(?:[a-z]+\s+){0,2}nao\b)')
_QUOTE_CONNECTOR = re.compile(r'^[\s,;/]*(?:(?:and|or|versus|vs|va|voi|hay)[\s,;/]*)?$')
_WHAT_IS_RE = re.compile(r'^(?:in\s+[^?!.]{1,80},\s*)?what\s+(?:is|are)\s+(?:(?:a|an)\s+)?(.+?)[?!.]*$')
SENSE_RESOLUTION_MARGIN = 6


def _fold(text):
    """Normalize accents and Vietnamese đ for matching, never for evidence."""
    text = unicodedata.normalize('NFKD', str(text or '').lower())
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return text.replace('đ', 'd')


def _tokens(text):
    return _WORD_RE.findall(_fold(text))


def _meaning_key(text):
    # Search is accent-insensitive; sense identity must not conflate ma/má.
    return tuple(re.findall(r'[^\W_]+', unicodedata.normalize('NFC', str(text or '')).casefold()))


def _literal_meaning_context(query):
    prefix, separator, meaning = query.rpartition(':')
    if separator and re.search(r'\btrong\s+ngu\s+canh\s*$', _fold(prefix)):
        return _meaning_key(meaning)
    return None


_VOCAB_INTENT_RE = re.compile(
    r'\b(?:what\s+does\b.+\bmeans?\b|what\s+is\s+(?:the\s+)?meaning\s+of|'
    r'meaning\s+of|define|translate|translation\s+of|'
    r'how\s+to\s+use|how\s+to\s+pronounce|how\s+do\s+you\s+pronounce|'
    r'how\s+to\s+say|how\s+do\s+you\s+say|use\s+of|pronunciation\s+of|'
    r'phat\s+am|cach\s+phat\s+am|'
    r'nghia\s+la\s+gi|la\s+gi|duoc\s+goi\s+la|giai\s+thich|dich|cach\s+(?:dung|su\s+dung))\b'
)
_QUESTION_START_RE = re.compile(
    r'^(?:what|when|where|why|who|which|how|is|are|did|does|do|can|could|'
    r'tai\s+sao|vi\s+sao|lam\s+sao|khi\s+nao|o\s+dau|bao\s+gio|co\s+phai)\b'
)


def _query_parts(query):
    raw_query = str(query or '')
    spans = list(_QUOTED_RE.finditer(raw_query))
    values = [next(value for value in span.groups() if value is not None) for span in spans]
    requested = {i for i, span in enumerate(spans)
                 if _QUOTE_REQUEST_BEFORE.search(_fold(raw_query[:span.start()]))
                 or _QUOTE_REQUEST_AFTER.search(_fold(raw_query[span.end():]))}
    # Adjacent quoted headwords can be a comparison; quoted example sentences
    # elsewhere are context, not competing lookup targets.
    if requested:
        for _ in spans:
            for i in range(len(spans)-1):
                if _QUOTE_CONNECTOR.fullmatch(_fold(raw_query[spans[i].end():spans[i+1].start()])) and {i, i+1} & requested:
                    requested.update((i, i+1))
    quoted_targets = [value for i, value in enumerate(values) if not requested or i in requested]
    unquoted_text = _QUOTED_RE.sub(' ', raw_query)
    unquoted_terms = {word for word in _tokens(unquoted_text) if word not in STOP_WORDS}
    quoted_terms = {word for target in quoted_targets for word in _tokens(target)}
    return unquoted_terms, quoted_terms, quoted_targets


def _phrase_in(phrase, text):
    phrase_tokens = _tokens(phrase)
    text_tokens = _tokens(text)
    if not phrase_tokens or len(phrase_tokens) > len(text_tokens):
        return False
    width = len(phrase_tokens)
    return any(text_tokens[index:index + width] == phrase_tokens for index in range(len(text_tokens) - width + 1))


def _lookup_policy(query, unquoted_terms, quoted_targets):
    unquoted = _fold(_QUOTED_RE.sub(' ', query))
    # Marker inspection excludes quoted instructions/example wording. A quoted
    # definition subject in What-is form is explicit, unlike "best bank ...".
    explicit_quote_definition = any(
        re.search(r'\bwhat\s+(?:is|are)(?:\s+(?:a|an|the))?\s*$', _fold(query[:m.start()]).strip())
        and re.match(r'^\s*(?:[?.!]|$|in\b|within\b)', _fold(query[m.end():]))
        for m in _QUOTED_RE.finditer(query))
    explicit_quote_request = any(
        ((marker := _QUOTE_REQUEST_BEFORE.search(_fold(query[:m.start()])))
         and not marker.group().startswith('what'))
        or _QUOTE_REQUEST_AFTER.search(_fold(query[m.end():]))
        for m in _QUOTED_RE.finditer(query))
    vocab_intent = bool(_VOCAB_INTENT_RE.search(unquoted)) or explicit_quote_definition or explicit_quote_request
    general_question = bool(_QUESTION_START_RE.search(unquoted.strip())) and not vocab_intent
    # Long advice/descriptive requests do not become vocabulary searches from
    # two incidental example/meaning tokens. Short library searches remain.
    allow_fallback = vocab_intent or (not quoted_targets and len(_tokens(query)) <= 3)
    definition = _WHAT_IS_RE.match(_fold(query).strip()) if not quoted_targets else None
    return vocab_intent, general_question, allow_fallback, _tokens(definition[1]) if definition else []


def _score_card(query, unquoted_terms, quoted_terms, quoted_targets, card, policy):
    term_tokens = _tokens(card.term)
    if not term_tokens:
        return None
    term_token_set = set(term_tokens)
    quoted_exact = any(_tokens(target) == term_tokens for target in quoted_targets)
    is_stopword_term = all(token in STOP_WORDS for token in term_tokens)
    vocab_intent, general_question, allow_fallback, definition_tokens = policy
    if (definition_tokens[:len(term_tokens)] == term_tokens
            and (len(definition_tokens) == len(term_tokens)
                 or definition_tokens[len(term_tokens)] in {'in', 'within'})):
        vocab_intent, general_question = True, False

    target_hits = term_token_set & unquoted_terms if term_token_set <= unquoted_terms else set()
    context_terms = unquoted_terms - term_token_set
    meaning_context = (
        set(_tokens(card.meaning_vi)) | set(_tokens(card.topic)) |
        set(_tokens(card.content.topic))
    ) - STOP_WORDS - term_token_set
    example_context = (
        set(_tokens(card.example_en)) | set(_tokens(card.example_vi))
    ) - STOP_WORDS - term_token_set
    meaning_hits = len(context_terms & meaning_context)
    example_hits = len(context_terms & example_context)
    contextual_hits = meaning_hits + example_hits

    # Quoting a headword doesn't turn a general question into a vocabulary
    # request. Preserve direct quoted lookups and explicit vocabulary prompts.
    if general_question:
        return None

    if quoted_targets and not quoted_exact:
        return None

    if quoted_exact:
        if not vocab_intent and len(_tokens(query)) > 3:
            return None
        literal_bonus = 30 if _literal_meaning_context(query) == _meaning_key(card.meaning_vi) else 0
        return (140.0 + min(meaning_hits * 6 + example_hits * 2, 20) + literal_bonus, 'exact_term')
    if _tokens(query) == term_tokens and not is_stopword_term:
        return (120.0, 'exact_term')
    if len(term_tokens) > 1 and _phrase_in(card.term, query) and vocab_intent:
        return (100.0 + min(meaning_hits * 5 + example_hits * 2, 15), 'phrase')

    # Headword mentions in general questions are incidental unless the learner
    # explicitly asks for vocabulary help or supplies useful sense context.
    if target_hits and (vocab_intent or len(_tokens(query)) <= 3):
        return (80.0 + min(meaning_hits * 6 + example_hits * 2, 18), 'token')
    if target_hits and allow_fallback and not general_question and contextual_hits >= 2:
        return (70.0 + min(meaning_hits * 6 + example_hits * 2, 18), 'token')
    if target_hits and allow_fallback and not general_question and len(unquoted_terms) <= 2 and contextual_hits >= 1:
        return (70.0 + min(meaning_hits * 6 + example_hits * 2, 18), 'token')

    # Do not let the lower-ranked semantic fallback turn a normal question
    # into an unrelated vocabulary lookup merely because its words overlap an
    # example sentence. Submitted question retrieval is handled separately.
    # Quoted material is one explicit target, not a bag of terms for broad
    # semantic search. This also blocks hostile quoted instructions.
    if quoted_targets or not allow_fallback:
        return None
    meaning_hits = len(unquoted_terms & meaning_context)
    if meaning_hits >= 2:
        return (40.0 + min(meaning_hits, 5), 'token')
    example_hits = len(unquoted_terms & example_context)
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
        'source_ref': flashcard_source_ref(card),
        'href': f"{reverse('learning:flashcards')}?{urlencode({'q': card.term, 'all': '1'})}",
        'match_type': match_type,
        'review_status': card.content.review_status,
        'term': card.term,
        'meaning_vi': card.meaning_vi,
        'topic': card.topic or card.content.topic,
        'ambiguous': False,
        'sense_count': 1,
    }


def _question_result(question, score, match_type):
    structured = question_structured(question)
    evidence = (
        f'Bài: {question.content.title}\nCâu hỏi: {question.prompt}\n'
        f'Đoạn văn: {question.passage}\n'
        f'Kịch bản nghe: {question.audio_script}\nBản chép lời: {question.transcript}\n'
        f'Lời giải tham khảo trong học liệu: {question.explanation_vi or question.explanation}'
    )
    options = list(question.options.all())
    if options:
        evidence += '\nPhương án: ' + '; '.join(
            f'{option.label}. {option.text}' + (' (đúng)' if option.is_correct else '')
            + (f' — {option.explanation_vi}' if option.explanation_vi else '')
            for option in options
        )
    return {
        'score': score,
        'text': evidence,
        'source': question.content.title,
        'kind': 'question',
        'source_id': question.pk,
        'source_ref': question_source_ref(question, structured),
        'structured': structured,
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


def retrieve_description_candidate(card_id, version, exam='TOEIC'):
    """Reopen one still-visible candidate at its displayed source version.

    IDs and hashes are freshness claims, never permissions. A stale/missing
    candidate cannot fall back to another meaning, source or question.
    """
    if isinstance(card_id, bool) or not isinstance(card_id, (int, str)):
        return []
    value = str(card_id)
    if not value.isascii() or not value.isdigit() or len(value) > 19:
        return []
    pk = int(value)
    if not 0 < pk <= MAX_SIGNED_BIGINT or not isinstance(version, str) or not re.fullmatch(r'[0-9a-f]{64}', version):
        return []
    card = Flashcard.objects.learner_visible(exam).filter(pk=pk, content__content_type='vocabulary').select_related('content').only(
        *CARD_FIELDS, *('content__' + field for field in CONTENT_FIELDS),
    ).first()
    if card is None:
        return []
    item = _card_result(card, 140, 'exact_term')
    return [item] if item['source_ref']['version'] == version else []


def retrieve_context(query, exam='TOEIC', limit=3, question_id=None, user=None, *, retrieval_mode='auto'):
    """Retrieve matched context while preserving learner visibility boundaries.

    Flashcards are shared, published study material. Question answers are
    private to a learner until that learner has submitted an attempt containing
    the question. Query matching is performed on normalized in-memory text so
    Vietnamese accent variants work without changing original evidence.
    """
    query = str(query or '')[:500]
    if retrieval_mode not in ('auto', 'description'):
        return []
    try:
        limit = max(0, int(limit))
    except (TypeError, ValueError):
        limit = 3
    limit = min(limit, MAX_RESULTS)
    if limit == 0:
        return []
    if retrieval_mode == 'description' and question_id is not None:
        return []  # Description search never reads a private question, or falls through from an ID.

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
        question = _submitted_questions(exam, user).filter(pk=exact_id).prefetch_related(option_prefetch()).first()
        if question is None:
            return []
        return [_question_result(question, 1.0, 'exact_term')]

    if retrieval_mode == 'description':
        from .retrieval_description import rank_description
        cards = Flashcard.objects.learner_visible(exam).filter(content__content_type='vocabulary').select_related('content').only(
            *CARD_FIELDS, *('content__' + field for field in CONTENT_FIELDS),
        ).order_by('id')[:MAX_FLASHCARDS_SCANNED]
        return [_card_result(card, 20 + min(score, 39), 'description')
                for card, score in rank_description(cards, query, limit)]

    unquoted_terms, quoted_terms, quoted_targets = _query_parts(query)
    query_terms = unquoted_terms | quoted_terms
    if not query_terms:
        return []
    policy = _lookup_policy(query, unquoted_terms, quoted_targets)

    candidates = []
    cards = Flashcard.objects.filter(is_available=True,
        content__is_published=True,
        content__review_status__in=VISIBLE_REVIEW_STATUSES,
        content__exam_type=exam,
    ).select_related('content').only(
        *CARD_FIELDS, *('content__' + field for field in CONTENT_FIELDS),
    ).order_by('id')[:MAX_FLASHCARDS_SCANNED]
    for card in cards:
        scored = _score_card(query, unquoted_terms, quoted_terms, quoted_targets, card, policy)
        if scored:
            score, match_type = scored
            item = _card_result(card, score, match_type)
            item['_sense_support'] = (unquoted_terms - set(_tokens(card.term))) & (
                set(_tokens(card.meaning_vi)) | set(_tokens(card.topic)) | set(_tokens(card.content.topic))
            ) - STOP_WORDS
            item['_literal_sense'] = _literal_meaning_context(query) == _meaning_key(card.meaning_vi)
            candidates.append(item)

    # Match postings first; never download/tokenize unrelated historical text.
    # The ownership/exam/publication constraints still apply before hydration.
    from .models import QuestionSearchToken
    from .question_search import token_hashes
    if len(unquoted_terms) >= 2:
        postings = QuestionSearchToken.objects.filter(
            token_hash__in=token_hashes(' '.join(unquoted_terms)),
        ).values('question_id').annotate(hits=Count('token_hash')).filter(hits__gte=2)
        hits = dict(postings.filter(question_id__in=_submitted_questions(exam, user).values('pk'))
                    .order_by('-hits', 'question_id').values_list('question_id', 'hits')[:limit])
        for question_id, matched in hits.items():
            score = 25.0 + 10.0 * matched / len(unquoted_terms)
            candidates.append({'score': score, 'kind': 'question',
                               'source_id': question_id, 'match_type': 'token'})

    # Deterministic ties make benchmark results repeatable.
    # Bare duplicate headwords are ambiguous by nature. Return all senses as
    # explicit choices instead of implying the lowest-ID card is authoritative.
    bare_term_candidates = [item for item in candidates if item['kind'] == 'flashcard']
    term_groups = {}
    resolved_senses = {}
    for item in bare_term_candidates:
        term_groups.setdefault(_fold(item['term']), []).append(item)
    for grouped in term_groups.values():
        # Collapse duplicated seed rows by normalized meaning, regardless of
        # topic. Keep the most contextually relevant source for each meaning.
        sense_rows = {}
        for item in grouped:
            meaning_key = _meaning_key(item['meaning_vi'])
            sense_rows.setdefault(meaning_key, []).append(item)
        distinct_senses = {
            meaning_key: min(rows, key=lambda item: (-item['score'], item['source_id']))
            for meaning_key, rows in sense_rows.items()
        }
        if len(distinct_senses) < 2:
            continue
        top_senses = sorted(distinct_senses.values(), key=lambda item: (-item['score'], item['source_id']))
        winner, runner_up = top_senses[:2]
        other_support = set().union(*(item['_sense_support'] for item in top_senses[1:]))
        # Example overlap alone is too weak to choose a meaning. Ask for
        # context unless meaning/topic evidence distinguishes the winner and
        # its score clears the conservative, uncalibrated lexical margin.
        if (winner['_literal_sense'] and not any(item['_literal_sense'] for item in top_senses[1:])):
            resolved_senses[_fold(winner['term'])] = _meaning_key(winner['meaning_vi'])
            continue
        if (winner['score'] - runner_up['score'] >= SENSE_RESOLUTION_MARGIN
                and winner['_sense_support'] - other_support):
            resolved_senses[_fold(winner['term'])] = _meaning_key(winner['meaning_vi'])
            continue
        choices = [
            {
                'source_id': item['source_id'],
                'term': item['term'],
                'meaning_vi': item['meaning_vi'],
                'topic': item['topic'],
                'title': item['source'],
                'review_status': item['review_status'],
                'href': item['href'],
                'source_ref': item['source_ref'],
            }
            for item in top_senses[:MAX_RESULTS]
        ]
        count = len(top_senses)
        for meaning_key in distinct_senses:
            for item in sense_rows[meaning_key]:
                item['ambiguous'] = True
                item['sense_count'] = count
                item['sense_options'] = choices
                item['sense_options_count'] = len(choices)
                item['sense_options_truncated'] = count > len(choices)

    # Multiple seed rows may describe the same term and normalized meaning.
    # Retain only their highest-scoring representative in learner results.
    deduplicated = []
    seen_senses = set()
    for item in sorted(candidates, key=lambda item: (-item['score'], item['kind'], item['source_id'])):
        if item['kind'] == 'flashcard':
            sense_key = (_fold(item['term']), _meaning_key(item['meaning_vi']))
            if sense_key[0] in resolved_senses and sense_key[1] != resolved_senses[sense_key[0]]:
                continue  # Do not send a competing meaning to the answer model.
            if sense_key in seen_senses:
                continue
            seen_senses.add(sense_key)
        deduplicated.append(item)

    selected = deduplicated[:limit]
    for item in selected:
        item.pop('_sense_support', None)
        item.pop('_literal_sense', None)
    # Recheck access and load full evidence only for the final bounded result.
    selected_ids = [item['source_id'] for item in selected if item['kind'] == 'question']
    selected_questions = list(_submitted_questions(exam, user).filter(pk__in=selected_ids).only(
        *QUESTION_FIELDS, *('content__' + field for field in CONTENT_FIELDS))) if selected_ids else []
    questions_by_id = {question.pk: question for question in selected_questions}
    selected = [item for item in selected if item['kind'] != 'question' or item['source_id'] in questions_by_id]
    for item in selected:
        if item['kind'] == 'question':
            item['question'] = questions_by_id[item['source_id']]
    if selected_questions:
        prefetch_related_objects(selected_questions, option_prefetch())
    return [
        _question_result(item['question'], item['score'], item['match_type'])
        if item['kind'] == 'question' else item
        for item in selected
    ]
