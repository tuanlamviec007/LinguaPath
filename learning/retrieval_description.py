"""Local lexical candidate search; scores are rankings, never confidence.

Only public/visible cards supplied by the caller are indexed, once per request.
No aliases, inferred synonyms, learner history, embeddings or persisted cache.
"""
from collections import Counter
from dataclasses import dataclass
import math
import re
import unicodedata

VERSION = 'description-lexical-v1'
MAX_FIELD_CHARS = 2000
MAX_QUERY_CHARS = 500
MAX_CANDIDATES = 3
# Functional/request tokens, not a per-headword synonym or benchmark mapping.
COMMON = frozenset('''a an and are as at be been but by can could do does for from has have how i if in into is it its me my of on or our please should that the their them then there these they this those to us was we were what when where which who why will with would you your
cac cai can cho chi co con cua da de den do duoc gi goi hay khi khong la lai loai ma mot nao nay nhieu nhung nhu noi o phai qua ra rang rat se su ta thi theo tren trong tu tung va vao ve vi voi xin du thuat ngu duoc mo ta
'''.split())


def tokens(text):
    folded = unicodedata.normalize('NFKD', str(text or '').casefold()).replace('đ', 'd')
    folded = ''.join(c for c in folded if not unicodedata.combining(c))
    return re.findall(r'[a-z0-9]+', folded)


def _features(text):
    raw = tokens(str(text or '')[:MAX_FIELD_CHARS])
    terms = Counter(t for t in raw if t not in COMMON and not t.isdigit())
    # Adjacent in the original text, never glued after removing stopwords.
    pairs = {tuple(raw[i:i+2]) for i in range(len(raw)-1)
             if raw[i] in terms and raw[i+1] in terms}
    return terms, pairs


def _identity(card):
    normalize = lambda value: ' '.join(unicodedata.normalize('NFC', value).casefold().split())
    return normalize(card.term), tuple(re.findall(r'[^\W_]+', normalize(card.meaning_vi)))


@dataclass
class _Document:
    card: object
    meaning: Counter
    meaning_pairs: set
    example: Counter
    example_pairs: set


def rank_description(cards, query, limit=MAX_CANDIDATES):
    """Return up to three (card, lexical_score) suggestions with source support.

    Meaning support is mandatory. Generic examples or broad topics cannot
    produce a hit. Repeated duplicate cards do not inflate document frequency.
    All matches remain candidates, even an apparent exact meaning overlap.
    """
    query_terms, query_pairs = _features(str(query or '')[:MAX_QUERY_CHARS])
    if not query_terms or limit <= 0:
        return []
    documents, seen = [], set()
    for card in cards:
        identity = _identity(card)
        if identity in seen:
            continue
        seen.add(identity)
        meaning, meaning_pairs = _features(card.meaning_vi)
        example, example_pairs = _features(card.example_vi)
        documents.append(_Document(card, meaning, meaning_pairs, example, example_pairs))
    if not documents:
        return []
    n = len(documents)
    frequency = Counter(term for doc in documents for term in doc.meaning)
    example_frequency = Counter(term for doc in documents for term in doc.example)
    avg_meaning = sum(sum(doc.meaning.values()) for doc in documents)/n or 1
    avg_example = sum(sum(doc.example.values()) for doc in documents)/n or 1

    def idf(term, frequencies):
        df = frequencies.get(term, 0)
        return math.log1p((n-df+.5)/(df+.5))

    def bm25(counts, frequencies, average):
        length = sum(counts.values())
        normalization = 1.2 * (.25 + .75 * length/average)
        return sum(idf(term, frequencies) * counts[term]*2.2/(counts[term]+normalization)
                   for term in query_terms if counts[term])

    ranked = []
    for doc in documents:
        hits = set(query_terms) & doc.meaning.keys()
        if not hits:
            continue
        # An example may reinforce a rare definition token, never stand alone.
        rare_definition = any(frequency[t] <= max(1, n*.1) for t in hits)
        example_phrase = bool(query_pairs & doc.example_pairs)
        if len(hits) < 2 and not (rare_definition and example_phrase):
            continue
        score = 3 * bm25(doc.meaning, frequency, avg_meaning)
        score += .5 * bm25(doc.example, example_frequency, avg_example)
        score += sum(idf(a,frequency)+idf(b,frequency) for a,b in query_pairs & doc.meaning_pairs)
        if score > 0:
            ranked.append((doc.card, round(score, 8)))
    return sorted(ranked, key=lambda row: (-row[1], row[0].pk))[:min(int(limit),MAX_CANDIDATES)]
