"""Read-only, versioned samples for human editorial review.

An export is neither an approval nor proof of reviewer qualification. Whole-source
hashes detect changes outside the sample too; they are not signatures or a promise
that separate database reads constitute a locked, point-in-time snapshot.
"""
from copy import deepcopy
from datetime import date, datetime
import hashlib
from itertools import islice
import json

from django.utils import timezone

from .models import AnswerOption, Flashcard, LearningContent, Question


SCHEMA_VERSION = 'linguapath-content-review-v2'
SELECTION_ORDER = 'content ID; held cards first then order and ID; questions by order and ID; options by label and ID'
MAX_CONTENTS = 10
MAX_ITEMS = 100
MAX_PACKET_BYTES = 20 * 1024 * 1024
CONTENT_FIELDS = ('id', 'title', 'description', 'exam_type', 'content_type', 'skill',
    'question_type', 'topic', 'cefr_level', 'difficulty', 'estimated_minutes',
    'source_name', 'source_url', 'rights_note', 'review_status', 'reviewer',
    'reviewed_at', 'source_checked_on', 'is_published')
CARD_FIELDS = ('id', 'content_id', 'order', 'term', 'cefr_level', 'topic',
    'part_of_speech', 'meaning_vi', 'example_en', 'example_vi', 'pronunciation',
    'audio_url', 'source_name', 'source_url', 'rights_note', 'is_available', 'availability_note')
QUESTION_FIELDS = ('id', 'content_id', 'order', 'prompt', 'passage', 'audio_url',
    'audio_script', 'transcript', 'explanation', 'explanation_vi')
OPTION_FIELDS = ('id', 'question_id', 'label', 'text', 'is_correct', 'explanation_vi')
CHECKLIST_TEMPLATE = {
    key: {'result': None, 'notes': ''} for key in (
        'sense_and_context', 'answer_key', 'distractors_and_explanations',
        'cefr_reference', 'source_and_rights', 'audio_and_accessibility',
    )
}
HUMAN_REVIEW_TEMPLATE = {'reviewer_name': '', 'qualifications': '', 'reviewed_at': None,
                       'conclusion': None, 'notes': ''}


def _default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), default=_default).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _feed(digest, kind, value):
    raw = _encoded({'kind': kind, 'value': value})
    digest.update(str(len(raw)).encode('ascii') + b':' + raw)


def _selection(content_ids, max_items):
    if type(max_items) is not int or not 1 <= max_items <= MAX_ITEMS:
        raise ValueError('max_items must be an integer from 1 to 100.')
    if isinstance(content_ids, (str, bytes)):
        raise ValueError('Provide a list of exact content IDs.')
    try:
        ids = list(islice(content_ids, MAX_CONTENTS + 1))
    except TypeError:
        raise ValueError('Provide a list of exact content IDs.') from None
    if not 1 <= len(ids) <= MAX_CONTENTS:
        raise ValueError('Select from 1 to 10 content IDs.')
    if any(type(value) is not int or not 0 < value <= 2**63 - 1 for value in ids):
        raise ValueError('Content IDs must be positive 64-bit integers.')
    if len(ids) != len(set(ids)):
        raise ValueError('Content IDs must not repeat.')
    return sorted(ids)


def _finding(kind, object_id, code, message):
    return {'kind': kind, 'object_id': object_id, 'code': code, 'message': message}


def _sample_findings(content, cards, questions):
    findings = []
    def add(kind, object_id, code, message):
        findings.append(_finding(kind, object_id, code, message))
    if content['content_type'] != content['skill']:
        add('content', content['id'], 'skill_kind_mismatch', 'Kỹ năng và loại học liệu không khớp.')
    if not content['source_name'].strip() or not content['rights_note'].strip():
        add('content', content['id'], 'missing_source_or_rights', 'Thiếu nguồn hoặc ghi chú quyền sử dụng.')
    for card in cards:
        if not card['is_available']:
            add('flashcard', card['id'], 'temporarily_held', 'Thẻ đang tạm giữ, chưa được đưa vào phiên học mới.')
        if not card['term'].strip() or not card['meaning_vi'].strip():
            add('flashcard', card['id'], 'missing_term_or_meaning', 'Thiếu từ hoặc nghĩa.')
        if not card['example_en'].strip() or not card['example_vi'].strip():
            add('flashcard', card['id'], 'missing_bilingual_example', 'Chưa đủ ví dụ song ngữ để người duyệt đối chiếu.')
        if not card['source_name'].strip() or not card['rights_note'].strip():
            add('flashcard', card['id'], 'missing_source_or_rights', 'Thiếu nguồn hoặc ghi chú quyền sử dụng.')
    for question in questions:
        if not question['prompt'].strip():
            add('question', question['id'], 'missing_prompt', 'Thiếu đề câu hỏi.')
        options = question['options']
        if len(options) < 2:
            add('question', question['id'], 'too_few_options', 'Cần ít nhất hai lựa chọn.')
        if sum(option['is_correct'] for option in options) != 1:
            add('question', question['id'], 'invalid_key_count', 'Cần đúng một khóa đáp án đúng.')
        if not (question['explanation_vi'] or question['explanation']).strip():
            add('question', question['id'], 'missing_explanation', 'Thiếu lời giải chung.')
        for option in options:
            if not option['text'].strip():
                add('option', option['id'], 'missing_option_text', 'Thiếu nội dung lựa chọn.')
            if not option['explanation_vi'].strip():
                add('option', option['id'], 'missing_option_explanation', 'Chưa có giải thích riêng cho lựa chọn.')
        if content['content_type'] == 'listening' and not (question['audio_url'].strip() or question['audio_script'].strip()):
            add('question', question['id'], 'missing_audio_or_script', 'Chưa có audio hoặc script; chưa kiểm chứng âm thanh.')
    return findings


def build_review_packet(content_ids, *, max_items=20):
    """Export bounded samples and hashes using four queries, with no writes.

    Up to ``max_items`` cards AND questions are sampled per parent. All source
    rows contribute to each content hash, but unsampled rows are not certified
    or subjected to linguistic checks. Byte limits fail rather than cut evidence.
    """
    ids = _selection(content_ids, max_items)
    parents = [json.loads(_encoded(row)) for row in LearningContent.objects.filter(
        pk__in=ids).order_by('pk').values(*CONTENT_FIELDS)]
    if len(parents) != len(ids):
        raise ValueError('One or more selected content IDs do not exist.')
    contents = {row['id']: {'content': row, 'flashcards': [], 'questions': [],
        'coverage': {'flashcards': {'total': 0, 'exported': 0, 'complete': False},
                     'questions': {'total': 0, 'exported': 0, 'complete': False}}}
        for row in parents}
    digests = {pk: hashlib.sha256() for pk in ids}
    for pk in ids:
        _feed(digests[pk], 'schema', SCHEMA_VERSION)
        _feed(digests[pk], 'content', contents[pk]['content'])
    selected_questions, selected_bytes = {}, 0
    for card in Flashcard.objects.filter(content_id__in=ids).order_by('content_id', 'is_available', 'order', 'id').values(*CARD_FIELDS).iterator(chunk_size=200):
        record = contents[card['content_id']]
        record['coverage']['flashcards']['total'] += 1
        _feed(digests[card['content_id']], 'flashcard', card)
        if len(record['flashcards']) < max_items:
            selected_bytes += len(_encoded(card))
            if selected_bytes > MAX_PACKET_BYTES:
                raise ValueError('Review sample exceeds 20 MiB; select fewer items or parents.')
            record['flashcards'].append(card | {'version_hash': _hash(card),
                'human_review': deepcopy(HUMAN_REVIEW_TEMPLATE), 'checklist': deepcopy(CHECKLIST_TEMPLATE)})
    for question in Question.objects.filter(content_id__in=ids).order_by('content_id', 'order', 'id').values(*QUESTION_FIELDS).iterator(chunk_size=200):
        record = contents[question['content_id']]
        record['coverage']['questions']['total'] += 1
        _feed(digests[question['content_id']], 'question', question)
        if len(record['questions']) < max_items:
            selected_bytes += len(_encoded(question))
            if selected_bytes > MAX_PACKET_BYTES:
                raise ValueError('Review sample exceeds 20 MiB; select fewer items or parents.')
            question['options'] = []
            record['questions'].append(question)
            selected_questions[question['id']] = question
    fields = ('question__content_id', *OPTION_FIELDS)
    for option in AnswerOption.objects.filter(question__content_id__in=ids).order_by(
            'question__content_id', 'question__order', 'question_id', 'label', 'id').values(*fields).iterator(chunk_size=200):
        parent_id = option.pop('question__content_id')
        _feed(digests[parent_id], 'option', option)
        question = selected_questions.get(option['question_id'])
        if question is not None:
            selected_bytes += len(_encoded(option))
            if selected_bytes > MAX_PACKET_BYTES:
                raise ValueError('Review sample exceeds 20 MiB; select fewer items or parents.')
            question['options'].append(option)
    for pk, record in contents.items():
        record['content_hash'] = digests[pk].hexdigest()
        for kind in ('flashcards', 'questions'):
            coverage = record['coverage'][kind]
            coverage.update(exported=len(record[kind]), complete=len(record[kind]) == coverage['total'])
        for question in record['questions']:
            question['version_hash'] = _hash(question)
            question.update(human_review=deepcopy(HUMAN_REVIEW_TEMPLATE), checklist=deepcopy(CHECKLIST_TEMPLATE))
        record['structural_findings'] = _sample_findings(record['content'], record['flashcards'], record['questions'])
        if not record['coverage']['flashcards']['total'] and not record['coverage']['questions']['total']:
            record['structural_findings'].append(_finding('content', pk, 'empty_content', 'Bộ học liệu không có mục để rà soát.'))
        record['findings_scope'] = 'Structural checks of exported samples only; no linguistic or professional approval.'
    packet = {'schema_version': SCHEMA_VERSION, 'scope': 'sample_for_human_review', 'approval_allowed': False,
        'authority_notice': 'Phiếu mẫu để người có chuyên môn rà soát; không phê duyệt hoặc xác nhận toàn bộ bộ học liệu.',
        'selection': {'content_ids': ids, 'max_items_per_kind_per_content': max_items,
                      'order': SELECTION_ORDER},
        'checklist_template': deepcopy(CHECKLIST_TEMPLATE), 'human_review': deepcopy(HUMAN_REVIEW_TEMPLATE),
        'contents': list(contents.values())}
    packet['fingerprint'] = _hash(packet)
    packet['generated_at'] = timezone.now().isoformat()
    if len(_encoded(packet)) > MAX_PACKET_BYTES:
        raise ValueError('Review packet exceeds 20 MiB; select fewer items or parents.')
    return packet
