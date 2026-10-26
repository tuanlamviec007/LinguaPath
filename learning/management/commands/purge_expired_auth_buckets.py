"""Remove a bounded batch of old counters without deleting refreshed windows."""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from learning.auth_models import AuthRateBucket


class Command(BaseCommand):
    help = 'Preview auth-rate counters expired over 24 hours ago; use --apply to delete one bounded batch.'

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=1000)
        parser.add_argument('--apply', action='store_true', help='Delete the selected batch; otherwise preview only.')

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if not 1 <= batch_size <= 10000:
            raise CommandError('batch-size must be between 1 and 10000')
        cutoff = timezone.now() - timedelta(hours=24)
        ids = list(AuthRateBucket.objects.filter(expires_at__lt=cutoff)
                   .order_by('expires_at', 'pk').values_list('pk', flat=True)[:batch_size])
        if not options['apply']:
            self.stdout.write(f'Dry run: {len(ids)} expired authentication rate-limit buckets in this batch; use --apply to delete.')
            return
        # Recheck expiry in DELETE: a concurrent request may have reused a key
        # since the batch was selected. Active quota must not be reset by purge.
        count, _ = AuthRateBucket.objects.filter(pk__in=ids, expires_at__lt=cutoff).delete()
        self.stdout.write(f'Deleted {count} expired authentication rate-limit buckets.')
