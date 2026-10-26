import unicodedata

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

from .models import Flashcard, LearningContent
from .locking import nonkey_row_lock
from .strict_csv import read_strict_csv


REQUIRED_COLUMNS = {'term', 'meaning_vi', 'cefr_level'}
OPTIONAL_COLUMNS = {
    'part_of_speech', 'topic', 'example_en', 'example_vi',
    'pronunciation', 'audio_url',
}
LEVELS = {value for value, _ in Flashcard.LEVELS}
_http_url = URLValidator(schemes=['http', 'https'])


def normalized_term(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def _validate_field(model, name, value, *, required=False):
    if not isinstance(value, str):
        raise ValueError(f'{name}: dữ liệu phải là chuỗi.')
    value = value.strip()
    if required and not value:
        raise ValueError(f'{name}: không được để trống.')
    limit = model._meta.get_field(name).max_length
    if limit and len(value) > limit:
        raise ValueError(f'{name}: tối đa {limit} ký tự.')
    if name.endswith('_url') and value:
        try:
            _http_url(value)
        except ValidationError as exc:
            raise ValueError(f'{name}: cần URL HTTP(S) hợp lệ.') from exc
    return value


def validate_vocabulary_rows(rows, *, required_fields=REQUIRED_COLUMNS):
    """Validate the complete source before any database changes."""
    result, seen = [], set()
    for number, raw in enumerate(rows, 2):
        try:
            row = {key: _validate_field(Flashcard, key, value, required=key in required_fields)
                   for key, value in raw.items()}
            row['cefr_level'] = row.get('cefr_level', '').upper()
            if row['cefr_level'] not in LEVELS:
                raise ValueError('cefr_level phải là A1, A2, B1, B2 hoặc C1.')
            term = normalized_term(row.get('term', ''))
            if term in seen:
                raise ValueError('term bị trùng sau khi chuẩn hóa.')
            seen.add(term)
            result.append(row)
        except ValueError as exc:
            raise ValueError(f'Dòng {number}: {exc}') from exc
    if not result:
        raise ValueError('CSV không có từ vựng để nhập.')
    return result


def import_vocabulary_csv(text, *, title, topic='', source_name, source_url='', rights_note,
                          exam_type='TOEIC', permission_check=None):
    """Explicitly merge CSV into a draft, retaining words omitted from the CSV.

    Optional ``permission_check(content_or_none)`` must raise PermissionDenied
    when the actual operation is unauthorized. It runs inside the transaction,
    after resolving and locking the parent. A shared content-type row serializes
    imports, including creates where no parent row exists yet. This avoids an
    add-only permission check being reused for a concurrent merge operation.
    Callers needing an actor lock must take it before calling this service;
    callbacks should use that prelocked principal rather than reversing the
    actor-before-parent order used by learner practice.
    """
    metadata = {
        key: _validate_field(LearningContent, key, value, required=key in {'title', 'source_name', 'rights_note'})
        for key, value in dict(title=title, topic=topic, source_name=source_name,
                               source_url=source_url, rights_note=rights_note).items()
    }
    if exam_type not in {key for key, _ in LearningContent.EXAMS}:
        raise ValueError('exam_type không hợp lệ.')
    rows = validate_vocabulary_rows(read_strict_csv(
        text, required_columns=REQUIRED_COLUMNS, optional_columns=OPTIONAL_COLUMNS,
    ))

    with transaction.atomic():
        # This row exists after migrations, unlike a not-yet-created deck.
        nonkey_row_lock(ContentType.objects.all()).get(app_label='learning', model='learningcontent')
        parents = list(LearningContent.objects.select_for_update().filter(
            title=metadata['title'], exam_type=exam_type, content_type='vocabulary',
        ).order_by('pk')[:2])
        if len(parents) > 1:
            raise ValueError('Có nhiều bộ từ cùng định danh; cần quản trị viên xử lý trước khi nhập.')
        content = parents[0] if parents else None
        if permission_check is not None:
            permission_check(content)
        existing = {}
        if content:
            for card in content.flashcards.select_for_update().all():
                key = normalized_term(card.term)
                if key in existing:
                    raise ValueError('Bộ hiện tại có term trùng sau chuẩn hóa; cần xử lý trước khi nhập.')
                existing[key] = card
        else:
            content = LearningContent.objects.create(
                title=metadata['title'], exam_type=exam_type, content_type='vocabulary', skill='vocabulary',
            )
        content.topic = metadata['topic'] or content.topic
        for key in ('source_name', 'source_url', 'rights_note'):
            setattr(content, key, metadata[key])
        content.review_status = 'draft'
        content.reviewer = ''
        content.reviewed_at = None
        content.review_note = ''
        content.source_checked_on = None
        content.is_published = False
        content.save(update_fields=[
            'topic', 'source_name', 'source_url', 'rights_note', 'source_checked_on',
            'review_status', 'reviewer', 'reviewed_at', 'review_note', 'is_published', 'updated_at',
        ])

        created_count = updated_count = 0
        for row in rows:
            card = existing.get(normalized_term(row['term']))
            defaults = {
                'meaning_vi': row['meaning_vi'], 'cefr_level': row['cefr_level'],
                'topic': row.get('topic') or metadata['topic'],
                **{key: row.get(key, '') for key in ('part_of_speech', 'example_en', 'example_vi', 'pronunciation', 'audio_url')},
                **{key: metadata[key] for key in ('source_name', 'source_url', 'rights_note')},
            }
            if card is None:
                Flashcard.objects.create(content=content, term=row['term'], **defaults)
                created_count += 1
            else:
                # Omitted optional columns must not erase editor additions.
                for key, value in defaults.items():
                    if key in OPTIONAL_COLUMNS and key not in row:
                        continue
                    setattr(card, key, value)
                card.save()
                updated_count += 1
    return content, created_count, updated_count
