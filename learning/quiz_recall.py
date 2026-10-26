"""Conservative recall eligibility; never invent or automatically accept synonyms."""
from collections import defaultdict

from .models import Flashcard, LEARNER_REVIEW_STATUSES
from .quiz_answers import normalize_recall_answer, recall_prompt_is_usable, recall_prompt_signature


RECALL_FIELDS = ('id', 'term', 'meaning_vi', 'part_of_speech')


def recall_fields(card):
    return card if isinstance(card, dict) else {key: getattr(card, key) for key in RECALL_FIELDS}


class RecallPromptIndex:
    """Build once from the entire visible exam bank; each eligibility check is O(1).

    Different cards containing the same normalized lemma are not an ambiguity.
    A historical snapshot is checked against other currently visible lemmas,
    without replacing its immutable wording or changing its stored grade.
    """
    def __init__(self, cards, exam_type=None):
        self.exam_type = exam_type
        self.terms = defaultdict(set)
        self.cards = [recall_fields(card) for card in cards]
        for card in self.cards:
            term = normalize_recall_answer(card.get('term'))
            if term:
                self.terms[recall_prompt_signature(card)].add(term)
        self.visible_ids = {card['id'] for card in self.cards if 'id' in card}
        self.eligible_ids = {card['id'] for card in self.cards if 'id' in card and self.allows(card)}

    @classmethod
    def for_exam(cls, exam_type):
        bank = Flashcard.objects.filter(is_available=True,
            content__exam_type=exam_type, content__content_type='vocabulary',
            content__is_published=True, content__review_status__in=LEARNER_REVIEW_STATUSES,
        ).exclude(term='').exclude(meaning_vi='').values(*RECALL_FIELDS)
        return cls(bank, exam_type)

    def ambiguous(self, question):
        question = recall_fields(question)
        term = normalize_recall_answer(question.get('term'))
        # No synonym expansion: any other bank lemma sharing all visible cues
        # blocks the prompt, rather than making either spelling an accepted key.
        terms = self.terms.get(recall_prompt_signature(question), set())
        return len(terms) > 1 or (len(terms) == 1 and term not in terms)

    def allows(self, question):
        question = recall_fields(question)
        return recall_prompt_is_usable(question) and not self.ambiguous(question)
