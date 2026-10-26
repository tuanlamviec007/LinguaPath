"""Versioned tutor evidence and read-only, owner-scoped history validation."""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from django.db.models import Exists, OuterRef, Prefetch
from django.urls import reverse

from .models import AnswerOption, AttemptAnswer, CEFR_LEVELS, Flashcard, LearningContent, LEARNER_REVIEW_STATUSES, Question

CONTENT_FIELDS = ('id', 'title', 'topic', 'exam_type', 'content_type', 'skill', 'is_published',
                  'review_status', 'reviewer', 'reviewed_at', 'source_name', 'source_url', 'rights_note')
CARD_FIELDS = ('id', 'content_id', 'term', 'meaning_vi', 'part_of_speech', 'topic', 'cefr_level',
               'example_en', 'example_vi', 'pronunciation', 'audio_url', 'source_name', 'source_url', 'rights_note')
QUESTION_FIELDS = ('id', 'content_id', 'prompt', 'passage', 'audio_url', 'audio_script', 'transcript',
                   'explanation', 'explanation_vi')
OPTION_FIELDS = ('id', 'question_id', 'label', 'text', 'is_correct', 'explanation_vi')
MAX_HISTORY_SOURCES = 20
_HASH = re.compile(r'[0-9a-f]{64}\Z')


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def evidence_version(payload):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=_json_default)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _content_payload(content):
    # updated_at is deliberately absent: touching an unrelated administrative
    # field must not pretend the explanation changed. Review time is evidence.
    return {field: getattr(content, field) for field in CONTENT_FIELDS}


def _descriptor(kind, object_id, content, payload):
    return {'kind': kind, 'object_id': object_id, 'content_id': content.pk,
            'exam_type': content.exam_type, 'version': evidence_version(payload),
            'review_status': content.review_status}


def flashcard_source_ref(card):
    payload = {'schema': 'tutor-source-v1', 'kind': 'flashcard', 'content': _content_payload(card.content),
               'card': {field: getattr(card, field) for field in CARD_FIELDS}}
    return _descriptor('flashcard', card.pk, card.content, payload)


def question_structured(question):
    fields = ('prompt', 'passage', 'audio_script', 'transcript', 'explanation', 'explanation_vi')
    return {field: getattr(question, field) for field in fields} | {'options': [
        {field: getattr(option, field) for field in ('id', 'label', 'text', 'is_correct', 'explanation_vi')}
        for option in sorted(question.options.all(), key=lambda option: (option.label, option.pk))
    ]}


def question_source_ref(question, structured=None):
    payload = {'schema': 'tutor-source-v1', 'kind': 'question', 'content': _content_payload(question.content),
               'question_id': question.pk, 'audio_url': question.audio_url,
               'structured': structured if structured is not None else question_structured(question)}
    return _descriptor('question', question.pk, question.content, payload)


def knowledge_source_ref(key, record):
    """Pure helper for static editorial notes; no DB or implicit certification."""
    payload = {'schema': 'tutor-source-v1', 'kind': 'knowledge', 'id': key,
               'title': record.get('title', ''), 'text': record.get('text', ''),
               'exam_type': 'TOEIC', 'review_status': 'language_checked'}
    return {'kind': 'knowledge', 'object_id': key, 'content_id': None, 'exam_type': 'TOEIC',
            'version': evidence_version(payload), 'review_status': 'language_checked'}


def option_prefetch():
    return Prefetch('options', queryset=AnswerOption.objects.only(*OPTION_FIELDS).order_by('label', 'id'))


def _valid_ref(ref):
    if not isinstance(ref, dict) or ref.get('kind') not in ('question', 'flashcard', 'knowledge'):
        return False
    if ref.get('exam_type') not in ('TOEIC', 'IELTS') or ref.get('review_status') not in LEARNER_REVIEW_STATUSES:
        return False
    if not isinstance(ref.get('version'), str) or not _HASH.fullmatch(ref['version']):
        return False
    if ref['kind'] == 'knowledge':
        return isinstance(ref.get('object_id'), str) and 0 < len(ref['object_id']) <= 100 and ref.get('content_id') is None
    return all(isinstance(ref.get(key), int) and not isinstance(ref[key], bool) and 0 < ref[key] <= 2**63 - 1
               for key in ('object_id', 'content_id'))


def _safe_result(raw):
    """Keep the stored answer text; tolerate malformed historical JSON shapes."""
    if not isinstance(raw, dict):
        raw = {}
    result = deepcopy(raw)
    result['answer'] = raw.get('answer') if isinstance(raw.get('answer'), str) else 'Không thể đọc nội dung trả lời đã lưu của lượt này.'
    result['mode'] = raw.get('mode') if isinstance(raw.get('mode'), str) else 'retrieval_only'
    for key in ('sources', 'clarification_prompts'):
        values = result.get(key)
        result[key] = [item for item in values[:MAX_HISTORY_SOURCES] if isinstance(item, str)] if isinstance(values, list) else []
    values = result.get('evidence_sources')
    result['evidence_sources'] = [item for item in values[:MAX_HISTORY_SOURCES] if isinstance(item, dict)] if isinstance(values, list) else []
    for source in result['evidence_sources']:
        for field in ('title', 'kind', 'label', 'meaning_vi', 'review_status'):
            if not isinstance(source.get(field), str):
                source[field] = 'Học liệu đã lưu' if field == 'title' else ''
    values = result.get('actions')
    result['actions'] = [item for item in values[:MAX_HISTORY_SOURCES] if isinstance(item, dict)] if isinstance(values, list) else []
    for action in result['actions']:
        if not isinstance(action.get('title'), str):
            action['title'] = 'Mở trang học tập'
    return result


def _validate_tool_actions(result, exam):
    """Rebuild a small set of current, authenticated GET navigation links.

    Old progress/plan text is a dated snapshot. Its navigation may still work
    when the route is known and a referenced lesson remains visible; a stored
    URL is never sufficient authority for a link.
    """
    candidates, content_ids = [], set()
    allowed_static = {reverse('progress'), reverse('learning:mistake_notebook')}
    for action in result['actions']:
        href = action.get('href')
        action.update(href='', link_available=False)
        if result['mode'] not in ('learning_data', 'daily_plan') or not isinstance(href, str) or len(href) > 500:
            continue
        try:
            parts = urlsplit(href)
            if parts.scheme or parts.netloc or parts.fragment:
                continue
            if result['mode'] == 'learning_data' and parts.path in allowed_static and not parts.query:
                action.update(href=parts.path, link_available=True)
                continue
            if result['mode'] != 'daily_plan':
                continue
            match = re.fullmatch(r'/learn/(?:flashcards/content|practice)/([1-9][0-9]{0,18})/', parts.path)
            if not match or int(match[1]) > 2**63 - 1:
                continue
            content_id = int(match[1])
            is_card = parts.path == reverse('learning:flashcards_content', args=[content_id])
            canonical = reverse('learning:flashcards_content' if is_card else 'learning:practice', args=[content_id])
            if parts.path != canonical:
                continue
            query = parse_qs(parts.query, keep_blank_values=True, max_num_fields=2)
            if query and (not is_card or set(query) != {'level'} or len(query['level']) != 1
                          or query['level'][0] not in dict(CEFR_LEVELS)):
                continue
            rebuilt = canonical + ('?' + urlencode({'level': query['level'][0]}) if query else '')
            candidates.append((action, content_id, rebuilt, is_card, query.get('level', [None])[0]))
            content_ids.add(content_id)
        except (TypeError, ValueError):
            continue
    visible_ids = set(LearningContent.objects.filter(
        pk__in=content_ids, exam_type=exam, is_published=True,
        review_status__in=LEARNER_REVIEW_STATUSES,
    ).values_list('id', flat=True)) if content_ids else set()
    card_content_ids = {content_id for _, content_id, _, is_card, _ in candidates if is_card and content_id in visible_ids}
    available_levels = set(Flashcard.objects.filter(is_available=True,
        content_id__in=card_content_ids).values_list('content_id', 'cefr_level')) if card_content_ids else set()
    available_decks = {content_id for content_id, _ in available_levels}
    for action, content_id, href, is_card, level in candidates:
        if (content_id in visible_ids and (not is_card or
                ((content_id, level) in available_levels if level else content_id in available_decks))):
            action.update(href=href, link_available=True)


def revalidate_tutor_history(raw_result, user, exam, created_at):
    """Return a decorated copy; never rewrite a historical answer or stored JSON.

    Only referenced objects are loaded. Up to one card query and two question
    queries (including options) serve any bounded source list, with authorization
    folded into the question query through EXISTS.
    """
    result = _safe_result(raw_result)
    sources = result['evidence_sources']
    refs = [source.get('source_ref') for source in sources]
    valid_refs = [ref for ref in refs if _valid_ref(ref) and ref['exam_type'] == exam]
    card_ids = {ref['object_id'] for ref in valid_refs if ref['kind'] == 'flashcard'}
    question_ids = {ref['object_id'] for ref in valid_refs if ref['kind'] == 'question'}
    content_fields = tuple('content__' + field for field in CONTENT_FIELDS)
    cards = {card.pk: card for card in Flashcard.objects.filter(pk__in=card_ids).select_related('content').only(*CARD_FIELDS, 'is_available', *content_fields)} if card_ids else {}
    authorized = AttemptAnswer.objects.filter(question_id=OuterRef('pk'), attempt__user_id=getattr(user, 'pk', None),
                                             attempt__status='submitted')
    questions = {q.pk: q for q in Question.objects.filter(pk__in=question_ids).select_related('content').only(
        *QUESTION_FIELDS, *content_fields).annotate(has_learner_access=Exists(authorized)).prefetch_related(option_prefetch())} if question_ids else {}
    from .tutor_knowledge import KNOWLEDGE
    notes = {note['id']: note for note in KNOWLEDGE}
    current_refs = {}
    states = []
    messages = {
        'current': 'Nguồn vẫn khả dụng và chưa thay đổi so với lúc trả lời.',
        'stale': 'Nguồn đã thay đổi. Câu trả lời đã lưu giữ nguyên; liên kết mở học liệu hiện tại.',
        'withdrawn': 'Nguồn không còn khả dụng trong mục tiêu hoặc quyền truy cập hiện tại. Liên kết đã tắt.',
        'legacy': 'Lượt cũ chưa có thông tin phiên bản nguồn hợp lệ; không thể xác nhận trạng thái hiện tại.',
    }
    for source, ref in zip(sources, refs):
        state, href, current_review = 'legacy', '', ''
        original_review = ref.get('review_status', '') if isinstance(ref, dict) else source.get('review_status', '')
        if not isinstance(original_review, str):
            original_review = ''
        if _valid_ref(ref):
            state = 'withdrawn'
            if ref['exam_type'] == exam:
                key = (ref['kind'], ref['object_id'], ref['content_id'])
                if key not in current_refs:
                    obj = cards.get(ref['object_id']) if ref['kind'] == 'flashcard' else questions.get(ref['object_id'])
                    if ref['kind'] == 'knowledge':
                        note = notes.get(ref['object_id'])
                        current_refs[key] = (knowledge_source_ref(ref['object_id'], note), '/tutor/#knowledge-' + ref['object_id']) if note else None
                    elif (obj and obj.content.pk == ref['content_id'] and obj.content.exam_type == exam
                          and obj.content.is_published and obj.content.review_status in LEARNER_REVIEW_STATUSES
                          and (ref['kind'] != 'flashcard' or obj.is_available)
                          and (ref['kind'] != 'question' or obj.has_learner_access)):
                        current = flashcard_source_ref(obj) if ref['kind'] == 'flashcard' else question_source_ref(obj)
                        link = (reverse('learning:flashcards') + '?' + urlencode({'q': obj.term, 'all': '1'})
                                if ref['kind'] == 'flashcard' else reverse('tutor') + '?' + urlencode({'question_id': obj.pk}))
                        current_refs[key] = (current, link)
                    else:
                        current_refs[key] = None
                found = current_refs[key]
                if found:
                    current, href = found
                    state = 'current' if current['version'] == ref['version'] else 'stale'
                    current_review = current['review_status'] if state == 'current' else ''
        source.update(provenance_state=state, provenance_message=messages[state], link_available=bool(href),
                      href=href, review_status_as_of=original_review, current_review_status=current_review)
        if state != 'current':
            source['review_status'] = ''
        states.append(state)
    priority = ('withdrawn', 'stale', 'legacy', 'current')
    state = next((candidate for candidate in priority if candidate in states), 'legacy')
    _validate_tool_actions(result, exam)
    # Deterministic progress/plans are dated personal snapshots rather than
    # citations to course evidence. Known links still enforce today's access.
    if not sources and result['mode'] in ('learning_data', 'daily_plan'):
        state = 'snapshot'
        messages['snapshot'] = 'Đây là dữ liệu hoặc kế hoạch tại thời điểm đã hỏi. Hãy hỏi lại để xem thông tin mới nhất; liên kết bên dưới mở trang hiện tại.'
    notice = {'state': state, 'severity': 'info' if state in ('current', 'snapshot') else 'warning',
              'message': messages[state], 'created_at': created_at}
    return result, notice
