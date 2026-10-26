"""Isolated, content-validated retry sessions for personal mistakes."""

from django.contrib.auth import get_user_model
from .locking import nonkey_row_lock
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import (
    LEARNER_REVIEW_STATUSES,
    AnswerOption,
    AttemptAnswer,
    ErrorNotebookEntry,
    LearningContent,
    MistakeReviewAnswer,
    MistakeReviewItem,
    MistakeReviewSession,
    PracticeAttempt,
    Question,
)
from .practice_sessions import DraftConflictError, parse_draft_revision, fingerprint_questions


MAX_REVIEW_ITEMS = 10


class MistakeReviewInputError(ValueError):
    """Invalid retry session request or answer payload."""


class MistakeReviewUnavailable(Exception):
    """The retry content or its source mistake is no longer eligible."""


class NoMistakesAvailable(Exception):
    """There are no eligible pending mistakes for the requested filter."""


def _validate_filter(exam_type, category):
    if exam_type not in dict(LearningContent.EXAMS):
        raise MistakeReviewInputError('Kỳ thi không hợp lệ.')
    categories = {value for value, _ in ErrorNotebookEntry.CATEGORIES}
    if category and category not in categories:
        raise MistakeReviewInputError('Nhóm lỗi không hợp lệ.')


def pending_mistake_entries(user, exam_type, category=None):
    """Return pending, ownership-consistent entries suitable for retry selection."""
    _validate_filter(exam_type, category)
    entries = ErrorNotebookEntry.objects.filter(
        reviewed_at__isnull=True,
        answer__is_correct=False,
        answer__attempt__user=user,
        answer__attempt__status='submitted',
        answer__attempt__content__exam_type=exam_type,
        answer__question__content__exam_type=exam_type,
        answer__question__content__is_published=True,
        answer__question__content__review_status__in=LEARNER_REVIEW_STATUSES,
        answer__question__content_id=F('answer__attempt__content_id'),
    ).filter(
        Q(answer__selected_option__isnull=True)
        | Q(
            answer__selected_option__question_id=F('answer__question_id'),
            answer__selected_option__is_correct=False,
        )
    ).exclude(
        answer__question__content__content_type='listening',
        answer__question__audio_url='',
    ).select_related(
        'answer__attempt__content', 'answer__question__content', 'answer__selected_option',
    ).prefetch_related('answer__question__options')
    if category:
        entries = entries.filter(category=category)
    return entries.order_by('-created_at', '-id')


def _valid_question(question):
    options = list(question.options.all())
    return (
        len(options) >= 2
        and sum(option.is_correct for option in options) == 1
        and (
            question.content.content_type != 'listening'
            or bool(question.audio_url.strip())
        )
    )


def count_eligible_mistakes(user, exam_type, category=None):
    """Count distinct eligible questions, excluding malformed question banks."""
    seen = set()
    for entry in pending_mistake_entries(user, exam_type, category):
        question = entry.answer.question
        if question.pk not in seen and _valid_question(question):
            seen.add(question.pk)
    return len(seen)


def eligible_mistake_count(user, exam_type, category=None):
    """Backward-compatible alias for the notebook count helper."""
    return count_eligible_mistakes(user, exam_type, category)


def _select_entries(user, exam_type, category=None):
    selected = []
    seen_questions = set()
    for entry in pending_mistake_entries(user, exam_type, category):
        question = entry.answer.question
        if question.pk in seen_questions or not _valid_question(question):
            continue
        seen_questions.add(question.pk)
        selected.append(entry)
        if len(selected) >= MAX_REVIEW_ITEMS:
            break
    return selected


def _item_snapshot_valid(session, items):
    if not items or len(items) != session.question_count or len(items) > MAX_REVIEW_ITEMS:
        return False
    questions = [item.question for item in items]
    if not all(_valid_question(question) for question in questions):
        return False
    return fingerprint_questions(questions) == session.fingerprint and all(
        _entry_is_valid(
            item.source_entry,
            session.user,
            session.exam_type,
            session.category,
            session.started_at,
            expected_question=item.question,
        )
        for item in items
    )


def _entry_is_valid(entry, user, exam_type, category, started_at, expected_question=None):
    if entry is None:
        return False
    answer = entry.answer
    question = answer.question
    attempt = answer.attempt
    selected = answer.selected_option
    return (
        entry.reviewed_at is None
        and entry.created_at <= started_at
        and (not category or entry.category == category)
        and not answer.is_correct
        and attempt.user_id == user.pk
        and attempt.status == 'submitted'
        and attempt.content.exam_type == exam_type
        and attempt.content_id == question.content_id
        and question.content.exam_type == exam_type
        and question.content.is_published
        and question.content.review_status in LEARNER_REVIEW_STATUSES
        and (expected_question is None or question.pk == expected_question.pk)
        and (
            selected is None
            or (selected.question_id == question.pk and not selected.is_correct)
        )
    )


def _abandon(session):
    session.status = 'abandoned'
    session.draft_answers = {}
    session.last_saved_at = None
    session.save(update_fields=['status', 'draft_answers', 'last_saved_at'])


def _lock_retry_source_rows(items):
    """Lock mutable source rows before validating a final grade snapshot."""
    question_ids = sorted({item.question_id for item in items})
    content_ids = sorted({item.question.content_id for item in items})
    source_ids = sorted({item.source_entry_id for item in items if item.source_entry_id})
    answer_ids = sorted({item.source_entry.answer_id for item in items if item.source_entry_id})
    attempt_ids = sorted({item.source_entry.answer.attempt_id for item in items if item.source_entry_id})
    list(LearningContent.objects.select_for_update().filter(pk__in=content_ids).order_by('pk'))
    list(Question.objects.select_for_update().filter(pk__in=question_ids).order_by('pk'))
    list(AnswerOption.objects.select_for_update().filter(question_id__in=question_ids).order_by('pk'))
    list(PracticeAttempt.objects.select_for_update().filter(pk__in=attempt_ids).order_by('pk'))
    list(AttemptAnswer.objects.select_for_update().filter(pk__in=answer_ids).order_by('pk'))
    list(ErrorNotebookEntry.objects.select_for_update().filter(pk__in=source_ids).order_by('pk'))


def _safe_question_dto(item, drafts=None):
    question = item.question
    return {
        'id': question.pk,
        'position': item.position,
        'content_title': question.content.title,
        'skill': question.content.skill,
        'order': question.order,
        'prompt': question.prompt,
        'passage': question.passage,
        'audio_url': question.audio_url,
        'selected_option_id': (drafts or {}).get(str(question.pk)),
        'options': [
            {'id': option.pk, 'label': option.label, 'text': option.text}
            for option in question.options.all()
        ],
    }


def start_or_resume_mistake_review(user, exam_type, category=None):
    """Start a retry set or resume the learner's active set for this exam."""
    _validate_filter(exam_type, category)
    no_mistakes = False
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=user.pk)
        active = MistakeReviewSession.objects.select_for_update().filter(
            user=user, exam_type=exam_type, status='in_progress',
        ).first()
        if active:
            items = list(active.items.select_related(
                'question__content', 'source_entry__answer__attempt__content',
                'source_entry__answer__question__content', 'source_entry__answer__selected_option',
            ).prefetch_related('question__options').order_by('position', 'id'))
            if _item_snapshot_valid(active, items):
                return active, False
            _abandon(active)

        entries = _select_entries(user, exam_type, category)
        if not entries:
            no_mistakes = True
        else:
            questions = [entry.answer.question for entry in entries]
            session = MistakeReviewSession.objects.create(
                user=user,
                exam_type=exam_type,
                category=category or '',
                status='in_progress',
                fingerprint=fingerprint_questions(questions),
                question_count=len(questions),
            )
            MistakeReviewItem.objects.bulk_create([
                MistakeReviewItem(
                    session=session,
                    source_entry=entry,
                    question=entry.answer.question,
                    position=position,
                )
                for position, entry in enumerate(entries, 1)
            ])
            return session, True

    if no_mistakes:
        raise NoMistakesAvailable('Chưa có câu sai phù hợp để luyện lại.')


def _get_active_session(user, session_id):
    return get_object_or_404(
        MistakeReviewSession.objects.select_for_update().filter(user=user),
        pk=session_id,
        status='in_progress',
    )


def get_mistake_review_questions(user, session_id, include_revision=False):
    """Return learner-safe question and option DTOs for an active retry session."""
    unavailable = False
    result = None
    with transaction.atomic():
        session = _get_active_session(user, session_id)
        items = list(session.items.select_related(
            'question__content', 'source_entry__answer__attempt__content',
            'source_entry__answer__question__content', 'source_entry__answer__selected_option',
        ).prefetch_related('question__options').order_by('position', 'id'))
        if not _item_snapshot_valid(session, items):
            _abandon(session)
            unavailable = True
        else:
            result = [_safe_question_dto(item, session.draft_answers) for item in items]
            if include_revision:
                result = (result, session.draft_revision, session.last_saved_at)
    if unavailable:
        raise MistakeReviewUnavailable('Câu hỏi hoặc nguồn câu sai đã thay đổi; lượt luyện lại đã được đóng.')
    return result


def _parse_answer_map(answers):
    if not isinstance(answers, dict):
        raise MistakeReviewInputError('Câu trả lời phải có định dạng mã câu hỏi tới mã phương án.')
    if len(answers) > MAX_REVIEW_ITEMS:
        raise MistakeReviewInputError(f'Mỗi lượt chỉ hỗ trợ tối đa {MAX_REVIEW_ITEMS} câu.')
    parsed = {}
    for question_id, option_id in answers.items():
        try:
            qid, oid = int(question_id), int(option_id)
        except (TypeError, ValueError, OverflowError):
            raise MistakeReviewInputError('Mã câu hỏi và phương án phải là số nguyên dương.') from None
        if qid <= 0 or oid <= 0 or qid > 2**63 - 1 or oid > 2**63 - 1:
            raise MistakeReviewInputError('Mã câu hỏi và phương án phải là số nguyên dương hợp lệ.')
        if str(qid) != str(question_id).strip() or str(oid) != str(option_id).strip():
            raise MistakeReviewInputError('Mã câu hỏi và phương án phải là số nguyên dương hợp lệ.')
        if qid in parsed:
            raise MistakeReviewInputError('Mã câu hỏi bị lặp trong câu trả lời.')
        parsed[qid] = oid
    return parsed


def _result_data(session):
    if session.result_snapshot:
        return session.result_snapshot
    raise MistakeReviewUnavailable('Không tìm thấy snapshot kết quả đã nộp.')


def save_mistake_review_draft(user, session_id, answers, draft_revision=0):
    """Replace provisional choices without grading or changing source mistakes."""
    parsed = _parse_answer_map(answers)
    invalidated = False
    result = None
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=user.pk)
        session = get_object_or_404(
            MistakeReviewSession.objects.select_for_update().filter(user=user),
            pk=session_id,
        )
        if session.status != 'in_progress':
            raise DraftConflictError(session, 'submitted' if session.status == 'submitted' else 'unavailable')
        revision = parse_draft_revision(draft_revision)
        items = list(session.items.select_related(
            'question__content', 'source_entry__answer__attempt__content',
            'source_entry__answer__question__content', 'source_entry__answer__selected_option',
        ).prefetch_related('question__options').order_by('position', 'id'))
        if not _item_snapshot_valid(session, items):
            _abandon(session)
            invalidated = True
        else:
            if revision != session.draft_revision:
                raise DraftConflictError(session)
            options_by_question = {
                item.question_id: {option.pk for option in item.question.options.all()}
                for item in items
            }
            for question_id, option_id in parsed.items():
                if question_id not in options_by_question:
                    raise MistakeReviewInputError('Có câu hỏi không thuộc lượt ôn này.')
                if option_id not in options_by_question[question_id]:
                    raise MistakeReviewInputError('Phương án không thuộc câu hỏi tương ứng.')
            now = timezone.now()
            draft_answers = {str(question_id): option_id for question_id, option_id in parsed.items()}
            changed = MistakeReviewSession.objects.filter(
                pk=session.pk, status='in_progress', draft_revision=revision,
            ).update(draft_answers=draft_answers, last_saved_at=now, draft_revision=revision + 1)
            if not changed:
                session.refresh_from_db()
                raise DraftConflictError(session, 'submitted' if session.status == 'submitted' else 'conflict')
            session.draft_answers = draft_answers
            session.last_saved_at = now
            session.draft_revision = revision + 1
            result = {'ok': True, 'status': 'saved', 'saved_count': len(parsed), 'last_saved_at': now.isoformat(),
                      'draft_revision': session.draft_revision, 'revision': session.draft_revision}
    if invalidated:
        raise MistakeReviewUnavailable('Học liệu hoặc nguồn câu sai đã thay đổi; lượt ôn đã dừng và bản nháp đã được xóa.')
    return result


def _build_result_snapshot(session, items, selected_by_item, now, correct_count):
    answer_rows = []
    blank_count = 0
    for item in items:
        selected, is_correct = selected_by_item[item.pk]
        if selected is None:
            blank_count += 1
        options = list(item.question.options.all())
        correct_option = next(option for option in options if option.is_correct)
        answer_rows.append({
            'question_id': item.question_id,
            'position': item.position,
            'content_title': item.question.content.title,
            'skill': item.question.content.skill,
            'prompt': item.question.prompt,
            'passage': item.question.passage,
            'transcript': item.question.transcript,
            'explanation': item.question.explanation,
            'explanation_vi': item.question.explanation_vi,
            'selected_option_id': selected.pk if selected else None,
            'is_correct': is_correct,
            'correct_option_id': correct_option.pk,
            'options': [{
                'id': option.pk, 'label': option.label, 'text': option.text,
                'is_correct': option.is_correct, 'explanation_vi': option.explanation_vi,
            } for option in options],
        })
    total = session.question_count
    return {
        'session_id': session.pk,
        'status': 'submitted',
        'exam_type': session.exam_type,
        'question_count': total,
        'correct_count': correct_count,
        'wrong_count': max(total - correct_count - blank_count, 0),
        'blank_count': blank_count,
        'accuracy_percent': round(100 * correct_count / total) if total else 0,
        'submitted_at': now.isoformat(),
        'answers': answer_rows,
    }


def submit_mistake_review(user, session_id, answers, draft_revision=0):
    """Submit once, grade against current options, and mark retry successes reviewed."""
    invalidated = False
    result = None
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=user.pk)
        session = MistakeReviewSession.objects.select_for_update().filter(user=user).filter(pk=session_id).first()
        if session is None:
            raise Http404
        if session.status == 'submitted':
            return _result_data(session)
        if session.status != 'in_progress':
            raise MistakeReviewUnavailable('Lượt luyện lại không còn hoạt động.')
        revision = parse_draft_revision(draft_revision)
        if revision != session.draft_revision:
            raise DraftConflictError(session)
        parsed = _parse_answer_map(answers)
        # Lock item rows in a simple query. PostgreSQL rejects FOR UPDATE when
        # the same query also outer-joins nullable source_entry relations.
        list(session.items.select_for_update().order_by('pk').values_list('pk', flat=True))
        initial_items = list(session.items.select_related(
            'question', 'source_entry__answer',
        ).order_by('position', 'id'))
        _lock_retry_source_rows(initial_items)
        items = list(session.items.select_related(
            'question__content', 'source_entry__answer__attempt__content',
            'source_entry__answer__question__content', 'source_entry__answer__selected_option',
        ).prefetch_related('question__options').order_by('position', 'id'))
        if not _item_snapshot_valid(session, items):
            _abandon(session)
            invalidated = True
        elif any(question_id not in {item.question_id for item in items} for question_id in parsed):
            raise MistakeReviewInputError('Có câu hỏi không thuộc lượt luyện lại này.')
        else:
            option_ids = set(parsed.values())
            options = {
                option.pk: option for option in AnswerOption.objects.filter(id__in=option_ids)
            }
            if len(options) != len(option_ids):
                raise MistakeReviewInputError('Một hoặc nhiều phương án không tồn tại.')
            for item in items:
                question_options = list(item.question.options.all())
                if len(question_options) < 2 or sum(option.is_correct for option in question_options) != 1:
                    _abandon(session)
                    invalidated = True
                    break
                option_id = parsed.get(item.question_id)
                if option_id is not None and options[option_id].question_id != item.question_id:
                    raise MistakeReviewInputError('Phương án không thuộc câu hỏi tương ứng.')
            if not invalidated:
                now = timezone.now()
                correct_count = 0
                answer_objects = []
                selected_by_item = {}
                entries_to_review = set()
                for item in items:
                    selected = options.get(parsed.get(item.question_id))
                    correct = bool(selected and selected.is_correct)
                    correct_count += int(correct)
                    selected_by_item[item.pk] = (selected, correct)
                    answer_objects.append(MistakeReviewAnswer(
                        item=item,
                        selected_option=selected,
                        is_correct=correct,
                    ))
                    if correct:
                        entries_to_review.add(item.question_id)
                changed = MistakeReviewSession.objects.filter(
                    pk=session.pk, status='in_progress', draft_revision=revision,
                ).update(draft_revision=revision + 1)
                if not changed:
                    session.refresh_from_db()
                    raise DraftConflictError(session, 'submitted' if session.status == 'submitted' else 'conflict')
                session.draft_revision = revision + 1
                MistakeReviewAnswer.objects.bulk_create(answer_objects)
                session.status = 'submitted'
                session.correct_count = correct_count
                session.submitted_at = now
                session.draft_answers = {}
                session.last_saved_at = None
                session.save(update_fields=['status', 'correct_count', 'submitted_at', 'draft_answers', 'last_saved_at'])
                for question_id in entries_to_review:
                    ErrorNotebookEntry.objects.filter(
                        answer__question_id=question_id,
                        answer__attempt__user=user,
                        answer__attempt__status='submitted',
                        answer__attempt__content__exam_type=session.exam_type,
                        answer__attempt__content_id=F('answer__question__content_id'),
                        answer__question__content__exam_type=session.exam_type,
                        answer__question__content__is_published=True,
                        answer__question__content__review_status__in=LEARNER_REVIEW_STATUSES,
                        answer__is_correct=False,
                        reviewed_at__isnull=True,
                        created_at__lte=session.started_at,
                    ).filter(
                        Q(answer__selected_option__isnull=True)
                        | Q(
                            answer__selected_option__question_id=F('answer__question_id'),
                            answer__selected_option__is_correct=False,
                        )
                    ).update(reviewed_at=now)
                result = _build_result_snapshot(session, items, selected_by_item, now, correct_count)
                session.result_snapshot = result
                session.save(update_fields=['result_snapshot'])
    if invalidated:
        raise MistakeReviewUnavailable('Câu hỏi hoặc nguồn câu sai đã thay đổi; không có kết quả nào được chấm.')
    return result


def get_mistake_review_result(user, session_id):
    """Fetch a completed session result for its owner only."""
    session = get_object_or_404(
        MistakeReviewSession.objects.filter(user=user, status='submitted'),
        pk=session_id,
    )
    return _result_data(session)


def abandon_mistake_review(user, session_id):
    """Explicitly stop an active retry session without changing source mistakes."""
    with transaction.atomic():
        session = get_object_or_404(
            MistakeReviewSession.objects.select_for_update().filter(user=user),
            pk=session_id,
        )
        if session.status != 'in_progress':
            return False
        _abandon(session)
        return True
