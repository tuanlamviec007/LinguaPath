"""Bounded, prospective due-card practice. Never infer unassisted retention."""
from datetime import timedelta
import hashlib
import json

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import DueRecallObservation, Flashcard, LearningContent, UserFlashcardState

POLICY_VERSION = 'due-self-rating-gap-v1'
MIN_GAP = timedelta(hours=24)
_IDENTITY_FIELDS = ('term', 'meaning_vi', 'part_of_speech', 'cefr_level', 'example_en', 'example_vi')


def source_version(card):
    value = [card.get(key, '') if isinstance(card, dict) else getattr(card, key) for key in _IDENTITY_FIELDS]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def due_states(user, exam_type, now=None):
    """One candidate per recorded self-rating, until a due quiz is submitted.

    Any prior due observation consumes that baseline, even an excluded result:
    feedback has been exposed. A new flashcard rating is needed to try again.
    Other study routes and activity outside the app are not measured here.
    """
    now = now or timezone.now()
    observed = DueRecallObservation.objects.filter(
        quiz__user=user, quiz__status='submitted', quiz__is_retry=False,
        card_id=OuterRef('flashcard_id'), checked_at__gte=OuterRef('reviewed_at'),
    )
    return UserFlashcardState.objects.filter(
        user=user, flashcard__in=Flashcard.objects.learner_visible(exam_type).filter(content__content_type='vocabulary'),
        reviewed_at__lte=now - MIN_GAP, due_at__lte=now,
    ).annotate(already_checked=Exists(observed)).filter(already_checked=False)


def selection_metadata(state, card, selected_at):
    return {'policy': POLICY_VERSION, 'baseline_reviewed_at': state.reviewed_at.isoformat(),
            'selected_at': selected_at.isoformat(), 'source_version': source_version(card),
            'content_id': card['content_id']}


def lock_due_cards(questions):
    ids = {q['card_id'] for q in questions}
    parent_ids = sorted(Flashcard.objects.filter(pk__in=ids).values_list('content_id', flat=True).distinct())
    list(LearningContent.objects.select_for_update().filter(pk__in=parent_ids).order_by('pk'))
    # A card can move while we wait for its original parent's lock. Never
    # acquire a newly discovered parent out of order; fail this selection.
    return {c.pk: c for c in Flashcard.objects.select_for_update().filter(pk__in=ids).order_by('pk')
            if c.content_id in parent_ids}


def selection_is_current(user, exam_type, questions):
    """Recheck a prepared selection while its owner is locked before creation.

    Two starts can prepare the same baseline before either inserts a quiz.
    Serializing creation with submission and rechecking receipts prevents the
    second start from reusing feedback after the first quiz has been submitted.
    """
    ids = {q['card_id'] for q in questions}
    cards = lock_due_cards(questions)
    states = {s.flashcard_id: s for s in due_states(user, exam_type).filter(flashcard_id__in=ids)}
    return all(q['card_id'] in states and q['card_id'] in cards
        and states[q['card_id']].reviewed_at.isoformat() == q['due_check']['baseline_reviewed_at']
        and cards[q['card_id']].content_id == q['due_check']['content_id']
        and source_version(cards[q['card_id']]) == q['due_check']['source_version'] for q in questions)


def record_due_observations(quiz, locked_cards=None):
    """Called once inside submit's owner lock and transaction, after grading.

    Lock parents/cards in the same order as source editors. Re-rating uses the
    owner's lock, so its timestamp is stable during this check. No SRS changes.
    """
    if quiz.vocabulary_source != 'due' or quiz.mode != 'recall' or quiz.is_retry:
        return
    ids = {q['card_id'] for q in quiz.snapshot}
    cards = lock_due_cards(quiz.snapshot) if locked_cards is None else locked_cards
    visible_ids = set(Flashcard.objects.learner_visible(quiz.exam_type).filter(pk__in=ids, content__content_type='vocabulary').values_list('pk', flat=True))
    states = {s.flashcard_id: s for s in UserFlashcardState.objects.filter(user=quiz.user_id, flashcard_id__in=ids)}
    from .quiz_answers import quiz_answer_is_correct
    rows = []
    for q in quiz.snapshot:
        meta = q.get('due_check', {})
        meta = meta if isinstance(meta, dict) else {}
        baseline = selected = None
        try:
            baseline = parse_datetime(meta.get('baseline_reviewed_at', ''))
            selected = parse_datetime(meta.get('selected_at', ''))
            valid = (meta.get('policy') == POLICY_VERSION and baseline and selected
                     and timezone.is_aware(baseline) and timezone.is_aware(selected)
                     and baseline + MIN_GAP <= selected <= quiz.started_at <= quiz.submitted_at)
        except (TypeError, ValueError, OverflowError):
            valid = False
        reason = ''
        card, state = cards.get(q['card_id']), states.get(q['card_id'])
        if not valid:
            reason = 'invalid_baseline'
        elif not card or card.pk not in visible_ids or card.content_id != meta.get('content_id') or source_version(card) != meta.get('source_version') or source_version(q) != meta.get('source_version'):
            reason = 'source_changed'
        elif not state or state.reviewed_at != baseline:
            reason = 'review_changed'
        rows.append(DueRecallObservation(
            quiz=quiz, card_id=q['card_id'], baseline_reviewed_at=baseline if valid else quiz.started_at,
            checked_at=quiz.submitted_at, is_correct=quiz_answer_is_correct(q, quiz.answers.get(str(q['number'])), quiz.mode),
            exclusion_reason=reason,
        ))
    DueRecallObservation.objects.bulk_create(rows)


def due_summary(user, exam_type, now=None):
    now = now or timezone.now()
    rows = DueRecallObservation.objects.filter(
        quiz__user=user, quiz__exam_type=exam_type, quiz__status='submitted',
        quiz__is_retry=False, quiz__vocabulary_source='due', quiz__mode='recall',
        checked_at__gte=now-timedelta(days=30), checked_at__lte=now,
    )
    result = rows.aggregate(questions=Count('pk', filter=Q(exclusion_reason='')),
        correct=Count('pk', filter=Q(exclusion_reason='', is_correct=True)),
        excluded=Count('pk', filter=~Q(exclusion_reason='')))
    result['accuracy'] = round(100 * result['correct']/result['questions']) if result['questions'] >= 5 else None
    return result
