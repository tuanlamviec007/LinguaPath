"""Explicit, bounded indexing of public reference notes and visible flashcards."""
from django.core.management.base import BaseCommand, CommandError
from learning.ai_provider import cloudflare_rag_request
from learning.semantic_retrieval import note_evidence
from learning.models import Flashcard
from learning.retrieval import _card_result
from learning.tutor_knowledge import KNOWLEDGE


def public_documents(card_limit=0):
    evidence = [note_evidence(note) for note in KNOWLEDGE]
    if card_limit:
        evidence.extend(_card_result(card, 1, 'exact') for card in Flashcard.objects.learner_visible('TOEIC').select_related('content').order_by('id')[:card_limit])
    return [{'id': item['kind'] + ':' + str(item['source_id']), 'text': item['text'][:1200],
             'version': item['source_ref']['version']} for item in evidence]


class Command(BaseCommand):
    help = 'Index public TOEIC notes; --cards adds up to 100 visible cards. No learner data or unsubmitted test answers.'

    def add_arguments(self, parser):
        parser.add_argument('--cards', type=int, default=0)
        parser.add_argument('--apply', action='store_true', help='Send to the private indexing bridge. Default prints a count only.')

    def handle(self, *args, **options):
        if not 0 <= options['cards'] <= 100:
            raise CommandError('--cards must be between 0 and 100')
        documents = public_documents(options['cards'])
        self.stdout.write(f'{len(documents)} public documents selected; personal history and questions excluded.')
        if not options['apply']:
            self.stdout.write('Dry run. Add --apply to embed and upsert; the service enforces its daily limits.')
            return
        count = 0
        try:
            for start in range(0, len(documents), 8):
                batch = documents[start:start + 8]
                result = cloudflare_rag_request('index', {'documents': batch}, index=True)
                if result.get('accepted') != len(batch):
                    raise ValueError()
                count += len(batch)
        except Exception:
            raise CommandError(f'Indexing stopped after {count} accepted documents. Check private bridge configuration or quota. Re-running upserts the same IDs.')
        self.stdout.write(self.style.SUCCESS(f'{count} documents accepted. Vectorize indexing is asynchronous; queries may take time to reflect updates.'))
