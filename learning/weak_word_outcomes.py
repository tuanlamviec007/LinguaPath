"""Rebuildable weak-word aggregates without decoding quiz history on reads.

Every valid submitted quiz is receipted once. Aggregates retain separate recall
cue groups, because a subsequently ambiguous recall prompt must neither open a
mistake nor clear a valid multiple-choice mistake. The original snapshots and
grades remain untouched. Bulk imports/SQL repairs require explicit backfill.
"""
import hashlib
import json
import unicodedata

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .locking import nonkey_row_lock
from .quiz_answers import quiz_answer_is_valid, quiz_answer_is_correct, recall_prompt_signature


PROJECTION_VERSION = 1
GROUP_FIELDS = ('card_id', 'identity_hash', 'group_key', 'mode', 'term', 'meaning_vi', 'part_of_speech')


def normalized_identity(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split()) if isinstance(value, str) else ''


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def word_identity(term, meaning):
    return _hash([normalized_identity(term), normalized_identity(meaning)])


def _fingerprint(quiz):
    return _hash({'version': PROJECTION_VERSION, 'exam': quiz.exam_type, 'mode': quiz.mode,
        'status': quiz.status, 'submitted_at': quiz.submitted_at.isoformat() if quiz.submitted_at else None,
        'snapshot': quiz.snapshot, 'answers': quiz.answers})


def _events(quiz):
    """Validate immutable evidence independently of the bank's current state."""
    if quiz.status != 'submitted' or quiz.submitted_at is None or quiz.mode not in ('meaning', 'recall'):
        return
    if not isinstance(quiz.snapshot, list) or not isinstance(quiz.answers, dict):
        return
    from .quiz_recall import RecallPromptIndex
    prompts = None
    if quiz.mode == 'recall':
        prompts = RecallPromptIndex({key: q.get(key) for key in ('term', 'meaning_vi', 'part_of_speech')}
            for q in quiz.snapshot if isinstance(q, dict))
    candidates, conflicts = {}, set()
    for question in quiz.snapshot:
        if not isinstance(question, dict):
            continue
        card_id = question.get('card_id')
        if type(card_id) is not int or not 0 < card_id <= 2**63 - 1:
            continue
        term, meaning = question.get('term'), question.get('meaning_vi')
        if not normalized_identity(term) or not normalized_identity(meaning):
            continue
        # Real cards have much smaller model bounds. Reject corrupt imported
        # evidence instead of using huge strings as projection identities.
        if len(term) > 10000 or len(meaning) > 10000:
            continue
        if prompts is not None and not prompts.allows(question):
            continue
        answer = quiz.answers.get(str(question.get('number')))
        if not quiz_answer_is_valid(question, answer, quiz.mode):
            continue
        if quiz.mode == 'meaning' and not quiz_answer_is_valid(question, question.get('correct_key'), 'meaning'):
            continue
        pos = question.get('part_of_speech')
        pos = pos if isinstance(pos, str) else ''
        event = {'card_id': card_id, 'identity_hash': word_identity(term, meaning),
            'group_key': _hash(['meaning'] if quiz.mode == 'meaning' else ['recall', *recall_prompt_signature(question)]),
            'mode': quiz.mode, 'term': term, 'meaning_vi': meaning, 'part_of_speech': pos,
            'is_wrong': not quiz_answer_is_correct(question, answer, quiz.mode)}
        previous = candidates.get(card_id)
        if previous is None:
            candidates[card_id] = event
        elif (previous['identity_hash'], previous['group_key']) != (event['identity_hash'], event['group_key']):
            conflicts.add(card_id)
    # Generated quizzes contain each card once. Conflicting duplicate IDs in
    # corrupted/imported history have no trustworthy single displayed prompt;
    # neither open nor clear a mistake from that card in that session. Exact
    # duplicates keep the first valid answer once, as the prior reader did.
    yield from (event for card_id, event in candidates.items() if card_id not in conflicts)


def _models():
    from .weak_word_models import WeakWordOutcome, WeakWordPendingOutcome, WeakWordQuizReceipt, WeakWordProjectionState
    return WeakWordOutcome, WeakWordPendingOutcome, WeakWordQuizReceipt, WeakWordProjectionState


def _fold_event(user_id, exam, event, submitted_at, quiz_id):
    Outcome, _, _, _ = _models()
    key = {field: event[field] for field in ('card_id', 'identity_hash', 'group_key')}
    outcome, created = Outcome.objects.get_or_create(user_id=user_id, exam_type=exam, **key,
        defaults={field: event[field] for field in ('mode', 'term', 'meaning_vi', 'part_of_speech')} | {
            'last_attempt_at': submitted_at, 'last_quiz_id': quiz_id,
            'is_wrong': event['is_wrong'], 'wrong_count': int(event['is_wrong'])})
    if created:
        return
    fields = []
    if event['is_wrong']:
        outcome.wrong_count += 1
        fields.append('wrong_count')
    if (submitted_at, quiz_id) > (outcome.last_attempt_at, outcome.last_quiz_id):
        outcome.last_attempt_at, outcome.last_quiz_id = submitted_at, quiz_id
        outcome.is_wrong = event['is_wrong']
        fields.extend(('last_attempt_at', 'last_quiz_id', 'is_wrong'))
    if fields:
        outcome.save(update_fields=fields)


def _record_locked(quiz, now):
    """Caller holds the parent User lock in the surrounding transaction."""
    _, Pending, Receipt, State = _models()
    state, _ = State.objects.get_or_create(user_id=quiz.user_id)
    existing = Receipt.objects.filter(quiz_id=quiz.pk).first()
    fingerprint = _fingerprint(quiz)
    if existing:
        if existing.fingerprint != fingerprint or existing.user_id != quiz.user_id:
            State.objects.filter(user_id__in={quiz.user_id, existing.user_id}).update(ready=False, needs_rebuild=True)
        return False
    if quiz.status != 'submitted' or quiz.submitted_at is None:
        return False
    for event in _events(quiz):
        if quiz.submitted_at > now:
            Pending.objects.create(user_id=quiz.user_id, quiz_id=quiz.pk, exam_type=quiz.exam_type,
                submitted_at=quiz.submitted_at, **event)
        else:
            _fold_event(quiz.user_id, quiz.exam_type, event, quiz.submitted_at, quiz.pk)
    Receipt.objects.create(quiz_id=quiz.pk, user_id=quiz.user_id, fingerprint=fingerprint)
    return True


def record_quiz_outcomes(quiz, *, now=None):
    """Project an ordinary save; repeating the same immutable quiz is harmless.

    Quiz submission must lock User before Quiz and save inside the same atomic
    transaction as this receiver. Bulk ORM writes deliberately bypass signals;
    an explicit command must project/reconcile those imported records.
    """
    from .models import VocabularyQuizSession
    _, _, _, State = _models()
    if not quiz.pk:
        return False
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=quiz.user_id)
        changed = _record_locked(quiz, now or timezone.now())
        state = State.objects.get(user_id=quiz.user_id)
        if not state.needs_rebuild and state.version == PROJECTION_VERSION:
            missing = VocabularyQuizSession.objects.filter(user_id=quiz.user_id,
                status='submitted', submitted_at__isnull=False, weak_word_receipt__isnull=True).exists()
            if state.ready == missing:
                state.ready = not missing
                state.save(update_fields=['ready', 'updated_at'])
        return changed


def quiz_outcomes_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        record_quiz_outcomes(instance)


def quiz_outcomes_deleted(sender, instance, **kwargs):
    """Deleting source history invalidates counters until explicit reconciliation."""
    _, _, _, State = _models()
    State.objects.filter(user_id=instance.user_id).update(ready=False, needs_rebuild=True)


def rebuild_user_outcomes(user, *, now=None):
    """Atomically rebuild one account; repeat safely and never edit snapshots."""
    from .models import VocabularyQuizSession
    Outcome, Pending, Receipt, State = _models()
    now = now or timezone.now()
    user_id = user.pk if hasattr(user, 'pk') else int(user)
    with transaction.atomic():
        nonkey_row_lock(get_user_model().objects.all()).get(pk=user_id)
        state, _ = State.objects.get_or_create(user_id=user_id)
        state.ready, state.needs_rebuild = False, True
        state.save(update_fields=['ready', 'needs_rebuild', 'updated_at'])
        Outcome.objects.filter(user_id=user_id).delete()
        Pending.objects.filter(Q(user_id=user_id) | Q(quiz__user_id=user_id)).delete()
        Receipt.objects.filter(Q(user_id=user_id) | Q(quiz__user_id=user_id)).delete()
        processed = 0
        groups, receipts, pending = {}, [], []
        quizzes = VocabularyQuizSession.objects.filter(user_id=user_id, status='submitted',
            submitted_at__isnull=False).only('id', 'user_id', 'exam_type', 'status', 'mode',
                'submitted_at', 'snapshot', 'answers').order_by('pk')
        for quiz in quizzes.iterator(chunk_size=200):
            for event in _events(quiz):
                if quiz.submitted_at > now:
                    pending.append(Pending(user_id=user_id, quiz_id=quiz.pk, exam_type=quiz.exam_type,
                        submitted_at=quiz.submitted_at, **event))
                    if len(pending) >= 200:
                        Pending.objects.bulk_create(pending, batch_size=200)
                        pending.clear()
                    continue
                key = (quiz.exam_type, event['card_id'], event['identity_hash'], event['group_key'])
                current = groups.get(key)
                if current is None:
                    groups[key] = Outcome(user_id=user_id, exam_type=quiz.exam_type,
                        last_attempt_at=quiz.submitted_at, last_quiz_id=quiz.pk,
                        wrong_count=int(event['is_wrong']), **event)
                else:
                    current.wrong_count += int(event['is_wrong'])
                    if (quiz.submitted_at, quiz.pk) > (current.last_attempt_at, current.last_quiz_id):
                        current.last_attempt_at, current.last_quiz_id = quiz.submitted_at, quiz.pk
                        current.is_wrong = event['is_wrong']
            receipts.append(Receipt(quiz_id=quiz.pk, user_id=user_id, fingerprint=_fingerprint(quiz)))
            if len(receipts) >= 200:
                Receipt.objects.bulk_create(receipts, batch_size=200)
                receipts.clear()
            processed += 1
        Outcome.objects.bulk_create(groups.values(), batch_size=200)
        if receipts:
            Receipt.objects.bulk_create(receipts, batch_size=200)
        if pending:
            Pending.objects.bulk_create(pending, batch_size=200)
        state.version, state.ready, state.needs_rebuild = PROJECTION_VERSION, True, False
        state.save(update_fields=['version', 'ready', 'needs_rebuild', 'updated_at'])
        return {'user_id': user_id, 'quizzes': processed,
                'groups': Outcome.objects.filter(user_id=user_id).count(),
                'pending': Pending.objects.filter(user_id=user_id).count()}


def materialized_weak_word_summary(user, exam_type, *, visible_bank=None, recall_index=None, now=None):
    """Read compact projections only. Never silently rebuild from JSON on GET."""
    from .models import Flashcard, LEARNER_REVIEW_STATUSES, VocabularyQuizSession
    from .saved_words import with_saved_flags
    from .quiz_recall import RecallPromptIndex
    Outcome, Pending, _, State = _models()
    now = now or timezone.now()
    empty = {'words': [], 'count': 0, 'ready': True, 'needs_backfill': False}
    state = State.objects.filter(user_id=user.pk).values('version', 'ready', 'needs_rebuild').first()
    histories = VocabularyQuizSession.objects.filter(user_id=user.pk, status='submitted', submitted_at__isnull=False)
    if state is None:
        return empty if not histories.exists() else empty | {'ready': False, 'needs_backfill': True}
    if (state['version'] != PROJECTION_VERSION or not state['ready'] or state['needs_rebuild']
            or histories.filter(weak_word_receipt__isnull=True).exists()):
        return empty | {'ready': False, 'needs_backfill': True}
    if visible_bank is None:
        visible_bank = with_saved_flags(Flashcard.objects.filter(is_available=True, content__exam_type=exam_type,
            content__content_type='vocabulary', content__is_published=True,
            content__review_status__in=LEARNER_REVIEW_STATUSES).exclude(term='').exclude(meaning_vi=''), user)
        cards = {card.pk: card for card in visible_bank}
    else:
        supplied = {card.pk: card for card in visible_bank}
        # A caller may reuse an annotated bank loaded before an editorial hold.
        # Recheck availability in SQL rather than trusting stale object flags.
        available_ids = set(Flashcard.objects.learner_visible(exam_type).filter(
            pk__in=supplied, content__content_type='vocabulary').exclude(term='').exclude(
                meaning_vi='').values_list('pk', flat=True))
        cards = {pk: card for pk, card in supplied.items() if pk in available_ids}
    if not cards:
        return empty
    identities = {pk: word_identity(card.term, card.meaning_vi) for pk, card in cards.items()}
    groups = {}
    values = (*GROUP_FIELDS, 'last_attempt_at', 'last_quiz_id', 'is_wrong', 'wrong_count')
    for row in Outcome.objects.filter(user_id=user.pk, exam_type=exam_type, card_id__in=cards).values(*values).iterator(chunk_size=200):
        if row['last_attempt_at'] > now:
            # A backwards wall-clock can make an already-folded outcome lie in
            # the future. Do not infer an earlier state from the newest row;
            # explicit reconciliation moves these events to pending storage.
            return empty | {'ready': False, 'needs_backfill': True}
        groups[(row['card_id'], row['identity_hash'], row['group_key'])] = row
    # These rows exist only for imported future dates. They stay separate from
    # normal counters, and become eligible without touching a quiz snapshot.
    for row in Pending.objects.filter(user_id=user.pk, exam_type=exam_type,
            card_id__in=cards, submitted_at__lte=now).values(
                *GROUP_FIELDS, 'submitted_at', 'quiz_id', 'is_wrong').iterator(chunk_size=200):
        key = (row['card_id'], row['identity_hash'], row['group_key'])
        current = groups.get(key)
        if current is None:
            groups[key] = row | {'last_attempt_at': row['submitted_at'],
                'last_quiz_id': row['quiz_id'], 'wrong_count': int(row['is_wrong'])}
        else:
            current['wrong_count'] += int(row['is_wrong'])
            if (row['submitted_at'], row['quiz_id']) > (current['last_attempt_at'], current['last_quiz_id']):
                current.update(last_attempt_at=row['submitted_at'], last_quiz_id=row['quiz_id'], is_wrong=row['is_wrong'])
    states = {}
    for row in groups.values():
        card_id = row['card_id']
        if row['identity_hash'] != identities[card_id]:
            continue
        if row['mode'] == 'recall':
            if recall_index is None:
                recall_index = RecallPromptIndex(cards.values(), exam_type)
            if not recall_index.allows(row):
                continue
        current = states.get(card_id)
        if current is None:
            states[card_id] = dict(row)
        else:
            wrong_count = current['wrong_count'] + row['wrong_count']
            if (row['last_attempt_at'], row['last_quiz_id']) > (current['last_attempt_at'], current['last_quiz_id']):
                current = states[card_id] = dict(row)
            current['wrong_count'] = wrong_count
    words = []
    for card_id, row in states.items():
        if row['is_wrong']:
            card = cards[card_id]
            words.append({'card': card, 'term': card.term, 'meaning_vi': card.meaning_vi,
                'cefr_level': card.cefr_level, 'topic': card.topic, 'wrong_count': row['wrong_count'],
                'last_attempt_at': row['last_attempt_at'], 'last_quiz_id': row['last_quiz_id']})
    words.sort(key=lambda row: (row['last_attempt_at'], row['last_quiz_id'], row['card'].pk), reverse=True)
    return {'words': words, 'count': len(words), 'ready': True, 'needs_backfill': False}
