"""Read-only release gate for the rebuildable mistake-queue projection."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Exists, OuterRef

from learning.models import VocabularyQuizSession, WeakWordProjectionState
from learning.weak_word_outcomes import PROJECTION_VERSION


def projection_ready():
    """Check projection metadata only; never read history payloads or write."""
    submitted = VocabularyQuizSession.objects.filter(status='submitted', submitted_at__isnull=False)
    ready = WeakWordProjectionState.objects.filter(
        user_id=OuterRef('pk'), ready=True, needs_rebuild=False, version=PROJECTION_VERSION,
    )
    accounts = get_user_model().objects.annotate(
        has_history=Exists(submitted.filter(user_id=OuterRef('pk'))),
        projection_ready=Exists(ready),
    ).filter(has_history=True, projection_ready=False)
    return not (accounts.exists() or submitted.filter(weak_word_receipt__isnull=True).exists())


class Command(BaseCommand):
    help = 'Fail when submitted history lacks a ready weak-word projection; never reads snapshots or writes.'

    def handle(self, *args, **options):
        if not projection_ready():
            raise CommandError('Weak-word projection is not ready. Back up, run backfill_weak_word_outcomes --apply, then retry.')
        self.stdout.write('Weak-word projections are ready. Bulk history repairs still require explicit reconciliation.')
