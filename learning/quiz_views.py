"""Vocabulary challenges with server grading and immutable answer snapshots."""
from datetime import timedelta
from copy import deepcopy
import random
import re

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from planner.models import LearnerProfile
from .models import CEFR_LEVELS, LEARNER_REVIEW_STATUSES, Flashcard, VocabularyQuizDailyReward, VocabularyQuizSession
from .gamification import get_learning_rewards
from .saved_words import visible_saved_words, visible_cards, with_saved_flags
from .quiz_weak_words import weak_word_summary
from .quiz_history import submitted_quizzes
from .quiz_answers import quiz_answer_is_valid, quiz_answer_is_correct, normalize_recall_answer, recall_hint, MAX_RECALL_LENGTH
from .quiz_recall import RecallPromptIndex
from .quiz_due import due_states, selection_metadata, selection_is_current, record_due_observations, lock_due_cards
from .locking import nonkey_row_lock

_rng = random.SystemRandom()
_MEANING_STOPWORDS = {'sự', 'việc', 'một', 'các', 'để', 'trong', 'người', 'của', 'và', 'là', 'ở', 'có', 'cho', 'với', 'được', 'bị'}


def _meaning_tokens(text):
    return set(re.findall(r'[^\W_]+', text.casefold())) - _MEANING_STOPWORDS


def _too_similar(left, right):
    a, b = _meaning_tokens(left), _meaning_tokens(right)
    return bool(a and b and len(a & b) / min(len(a), len(b)) >= 0.6)


def _stored_draft(quiz):
    stored = quiz.draft_answers if isinstance(quiz.draft_answers, dict) else {}
    return {str(q['number']): stored[str(q['number'])] for q in quiz.snapshot if quiz_answer_is_valid(q, stored.get(str(q['number'])), quiz.mode)}


def _play_context(quiz, answers=None, error='', conflict=False):
    saved = _stored_draft(quiz)
    answers = saved if answers is None else answers
    safe_quiz = {
        'pk': quiz.pk, 'id': quiz.pk, 'question_count': quiz.question_count,
        'cefr_level': quiz.cefr_level, 'topic': quiz.topic, 'started_at': quiz.started_at,
        'draft_revision': quiz.draft_revision, 'last_saved_at': quiz.last_saved_at,
        'saved_count': len(saved), 'is_retry': quiz.is_retry, 'parent_quiz_id': quiz.parent_quiz_id,
        'vocabulary_source': quiz.vocabulary_source,
        'mode': quiz.mode,
    }
    safe_questions = []
    for question in quiz.snapshot:
        if quiz.mode == 'recall':
            safe = {key: question[key] for key in ('number', 'part_of_speech', 'cefr_level', 'meaning_vi')}
            safe['recall_hint'] = recall_hint(question)
            safe['selected_answer'] = answers.get(str(question['number']), '')
        else:
            safe = {key: question[key] for key in ('number', 'term', 'part_of_speech', 'cefr_level', 'example_en', 'options')}
            safe['selected_key'] = answers.get(str(question['number']), '')
        safe_questions.append(safe)
    return {
        'quiz': safe_quiz, 'questions': safe_questions, 'quiz_error': error,
        'quiz_conflict': conflict, 'quiz_has_unsaved': answers != saved,
    }


def _revision(post, required=False):
    fields = [key for key in ('revision', 'draft_revision') if key in post]
    if not fields:
        if required:
            raise ValueError('Thiếu phiên bản bản nháp. Hãy tải lại trang.')
        return None
    values = [post.getlist(key) for key in fields]
    if any(len(value) != 1 or not re.fullmatch(r'[0-9]{1,10}', value[0]) for value in values):
        raise ValueError('Phiên bản bản nháp không hợp lệ.')
    revisions = {int(value[0]) for value in values}
    if len(revisions) != 1 or next(iter(revisions)) > 2147483647:
        raise ValueError('Phiên bản bản nháp không hợp lệ.')
    return next(iter(revisions))


def _posted_answers(quiz, post, require_complete=False):
    expected = {f'answer_{question["number"]}' for question in quiz.snapshot}
    if any(key.startswith('answer_') and key not in expected for key in post):
        raise ValueError('Câu trả lời không thuộc lượt quiz này.')
    answers = {}
    for question in quiz.snapshot:
        field = f'answer_{question["number"]}'
        values = post.getlist(field)
        if not values and not require_complete:
            continue
        if quiz.mode == 'recall' and len(values) == 1 and len(values[0]) <= MAX_RECALL_LENGTH and not normalize_recall_answer(values[0]) and not require_complete:
            continue
        if len(values) != 1 or not quiz_answer_is_valid(question, values[0], quiz.mode):
            raise ValueError('Hãy nhập một câu trả lời cho mỗi câu (tối đa 240 ký tự).' if quiz.mode == 'recall' else ('Hãy chọn đúng một đáp án hợp lệ cho mỗi câu trước khi nộp.' if require_complete else 'Phương án bản nháp không hợp lệ.'))
        answers[str(question['number'])] = values[0]
    return answers


def _restore_posted(quiz, post):
    return {str(q['number']): post.get(f'answer_{q["number"]}', '') for q in quiz.snapshot if quiz_answer_is_valid(q, post.get(f'answer_{q["number"]}', ''), quiz.mode)}


def _draft_response(quiz, status='saved', http_status=200, message=''):
    return JsonResponse({
        'ok': http_status == 200, 'status': status, 'revision': quiz.draft_revision,
        'saved_count': quiz.saved_count,
        'last_saved_at': quiz.last_saved_at.isoformat() if quiz.last_saved_at else None,
        **({'message': message} if message else {}),
    }, status=http_status)


def _exam(user):
    profile, _ = LearnerProfile.objects.get_or_create(user=user)
    return profile.exam_goal


def _cards(user):
    return Flashcard.objects.filter(is_available=True,
        content__exam_type=_exam(user), content__content_type='vocabulary',
        content__is_published=True, content__review_status__in=LEARNER_REVIEW_STATUSES,
    ).exclude(term='').exclude(meaning_vi='')


def _available(quiz, recall_index=None):
    ids = {q['card_id'] for q in quiz.snapshot}
    if len(ids) != quiz.question_count:
        return False
    if quiz.mode == 'recall':
        if recall_index is None or recall_index.exam_type != quiz.exam_type:
            # This index is loaded from current available cards; its visible
            # IDs already perform the availability check in the same query.
            recall_index = RecallPromptIndex.for_exam(quiz.exam_type)
        elif Flashcard.objects.learner_visible(quiz.exam_type).filter(
                pk__in=ids, content__content_type='vocabulary').count() != len(ids):
            # A supplied index may predate an editorial hold.
            return False
        snapshot_prompts = RecallPromptIndex(quiz.snapshot)
        if any(recall_index.ambiguous(q) or snapshot_prompts.ambiguous(q) for q in quiz.snapshot):
            quiz.recall_ambiguous = True
            return False
        if not all(recall_index.allows(question) for question in quiz.snapshot):
            return False
        return len(ids) == quiz.question_count and ids <= recall_index.visible_ids
    return Flashcard.objects.learner_visible(quiz.exam_type).filter(
        pk__in=ids, content__content_type='vocabulary').count() == len(ids)


def _expire_unavailable(quiz, recall_index=None):
    if quiz.status == 'in_progress' and (quiz.started_at < timezone.now() - timedelta(days=1) or not _available(quiz, recall_index)):
        VocabularyQuizSession.objects.filter(pk=quiz.pk, status='in_progress').update(status='abandoned')
        return True
    return quiz.status == 'abandoned'


def active_quiz_for_user(user, exam_type=None, recall_index=None):
    active = VocabularyQuizSession.objects.filter(user=user, status='in_progress').first()
    if active and _expire_unavailable(active, recall_index):
        return None
    if active and exam_type and active.exam_type != exam_type:
        return None
    return active


def _unavailable_message(quiz):
    if getattr(quiz, 'recall_ambiguous', False):
        return 'Lượt gõ từ đã dừng vì một gợi ý hiện khớp với nhiều từ tiếng Anh. Lượt này không được chấm hoặc cộng XP. Hãy chuyển sang Chọn nghĩa hoặc bắt đầu lượt mới.'
    return 'Lượt quiz đã hết hạn hoặc học liệu không còn khả dụng. Hãy mở trang Quiz để bắt đầu lượt mới.'


@login_required
@require_GET
@never_cache
def quiz_hub(request):
    cards = _cards(request.user)
    source = request.GET.get('source', 'all')
    source = source if source in ('all', 'saved', 'weak', 'due') else 'all'
    mode = 'recall' if source == 'due' or request.GET.get('mode') == 'recall' else 'meaning'
    raw_count = request.GET.get('count', '10')
    count = int(raw_count) if raw_count in ('5', '10', '15') else 10
    bank = list(with_saved_flags(cards, request.user)) if mode == 'recall' else None
    recall_index = RecallPromptIndex(bank, _exam(request.user)) if bank is not None else None
    personal_cards = visible_saved_words(request.user)
    weak_summary = weak_word_summary(request.user, visible_bank=bank, recall_index=recall_index)
    due_ids = set(due_states(request.user, _exam(request.user)).values_list('flashcard_id', flat=True))
    if source == 'saved':
        cards = cards.filter(pk__in=personal_cards.values('pk'))
    elif source == 'weak':
        cards = cards.filter(pk__in=[word['card'].pk for word in weak_summary['words']])
    elif source == 'due':
        cards = cards.filter(pk__in=due_ids)
    if recall_index is not None:
        cards = cards.filter(pk__in=recall_index.eligible_ids)
    active = active_quiz_for_user(request.user, recall_index=recall_index)
    return render(request, 'learning/quiz_hub.html', {
        'levels': [key for key, _ in CEFR_LEVELS],
        'topics': list(cards.exclude(topic='').values_list('topic', flat=True).distinct().order_by('topic')),
        'available_count': cards.count(),
        'selected_source': source, 'saved_word_count': personal_cards.count(),
        'due_word_count': len(due_ids & recall_index.eligible_ids) if recall_index is not None else len(due_ids),
        'weak_word_count': weak_summary['count'], 'weak_words_ready': weak_summary.get('ready', True),
        'selected_level': request.GET.get('level', ''), 'selected_topic': request.GET.get('topic', ''),
        'selected_mode': mode, 'selected_count': count,
        'recent_quizzes': submitted_quizzes(request.user, _exam(request.user)).defer('snapshot', 'answers', 'draft_answers')[:5],
        'active_quiz': active, 'rewards': get_learning_rewards(request.user),
    })


@login_required
@require_POST
@never_cache
def quiz_start(request):
    mode = request.POST.get('mode', 'meaning')
    source = request.POST.get('source', 'all')
    level = request.POST.get('level', '').strip()
    topic = request.POST.get('topic', '').strip()
    raw_count = request.POST.get('count', '10')
    if mode not in ('meaning', 'recall') or len(request.POST.getlist('mode')) > 1 or source not in ('all', 'saved', 'weak', 'due') or len(request.POST.getlist('source')) > 1 or level not in ['', *(key for key, _ in CEFR_LEVELS)] or raw_count not in ('5', '10', '15') or len(topic) > 80:
        return HttpResponseBadRequest('Bộ lọc quiz không hợp lệ.')
    if source == 'due' and mode != 'recall':
        return HttpResponseBadRequest('Nguồn đến lịch ôn yêu cầu cách luyện Gõ từ.')
    replace_id = request.POST.get('replace_quiz', '')
    if replace_id and (len(request.POST.getlist('replace_quiz')) != 1 or
                       not re.fullmatch(r'[1-9][0-9]{0,18}', replace_id)):
        return HttpResponseBadRequest('Lượt quiz cần thay thế không hợp lệ.')
    active = VocabularyQuizSession.objects.filter(user=request.user, status='in_progress').first()
    if active and _expire_unavailable(active):
        active = None
    if replace_id:
        if not active or active.pk != int(replace_id):
            messages.warning(request, 'Lượt quiz đang làm đã thay đổi. Hãy kiểm tra lại trước khi tạo bài mới.')
            return redirect('learning:quiz_hub')
        if request.POST.get('confirm_replace') != 'yes':
            return render(request, 'learning/quiz_replace_confirm.html', {
                'quiz': active, 'mode': mode, 'source': source, 'level': level,
                'topic': topic, 'count': raw_count,
            })
        revision = request.POST.get('replace_revision', '')
        if len(request.POST.getlist('replace_revision')) != 1 or not re.fullmatch(r'[0-9]{1,10}', revision):
            return HttpResponseBadRequest('Phiên bản quiz không hợp lệ.')
    elif active:
        messages.info(request, 'Tiếp tục lượt quiz đang làm trước khi bắt đầu lượt mới.')
        return redirect('learning:quiz_take', quiz_id=active.pk)
    fields = ('id', 'content_id', 'term', 'meaning_vi', 'part_of_speech', 'cefr_level', 'topic',
              'example_en', 'example_vi', 'source_url')
    bank = list(with_saved_flags(_cards(request.user).order_by('pk'), request.user)) if mode == 'recall' else None
    all_cards = ([{field: getattr(card, field) for field in fields} for card in bank] if bank is not None else
                 list(_cards(request.user).order_by('pk').values(*fields)))
    recall_index = RecallPromptIndex(all_cards, _exam(request.user)) if mode == 'recall' else None
    meanings, term_meanings = {}, {}
    if mode == 'meaning':
        for card in all_cards:
            normalized = ' '.join(card['meaning_vi'].casefold().split())
            if normalized:
                meanings.setdefault(normalized, card['meaning_vi'].strip())
                term_meanings.setdefault(card['term'].strip().casefold(), set()).add(normalized)
    source_ids = None
    selected_at = timezone.now()
    selected_states = {}
    if source == 'due':
        selected_states = {state.flashcard_id: state for state in due_states(request.user, _exam(request.user), selected_at)}
        source_ids = set(selected_states)
    elif source == 'saved':
        source_ids = ({card.pk for card in bank if card.is_saved} if bank is not None else
                      set(visible_saved_words(request.user).values_list('pk', flat=True)))
    elif source == 'weak':
        weak_summary = weak_word_summary(request.user, visible_bank=bank, recall_index=recall_index)
        if not weak_summary.get('ready', True):
            messages.info(request, 'Danh sách từ cần ôn đang chờ đồng bộ. Bạn vẫn có thể luyện từ thư viện.')
            return redirect('learning:weak_words')
        source_ids = {word['card'].pk for word in weak_summary['words']}
    pool = [card for card in all_cards if (source_ids is None or card['id'] in source_ids) and (not level or card['cefr_level'] == level) and (not topic or card['topic'] == topic)]
    _rng.shuffle(pool)
    questions, seen_terms = [], set()
    for card in pool:
        term_key = normalize_recall_answer(card['term']) if mode == 'recall' else card['term'].strip().casefold()
        meaning_key = ' '.join(card['meaning_vi'].casefold().split())
        if not term_key or term_key in seen_terms or not meaning_key:
            continue
        if recall_index is not None and not recall_index.allows(card):
            continue
        options = []
        if mode == 'meaning':
            same_term_meanings = term_meanings[term_key]
            distractors = [value for key, value in meanings.items() if key not in same_term_meanings and not any(_too_similar(value, meaning) for meaning in same_term_meanings)]
            if len(distractors) < 3:
                continue
            choices = [card['meaning_vi'].strip(), *_rng.sample(distractors, 3)]
            _rng.shuffle(choices)
            options = [{'key': chr(65 + index), 'label': chr(65 + index), 'text': text} for index, text in enumerate(choices)]
        questions.append({
            'number': len(questions) + 1, 'card_id': card['id'], 'term': card['term'],
            'part_of_speech': card['part_of_speech'], 'cefr_level': card['cefr_level'],
            'meaning_vi': card['meaning_vi'], 'example_en': card['example_en'], 'example_vi': card['example_vi'],
            'source_url': card['source_url'], 'options': options,
            'correct_key': next((option['key'] for option in options if option['text'] == card['meaning_vi'].strip()), ''),
        })
        if source == 'due':
            questions[-1]['due_check'] = selection_metadata(selected_states[card['id']], card, selected_at)
        seen_terms.add(term_key)
        if len(questions) == int(raw_count):
            break
    if len(questions) < (1 if source in ('weak', 'due') else 5):
        if source == 'due':
            message = 'Chưa có từ đến lịch ôn đủ điều kiện gõ. Cần lần tự đánh giá cách ít nhất 24 giờ, gợi ý rõ và chưa dùng mốc đó trong quiz đến lịch ôn.'
        elif mode == 'recall':
            message = 'Chưa đủ từ có gợi ý rõ để gõ: gợi ý trùng với nhiều từ hoặc chứa sẵn đáp án sẽ được bỏ qua. Hãy đổi bộ lọc hoặc chuyển sang Chọn nghĩa.'
        else:
            message = 'Chưa có từ cần ôn phù hợp với đủ phương án khác nghĩa. Hãy chọn bộ lọc khác hoặc làm quiz để tìm từ cần luyện.' if source == 'weak' else 'Cần ít nhất 5 từ phù hợp và bốn nghĩa khác nhau để tạo quiz. Hãy chọn chủ đề hoặc cấp độ khác.'
        messages.warning(request, message)
        query = ([f'source={source}'] if source in ('saved', 'weak', 'due') else []) + (['mode=recall'] if mode == 'recall' else [])
        return redirect(reverse('learning:quiz_hub') + ('?' + '&'.join(query) if query else ''))
    try:
        with transaction.atomic():
            if replace_id or source == 'due':
                nonkey_row_lock(get_user_model().objects.all()).get(pk=request.user.pk)
            if replace_id:
                current = VocabularyQuizSession.objects.select_for_update().filter(
                    pk=int(replace_id), user=request.user, status='in_progress').first()
                if not current or current.draft_revision != int(revision):
                    messages.warning(request, 'Quiz đang làm đã thay đổi. Hãy kiểm tra lại trước khi tạo bài mới.')
                    return redirect('learning:quiz_hub')
            if source == 'due':
                if not selection_is_current(request.user, _exam(request.user), questions):
                    messages.info(request, 'Lịch ôn hoặc nguồn vừa thay đổi ở một tab khác. Hãy chọn lại từ đến lịch ôn.')
                    return redirect(reverse('learning:quiz_hub') + '?source=due&mode=recall')
            if source != 'due':
                # Use the same parent/card lock order as source editors. Validate
                # the prepared snapshot before changing the learner's old quiz.
                locked = lock_due_cards(questions)
                selected = {card['id']: card for card in all_cards if card['id'] in locked}
                visible_ids = set(_cards(request.user).filter(pk__in=locked).values_list('pk', flat=True))
                unchanged = all(
                    q['card_id'] in visible_ids and q['card_id'] in selected
                    and all(getattr(locked[q['card_id']], field) == selected[q['card_id']][field]
                            for field in fields)
                    for q in questions
                )
                prepared = VocabularyQuizSession(exam_type=_exam(request.user), mode=mode,
                                                 question_count=len(questions), snapshot=questions)
                if not unchanged or not _available(prepared):
                    messages.warning(request, 'Học liệu vừa thay đổi. Bài đang làm được giữ lại; hãy chọn lại quiz mới.')
                    return redirect('learning:quiz_hub')
            if replace_id:
                current.status = 'abandoned'
                current.save(update_fields=['status'])
            quiz = VocabularyQuizSession.objects.create(user=request.user, exam_type=_exam(request.user), cefr_level=level, topic=topic, vocabulary_source=source, mode=mode, is_retry=source == 'weak', question_count=len(questions), snapshot=questions)
    except IntegrityError:
        quiz = VocabularyQuizSession.objects.filter(user=request.user, status='in_progress').first()
        if quiz is None:
            messages.info(request, 'Lượt quiz đã thay đổi ở một tab khác. Hãy chọn lại thử thách.')
            return redirect('learning:quiz_hub')
    if len(questions) < int(raw_count):
        messages.info(request, f'Bộ lọc hiện có {len(questions)} từ phù hợp; quiz sử dụng tất cả các từ này.')
    return redirect('learning:quiz_take', quiz_id=quiz.pk)


@login_required
@require_GET
@never_cache
def quiz_take(request, quiz_id):
    quiz = get_object_or_404(VocabularyQuizSession, pk=quiz_id, user=request.user)
    if quiz.status == 'submitted':
        return redirect('learning:quiz_result', quiz_id=quiz.pk)
    if _expire_unavailable(quiz):
        messages.warning(request, _unavailable_message(quiz))
        return redirect('learning:quiz_hub')
    # Explicit allowlist: the model and answer-bearing snapshot never enter this context.
    return render(request, 'learning/quiz_play.html', _play_context(quiz))


@login_required
@require_POST
@never_cache
def quiz_submit(request, quiz_id):
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=request.user.pk)
        quiz = get_object_or_404(VocabularyQuizSession.objects.select_for_update(), pk=quiz_id, user=request.user)
        if quiz.status == 'submitted':
            return redirect('learning:quiz_result', quiz_id=quiz.pk)
        due_cards = lock_due_cards(quiz.snapshot) if quiz.vocabulary_source == 'due' else None
        if due_cards is not None and set(due_cards) != {q['card_id'] for q in quiz.snapshot}:
            VocabularyQuizSession.objects.filter(pk=quiz.pk, status='in_progress').update(status='abandoned')
            return HttpResponse(_unavailable_message(quiz), status=410)
        if _expire_unavailable(quiz):
            return HttpResponse(_unavailable_message(quiz), status=410)
        try:
            revision = _revision(request.POST)
            answers = _posted_answers(quiz, request.POST, require_complete=True)
        except ValueError as exc:
            return render(request, 'learning/quiz_play.html', _play_context(quiz, _restore_posted(quiz, request.POST), str(exc)), status=400)
        if revision is not None and revision != quiz.draft_revision:
            return render(request, 'learning/quiz_play.html', _play_context(quiz, answers, 'Bản nháp đã thay đổi ở tab khác. Hãy tải lại trang để xem bản đã lưu trước khi nộp.', conflict=True), status=409)
        correct = sum(quiz_answer_is_correct(question, answers[str(question['number'])], quiz.mode) for question in quiz.snapshot)
        now = timezone.now()
        quiz.status, quiz.answers, quiz.correct_count, quiz.submitted_at = 'submitted', answers, correct, now
        quiz.xp_earned = 0
        if not quiz.is_retry:
            reward, created = VocabularyQuizDailyReward.objects.get_or_create(
                user=request.user, day=timezone.localdate(now),
                defaults={'quiz': quiz, 'xp': 20 + correct * 2},
            )
            quiz.xp_earned = reward.xp if created else 0
        quiz.save(update_fields=['status', 'answers', 'correct_count', 'submitted_at', 'xp_earned'])
        record_due_observations(quiz, locked_cards=due_cards)
    return redirect('learning:quiz_result', quiz_id=quiz.pk)


@login_required
@require_GET
@never_cache
def quiz_result(request, quiz_id):
    quiz = get_object_or_404(VocabularyQuizSession, pk=quiz_id, user=request.user)
    if quiz.status != 'submitted':
        return redirect('learning:quiz_take', quiz_id=quiz.pk)
    results = []
    saveable = {card.pk: card for card in with_saved_flags(visible_cards(request.user).filter(pk__in=[q['card_id'] for q in quiz.snapshot]), request.user)}
    for question in quiz.snapshot:
        chosen = quiz.answers.get(str(question['number']), '')
        options = {option['key']: option['text'] for option in question['options']}
        current_card = saveable.get(question['card_id'])
        can_save = bool(current_card and current_card.term.strip() == question['term'].strip() and current_card.meaning_vi.strip() == question['meaning_vi'].strip())
        results.append({
            key: question[key] for key in ('number', 'term', 'meaning_vi', 'example_en', 'example_vi', 'cefr_level', 'source_url')
        } | {'selected_text': chosen if quiz.mode == 'recall' else options.get(chosen, 'Chưa trả lời'), 'correct_text': question['term'] if quiz.mode == 'recall' else options[question['correct_key']], 'is_correct': quiz_answer_is_correct(question, chosen, quiz.mode), 'card_id': question['card_id'], 'can_save': can_save, 'is_saved': current_card.is_saved if can_save else False})
    missed_count = sum(not result['is_correct'] for result in results)
    return render(request, 'learning/quiz_result.html', {
        'quiz': quiz, 'results': results, 'rewards': get_learning_rewards(request.user),
        'missed_count': missed_count, 'retry_available_count': len(_retry_candidates(quiz)),
        'original_parent': quiz.parent_quiz,
        'due_observations': list(quiz.due_observations.order_by('card_id')) if quiz.vocabulary_source == 'due' and not quiz.is_retry else [],
    })


@login_required
@require_POST
@never_cache
def quiz_abandon(request, quiz_id):
    quiz = get_object_or_404(VocabularyQuizSession, pk=quiz_id, user=request.user)
    changed = VocabularyQuizSession.objects.filter(pk=quiz.pk, user=request.user, status='in_progress').update(status='abandoned')
    if changed:
        messages.info(request, 'Đã dừng lượt quiz. Bạn có thể chọn một thử thách mới.')
    return redirect('learning:quiz_hub')


@login_required
@require_POST
@never_cache
def quiz_draft(request, quiz_id):
    with transaction.atomic():
        quiz = get_object_or_404(VocabularyQuizSession.objects.select_for_update(), pk=quiz_id, user=request.user)
        if quiz.status == 'submitted':
            return _draft_response(quiz, 'submitted', 409, 'Lượt quiz đã nộp; bản nháp không thể thay đổi.')
        if _expire_unavailable(quiz):
            return _draft_response(quiz, 'unavailable', 410, _unavailable_message(quiz))
        try:
            revision = _revision(request.POST, required=True)
            answers = _posted_answers(quiz, request.POST)
        except ValueError as exc:
            return _draft_response(quiz, 'invalid', 400, str(exc))
        if revision != quiz.draft_revision:
            return _draft_response(quiz, 'conflict', 409, 'Bản nháp đã thay đổi ở tab khác. Hãy tải lại trang trước khi lưu tiếp.')
        if answers == quiz.draft_answers:
            return _draft_response(quiz)
        now = timezone.now()
        changed = VocabularyQuizSession.objects.filter(pk=quiz.pk, status='in_progress', draft_revision=revision).update(
            draft_answers=answers, draft_revision=revision + 1, last_saved_at=now,
        )
        if not changed:
            quiz.refresh_from_db()
            return _draft_response(quiz, 'submitted' if quiz.status == 'submitted' else 'conflict', 409, 'Lượt quiz đã thay đổi. Hãy tải lại trang.')
        quiz.draft_answers, quiz.draft_revision, quiz.last_saved_at = answers, revision + 1, now
        return _draft_response(quiz)


def _retry_candidates(parent, recall_index=None):
    missed = [q for q in parent.snapshot if not quiz_answer_is_correct(q, parent.answers.get(str(q['number'])), parent.mode)]
    visible_ids = set(Flashcard.objects.learner_visible(parent.exam_type).filter(
        pk__in=[q['card_id'] for q in missed], content__content_type='vocabulary',
    ).values_list('pk', flat=True))
    if parent.mode == 'recall':
        if recall_index is None:
            recall_index = RecallPromptIndex.for_exam(parent.exam_type)
        missed_prompts = RecallPromptIndex(missed)
        return [q for q in missed if q['card_id'] in visible_ids and q['card_id'] in recall_index.visible_ids
                and recall_index.allows(q) and missed_prompts.allows(q)]
    return [q for q in missed if q['card_id'] in visible_ids]


@login_required
@require_POST
@never_cache
def quiz_retry(request, quiz_id):
    parent = get_object_or_404(VocabularyQuizSession, pk=quiz_id, user=request.user, exam_type=_exam(request.user))
    if parent.status != 'submitted':
        messages.info(request, 'Hãy nộp lượt quiz này trước khi ôn từ sai.')
        return redirect('learning:quiz_take', quiz_id=parent.pk)
    recall_index = RecallPromptIndex.for_exam(parent.exam_type) if parent.mode == 'recall' else None
    active = active_quiz_for_user(request.user, recall_index=recall_index)
    if active:
        messages.info(request, 'Bạn có một lượt quiz đang làm. Hãy tiếp tục hoặc dừng lượt đó trước.')
        return redirect('learning:quiz_take', quiz_id=active.pk)
    candidates = _retry_candidates(parent, recall_index)
    if not candidates:
        message = ('Không còn từ sai có gợi ý rõ để gõ. Gợi ý khớp nhiều từ hoặc chứa sẵn đáp án không được dùng; hãy chuyển sang Chọn nghĩa.'
                   if parent.mode == 'recall' else 'Không còn từ sai khả dụng để ôn trong lượt này.')
        messages.info(request, message)
        return redirect('learning:quiz_result', quiz_id=parent.pk)
    snapshot = []
    for number, original in enumerate(candidates, start=1):
        question = deepcopy(original)
        question.pop('due_check', None)  # Retry feedback is not a new spaced observation.
        if parent.mode == 'recall':
            question['number'] = number
            snapshot.append(question)
            continue
        previous_texts = [option['text'] for option in original['options']]
        correct_text = next(option['text'] for option in original['options'] if option['key'] == original['correct_key'])
        texts = previous_texts[:]
        _rng.shuffle(texts)
        if texts == previous_texts:
            texts = texts[1:] + texts[:1]
        question['number'] = number
        question['options'] = [{'key': chr(65 + index), 'label': chr(65 + index), 'text': text} for index, text in enumerate(texts)]
        question['correct_key'] = next(option['key'] for option in question['options'] if option['text'] == correct_text)
        snapshot.append(question)
    try:
        with transaction.atomic():
            quiz = VocabularyQuizSession.objects.create(
                user=request.user, exam_type=parent.exam_type, cefr_level=parent.cefr_level,
                topic=parent.topic, parent_quiz=parent, is_retry=True,
                vocabulary_source=parent.vocabulary_source,
                mode=parent.mode,
                question_count=len(snapshot), snapshot=snapshot,
            )
    except IntegrityError:
        quiz = VocabularyQuizSession.objects.filter(user=request.user, status='in_progress').first()
        if quiz is None:
            messages.info(request, 'Lượt quiz đã thay đổi ở tab khác. Hãy mở lại kết quả để ôn tiếp.')
            return redirect('learning:quiz_result', quiz_id=parent.pk)
    return redirect('learning:quiz_take', quiz_id=quiz.pk)
