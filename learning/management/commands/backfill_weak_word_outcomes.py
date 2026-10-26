"""Explicit, bounded-account reconciliation; never run during a web request."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from learning.weak_word_outcomes import rebuild_user_outcomes


class Command(BaseCommand):
    help = 'Preview/rebuild compact weak-word outcomes, locking one user at a time.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Write projections; default only lists account scope.')
        parser.add_argument('--user-id', type=int)
        parser.add_argument('--after-user-id', type=int, default=0, help='Resume after the last successfully completed account.')
        parser.add_argument('--limit', type=int, default=100, help='At most this many accounts; maximum 10000.')

    def handle(self, *args, **options):
        if not 1 <= options['limit'] <= 10000 or options['after_user_id'] < 0:
            raise CommandError('Use --limit 1..10000 and a non-negative --after-user-id.')
        users = get_user_model().objects.filter(pk__gt=options['after_user_id']).order_by('pk')
        if options['user_id'] is not None:
            if options['user_id'] < 1:
                raise CommandError('--user-id must be positive.')
            users = users.filter(pk=options['user_id'])
        ids = list(users.values_list('pk', flat=True)[:options['limit']])
        self.stdout.write(f'Accounts in batch: {len(ids)}; mode: {"apply" if options["apply"] else "preview (no writes)"}')
        if not options['apply']:
            self.stdout.write('Use --apply after backup and before enabling the new read path. Each account is atomic.')
            return
        for user_id in ids:
            result = rebuild_user_outcomes(user_id)
            self.stdout.write(f'user_id={user_id} quizzes={result["quizzes"]} groups={result["groups"]} pending={result["pending"]}')
            self.stdout.write(f'Checkpoint: --after-user-id {user_id}')
        self.stdout.write('Backfill batch complete. Snapshots, grades and XP were not changed.')
