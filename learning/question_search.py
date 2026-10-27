"""Accent-folded token postings for question candidate lookup."""
import hashlib
import re
import unicodedata

SEARCH_FIELDS = ('prompt', 'passage', 'audio_script', 'transcript', 'explanation_vi', 'explanation')


def token_hashes(text):
    folded = unicodedata.normalize('NFKD', str(text or '').lower())
    folded = ''.join(char for char in folded if not unicodedata.combining(char)).replace('đ', 'd')
    return {hashlib.sha256(token.encode()).hexdigest() for token in re.findall(r'[a-z0-9]+', folded)}


def sync_questions(questions, using):
    from .models import QuestionSearchToken
    for question in questions:
        QuestionSearchToken.objects.using(using).filter(question_id=question.pk).delete()
        hashes = token_hashes(' '.join(getattr(question, field) for field in SEARCH_FIELDS))
        QuestionSearchToken.objects.using(using).bulk_create([
            QuestionSearchToken(question_id=question.pk, token_hash=token) for token in sorted(hashes)
        ], batch_size=500)


def question_saved(sender, instance, using, update_fields=None, **kwargs):
    if update_fields is not None and not set(update_fields).intersection(SEARCH_FIELDS):
        return
    # Partial saves must index database values, never unsaved instance edits.
    current = sender.objects.using(using).only('pk', *SEARCH_FIELDS).get(pk=instance.pk)
    sync_questions([current], using)
