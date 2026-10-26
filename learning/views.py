from datetime import timedelta
import json
import hashlib
import random

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import get_user_model
from .locking import nonkey_row_lock
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.core.paginator import Paginator
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache

from planner.models import LearnerProfile, StudyTask
from planner.services import generate_daily_plan, replan_daily_plan
from .ai import answer_description_candidate, answer_tutor_question
from .ai_provider import tutor_ai_available
from .tutor_knowledge import KNOWLEDGE
from .tutor_provenance import revalidate_tutor_history
from .tutor_tools import daily_tasks, learner_progress, practice_recommendations
from planner.forms import LearningGoalForm
from .models import AnswerOption, AttemptAnswer, ErrorNotebookEntry, Flashcard, FlashcardReview, LearningContent, PracticeAttempt, Question, UserFlashcardState
from .models import CEFR_LEVELS, LEARNER_REVIEW_STATUSES, TutorUsageBudget, TutorTurn
from .spaced_repetition import schedule_review
from .flashcard_navigation import attach_rating_return_urls, flashcard_return_url
from .activity import build_activity_summary
from .gamification import get_learning_rewards
from .saved_words import visible_saved_words, with_saved_flags
from .quiz_weak_words import weak_word_summary
from .practice_sessions import DraftConflictError, DraftValidationError, PracticeUnavailableError, answer_evidence, valid_answer_evidence, parse_draft_revision, fingerprint_questions, save_draft as persist_draft, start_or_resume


def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    # A GET-only sample works without JavaScript and never records a grade/XP.
    answer = request.GET.get('demo_answer', '')
    answer = answer if answer in {'A', 'B', 'C'} else ''
    return render(request, 'learning/home.html', {'demo_answer': answer,
        'demo_correct': answer == 'B'})


@require_GET
def getting_started(request):
    return render(request, 'learning/getting_started.html')


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = UserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            LearnerProfile.objects.create(user=user)
        login(request, user)
        messages.success(request, 'Tài khoản đã sẵn sàng. Hãy bắt đầu với mục tiêu học của bạn.')
        return redirect('learning_goal')
    return render(request, 'registration/register.html', {'form': form})


@login_required
def dashboard(request):
    from .quiz_views import active_quiz_for_user
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_complete:
        return redirect('learning_goal')
    today = timezone.localdate()
    tasks = list(generate_daily_plan(request.user, profile, today))
    completed_task_count = sum(task.status == 'done' for task in tasks)
    task_progress_percent = round(100 * completed_task_count / len(tasks)) if tasks else 0
    next_task = next((task for task in tasks if task.status in {'todo', 'in_progress'}), None)
    recent_attempts = PracticeAttempt.objects.filter(user=request.user, status='submitted', content__exam_type=profile.exam_goal, submitted_at__lte=timezone.now()).select_related('content').defer('question_ids', 'content_fingerprint', 'result_snapshot').order_by('-submitted_at', '-id')[:4]
    resume_attempts = PracticeAttempt.objects.filter(
        user=request.user, status='in_progress', content__exam_type=profile.exam_goal,
        content__is_published=True, content__review_status__in=LEARNER_REVIEW_STATUSES,
    ).select_related('content').annotate(saved_count=Count('draft_answers')).order_by('-started_at', '-id')[:3]
    pending_states = UserFlashcardState.objects.filter(user=request.user, due_at__gt=timezone.now()).values_list('flashcard_id', flat=True)
    due_cards = Flashcard.objects.learner_visible(profile.exam_goal).exclude(id__in=pending_states).count()
    new_error_count = _notebook_entries(request.user, profile.exam_goal).filter(reviewed_at__isnull=True).count()
    weak_summary = weak_word_summary(request.user, profile.exam_goal)
    from .getting_started import starter_progress
    starter = starter_progress(request.user, profile)
    return render(request, 'learning/dashboard.html', {
        'profile': profile, 'tasks': tasks, 'recent_attempts': recent_attempts,
        'due_cards': due_cards, 'today': today,
        'current_cefr': profile.current_cefr,
        'target_cefr': profile.target_cefr,
        'completed_task_count': completed_task_count,
        'task_progress_percent': task_progress_percent,
        'new_error_count': new_error_count,
        'next_task': next_task, 'resume_attempts': resume_attempts,
        'active_quiz': active_quiz_for_user(request.user, profile.exam_goal),
        'activity': build_activity_summary(request.user, profile.exam_goal),
        'rewards': get_learning_rewards(request.user),
        'saved_word_count': visible_saved_words(request.user).count(),
        'weak_word_count': weak_summary['count'], 'weak_words_ready': weak_summary.get('ready', True),
        'starter': starter,
        'show_dashboard_details': starter['complete'] or request.GET.get('view') == 'all',
    })


@login_required
def learning_goal(request):
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    first_setup = not profile.onboarding_complete
    form = LearningGoalForm(request.POST or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            nonkey_row_lock(get_user_model().objects.all()).get(pk=request.user.pk)
            form.save()
            profile.onboarding_complete = True
            profile.save(update_fields=['onboarding_complete', 'updated_at'])
            replan_daily_plan(request.user, profile, changed_fields=form.changed_data)
        if first_setup:
            messages.success(request, 'Kế hoạch đầu tiên đã sẵn sàng. Bắt đầu với một thẻ từ nhé!')
        else:
            messages.success(request, 'Đã lưu mục tiêu. Các nhiệm vụ đã hoàn thành hôm nay vẫn được giữ lại; kế hoạch mới sẽ tính phần thời gian còn lại.')
        return redirect('dashboard')
    return render(request, 'learning/learning_goal.html', {'form': form, 'profile': profile})


@login_required
def progress(request):
    from .quiz_progress import quiz_progress_summary
    from .quiz_due import due_summary
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    attempts = PracticeAttempt.objects.filter(
        user=request.user, status='submitted', content__exam_type=profile.exam_goal,
        submitted_at__lte=timezone.now(),
    )
    totals = attempts.aggregate(total_attempts=Count('pk'), total_questions=Sum('question_count'), correct=Sum('correct_count'))
    total_questions, correct = totals['total_questions'] or 0, totals['correct'] or 0
    practice_page = Paginator(
        attempts.select_related('content').defer('question_ids', 'content_fingerprint', 'result_snapshot').order_by('-submitted_at', '-pk'),
        20,
    ).get_page(request.GET.get('practice_page'))
    levels = [value for value, _ in Flashcard.LEVELS]
    cefr_progress = []
    for level in levels:
        level_cards = Flashcard.objects.learner_visible(profile.exam_goal).filter(cefr_level=level)
        total = level_cards.count()
        known = UserFlashcardState.objects.filter(user=request.user, flashcard__in=level_cards, last_rating='known').count()
        cefr_progress.append({'level': level, 'total': total, 'known': known, 'percent': round(100 * known / total) if total else 0})
    today = timezone.localdate()
    states = UserFlashcardState.objects.filter(
        user=request.user, flashcard__is_available=True, flashcard__content__exam_type=profile.exam_goal,
        flashcard__content__is_published=True,
        flashcard__content__review_status__in=LEARNER_REVIEW_STATUSES,
    )
    counts = dict(states.annotate(day=TruncDate('due_at')).values('day').annotate(total=Count('id')).values_list('day', 'total'))
    upcoming_reviews = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        count = sum(n for date, n in counts.items() if date <= day) if offset == 0 else counts.get(day, 0)
        upcoming_reviews.append({'day': day, 'count': count, 'today': offset == 0})
    weak_summary = weak_word_summary(request.user, profile.exam_goal)
    return render(request, 'learning/progress.html', {
        'profile': profile,
        'attempts': practice_page, 'practice_page_obj': practice_page, 'total_attempts': totals['total_attempts'],
        'total_questions': total_questions, 'accuracy': round(100 * correct / total_questions) if total_questions else 0,
        'cefr_progress': cefr_progress,
        'upcoming_reviews': upcoming_reviews, 'reviewed_card_count': states.count(),
        'activity': build_activity_summary(request.user, profile.exam_goal),
        'quiz_progress': quiz_progress_summary(request.user, profile.exam_goal),
        'due_summary': due_summary(request.user, profile.exam_goal),
        'weak_word_count': weak_summary['count'], 'weak_words_ready': weak_summary.get('ready', True),
    })


def _placement_card_version(card):
    value = [card.pk, card.content_id, card.cefr_level, card.term, card.meaning_vi, card.part_of_speech]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def _placement_sources_current(questions, exam):
    """Revalidate the original target and all displayed options under parent locks.

    Called inside the owner's transaction. Old sessions without identities cannot
    prove which cards were shown and must be restarted rather than graded.
    """
    if not isinstance(questions, list) or len(questions) != 15:
        return False
    ids, targets, levels = set(), set(), []
    for question in questions:
        if (not isinstance(question, dict) or set(question) != {'level', 'correct', 'target_id', 'source_versions'}
                or not isinstance(question['level'], str) or question['level'] not in dict(CEFR_LEVELS)
                or question['correct'] not in ('A', 'B', 'C', 'D')
                or type(question['target_id']) is not int or not 0 < question['target_id'] <= 2**63 - 1
                or question['target_id'] in targets or not isinstance(question['source_versions'], list)
                or len(question['source_versions']) != 4):
            return False
        option_ids = set()
        for source in question['source_versions']:
            if (not isinstance(source, dict) or set(source) != {'id', 'version'}
                    or type(source['id']) is not int or not 0 < source['id'] <= 2**63 - 1
                    or source['id'] in option_ids or not isinstance(source['version'], str)
                    or len(source['version']) != 64):
                return False
            option_ids.add(source['id'])
        if (question['target_id'] not in option_ids
                or question['source_versions'][ord(question['correct']) - ord('A')]['id'] != question['target_id']):
            return False
        ids.update(option_ids)
        targets.add(question['target_id'])
        levels.append(question['level'])
    if any(levels.count(level) != 3 for level, _ in CEFR_LEVELS):
        return False
    initial = dict(Flashcard.objects.filter(pk__in=ids).values_list('pk', 'content_id'))
    if len(initial) != len(ids):
        return False
    list(LearningContent.objects.select_for_update().filter(pk__in=set(initial.values())).order_by('pk'))
    cards = {card.pk: card for card in Flashcard.objects.learner_visible(exam).filter(
        pk__in=ids, content__content_type='vocabulary').select_for_update().order_by('pk')}
    if set(cards) != ids or any(cards[pk].content_id != initial[pk] for pk in ids):
        return False
    for question in questions:
        if cards[question['target_id']].cefr_level != question['level']:
            return False
        if any(_placement_card_version(cards[source['id']]) != source['version'] for source in question['source_versions']):
            return False
    return True


@login_required
def placement_test(request):
    """Offer a short vocabulary placement estimate from reviewed lesson content."""
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    levels = [value for value, _ in CEFR_LEVELS]
    cards_by_level = {}
    seen_terms = set()
    for level in levels:
        candidates = Flashcard.objects.learner_visible(profile.exam_goal).filter(
            cefr_level=level, content__content_type='vocabulary',
            meaning_vi__gt='',
        ).select_related('content').order_by('term', 'id')
        # A short demo bank may contain the same lemma in multiple levels or
        # sources. Ask each lemma at most once; don't treat alternate senses
        # as separate evidence of level.
        unique = []
        for card in candidates:
            lemma = card.term.strip().casefold()
            if lemma in seen_terms:
                continue
            seen_terms.add(lemma)
            unique.append(card)
        cards_by_level[level] = unique
    all_meanings = {card.meaning_vi for level_cards in cards_by_level.values() for card in level_cards}
    ready = all(len(cards_by_level[level]) >= 3 for level in levels) and len(all_meanings) >= 4
    if request.method == 'POST' and ready:
        questions = request.session.get('placement_questions')
        with transaction.atomic():
            nonkey_row_lock(get_user_model().objects.all()).get(pk=request.user.pk)
            if not _placement_sources_current(questions, profile.exam_goal):
                request.session.pop('placement_questions', None)
                messages.error(request, 'Bài kiểm tra đã hết hiệu lực hoặc học liệu đã thay đổi. Hãy bắt đầu lại.')
                return redirect('learning:placement_test')
            if any(len(request.POST.getlist(f'q_{index}')) != 1 or request.POST.get(f'q_{index}') not in {'A', 'B', 'C', 'D'} for index in range(len(questions))):
                messages.error(request, 'Hãy trả lời đủ 15 câu trước khi nộp bài.')
                return redirect('learning:placement_test')
            scores = {level: 0 for level in levels}
            for index, question in enumerate(questions):
                if request.POST.get(f'q_{index}') == question['correct']:
                    scores[question['level']] += 1
            estimate = 'A1'
            for level in levels:
                if scores[level] >= 2:
                    estimate = level
                else:
                    break
            request.session['placement_estimate'] = estimate
            request.session['placement_scores'] = scores
            request.session.pop('placement_questions', None)
        return redirect('learning:placement_result')
    if request.method == 'POST':
        request.session.pop('placement_questions', None)
        messages.error(request, 'Chưa đủ từ vựng đã xuất bản để tạo bài xếp mức. Hãy thử lại sau khi quản trị viên bổ sung dữ liệu.')
        return redirect('learning:placement_test')

    if request.method == 'GET':
        all_cards = [card for level_cards in cards_by_level.values() for card in level_cards]
        questions, rendered = [], []
        for level in levels:
            for card in random.sample(cards_by_level[level], 3) if ready else []:
                decoys = list({item.meaning_vi: item for item in all_cards if item.id != card.id and item.meaning_vi != card.meaning_vi}.values())
                choices = random.sample(decoys, 3) + [card]
                random.shuffle(choices)
                labels = ['A', 'B', 'C', 'D']
                option_data = [{'label': label, 'meaning': choice.meaning_vi} for label, choice in zip(labels, choices)]
                correct = next(label for label, choice in zip(labels, choices) if choice.id == card.id)
                questions.append({'level': level, 'correct': correct, 'target_id': card.pk,
                    'source_versions': [{'id': choice.pk, 'version': _placement_card_version(choice)} for choice in choices]})
                rendered.append({'term': card.term, 'index': len(questions) - 1, 'options': option_data})
        if ready:
            request.session['placement_questions'] = questions
    return render(request, 'learning/placement.html', {
        'profile': profile, 'questions': rendered if request.method == 'GET' else [],
        'ready': ready, 'levels': levels,
    })


@login_required
def placement_result(request):
    estimate = request.session.get('placement_estimate')
    scores = request.session.get('placement_scores')
    if not estimate or not scores:
        return redirect('learning:placement_test')
    return render(request, 'learning/placement_result.html', {
        'estimate': estimate,
        'score_rows': [{'level': value, 'score': scores.get(value, 0)} for value, _ in CEFR_LEVELS],
    })


@login_required
def apply_placement_result(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    estimate = request.session.get('placement_estimate')
    valid_levels = {value for value, _ in CEFR_LEVELS}
    if estimate not in valid_levels:
        return redirect('learning:placement_test')
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    previous_levels = {'current_cefr': profile.current_cefr, 'target_cefr': profile.target_cefr}
    profile.current_cefr = estimate
    levels = [value for value, _ in CEFR_LEVELS]
    if levels.index(profile.target_cefr) < levels.index(estimate):
        profile.target_cefr = estimate
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=request.user.pk)
        profile.save(update_fields=['current_cefr', 'target_cefr', 'updated_at'])
        changed_fields = {field for field, value in previous_levels.items() if getattr(profile, field) != value}
        replan_daily_plan(request.user, profile, changed_fields=changed_fields)
    messages.success(request, f'Đã cập nhật trình độ hiện tại thành {estimate}. Bạn có thể chỉnh mục tiêu trong hồ sơ.')
    return redirect('learning_goal')


@login_required
@never_cache
def tutor(request):
    answer = None
    prompt = ''
    sources = []
    evidence_sources = []
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    suggestion_terms = Flashcard.objects.learner_visible(profile.exam_goal).filter(
        cefr_level=profile.current_cefr,
    ).order_by('term').values_list('term', flat=True).distinct()[:3]
    suggested_prompts = [f'Giải thích từ “{term}” và cho ví dụ.' for term in suggestion_terms]
    mode = 'retrieval_only'
    tutor_mode = 'lookup'
    query_mode = 'description' if request.GET.get('query_mode') == 'description' else 'auto'
    llm_enabled = tutor_ai_available()
    context_question_id = request.GET.get('question_id', '')
    result = {}
    history_notice = None
    if request.method == 'GET' and request.GET.get('turn'):
        turn_id = request.GET['turn']
        if not turn_id.isascii() or not turn_id.isdigit() or len(turn_id) > 18:
            raise Http404
        turn = get_object_or_404(TutorTurn, pk=turn_id, user=request.user)
        prompt = turn.question
        result, history_notice = revalidate_tutor_history(
            turn.result, request.user, profile.exam_goal, turn.created_at,
        )
        tutor_mode, context_question_id = turn.response_mode if llm_enabled else 'lookup', turn.question_id_context
    if request.method == 'POST':
        action = request.POST.get('action', 'question')
        if action == 'clear_history':
            TutorTurn.objects.filter(user=request.user).delete()
            messages.success(request, 'Đã xóa lịch sử trợ lý của bạn.')
            return redirect('tutor')
        prompt = request.POST.get('question', '').strip()[:500]
        query_mode = request.POST.get('query_mode', 'auto')
        if query_mode not in ('auto', 'description') or len(request.POST.getlist('query_mode')) > 1:
            return HttpResponseBadRequest('Cách tra cứu không hợp lệ.')
        context_question_id = request.POST.get('question_id', '')
        tutor_mode = 'ai' if request.POST.get('response_mode') == 'ai' and llm_enabled else 'lookup'
        if query_mode == 'description':
            tutor_mode = 'lookup'
        if action == 'select_candidate':
            if context_question_id or any(len(request.POST.getlist(field)) != 1 for field in ('candidate_id', 'candidate_version')):
                return HttpResponseBadRequest('Lựa chọn mục từ không hợp lệ. Hãy tìm lại từ mô tả.')
            result = answer_description_candidate(request.POST.get('candidate_id'), request.POST.get('candidate_version'), profile.exam_goal)
            selected = result.get('evidence_sources', [])
            prompt = (f'Giải thích từ “{selected[0]["label"]}” trong ngữ cảnh: {selected[0]["meaning_vi"]}.'
                      if selected else 'Mở lại mục từ đã chọn')
            tutor_mode, query_mode, context_question_id = 'lookup', 'auto', ''
        elif action == 'progress':
            prompt, result = 'Tiến độ học của tôi', learner_progress(request.user, profile)
            tutor_mode, context_question_id = 'lookup', ''
        elif action == 'plan':
            prompt, result = 'Nhiệm vụ học hôm nay', daily_tasks(request.user, profile)
            tutor_mode, context_question_id = 'lookup', ''
        elif action != 'question':
            return HttpResponseBadRequest('Invalid tutor action')
        elif not prompt:
            messages.error(request, 'Hãy nhập câu hỏi trước khi gửi.')
        else:
            # A supplied invalid ID remains explicit; retrieval denies it without
            # falling through to a different question or generic vocabulary.
            question_id = context_question_id if context_question_id else None
            retrieval_options = {'retrieval_mode': 'description'} if query_mode == 'description' else {}
            result = answer_tutor_question(prompt, exam=profile.exam_goal, question_id=question_id, user=request.user, use_ai=tutor_mode == 'ai', **retrieval_options)
        if result:
            with transaction.atomic():
                # Serialize history retention per account on PostgreSQL. A
                # concurrent result must not prune a newly created turn.
                nonkey_row_lock(get_user_model().objects.all()).get(pk=request.user.pk)
                turn = TutorTurn.objects.create(
                    user=request.user, question=prompt, result=result,
                    response_mode=tutor_mode, question_id_context=context_question_id[:100],
                )
                retained = list(TutorTurn.objects.filter(user=request.user).values_list('id', flat=True)[:50])
                TutorTurn.objects.filter(user=request.user, id__lt=retained[-1]).delete()
            # Refresh repeats a GET rather than another paid inference call.
            return redirect(f'{reverse("tutor")}?turn={turn.pk}#answer-title')
    if result:
        answer, sources, mode = result['answer'], result['sources'], result['mode']
        evidence_sources = result.get('evidence_sources', [])
        suggested_prompts = result.get('clarification_prompts') or suggested_prompts
        query_mode = 'description' if result.get('retrieval_mode') == 'description' else 'auto'
        if query_mode == 'description':
            # Keep stored history immutable; offer only currently verified
            # candidates in the live picker and its prompt shortcuts.
            suggested_prompts = [f'Giải thích từ “{source["label"]}” trong ngữ cảnh: {source["meaning_vi"]}.'
                for source in evidence_sources if source.get('kind') == 'flashcard'
                and source.get('label') and source.get('meaning_vi') and source.get('href')
                and source.get('link_available') is not False
                and source.get('provenance_state') in (None, 'current')]
    usage = TutorUsageBudget.objects.filter(user=request.user, day=timezone.localdate()).first()
    used = usage.day_count if usage else 0
    return render(request, 'learning/tutor.html', {
        'answer': answer, 'prompt': prompt, 'sources': sources, 'mode': mode,
        'history_notice': history_notice,
        'context_question_id': context_question_id,
        'evidence_sources': evidence_sources, 'suggested_prompts': suggested_prompts,
        'tutor_mode': tutor_mode, 'query_mode': query_mode,
        'llm_enabled': llm_enabled,
        'ai_calls_used': used, 'ai_daily_limit': settings.AI_TUTOR_DAILY_LIMIT,
        'ai_calls_remaining': max(0, settings.AI_TUTOR_DAILY_LIMIT - used),
        'ai_minute_limit': settings.AI_TUTOR_MINUTE_LIMIT,
        'profile': profile, 'tutor_actions': result.get('actions', []),
        'tutor_history': TutorTurn.objects.filter(user=request.user)[:8],
        'recommended_practice': practice_recommendations(profile),
        'knowledge_notes': KNOWLEDGE,
    })


@login_required
def flashcards(request, content_id=None):
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    cards = Flashcard.objects.learner_visible(profile.exam_goal).select_related('content')
    cards = with_saved_flags(cards, request.user)
    if content_id is not None:
        cards = cards.filter(content_id=content_id)
    requested_level = request.GET.get('level', '').upper()
    valid_levels = {value for value, _ in Flashcard.LEVELS}
    if requested_level in valid_levels:
        cards = cards.filter(cefr_level=requested_level)
    requested_topic = request.GET.get('topic', '').strip()
    available_topics = list(Flashcard.objects.learner_visible(profile.exam_goal).exclude(topic='').values_list('topic', flat=True).distinct().order_by('topic'))
    if requested_topic in available_topics:
        cards = cards.filter(topic=requested_topic)
    else:
        requested_topic = ''
    search_term = request.GET.get('q', '').strip()[:80]
    if search_term:
        cards = cards.filter(Q(term__icontains=search_term) | Q(meaning_vi__icontains=search_term) | Q(example_en__icontains=search_term))
    show_all = request.GET.get('all') == '1'
    if not show_all:
        not_due_ids = UserFlashcardState.objects.filter(user=request.user, due_at__gt=timezone.now()).values_list('flashcard_id', flat=True)
        cards = cards.exclude(id__in=not_due_ids)
    page = Paginator(cards, 20).get_page(request.GET.get('page'))
    attach_rating_return_urls(
        page, path=request.path, show_all=show_all,
        level=requested_level if requested_level in valid_levels else '',
        topic=requested_topic, query=search_term,
    )
    return render(request, 'learning/flashcards.html', {
        'cards': page, 'page_obj': page, 'card_count': cards.count(),
        'selected_level': requested_level if requested_level in valid_levels else '',
        'selected_topic': requested_topic, 'available_topics': available_topics,
        'search_term': search_term, 'show_all': show_all,
        'has_filters': bool(search_term or requested_topic or requested_level in valid_levels),
        'profile': profile,
        'cefr_levels': CEFR_LEVELS,
    })


@login_required
def review_flashcard(request, card_id):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    card = get_object_or_404(Flashcard.objects.learner_visible(profile.exam_goal), id=card_id)
    rating = request.POST.get('rating')
    if rating not in {'again', 'hard', 'known'}:
        return HttpResponseBadRequest('Invalid rating')
    expected_content_id = card.content_id
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=request.user.pk)
        get_object_or_404(LearningContent.objects.select_for_update(), pk=expected_content_id)
        card = get_object_or_404(Flashcard.objects.learner_visible(profile.exam_goal).select_for_update(),
            pk=card_id, content_id=expected_content_id)
        destination = flashcard_return_url(request, card)
        now = timezone.now()
        state, created = UserFlashcardState.objects.select_for_update().get_or_create(
            user=request.user, flashcard=card,
            defaults={'last_rating': rating, 'reviewed_at': now, 'due_at': now, 'review_count': 0},
        )
        if not created and rating == 'known' and state.due_at > now:
            messages.info(request, 'Thẻ này chưa đến hạn ôn. Bạn có thể xem lại thẻ; khoảng ôn sẽ tăng sau lượt ôn đến hạn.')
            return redirect(destination)
        scheduled = schedule_review(state, rating, now)
        for field, value in scheduled.items():
            setattr(state, field, value)
        state.save(update_fields=list(scheduled))
        FlashcardReview.objects.create(user=request.user, flashcard=card, rating=rating, due_at=state.due_at)
        pending_states = UserFlashcardState.objects.filter(user=request.user, due_at__gt=now).values_list('flashcard_id', flat=True)
        still_due = Flashcard.objects.learner_visible(profile.exam_goal).filter(
            content_id=card.content_id, cefr_level=card.cefr_level,
        ).exclude(id__in=pending_states).exists()
        if not still_due:
            StudyTask.objects.filter(
                user=request.user, content=card.content, cefr_level=card.cefr_level,
                scheduled_for=timezone.localdate(), status__in=['todo', 'in_progress'],
            ).update(status='done', completed_at=now)
    next_review = timezone.localtime(state.due_at).strftime('%H:%M %d/%m')
    messages.success(request, f'Đã lưu đánh giá “{card.term}”. Lịch ôn tiếp theo: {next_review}.')
    return redirect(destination)


@login_required
def practice_list(request):
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    content = LearningContent.objects.filter(is_published=True, review_status__in=LEARNER_REVIEW_STATUSES, exam_type=profile.exam_goal).filter(
        Q(content_type='reading', questions__isnull=False)
        | Q(content_type='listening', questions__isnull=False)
        | Q(content_type='vocabulary', questions__isnull=False)
    ).distinct().annotate(question_total=Count('questions', distinct=True))
    total_content = content.count()
    total_questions = Question.objects.filter(content__in=content).count()
    skill_choices = [('reading', 'Reading'), ('listening', 'Listening'), ('vocabulary', 'Từ vựng')]
    selected_skill = request.GET.get('skill', '')
    selected_mode = request.GET.get('mode', '')
    selected_level = request.GET.get('level', '').upper()
    search_term = request.GET.get('q', '').strip()[:100]
    if selected_skill in dict(skill_choices):
        content = content.filter(content_type=selected_skill)
    else:
        selected_skill = ''
    if selected_mode == 'meaning' and selected_skill in ('', 'vocabulary'):
        content = content.filter(
            Q(question_type='lp3000-v1-meaning') | Q(topic='Vocabulary practice')
            | Q(question_type__startswith='lp-workplace-v1-', question_type__endswith='-meaning')
        )
    elif selected_mode == 'cloze' and selected_skill in ('', 'vocabulary'):
        content = content.filter(
            Q(question_type='lp3000-v1-cloze')
            | Q(question_type__startswith='lp-workplace-v1-', question_type__endswith='-cloze')
        )
    else:
        selected_mode = ''
    if selected_level in dict(CEFR_LEVELS):
        content = content.filter(cefr_level=selected_level)
    else:
        selected_level = ''
    if search_term:
        content = content.filter(Q(title__icontains=search_term) | Q(topic__icontains=search_term))
    page = Paginator(content.order_by('skill', 'cefr_level', 'title', 'id'), 12).get_page(request.GET.get('page'))
    return render(request, 'learning/practice_list.html', {
        'content_list': page, 'total_content': total_content, 'total_questions': total_questions,
        'filtered_count': page.paginator.count, 'selected_skill': selected_skill,
        'selected_mode': selected_mode,
        'selected_level': selected_level, 'search_term': search_term,
        'cefr_levels': CEFR_LEVELS, 'skill_choices': skill_choices,
    })


@login_required
def practice(request, content_id):
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    content = get_object_or_404(LearningContent, id=content_id, is_published=True, review_status__in=LEARNER_REVIEW_STATUSES, exam_type=profile.exam_goal, content_type__in=['reading', 'listening', 'vocabulary'])
    question_ids = list(content.questions.values_list('id', flat=True))
    if not question_ids:
        messages.info(request, 'Bài này chưa có câu hỏi được xuất bản.')
        return redirect('learning:practice_list')
    if request.method == 'POST':
        try:
            attempt, _ = start_or_resume(request.user, content)
        except PracticeUnavailableError as exc:
            messages.error(request, str(exc))
            return redirect('learning:practice_list')
        StudyTask.objects.filter(user=request.user, content=content, scheduled_for=timezone.localdate(), status='todo').update(status='in_progress')
        return redirect('learning:take_attempt', attempt_id=attempt.id)
    active_attempt = PracticeAttempt.objects.filter(user=request.user, content=content, status='in_progress').annotate(draft_count=Count('draft_answers')).first()
    return render(request, 'learning/practice_start.html', {'content': content, 'question_count': len(question_ids), 'active_attempt': active_attempt})


@login_required
def take_attempt(request, attempt_id):
    attempt = get_object_or_404(PracticeAttempt, id=attempt_id, user=request.user, status='in_progress')
    questions = list(Question.objects.filter(content=attempt.content).prefetch_related('options').order_by('order', 'id'))
    if not _attempt_content_available(attempt, questions):
        return _abandon_changed_attempt(request, attempt)
    drafts = dict(attempt.draft_answers.values_list('question_id', 'selected_option_id'))
    for question in questions:
        question.selected_option_id = drafts.get(question.id)
    return render(request, 'learning/practice.html', {
        'content': attempt.content, 'questions': questions, 'attempt': attempt,
        'draft_count': len(drafts), 'has_draft': bool(drafts), 'last_saved_at': attempt.last_saved_at,
    })


@login_required
@require_POST
def save_draft(request, attempt_id):
    if len(request.body) > 65536:
        return JsonResponse({'error': 'Bản nháp quá lớn.'}, status=400)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or 'answers' not in payload:
            raise DraftValidationError('Thiếu danh sách lựa chọn cần lưu.')
        result = persist_draft(request.user, attempt_id, payload['answers'], payload.get('draft_revision', 0))
    except DraftConflictError as exc:
        return JsonResponse(exc.payload(), status=409)
    except (json.JSONDecodeError, UnicodeDecodeError, DraftValidationError) as exc:
        return JsonResponse({'error': str(exc) if isinstance(exc, DraftValidationError) else 'Dữ liệu nháp không hợp lệ.'}, status=400)
    except PracticeUnavailableError as exc:
        return JsonResponse({'ok': False, 'status': 'unavailable', 'error': str(exc)}, status=409)
    return JsonResponse(result)


@login_required
@require_POST
@transaction.atomic
def abandon_attempt(request, attempt_id):
    attempt = get_object_or_404(PracticeAttempt.objects.select_for_update(), id=attempt_id, user=request.user, status='in_progress')
    attempt.draft_answers.all().delete()
    attempt.status = 'abandoned'
    attempt.save(update_fields=['status'])
    messages.success(request, 'Đã dừng lượt làm và xóa bản nháp. Bạn có thể bắt đầu lại khi sẵn sàng.')
    return redirect('learning:practice_list')


def _attempt_content_available(attempt, questions):
    return (
        attempt.content.is_published
        and attempt.content.review_status in LEARNER_REVIEW_STATUSES
        and len(questions) == attempt.question_count == len(set(attempt.question_ids))
        and [question.id for question in questions] == attempt.question_ids
        and (not attempt.content_fingerprint or fingerprint_questions(questions) == attempt.content_fingerprint)
    )


def _abandon_changed_attempt(request, attempt):
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=request.user.pk)
        changed = PracticeAttempt.objects.filter(pk=attempt.pk, status='in_progress').update(status='abandoned')
        if not changed:
            attempt.refresh_from_db(fields=['status'])
            if attempt.status == 'submitted':
                return redirect('learning:attempt_result', attempt_id=attempt.pk)
        else:
            attempt.draft_answers.all().delete()
    messages.error(request, 'Học liệu đã thay đổi hoặc tạm ngừng xuất bản. Lượt này không được chấm; hãy chọn bài luyện hiện có.')
    return redirect('learning:practice_list')


@login_required
@transaction.atomic
def submit_attempt(request, attempt_id):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    nonkey_row_lock(get_user_model().objects.all()).get(pk=request.user.pk)
    attempt = get_object_or_404(PracticeAttempt.objects.select_for_update().select_related('content'), id=attempt_id, user=request.user)
    if attempt.status == 'submitted':
        return redirect('learning:attempt_result', attempt_id=attempt.id)
    if attempt.status != 'in_progress':
        raise Http404
    if len(request.POST.getlist('draft_revision')) > 1:
        return HttpResponseBadRequest('Duplicate draft revision')
    try:
        revision = parse_draft_revision(request.POST.get('draft_revision', '0'))
    except DraftValidationError as exc:
        return HttpResponseBadRequest(str(exc))
    # Lock mutable source rows before checking the fingerprint and freezing a
    # result. A concurrent teacher edit cannot change half a grading snapshot.
    attempt.content = LearningContent.objects.select_for_update().get(pk=attempt.content_id)
    list(Question.objects.select_for_update().filter(content_id=attempt.content_id).order_by('pk'))
    list(AnswerOption.objects.select_for_update().filter(question__content_id=attempt.content_id).order_by('pk'))
    questions = list(attempt.content.questions.prefetch_related('options').order_by('order', 'id'))
    if not _attempt_content_available(attempt, questions):
        return _abandon_changed_attempt(request, attempt)
    if revision != attempt.draft_revision:
        for question in questions:
            value = request.POST.get(f'question_{question.pk}', '')
            question.selected_option_id = int(value) if value.isascii() and value.isdecimal() and len(value) <= 18 else None
        return render(request, 'learning/practice.html', {
            'content': attempt.content, 'questions': questions, 'attempt': attempt,
            'draft_count': sum(question.selected_option_id is not None for question in questions), 'has_draft': bool(attempt.last_saved_at),
            'last_saved_at': attempt.last_saved_at, 'draft_conflict': True, 'draft_has_unsaved': True,
            'draft_error': str(DraftConflictError(attempt)),
        }, status=409)
    # Validate every ID before writing any answer. Arbitrary strings or oversized
    # integers must produce a client error rather than an ORM/SQLite exception.
    submitted_ids = {}
    draft_ids = dict(attempt.draft_answers.values_list('question_id', 'selected_option_id'))
    for question in questions:
        value = request.POST.get(f'question_{question.id}', str(draft_ids.get(question.id, '')))
        if value and (not value.isascii() or not value.isdecimal() or len(value) > 18):
            return HttpResponseBadRequest('Invalid answer option ID')
        submitted_ids[question.id] = int(value) if value else None
    options_by_id = {option.id: option for question in questions for option in question.options.all()}
    for question in questions:
        option_id = submitted_ids[question.id]
        if option_id is not None and (option_id not in options_by_id or options_by_id[option_id].question_id != question.id):
            return HttpResponseBadRequest('Answer option does not belong to the question')
    score = 0
    evidence_rows = []
    changed = PracticeAttempt.objects.filter(
        pk=attempt.pk, status='in_progress', draft_revision=revision,
    ).update(draft_revision=revision + 1)
    if not changed:
        # Row locks serialize PostgreSQL writers; CAS also protects databases
        # where a row lock is not available.
        return JsonResponse({'ok': False, 'status': 'conflict', 'error': 'Lượt làm đã thay đổi. Hãy tải lại trang.'}, status=409)
    attempt.draft_revision = revision + 1
    for question in questions:
        option_id = submitted_ids[question.id]
        option = options_by_id.get(option_id)
        correct = bool(option and option.is_correct)
        score += int(correct)
        evidence = answer_evidence(question, option, correct, attempt.content)
        evidence_rows.append(evidence)
        AttemptAnswer.objects.update_or_create(
        attempt=attempt, question=question,
            defaults={'selected_option': option, 'is_correct': correct, 'evidence_snapshot': evidence},
        )
    attempt.correct_count = score
    attempt.status = 'submitted'
    attempt.submitted_at = timezone.now()
    attempt.result_snapshot = {
        'version': 1, 'content_title': attempt.content.title, 'skill': attempt.content.skill,
        'answers': evidence_rows, 'correct_count': score, 'question_count': attempt.question_count,
        'submitted_at': attempt.submitted_at.isoformat(),
    }
    attempt.save(update_fields=['correct_count', 'status', 'submitted_at', 'result_snapshot'])
    attempt.draft_answers.all().delete()
    for wrong_answer in attempt.answers.filter(is_correct=False):
        ErrorNotebookEntry.objects.get_or_create(answer=wrong_answer)
    StudyTask.objects.filter(user=request.user, content=attempt.content, scheduled_for=timezone.localdate(), status__in=['todo', 'in_progress']).update(status='done', completed_at=attempt.submitted_at)
    return redirect('learning:attempt_result', attempt_id=attempt.id)


@login_required
def attempt_result(request, attempt_id):
    attempt = get_object_or_404(PracticeAttempt, id=attempt_id, user=request.user, status='submitted')
    snapshot = attempt.result_snapshot
    legacy = snapshot == {}
    unavailable = False
    if (isinstance(snapshot, dict) and snapshot.get('version') == 1
            and isinstance(snapshot.get('answers'), list)
            and len(snapshot['answers']) == attempt.question_count
            and all(valid_answer_evidence(answer) for answer in snapshot['answers'])):
        answers = snapshot['answers']
        result = snapshot
    elif legacy:
        rows = attempt.answers.select_related('question', 'selected_option', 'attempt__content').prefetch_related('question__options').order_by('question__order', 'question_id', 'pk')
        answers = [answer.evidence for answer in rows]
        result = {'content_title': attempt.content.title, 'skill': attempt.content.skill}
    else:
        # Corrupt new evidence must not silently become a reconstruction.
        answers = []
        result = {'content_title': 'Kết quả luyện tập', 'skill': ''}
        unavailable = True
    return render(request, 'learning/result.html', {
        'attempt': attempt, 'answers': answers, 'result': result,
        'legacy_result': legacy, 'result_unavailable': unavailable,
        'error_count': sum(not answer['is_correct'] for answer in answers),
    })


def _notebook_entries(user, exam):
    """Visible, ownership-consistent mistake history for the selected exam."""
    return ErrorNotebookEntry.objects.filter(
        answer__attempt__user=user, answer__attempt__status='submitted',
        answer__is_correct=False, answer__attempt__content__exam_type=exam,
        answer__question__content__exam_type=exam,
        answer__question__content_id=F('answer__attempt__content_id'),
        answer__question__content__is_published=True,
        answer__question__content__review_status__in=LEARNER_REVIEW_STATUSES,
    )


@login_required
@require_GET
def mistake_notebook(request):
    from .mistake_review import count_eligible_mistakes
    from .models import MistakeReviewSession
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    all_entries = _notebook_entries(request.user, profile.exam_goal)
    entries = all_entries.select_related(
        'answer__attempt__content', 'answer__question__content', 'answer__selected_option',
    ).prefetch_related('answer__question__options').order_by('-created_at', '-id')
    state = request.GET.get('state', 'new')
    if state == 'reviewed':
        entries = entries.filter(reviewed_at__isnull=False)
    elif state != 'all':
        state = 'new'
        entries = entries.filter(reviewed_at__isnull=True)
    category = request.GET.get('category', '')
    valid_categories = {value for value, _ in ErrorNotebookEntry.CATEGORIES}
    if category in valid_categories:
        entries = entries.filter(category=category)
    else:
        category = ''
    page = Paginator(entries, 20).get_page(request.GET.get('page'))
    sessions = MistakeReviewSession.objects.filter(user=request.user, exam_type=profile.exam_goal)
    return render(request, 'learning/mistake_notebook.html', {
        'entries': page, 'page_obj': page, 'state': state, 'category': category,
        'categories': ErrorNotebookEntry.CATEGORIES,
        'new_count': all_entries.filter(reviewed_at__isnull=True).count(),
        'total_count': all_entries.count(),
        'retry_count': count_eligible_mistakes(request.user, profile.exam_goal, category or None),
        'active_review': sessions.filter(status='in_progress').first(),
        'recent_reviews': sessions.filter(status='submitted').order_by('-submitted_at', '-id')[:3],
    })


@login_required
def update_mistake_entry(request, entry_id):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    entry = get_object_or_404(
        _notebook_entries(request.user, LearnerProfile.objects.get_or_create(user=request.user)[0].exam_goal),
        id=entry_id,
    )
    category = request.POST.get('category', 'other')
    valid_categories = {value for value, _ in ErrorNotebookEntry.CATEGORIES}
    note = request.POST.get('learner_note', '').strip()
    if category not in valid_categories or len(note) > 1000:
        return HttpResponseBadRequest('Invalid category or note length')
    entry.category = category
    entry.learner_note = note
    action = request.POST.get('review_action', 'mark_reviewed' if request.POST.get('reviewed') == 'yes' else 'save')
    if action not in {'save', 'mark_reviewed', 'reopen'}:
        return HttpResponseBadRequest('Invalid review action')
    if action == 'mark_reviewed':
        entry.reviewed_at = timezone.now()
        message = 'Đã đánh dấu câu sai là đã ôn lại.'
    elif action == 'reopen':
        entry.reviewed_at = None
        message = 'Đã chuyển câu này về mục cần ôn.'
    else:
        message = 'Đã lưu ghi chú và loại lỗi.'
    entry.save(update_fields=['category', 'learner_note', 'reviewed_at'])
    messages.success(request, message)
    return redirect('learning:mistake_notebook')


def _get_review_session(request, session_id):
    from .models import MistakeReviewSession
    if session_id < 1 or session_id > 2**63 - 1:
        raise Http404
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    return get_object_or_404(
        MistakeReviewSession, pk=session_id, user=request.user, exam_type=profile.exam_goal,
    )


@login_required
@require_POST
def start_mistake_review(request):
    from .mistake_review import (
        MistakeReviewInputError, NoMistakesAvailable, start_or_resume_mistake_review,
    )
    profile, _ = LearnerProfile.objects.get_or_create(user=request.user)
    try:
        session, created = start_or_resume_mistake_review(
            request.user, profile.exam_goal, request.POST.get('category') or None,
        )
    except MistakeReviewInputError as exc:
        return HttpResponseBadRequest(str(exc))
    except NoMistakesAvailable:
        messages.info(request, 'Chưa có câu sai phù hợp để làm lại. Bài nghe cần có file audio và học liệu phải đang được xuất bản.')
        return redirect('learning:mistake_notebook')
    if not created:
        messages.info(request, 'Đã mở lượt ôn đang làm và khôi phục các lựa chọn đã lưu trên tài khoản của bạn.')
    return redirect('learning:take_mistake_review', session_id=session.pk)


@login_required
@require_GET
def take_mistake_review(request, session_id):
    from .mistake_review import MistakeReviewUnavailable, get_mistake_review_questions
    session = _get_review_session(request, session_id)
    if session.status == 'submitted':
        return redirect('learning:mistake_review_result', session_id=session.pk)
    if session.status != 'in_progress':
        messages.info(request, 'Lượt ôn này đã dừng. Bạn có thể tạo lượt mới từ Sổ lỗi.')
        return redirect('learning:mistake_notebook')
    try:
        questions, revision, saved_at = get_mistake_review_questions(request.user, session.pk, include_revision=True)
    except MistakeReviewUnavailable:
        messages.warning(request, 'Học liệu hoặc nguồn câu sai đã thay đổi; lượt ôn đã dừng và chưa chấm điểm.')
        return redirect('learning:mistake_notebook')
    session.draft_revision, session.last_saved_at = revision, saved_at
    return render(request, 'learning/mistake_review.html', {
        'review_session': session, 'questions': questions, 'question_count': len(questions),
        'draft_count': sum(question['selected_option_id'] is not None for question in questions),
        'has_draft': bool(session.last_saved_at), 'last_saved_at': session.last_saved_at,
    })


@login_required
@require_POST
def save_mistake_review_draft(request, session_id):
    from .mistake_review import (
        MistakeReviewInputError, MistakeReviewUnavailable,
        save_mistake_review_draft as persist_review_draft,
    )
    session = _get_review_session(request, session_id)
    if len(request.body) > 16384:
        return JsonResponse({'error': 'Bản nháp quá lớn.'}, status=400)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or 'answers' not in payload:
            raise MistakeReviewInputError('Thiếu danh sách lựa chọn cần lưu.')
        result = persist_review_draft(request.user, session.pk, payload['answers'], payload.get('draft_revision', 0))
    except DraftConflictError as exc:
        return JsonResponse(exc.payload(), status=409)
    except DraftValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Dữ liệu nháp không hợp lệ.'}, status=400)
    except MistakeReviewInputError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except MistakeReviewUnavailable as exc:
        return JsonResponse({'ok': False, 'status': 'unavailable', 'error': str(exc)}, status=409)
    return JsonResponse(result)


@login_required
@require_POST
def submit_mistake_review(request, session_id):
    from .mistake_review import MistakeReviewInputError, MistakeReviewUnavailable, get_mistake_review_questions, submit_mistake_review as grade_review
    session = _get_review_session(request, session_id)
    if session.status == 'submitted':
        return redirect('learning:mistake_review_result', session_id=session.pk)
    if len(request.POST.getlist('draft_revision')) > 1:
        return HttpResponseBadRequest('Duplicate draft revision')
    answers = {}
    for key in request.POST:
        if key.startswith('question_'):
            values = request.POST.getlist(key)
            if len(values) != 1:
                return HttpResponseBadRequest('Duplicate answer field')
            if values[0]:
                answers[key[len('question_'):]] = values[0]
    try:
        grade_review(request.user, session.pk, answers, request.POST.get('draft_revision', '0'))
    except DraftConflictError as exc:
        try:
            questions, current_revision, saved_at = get_mistake_review_questions(request.user, session.pk, include_revision=True)
        except MistakeReviewUnavailable:
            return redirect('learning:mistake_notebook')
        session.draft_revision, session.last_saved_at = current_revision, saved_at
        for question in questions:
            value = answers.get(str(question['id']), '')
            question['selected_option_id'] = int(value) if value.isascii() and value.isdecimal() and len(value) <= 18 else None
        return render(request, 'learning/mistake_review.html', {
            'review_session': session, 'questions': questions, 'question_count': len(questions),
            'draft_count': sum(question['selected_option_id'] is not None for question in questions),
            'has_draft': bool(saved_at), 'last_saved_at': saved_at,
            'draft_conflict': True, 'draft_has_unsaved': True, 'draft_error': str(exc),
        }, status=409)
    except (MistakeReviewInputError, DraftValidationError) as exc:
        return HttpResponseBadRequest(str(exc))
    except MistakeReviewUnavailable:
        messages.warning(request, 'Lượt ôn không còn hợp lệ hoặc học liệu đã thay đổi. Không chấm lại nội dung mới.')
        return redirect('learning:mistake_notebook')
    return redirect('learning:mistake_review_result', session_id=session.pk)


@login_required
@require_GET
def mistake_review_result(request, session_id):
    from .mistake_review import MistakeReviewUnavailable, get_mistake_review_result
    session = _get_review_session(request, session_id)
    try:
        result = get_mistake_review_result(request.user, session.pk)
    except MistakeReviewUnavailable:
        messages.warning(request, 'Không thể mở kết quả đã lưu của lượt ôn này.')
        return redirect('learning:mistake_notebook')
    return render(request, 'learning/mistake_review_result.html', {'review_session': session, 'result': result})


@login_required
@require_POST
def abandon_mistake_review(request, session_id):
    from .mistake_review import abandon_mistake_review as stop_review
    session = _get_review_session(request, session_id)
    stopped = stop_review(request.user, session.pk)
    if stopped:
        messages.info(request, 'Đã dừng lượt ôn. Các câu sai vẫn được giữ trong Sổ lỗi.')
    return redirect('learning:mistake_notebook')
