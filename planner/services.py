from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from learning.locking import nonkey_row_lock
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Sum
from django.utils import timezone

from learning.models import CEFR_LEVELS, LEARNER_REVIEW_STATUSES, Flashcard, LearningContent, PracticeAttempt, UserFlashcardState
from .models import StudyTask


RECOMMENDATION_VERSION = 'rule-v2-cefr'
KNOWN_SELF_RATING_THRESHOLD = 0.8
PLAN_INPUT_FIELDS = frozenset({'exam_goal', 'current_cefr', 'target_cefr', 'daily_minutes'})


def _visible_tasks(user, profile, today):
    available = Flashcard.objects.learner_visible(profile.exam_goal).filter(content_id=OuterRef('content_id'))
    return StudyTask.objects.filter(
        user=user, scheduled_for=today, content__is_published=True, content__exam_type=profile.exam_goal,
        content__review_status__in=LEARNER_REVIEW_STATUSES,
    ).annotate(
        has_available_vocab=Exists(available),
        has_available_level=Exists(available.filter(cefr_level=OuterRef('cefr_level'))),
    ).filter(Q(status='done') | ~Q(content__content_type='vocabulary')
        | Q(cefr_level='', has_available_vocab=True) | Q(has_available_level=True)).select_related('content')


@transaction.atomic
def generate_daily_plan(user, profile, today=None):
    """Return today's existing plan, or build it once under its owner's lock."""
    nonkey_row_lock(get_user_model().objects.all()).get(pk=user.pk)
    return _generate_daily_plan(user, profile, today)


@transaction.atomic
def replan_daily_plan(user, profile, changed_fields, today=None):
    """Rebuild unfinished tasks only after an actual planner-input change.

    Pass actual changed field names (for example ``form.changed_data``), not
    every submitted field. Tracking-only score/date changes preserve IDs.
    Completed work is retained across exam changes and consumes the same
    daily time budget, including work whose content is no longer visible.
    """
    nonkey_row_lock(get_user_model().objects.all()).get(pk=user.pk)
    today = today or timezone.localdate()
    if not PLAN_INPUT_FIELDS.intersection(changed_fields):
        return _generate_daily_plan(user, profile, today)
    StudyTask.objects.filter(user=user, scheduled_for=today).exclude(status='done').delete()
    return _generate_daily_plan(user, profile, today, replan=True)


def _generate_daily_plan(user, profile, today=None, *, replan=False):
    """Create a deterministic, explainable TOEIC plan using recent results and CEFR.

    CEFR labels classify vocabulary content; they do not convert TOEIC scores to CEFR.
    A learner receives due cards at their current level. The next level may be included
    after at least 80% of current-level cards have a latest ``known`` self-rating, capped
    at the learner's target level. This is a transparent project heuristic, not an
    official proficiency assessment or trained recommendation model.
    """
    today = today or timezone.localdate()
    existing = _visible_tasks(user, profile, today)
    # Completing a task must not silently refill the plan and grow its budget.
    # Only an explicit input-change replan may add work after completed tasks.
    if not replan and StudyTask.objects.filter(user=user, scheduled_for=today).exists():
        return existing
    now = timezone.now()
    attempts = PracticeAttempt.objects.filter(
        user=user, status='submitted', submitted_at__gte=now - timedelta(days=30),
    )
    recent_content_ids = set(attempts.order_by('-submitted_at').values_list('content_id', flat=True)[:20])
    skill_accuracy = {
        row['content__skill']: row['correct'] / row['total']
        for row in attempts.values('content__skill').annotate(correct=Sum('correct_count'), total=Sum('question_count'))
        if row['total']
    }

    levels = [key for key, _ in CEFR_LEVELS]
    current = profile.current_cefr if profile.current_cefr in levels else 'A1'
    target = profile.target_cefr if profile.target_cefr in levels else current
    current_index = levels.index(current)
    target_index = max(current_index, levels.index(target))
    eligible_vocab_levels = [current]

    current_cards = Flashcard.objects.learner_visible(profile.exam_goal).filter(cefr_level=current)
    current_total = current_cards.count()
    known_ids = UserFlashcardState.objects.filter(
        user=user, last_rating='known', flashcard__in=current_cards,
    ).values_list('flashcard_id', flat=True)
    known_self_rating_share = len(set(known_ids)) / current_total if current_total else 0
    if current_index < target_index and known_self_rating_share >= KNOWN_SELF_RATING_THRESHOLD:
        eligible_vocab_levels.append(levels[current_index + 1])

    not_due_ids = UserFlashcardState.objects.filter(
        user=user, due_at__gt=now,
    ).values_list('flashcard_id', flat=True)
    due_vocab_content_levels = set(
        Flashcard.objects.learner_visible(profile.exam_goal).filter(
            cefr_level__in=eligible_vocab_levels,
        ).exclude(id__in=not_due_ids).values_list('content_id', 'cefr_level')
    )
    completed = set(StudyTask.objects.filter(
        user=user, scheduled_for=today, status='done',
    ).values_list('content_id', 'cefr_level'))

    content_items = list(LearningContent.objects.filter(
        is_published=True, review_status__in=LEARNER_REVIEW_STATUSES, exam_type=profile.exam_goal,
    ).filter(
        Q(content_type='vocabulary', flashcards__is_available=True)
        | Q(content_type='reading', questions__isnull=False)
        | Q(content_type='listening', questions__audio_url__gt='')
        | Q(content_type='listening', questions__audio_script__gt='')
    ).distinct().order_by('id'))

    candidates = []
    for item in content_items:
        if item.content_type == 'vocabulary':
            levels_for_item = sorted(
                level for content_id, level in due_vocab_content_levels if content_id == item.id
            )
            for level in levels_for_item:
                if (item.id, level) in completed:
                    continue
                candidates.append((item, level))
        else:
            if item.cefr_level in levels and levels.index(item.cefr_level) > current_index:
                continue
            if (item.id, '') not in completed:
                candidates.append((item, ''))

    scored = []
    for item, level in candidates:
        accuracy = skill_accuracy.get(item.skill)
        weakness = 1 - accuracy if accuracy is not None else 0.5
        difficulty_fit = 1.0 if item.difficulty <= 2 or item.cefr_level == current else 0.65
        variety = 1.0 if item.id not in recent_content_ids else 0.35
        level_fit = 1.0 if (level or item.cefr_level) == current else 0.65
        due_fit = 1.0 if level else 0.45
        score = 0.5 * weakness + 0.18 * due_fit + 0.12 * difficulty_fit + 0.1 * variety + 0.1 * level_fit
        reason = _selection_reason(item, level, current, accuracy)
        scored.append((score, item, level, reason))
    scored.sort(key=lambda entry: (-entry[0], entry[1].id, entry[2]))

    completed_tasks = StudyTask.objects.filter(user=user, scheduled_for=today, status='done')
    spent_minutes = completed_tasks.aggregate(total=Sum('estimated_minutes'))['total'] or 0
    remaining = max(profile.daily_minutes - spent_minutes, 0)
    available_slots = max(3 - completed_tasks.count(), 0)
    if not remaining or not available_slots:
        return existing
    chosen = []
    chosen_keys = set()
    chosen_skills = set()
    for score, item, level, reason in scored:
        if item.skill in chosen_skills:
            continue
        if 0 < item.estimated_minutes <= remaining:
            chosen.append((score, item, level, reason))
            chosen_keys.add((item.id, level))
            chosen_skills.add(item.skill)
            remaining = max(0, remaining - item.estimated_minutes)
        if remaining == 0 or len(chosen) == available_slots:
            break
    if remaining and len(chosen) < available_slots:
        for score, item, level, reason in scored:
            if (item.id, level) in chosen_keys or item.estimated_minutes > remaining:
                continue
            chosen.append((score, item, level, reason))
            chosen_keys.add((item.id, level))
            remaining = max(0, remaining - item.estimated_minutes)
            if remaining == 0 or len(chosen) == available_slots:
                break

    for score, item, level, reason in chosen:
        StudyTask.objects.get_or_create(
            user=user, content=item, scheduled_for=today, cefr_level=level,
            defaults={
                'estimated_minutes': item.estimated_minutes,
                'reason': reason,
                'recommendation_score': Decimal(str(round(score, 4))),
                'recommendation_version': RECOMMENDATION_VERSION,
            },
        )
    return _visible_tasks(user, profile, today)


def _selection_reason(item, level, current_level, accuracy):
    if level:
        if level == current_level:
            return f'Ôn từ vựng mức {level} đang phù hợp với trình độ hiện tại của bạn.'
        return (f'Bạn đã tự đánh giá “Đã nhớ” cho ít nhất 80% thẻ mức {current_level}; '
                f'thử một bộ từ mức {level} trong giới hạn mục tiêu. '
                'Gợi ý này chỉ mở thêm nội dung để thử, không xác nhận nhớ lâu hoặc nâng mức CEFR hiện tại.')
    if accuracy is not None and accuracy < 0.7:
        return f'Ưu tiên {item.get_skill_display()} vì tỷ lệ đúng gần đây thấp ({round(100 * accuracy)}%).'
    if accuracy is None:
        return f'Bổ sung {item.get_skill_display()} để kế hoạch khởi động có nhiều kỹ năng.'
    return f'Bài bổ sung trong thời lượng học đã chọn; tỷ lệ đúng gần đây là {round(100 * accuracy)}%.'
