"""Offline vocabulary retrieval metrics; no model requests or learner logs."""
import json
import unicodedata
from collections import defaultdict
from pathlib import Path


BENCHMARK_PATH = Path(__file__).resolve().parent / 'data' / 'retrieval_benchmark.json'


def _sense_text(value):
    """Normalize only typography, never accents, punctuation or synonyms.

    A sense label is the source's literal meaning, not semantic similarity.
    Vietnamese ``ma`` and ``má`` must remain different labels.
    """
    return ' '.join(unicodedata.normalize('NFC', value).casefold().split()) if isinstance(value, str) else ''


def _sense_identity(value):
    return (_sense_text(value.get('term')), _sense_text(value.get('meaning_vi')))


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('JSON benchmark có khóa trùng.')
        result[key] = value
    return result


def load_benchmark(path=BENCHMARK_PATH):
    def reject_constant(value):
        raise ValueError('JSON benchmark chứa giá trị số không hữu hạn.')
    data = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_strict_object,
                      parse_constant=reject_constant)
    if not isinstance(data, dict):
        raise ValueError('Benchmark phải là JSON object.')
    cases = data.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Benchmark thiếu danh sách truy vấn.')
    seen = set()
    term_splits = defaultdict(set)
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id'].strip() or case['id'] in seen:
            raise ValueError('ID benchmark không hợp lệ hoặc trùng.')
        seen.add(case['id'])
        if case.get('split') not in {'dev', 'test'} or not isinstance(case.get('query'), str) or not case['query'].strip():
            raise ValueError('Split hoặc truy vấn không hợp lệ.')
        if not isinstance(case.get('category'), str) or not case['category'].strip():
            raise ValueError('Category benchmark không hợp lệ.')
        gold = case.get('expected_terms')
        if not isinstance(gold, list) or any(not isinstance(term, str) or not term.strip() for term in gold):
            raise ValueError('Nhãn nguồn phải là danh sách mục từ.')
        normalized_gold = {_sense_text(term) for term in gold}
        if len(normalized_gold) != len(gold):
            raise ValueError('Nhãn mục từ bị trùng.')
        if 'expected_senses' in case:
            senses = case['expected_senses']
            if not gold or not isinstance(senses, list) or not senses:
                raise ValueError('Nhãn nghĩa cần danh sách không rỗng cho truy vấn dương.')
            seen_senses = set()
            for sense in senses:
                if (not isinstance(sense, dict) or set(sense) != {'term', 'meaning_vi'}
                        or any(not isinstance(sense[field], str) or not sense[field].strip()
                               for field in ('term', 'meaning_vi'))):
                    raise ValueError('Nhãn nghĩa phải có đúng term và meaning_vi không rỗng.')
                identity = _sense_identity(sense)
                if identity[0] not in normalized_gold:
                    raise ValueError('Mục từ của nhãn nghĩa không thuộc expected_terms.')
                if identity in seen_senses:
                    raise ValueError('Nhãn nghĩa bị trùng.')
                seen_senses.add(identity)
        if 'ambiguity_required' in case and (type(case['ambiguity_required']) is not bool or not gold):
            raise ValueError('Nhãn ambiguity_required phải là boolean cho truy vấn dương.')
        for term in gold:
            term_splits[_sense_text(term)].add(case['split'])
    if any(len(splits) > 1 for splits in term_splits.values()):
        raise ValueError('Một mục từ không được xuất hiện ở cả dev và test.')
    return data


def evaluate_cases(cases, retriever):
    records = []
    for case in cases:
        retrieved = retriever(case['query'], limit=3)
        terms = [str(item.get('term') or '').strip().casefold() for item in retrieved[:3]]
        gold = {term.strip().casefold() for term in case['expected_terms']}
        relevant = gold.intersection(terms)
        first_rank = next((rank for rank, term in enumerate(terms, 1) if term in gold), None)
        senses = [{field: item.get(field) if isinstance(item.get(field), str) else None
                   for field in ('term', 'meaning_vi')} for item in retrieved[:3]]
        gold_senses = {_sense_identity(sense) for sense in case.get('expected_senses', [])}
        retrieved_senses = [_sense_identity(sense) for sense in senses]
        relevant_senses = gold_senses.intersection(retrieved_senses)
        sense_rank = next((rank for rank, sense in enumerate(retrieved_senses, 1) if sense in gold_senses), None)
        top_ambiguous = bool(retrieved and retrieved[0].get('ambiguous') is True)
        ambiguity_required = case.get('ambiguity_required')
        records.append({
            'id': case['id'], 'split': case['split'], 'category': case['category'],
            'query': case['query'], 'expected_terms': case['expected_terms'],
            'retrieved_terms': [item.get('term') for item in retrieved[:3]],
            'expected_senses': case.get('expected_senses'), 'retrieved_senses': senses,
            'sense_labeled': bool(gold_senses),
            'sense_recall_at_3': len(relevant_senses) / len(gold_senses) if gold_senses else None,
            'sense_hit_at_3': bool(relevant_senses) if gold_senses else None,
            'sense_reciprocal_rank_at_3': (1 / sense_rank if sense_rank else 0) if gold_senses else None,
            'ambiguity_required': ambiguity_required, 'retrieved_top_ambiguous': top_ambiguous,
            'ambiguity_matches': bool(retrieved) and top_ambiguous == ambiguity_required if ambiguity_required is not None else None,
            'positive': bool(gold), 'empty': not retrieved,
            'recall_at_3': len(relevant) / len(gold) if gold else None,
            'hit_at_3': bool(relevant), 'reciprocal_rank_at_3': 1 / first_rank if first_rank else 0,
        })
    return {
        'overall': summarize(records),
        'by_split': {split: summarize([r for r in records if r['split'] == split]) for split in ('dev', 'test')},
        'by_category': {category: summarize([r for r in records if r['category'] == category]) for category in sorted({r['category'] for r in records})},
        'cases': records,
    }


def summarize(records):
    positives = [r for r in records if r['positive']]
    negatives = [r for r in records if not r['positive']]
    abstentions = [r for r in records if r['empty']]
    true_abstentions = sum(r['empty'] for r in negatives)
    sense_labeled = [r for r in records if r.get('sense_labeled')]
    ambiguity_labeled = [r for r in records if r.get('ambiguity_required') is not None]
    mean = lambda key: round(sum(r[key] for r in positives) / len(positives), 4) if positives else None
    sense_mean = lambda key: round(sum(r[key] for r in sense_labeled) / len(sense_labeled), 4) if sense_labeled else None
    return {
        'queries': len(records), 'positive_queries': len(positives), 'negative_queries': len(negatives),
        'recall_at_3': mean('recall_at_3'), 'hit_at_3': mean('hit_at_3'),
        'mrr_at_3': mean('reciprocal_rank_at_3'),
        'negative_abstention_rate': round(true_abstentions / len(negatives), 4) if negatives else None,
        'abstention_precision': round(true_abstentions / len(abstentions), 4) if abstentions else None,
        'false_positive_negatives': sum(not r['empty'] for r in negatives),
        'sense_labeled_queries': len(sense_labeled),
        'sense_recall_at_3': sense_mean('sense_recall_at_3'),
        'sense_hit_at_3': sense_mean('sense_hit_at_3'),
        'sense_mrr_at_3': sense_mean('sense_reciprocal_rank_at_3'),
        'ambiguity_labeled_queries': len(ambiguity_labeled),
        # This is a separate decision check, not answer/sense correctness.
        'ambiguity_accuracy': round(sum(r['ambiguity_matches'] for r in ambiguity_labeled) / len(ambiguity_labeled), 4) if ambiguity_labeled else None,
    }
