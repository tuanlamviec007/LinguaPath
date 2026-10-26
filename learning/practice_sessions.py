"""Safe start/resume and draft persistence for practice attempts."""

import hashlib
import json
from django.contrib.auth import get_user_model
from .locking import nonkey_row_lock
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import AnswerOption, AttemptDraftAnswer, LearningContent, PracticeAttempt, Question


class DraftValidationError(ValueError):
    """The submitted draft payload is malformed or references invalid answers."""


class PracticeUnavailableError(Exception):
    """The published practice content changed or is no longer available."""


class DraftConflictError(Exception):
    """A stale page must reload before replacing server-side choices."""
    def __init__(self, record, status='conflict'):
        self.record = record
        self.status = status
        super().__init__('Lượt làm đã nộp; bản nháp không thể thay đổi.' if status == 'submitted' else
                         'Bản nháp đã thay đổi ở tab khác. Hãy tải lại trang trước khi lưu hoặc nộp.')

    def payload(self):
        return {'ok': False, 'status': self.status, 'error': str(self), 'message': str(self),
                'draft_revision': self.record.draft_revision, 'revision': self.record.draft_revision}


def parse_draft_revision(value):
    # A missing revision on an already-open pre-upgrade page means revision 0;
    # it cannot overwrite any draft saved after the upgrade.
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise DraftValidationError('Phiên bản bản nháp không hợp lệ.')
    raw = str(value)
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 10 or int(raw) >= 2147483647:
        raise DraftValidationError('Phiên bản bản nháp không hợp lệ.')
    return int(raw)


def answer_evidence(question, selected, is_correct, content, legacy=False):
    """Freeze the exact question and grading evidence shown at submission."""
    options = [{key: getattr(option, key) for key in ('id', 'label', 'text', 'is_correct', 'explanation_vi')}
               for option in question.options.all()]
    return {
        'question': {key: getattr(question, key) for key in (
            'id', 'order', 'prompt', 'passage', 'audio_url', 'audio_script', 'transcript',
            'explanation', 'explanation_vi',
        )} | {'options': options},
        'selected_option': next((option for option in options if selected and option['id'] == selected.pk), None),
        'is_correct': bool(is_correct), 'content_title': content.title,
        'skill': content.skill, 'legacy': legacy,
    }


def valid_answer_evidence(value):
    return (isinstance(value, dict) and isinstance(value.get('question'), dict)
            and all(key in value['question'] for key in ('id', 'order', 'prompt', 'passage', 'audio_url',
                                                        'audio_script', 'transcript', 'explanation', 'explanation_vi', 'options'))
            and isinstance(value['question']['options'], list)
            and all(isinstance(option, dict) and all(key in option for key in ('id', 'label', 'text', 'is_correct'))
                    for option in value['question']['options'])
            and (value.get('selected_option') is None or isinstance(value['selected_option'], dict))
            and isinstance(value.get('is_correct'), bool)
            and isinstance(value.get('content_title'), str) and isinstance(value.get('skill'), str))


def fingerprint_questions(questions):
    """Hash the ordered question content and answer options for an attempt."""
    snapshot = []
    for question in questions:
        options = sorted(
            question.options.all(),
            key=lambda option: (option.label, option.id or 0),
        )
        snapshot.append({
            'id': question.id,
            'prompt': question.prompt,
            'passage': question.passage,
            'audio_url': question.audio_url,
            'audio_script': question.audio_script,
            'transcript': question.transcript,
            'explanation': question.explanation,
            'explanation_vi': question.explanation_vi,
            'options': [{
                'id': option.id,
                'label': option.label,
                'text': option.text,
                'is_correct': option.is_correct,
                'explanation_vi': option.explanation_vi,
            } for option in options],
        })
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _content_is_visible(content):
    return (
        content.is_published
        and content.review_status in {'language_checked', 'teacher_approved'}
    )


def _current_questions(content):
    return list(
        Question.objects.filter(content=content)
        .prefetch_related('options')
        .order_by('order', 'id')
    )


def _snapshot_matches(attempt, questions, fingerprint):
    current_ids = [question.id for question in questions]
    stored_ids = attempt.question_ids
    return (
        isinstance(stored_ids, list)
        and stored_ids == current_ids
        and attempt.question_count == len(current_ids)
        and bool(attempt.content_fingerprint)
        and attempt.content_fingerprint == fingerprint
    )


def _abandon(attempt):
    # Draft choices are provisional; discard them when their session is invalid.
    AttemptDraftAnswer.objects.filter(attempt=attempt).delete()
    attempt.status = 'abandoned'
    attempt.save(update_fields=['status'])


def start_or_resume(user, content):
    """Return an active attempt for this user/content or create a fresh one.

    Locking the user row serializes starts for this owner on databases that
    support row locks. The database's conditional unique constraint remains the
    final protection against duplicate active attempts.
    """
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=user.pk)
        locked_content = LearningContent.objects.select_for_update().get(pk=content.pk)
        questions = _current_questions(locked_content)
        if not _content_is_visible(locked_content) or not questions:
            active = PracticeAttempt.objects.select_for_update().filter(
                user=user, content=locked_content, status='in_progress',
            ).first()
            if active:
                _abandon(active)
            unavailable = True
        else:
            unavailable = False
            fingerprint = fingerprint_questions(questions)
            active = PracticeAttempt.objects.select_for_update().filter(
                user=user, content=locked_content, status='in_progress',
            ).first()
            if active and _snapshot_matches(active, questions, fingerprint):
                return active, False
            if active:
                _abandon(active)
            attempt = PracticeAttempt.objects.create(
                user=user,
                content=locked_content,
                status='in_progress',
                question_count=len(questions),
                question_ids=[question.id for question in questions],
                content_fingerprint=fingerprint,
            )
            return attempt, True

    if unavailable:
        raise PracticeUnavailableError('Bài luyện hiện không có sẵn hoặc chưa được xuất bản.')


def _parse_id(value, label):
    if isinstance(value, bool):
        raise DraftValidationError(f'{label} phải là mã số nguyên hợp lệ.')
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise DraftValidationError(f'{label} phải là mã số nguyên hợp lệ.') from None
    if parsed < 1 or parsed > (2**63 - 1) or str(parsed) != str(value).strip():
        raise DraftValidationError(f'{label} phải là mã số nguyên dương hợp lệ.')
    return parsed


def save_draft(user, attempt_id, answers, draft_revision=0):
    """Validate and replace draft responses without grading or creating answers.

    ``answers`` maps question ids to selected option ids. It represents the
    complete current draft; omitted questions have their saved draft removed.
    """
    if not isinstance(answers, dict):
        raise DraftValidationError('Câu trả lời nháp phải có định dạng ánh xạ mã câu hỏi tới mã phương án.')
    if len(answers) > 500:
        raise DraftValidationError('Một lượt luyện không thể lưu quá 500 câu trả lời.')

    parsed = {}
    for question_id, option_id in answers.items():
        question_pk = _parse_id(question_id, 'Mã câu hỏi')
        option_pk = _parse_id(option_id, 'Mã phương án')
        if question_pk in parsed:
            raise DraftValidationError('Mã câu hỏi bị lặp trong dữ liệu nháp.')
        parsed[question_pk] = option_pk

    unavailable = False
    saved_count = 0
    saved_at = None
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=user.pk)
        attempt = get_object_or_404(
            PracticeAttempt.objects.select_for_update().select_related('content'),
            id=attempt_id, user=user,
        )
        if attempt.status != 'in_progress':
            raise DraftConflictError(attempt, 'submitted' if attempt.status == 'submitted' else 'unavailable')
        revision = parse_draft_revision(draft_revision)
        content = LearningContent.objects.select_for_update().get(pk=attempt.content_id)
        questions = _current_questions(content)
        fingerprint = fingerprint_questions(questions)
        if not _content_is_visible(content) or not _snapshot_matches(attempt, questions, fingerprint):
            _abandon(attempt)
            unavailable = True
        else:
            if revision != attempt.draft_revision:
                raise DraftConflictError(attempt)
            allowed_question_ids = set(attempt.question_ids)
            if any(question_id not in allowed_question_ids for question_id in parsed):
                raise DraftValidationError('Bản nháp chứa câu hỏi không thuộc lượt luyện này.')

            option_rows = {}
            if parsed:
                rows = list(
                    AnswerOption.objects.filter(id__in=parsed.values())
                    .select_related('question')
                )
                option_rows = {row.id: row for row in rows}
            if len(option_rows) != len(set(parsed.values())):
                raise DraftValidationError('Một hoặc nhiều phương án không tồn tại.')
            for question_id, option_id in parsed.items():
                option = option_rows[option_id]
                if option.question_id != question_id:
                    raise DraftValidationError('Phương án được chọn không thuộc câu hỏi tương ứng.')

            saved_at = timezone.now()
            changed = PracticeAttempt.objects.filter(
                pk=attempt.pk, status='in_progress', draft_revision=revision,
            ).update(draft_revision=revision + 1, last_saved_at=saved_at)
            if not changed:
                attempt.refresh_from_db()
                raise DraftConflictError(attempt, 'submitted' if attempt.status == 'submitted' else 'conflict')
            AttemptDraftAnswer.objects.filter(attempt=attempt).delete()
            AttemptDraftAnswer.objects.bulk_create([
                AttemptDraftAnswer(
                    attempt=attempt,
                    question_id=question_id,
                    selected_option_id=option_id,
                )
                for question_id, option_id in parsed.items()
            ])
            attempt.last_saved_at = saved_at
            attempt.draft_revision = revision + 1
            saved_count = len(parsed)

    if unavailable:
        raise PracticeUnavailableError('Nội dung bài luyện đã thay đổi hoặc không còn được xuất bản; lượt làm đã được đóng.')
    return {'ok': True, 'status': 'saved', 'saved_count': saved_count, 'last_saved_at': saved_at.isoformat(),
            'draft_revision': attempt.draft_revision, 'revision': attempt.draft_revision}
