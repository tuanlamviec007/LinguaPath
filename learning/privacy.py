"""Explicit, reauthenticated self-service privacy actions for learner accounts."""
import json

from django.apps import apps
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, connection, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from config.auth_throttle import client_ip
from planner.models import LearnerProfile, StudyTask
from .auth_limits import AuthReservationConflict, reserve_auth_request
from .gamification import get_learning_rewards
from .models import (
    DueRecallObservation, AttemptAnswer, AttemptDraftAnswer, ErrorNotebookEntry, FlashcardReview,
    MistakeReviewAnswer, MistakeReviewItem, MistakeReviewSession, PracticeAttempt,
    SavedWord, TutorTurn, TutorUsageBudget, UserFlashcardState,
    VocabularyQuizDailyReward, VocabularyQuizSession,
    WeakWordOutcome, WeakWordPendingOutcome, WeakWordProjectionState, WeakWordQuizReceipt,
)


MAX_EXPORT_BYTES = 20 * 1024 * 1024
_REAUTH_ERROR = 'Không thể xác nhận yêu cầu. Hãy kiểm tra mật khẩu và xác nhận lại.'
_OPTION_FIELDS = ('id', 'label', 'key', 'text', 'is_correct', 'explanation_vi')
_QUESTION_FIELDS = ('id', 'order', 'prompt', 'passage', 'audio_url', 'audio_script', 'transcript', 'explanation', 'explanation_vi')


class ExportTooLarge(Exception):
    pass


class SocialDataNotReady(Exception):
    pass


def _has_social_data(user):
    # Social tables may remain after the optional allauth app is disabled.
    # Inspect by fixed table name so a rollback cannot silently omit records.
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        for table in ('socialaccount_socialaccount', 'account_emailaddress'):
            if table in tables:
                cursor.execute(f'SELECT 1 FROM {connection.ops.quote_name(table)} WHERE user_id = %s LIMIT 1', [user.pk])
                if cursor.fetchone() is not None:
                    return True
    return False


def _pick(value, fields):
    return {key: value[key] for key in fields if key in value} if isinstance(value, dict) else {}


def _question(value):
    result = _pick(value, _QUESTION_FIELDS)
    if isinstance(value, dict):
        result['options'] = [_pick(option, _OPTION_FIELDS) for option in value.get('options', [])
                             if isinstance(option, dict)] if isinstance(value.get('options'), list) else []
    return result


def _evidence(value):
    result = _pick(value, ('is_correct', 'content_title', 'skill', 'legacy', 'unavailable'))
    if isinstance(value, dict):
        result['question'] = _question(value.get('question'))
        result['selected_option'] = _pick(value.get('selected_option'), _OPTION_FIELDS) if value.get('selected_option') is not None else None
    return result


def _practice_result(value):
    result = _pick(value, ('version', 'content_title', 'skill', 'correct_count', 'question_count', 'submitted_at'))
    if isinstance(value, dict) and isinstance(value.get('answers'), list):
        result['answers'] = [_evidence(item) for item in value['answers'] if isinstance(item, dict)]
    return result


def _mistake_result(value):
    result = _pick(value, ('session_id', 'status', 'exam_type', 'question_count', 'correct_count',
                           'wrong_count', 'blank_count', 'accuracy_percent', 'submitted_at'))
    if isinstance(value, dict) and isinstance(value.get('answers'), list):
        result['answers'] = []
        for item in value['answers']:
            if not isinstance(item, dict):
                continue
            row = _pick(item, ('question_id', 'position', 'content_title', 'skill', 'prompt', 'passage',
                               'transcript', 'explanation', 'explanation_vi', 'selected_option_id',
                               'is_correct', 'correct_option_id'))
            row['options'] = [_pick(option, _OPTION_FIELDS) for option in item.get('options', [])
                              if isinstance(option, dict)] if isinstance(item.get('options'), list) else []
            result['answers'].append(row)
    return result


def _tutor_result(value):
    result = _pick(value, ('answer', 'mode', 'provider', 'retrieval_mode'))
    if not isinstance(value, dict):
        return result
    for key in ('sources', 'clarification_prompts'):
        values = value.get(key)
        result[key] = [item for item in values if isinstance(item, str)] if isinstance(values, list) else []
    result['generation'] = _pick(value.get('generation'), (
        'provider', 'model', 'prompt_version', 'context_version', 'generated_at',
        'bridge_prompt_version', 'requested_model', 'attempted_provider', 'attempted_model'))
    result['evidence_sources'] = []
    for source in value.get('evidence_sources', []) if isinstance(value.get('evidence_sources'), list) else []:
        if isinstance(source, dict):
            row = _pick(source, ('title', 'href', 'kind', 'label', 'review_status', 'meaning_vi', 'context_format', 'context_complete'))
            row['source_ref'] = _pick(source.get('source_ref'), ('kind', 'object_id', 'content_id', 'exam_type', 'version', 'review_status'))
            result['evidence_sources'].append(row)
    result['actions'] = [_pick(action, ('title', 'href')) for action in value.get('actions', [])
                         if isinstance(action, dict)] if isinstance(value.get('actions'), list) else []
    return result


def _choice_map(value):
    # Only owned question-number -> selected answer maps are exported. Unknown
    # nested metadata cannot become an accidental credential export later.
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()
            if str(key).isascii() and str(key).isdigit() and type(item) in (str, int, type(None))}


def _quiz_snapshot(quiz):
    questions = quiz['snapshot']
    if not isinstance(questions, list):
        return []
    submitted = quiz['status'] == 'submitted'
    fields = ('number', 'part_of_speech', 'cefr_level', 'meaning_vi') if quiz['mode'] == 'recall' else (
        'number', 'term', 'part_of_speech', 'cefr_level', 'example_en')
    if submitted:
        fields = (*fields, 'number', 'card_id', 'term', 'meaning_vi', 'example_en', 'example_vi', 'source_url', 'correct_key')
    result = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        row = _pick(question, fields)
        if quiz['mode'] != 'recall' or submitted:
            row['options'] = [_pick(option, ('key', 'label', 'text')) for option in question.get('options', [])
                              if isinstance(option, dict)] if isinstance(question.get('options'), list) else []
        result.append(row)
    return result


def _rows(model, filters, fields):
    return model.objects.filter(**filters).order_by('pk').values(*fields).iterator(chunk_size=50)


def _export_sections(user):
    owner = {'user_id': user.pk}
    yield 'profile', _rows(LearnerProfile, owner, ('id', 'exam_goal', 'target_score', 'current_cefr', 'target_cefr',
        'daily_minutes', 'target_date', 'timezone', 'onboarding_complete', 'created_at', 'updated_at'))
    yield 'study_tasks', _rows(StudyTask, owner, ('id', 'content_id', 'cefr_level', 'scheduled_for', 'estimated_minutes',
        'status', 'reason', 'recommendation_score', 'recommendation_version', 'created_at', 'completed_at'))
    attempts = _rows(PracticeAttempt, owner, ('id', 'content_id', 'status', 'started_at', 'submitted_at', 'correct_count',
        'question_count', 'question_ids', 'last_saved_at', 'draft_revision', 'result_snapshot'))
    def practice_rows():
        for row in attempts:
            row['result_snapshot'] = _practice_result(row['result_snapshot']) if row['status'] == 'submitted' else {}
            yield row
    yield 'practice_attempts', practice_rows()
    answers = _rows(AttemptAnswer, {'attempt__user_id': user.pk, 'attempt__status': 'submitted'},
        ('id', 'attempt_id', 'question_id', 'selected_option_id', 'is_correct', 'answered_at', 'evidence_snapshot'))
    def answer_rows():
        for row in answers:
            row['evidence_snapshot'] = _evidence(row['evidence_snapshot'])
            yield row
    yield 'practice_answers', answer_rows()
    yield 'practice_drafts', _rows(AttemptDraftAnswer, {'attempt__user_id': user.pk},
        ('id', 'attempt_id', 'question_id', 'selected_option_id', 'updated_at'))
    yield 'error_notebook', _rows(ErrorNotebookEntry, {'answer__attempt__user_id': user.pk},
        ('id', 'answer_id', 'category', 'learner_note', 'reviewed_at', 'created_at'))
    reviews = _rows(MistakeReviewSession, owner, ('id', 'exam_type', 'category', 'status', 'result_snapshot', 'draft_answers',
        'draft_revision', 'last_saved_at', 'question_count', 'correct_count', 'started_at', 'created_at', 'submitted_at'))
    def review_rows():
        for row in reviews:
            row['result_snapshot'] = _mistake_result(row['result_snapshot']) if row['status'] == 'submitted' else {}
            row['draft_answers'] = _choice_map(row['draft_answers'])
            yield row
    yield 'mistake_review_sessions', review_rows()
    yield 'mistake_review_items', _rows(MistakeReviewItem, {'session__user_id': user.pk},
        ('id', 'session_id', 'source_entry_id', 'question_id', 'position'))
    yield 'mistake_review_answers', _rows(MistakeReviewAnswer,
        {'item__session__user_id': user.pk, 'item__session__status': 'submitted'},
        ('id', 'item_id', 'selected_option_id', 'is_correct', 'answered_at'))
    quizzes = _rows(VocabularyQuizSession, owner, ('id', 'status', 'exam_type', 'cefr_level', 'topic', 'vocabulary_source',
        'mode', 'question_count', 'correct_count', 'snapshot', 'answers', 'draft_answers', 'last_saved_at', 'draft_revision',
        'parent_quiz_id', 'is_retry', 'xp_earned', 'started_at', 'submitted_at'))
    def quiz_rows():
        for row in quizzes:
            row['snapshot'] = _quiz_snapshot(row)
            row['answers'], row['draft_answers'] = _choice_map(row['answers']), _choice_map(row['draft_answers'])
            row['answer_key_released'] = row['status'] == 'submitted'
            yield row
    yield 'vocabulary_quizzes', quiz_rows()
    yield 'due_recall_observations', _rows(DueRecallObservation, {'quiz__user_id': user.pk},
        ('id', 'quiz_id', 'card_id', 'baseline_reviewed_at', 'checked_at', 'is_correct', 'exclusion_reason'))
    turns = _rows(TutorTurn, owner, ('id', 'question', 'result', 'response_mode', 'question_id_context', 'created_at'))
    def tutor_rows():
        for row in turns:
            row['result'] = _tutor_result(row['result'])
            yield row
    yield 'tutor_history', tutor_rows()
    yield 'tutor_usage', _rows(TutorUsageBudget, owner, ('day', 'day_count', 'minute_started_at', 'minute_count'))
    yield 'flashcard_reviews', _rows(FlashcardReview, owner, ('id', 'flashcard_id', 'rating', 'reviewed_at', 'due_at'))
    yield 'spaced_repetition', _rows(UserFlashcardState, owner, ('id', 'flashcard_id', 'last_rating', 'reviewed_at', 'due_at',
        'review_count', 'interval_days', 'ease_factor', 'successful_reviews', 'lapse_count'))
    yield 'saved_words', _rows(SavedWord, owner, ('id', 'flashcard_id', 'created_at'))
    yield 'daily_rewards', _rows(VocabularyQuizDailyReward, {'user_id': user.pk, 'quiz__user_id': user.pk}, ('id', 'day', 'quiz_id', 'xp'))
    rewards = get_learning_rewards(user)
    yield 'reward_summary', [_pick(rewards, ('total_xp', 'level', 'level_name', 'xp_in_level', 'xp_to_next',
        'streak_days', 'longest_streak', 'today_xp', 'quiz_count', 'reviewed_today', 'rules'))]
    yield 'weak_word_projection', _rows(WeakWordProjectionState, owner, ('version', 'ready', 'needs_rebuild', 'updated_at'))
    yield 'weak_word_outcomes', _rows(WeakWordOutcome, owner, ('id', 'exam_type', 'card_id', 'identity_hash', 'group_key',
        'mode', 'term', 'meaning_vi', 'part_of_speech', 'last_attempt_at', 'last_quiz_id', 'is_wrong', 'wrong_count'))
    yield 'weak_word_pending', _rows(WeakWordPendingOutcome, {'user_id': user.pk, 'quiz__user_id': user.pk},
        ('id', 'quiz_id', 'exam_type', 'card_id', 'identity_hash', 'group_key', 'mode', 'term', 'meaning_vi',
         'part_of_speech', 'submitted_at', 'is_wrong'))
    yield 'weak_word_receipts', _rows(WeakWordQuizReceipt, {'user_id': user.pk, 'quiz__user_id': user.pk}, ('quiz_id', 'fingerprint'))


def personal_data_response(user):
    """Build bounded JSON without silently omitting records or persisting a file."""
    if _has_social_data(user):
        raise SocialDataNotReady
    chunks, size = [], 0
    def append(value):
        nonlocal size
        raw = value.encode('utf-8')
        size += len(raw)
        if size > MAX_EXPORT_BYTES:
            raise ExportTooLarge
        chunks.append(raw)
    encode = lambda value: json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(',', ':'))
    account = {field: getattr(user, field) for field in ('id', 'username', 'first_name', 'last_name', 'email', 'date_joined', 'last_login')}
    append('{"format_version":1,"generated_at":' + encode(timezone.now()) + ',"account":' + encode(account))
    append(',"notes":' + encode([
        'Dữ liệu chỉ thuộc tài khoản hiện tại; học liệu dùng chung được tham chiếu bằng ID hoặc bằng chứng đã được phép xem.',
        'Quiz chưa nộp chỉ xuất đề công khai và lựa chọn đã lưu; không xuất khóa chấm hoặc đáp án chưa được mở.',
        'Không xuất mật khẩu/hash, session/cookie/token, khóa dịch vụ, log hạ tầng hoặc dữ liệu tài khoản khác.',
    ]))
    for section, rows in _export_sections(user):
        append(',' + encode(section) + ':[')
        first = True
        for row in rows:
            append(('' if first else ',') + encode(row))
            first = False
        append(']')
    append('}')
    response = HttpResponse(b''.join(chunks), content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="linguapath-personal-data.json"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _limited(message, status, retry_after):
    response = HttpResponse(message, status=status, content_type='text/plain; charset=utf-8')
    response['Retry-After'] = str(retry_after)
    return response


def _page(request, error='', status=200):
    return render(request, 'learning/privacy.html', {
        'privacy_error': error, 'privileged_account': request.user.is_staff or request.user.is_superuser,
        'can_confirm_password': request.user.has_usable_password(),
        'export_size_mb': MAX_EXPORT_BYTES // (1024 * 1024),
    }, status=status)


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
@csrf_protect
@sensitive_post_parameters('password')
@sensitive_variables('password')
def privacy_center(request):
    if request.method == 'GET':
        return _page(request)
    action = request.POST.get('action')
    if action not in ('export', 'delete'):
        return HttpResponse('Thao tác không hợp lệ.', status=400)
    try:
        decision = reserve_auth_request('privacy_reauth', client_ip(request), str(request.user.pk))
    except AuthReservationConflict:
        return _limited('Bạn đang thao tác quá nhanh. Vui lòng thử lại sau.', 429, 1)
    except (DatabaseError, ImproperlyConfigured):
        return _limited('Tạm thời chưa thể xác nhận yêu cầu. Vui lòng thử lại sau.', 503, 30)
    if not decision.allowed:
        return _limited('Bạn đang thao tác quá nhanh. Vui lòng thử lại sau.', 429, decision.retry_after)
    password = request.POST.get('password', '')
    try:
        with transaction.atomic():
            # Full row lock blocks concurrent FK attachments until the export or
            # deletion commits; NO KEY UPDATE would allow those inserts.
            user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if action == 'delete' and (user.is_staff or user.is_superuser):
                return _page(request, 'Tài khoản có quyền quản trị cần được xử lý qua quy trình quản trị riêng.', 403)
            if not user.is_active or not password or len(password) > 1024 or not user.check_password(password):
                return _page(request, _REAUTH_ERROR, 403)
            if action == 'export':
                return personal_data_response(user)
            if request.POST.get('confirm_delete') != 'XOA' or request.POST.get('confirm_understood') != 'yes':
                return _page(request, 'Hãy nhập đúng XOA và đánh dấu ô xác nhận trước khi xóa tài khoản.', 400)
            if not apps.is_installed('allauth.socialaccount') and _has_social_data(user):
                raise SocialDataNotReady
            user.delete()
    except get_user_model().DoesNotExist:
        logout(request)
        return redirect('login')
    except SocialDataNotReady:
        return _page(request, 'Tài khoản có dữ liệu liên kết đăng nhập hoặc email do dịch vụ xác thực quản lý. Chức năng xử lý đầy đủ dữ liệu này chưa sẵn sàng; yêu cầu chưa được thực hiện.', 409)
    except ExportTooLarge:
        return _page(request, 'Dữ liệu vượt giới hạn tải trực tiếp. Chưa tạo bản xuất; hãy liên hệ quản trị để xuất đầy đủ qua quy trình đã xác thực.', 413)
    except DatabaseError:
        return _limited('Tạm thời chưa thể hoàn tất yêu cầu. Dữ liệu chưa được xác nhận đã thay đổi; vui lòng thử lại sau.', 503, 30)
    logout(request)
    messages.success(request, 'Tài khoản và dữ liệu học gắn trực tiếp với tài khoản đã được xóa khỏi ứng dụng hiện hành.')
    return redirect('login')
