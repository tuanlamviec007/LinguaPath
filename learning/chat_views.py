"""Bounded, owner-scoped chat orchestration over existing tutor tools."""
import logging
import re
import unicodedata
from uuid import UUID, uuid4

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from planner.models import LearnerProfile
from .ai import answer_tutor_question
from .ai_provider import tutor_ai_available
from .locking import nonkey_row_lock
from .models import TutorTurn
from .tutor_provenance import revalidate_tutor_history
from .tutor_tools import learner_progress, daily_tasks

logger = logging.getLogger(__name__)
SALT = 'learning.chat.send.v1'


def _thread(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise Http404


def _recent(user):
    turns = list(TutorTurn.objects.filter(user=user)[:50])
    for turn in turns:
        if not isinstance(turn.result, dict):
            turn.result = {}
    return turns


def _in_thread(turn, thread):
    return isinstance(turn.result, dict) and turn.result.get('chat_thread') == thread


def _pending_expired(turn):
    return (timezone.now() - turn.created_at).total_seconds() >= 90


def _url(thread):
    return reverse('learning:chat') + '?thread=' + thread + '#latest-response'


def current_memory(turns, user, exam):
    """Never replay tool data, withdrawn sources, old tutor sessions or private exam answers."""
    history, previous = [], ''
    for turn in list(reversed(turns))[-3:]:
        if turn.result.get('mode') not in ('llm_rag', 'retrieval_only'):
            continue
        result, notice = revalidate_tutor_history(turn.result, user, exam, turn.created_at)
        sources = result.get('evidence_sources', [])
        if notice['state'] != 'current' or not sources or any(s.get('kind') not in ('knowledge', 'flashcard') for s in sources):
            continue
        history += [{'role': 'user', 'content': turn.question[:500]},
                    {'role': 'assistant', 'content': str(result.get('answer', ''))[:1000]}]
        previous = turn.question
    return history, previous


def _retrieval_query(query, previous):
    folded = ''.join(c for c in unicodedata.normalize('NFD', query.lower()) if unicodedata.category(c) != 'Mn')
    if previous and len(query) <= 100 and re.search(r'\b(vi du|them|khac|tai sao|vi sao|no|tu do|cau do|that|another|more|example)\b', folded):
        return (previous[:350] + '\nCâu hỏi tiếp: ' + query)[:500]
    return query


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def chat(request):
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    turns = _recent(request.user)
    thread = _thread(request.GET['thread']) if request.GET.get('thread') else str(uuid4())
    if request.method == 'GET' and request.GET.get('thread') and not any(_in_thread(t, thread) for t in turns):
        raise Http404
    if request.method == 'POST':
        try:
            if len(request.POST.getlist('token')) != 1:
                raise ValueError()
            token = signing.loads(request.POST['token'], salt=SALT, max_age=3600)
            if token['user'] != request.user.pk:
                raise ValueError()
            thread = _thread(token['thread'])
            request_id = str(UUID(token['request']))
        except (signing.BadSignature, KeyError, ValueError, TypeError):
            return HttpResponseBadRequest('Phiên gửi đã hết hạn. Hãy tải lại trang chat.')
        tool = request.POST.get('tool', 'question')
        if tool not in ('question', 'progress', 'plan', 'clear', 'confirm_clear') or len(request.POST.getlist('tool')) > 1:
            return HttpResponseBadRequest('Thao tác không hợp lệ.')
        if tool in ('clear', 'confirm_clear'):
            owned = [t for t in turns if _in_thread(t, thread)]
            if tool == 'confirm_clear':
                TutorTurn.objects.filter(user=request.user, pk__in=[t.pk for t in owned]).delete()
                messages.success(request, 'Đã xóa cuộc trò chuyện này.')
                return redirect('learning:chat')
            return render(request, 'learning/chat_clear.html', {'token': request.POST['token'], 'thread_url': _url(thread)})
        query = request.POST.get('question', '').strip()
        query = {'progress': 'Tiến độ học của tôi', 'plan': 'Kế hoạch học hôm nay'}.get(tool, query)
        if not query or len(query) > 500 or len(request.POST.getlist('question')) > 1:
            return HttpResponseBadRequest('Hãy nhập câu hỏi từ 1 đến 500 ký tự.')
        use_ai = request.POST.get('response_mode') == 'ai' and tutor_ai_available() and tool == 'question'
        with transaction.atomic():
            nonkey_row_lock(get_user_model().objects.all()).get(pk=request.user.pk)
            turns = _recent(request.user)
            if any(t.result.get('chat_request') == request_id for t in turns):
                return redirect(_url(thread))
            if any(_in_thread(t, thread) and t.result.get('mode') == 'chat_pending' and not _pending_expired(t) for t in turns):
                messages.info(request, 'Câu hỏi trước đang được xử lý. Hãy mở lại chat sau ít giây.')
                return redirect(_url(thread))
            turn = TutorTurn.objects.create(user=request.user, question=query, response_mode='ai' if use_ai else 'lookup',
                result={'chat_thread': thread, 'chat_request': request_id, 'mode': 'chat_pending', 'answer': 'Đang xử lý câu hỏi…', 'sources': []})
            retained = list(TutorTurn.objects.filter(user=request.user).values_list('id', flat=True)[:50])
            TutorTurn.objects.filter(user=request.user, id__lt=retained[-1]).delete()
        try:
            if tool == 'progress':
                result = learner_progress(request.user, profile)
            elif tool == 'plan':
                result = daily_tasks(request.user, profile)
            else:
                memory, previous = current_memory([t for t in turns if _in_thread(t, thread)], request.user, profile.exam_goal)
                result = answer_tutor_question(query, exam=profile.exam_goal, user=request.user, use_ai=use_ai,
                    public_context_only=True, retrieval_query=_retrieval_query(query, previous),
                    chat_history=memory if use_ai else None, semantic=use_ai)
            result.update(chat_thread=thread, chat_request=request_id, tool=tool)
        except Exception:
            logger.warning('Chat turn failed; no exception or prompt details logged.')
            result = {'chat_thread': thread, 'chat_request': request_id, 'tool': tool, 'mode': 'unavailable',
                      'answer': 'Lumi chưa xử lý được lần này. Bạn có thể gửi lại câu hỏi mới hoặc mở phần tra cứu học liệu.', 'sources': []}
        # Clear-history may have removed this turn while inference was running.
        TutorTurn.objects.filter(pk=turn.pk, user=request.user).update(result=result)
        return redirect(_url(thread) if TutorTurn.objects.filter(pk=turn.pk, user=request.user).exists() else reverse('learning:chat'))
    conversation = []
    for turn in reversed([t for t in turns if _in_thread(t, thread)][:12]):
        result, notice = revalidate_tutor_history(turn.result, request.user, profile.exam_goal, turn.created_at)
        if result['mode'] == 'chat_pending' and _pending_expired(turn):
            result.update(mode='unavailable', answer='Lượt trước chưa hoàn thành. Bạn có thể gửi một câu hỏi mới; Lumi không tự gửi lại yêu cầu AI cũ.')
        conversation.append({'question': turn.question, 'result': result, 'notice': notice})
    threads, seen = [], set()
    for turn in turns:
        key = turn.result.get('chat_thread')
        if isinstance(key, str) and key not in seen:
            seen.add(key)
            threads.append({'title': turn.question, 'href': _url(key), 'active': key == thread})
    return render(request, 'learning/chat.html', {'conversation': conversation, 'threads': threads[:8],
        'thread': thread, 'llm_enabled': tutor_ai_available(),
        'use_ai': bool(conversation and next((t for t in turns if _in_thread(t, thread)), None).response_mode == 'ai'),
        'token': signing.dumps({'user': request.user.pk, 'thread': thread, 'request': str(uuid4())}, salt=SALT)})
