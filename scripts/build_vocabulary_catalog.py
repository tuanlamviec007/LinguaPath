"""Build a deterministic 2000-item extension from original authoring batches."""
import csv
import json
import sys
from collections import Counter
from itertools import zip_longest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from learning.vocabulary_catalog import COLUMNS, LEVELS, normalize_term, validate_rows

DATA = ROOT / 'learning' / 'data'
FOLDER = DATA / 'vocabulary_3000'
FILES = ('home_people_food.csv', 'travel_nature.csv', 'study_culture.csv', 'work_services.csv', 'science_health.csv', 'actions_descriptions.csv')
SPELLING = {'colour': 'color', 'favourite': 'favorite', 'neighbour': 'neighbor', 'centre': 'center', 'theatre': 'theater', 'traveller': 'traveler', 'organise': 'organize', 'recognise': 'recognize', 'analyse': 'analyze', 'apologise': 'apologize', 'behaviour': 'behavior', 'labour': 'labor', 'honour': 'honor', 'humour': 'humor', 'catalogue': 'catalog', 'jewellery': 'jewelry', 'grey': 'gray'}


def canonical(term):
    term = normalize_term(term)
    return SPELLING.get(term, term)


def main():
    baseline = {canonical(term) for term in (DATA / 'existing_terms_1000.txt').read_text().splitlines() if term.strip()}
    batches = []
    for filename in FILES:
        with (FOLDER / filename).open(encoding='utf-8-sig', newline='') as stream:
            rows = validate_rows(list(csv.DictReader(stream)))
        batches.append(sorted(rows, key=lambda row: (LEVELS.index(row['cefr_level']), canonical(row['term']))))
    seen, examples, selected, excluded = set(baseline), set(), [], []
    for group in zip_longest(*batches):
        for row in group:
            if row is None:
                continue
            term, sentence = canonical(row['term']), normalize_term(row['example_en'])
            reason = 'duplicate_or_baseline' if term in seen else 'duplicate_example' if sentence in examples else ''
            if reason:
                excluded.append({'term': row['term'], 'reason': reason})
                continue
            seen.add(term)
            examples.add(sentence)
            if len(selected) < 2000:
                selected.append(row)
    validate_rows(selected, expected_count=2000)
    selected.sort(key=lambda row: (LEVELS.index(row['cefr_level']), row['topic'], normalize_term(row['term'])))
    with (FOLDER / 'selected_2000.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(selected)
    report = {
        'baseline_distinct': len(baseline), 'authored_rows': sum(map(len, batches)),
        'extension_rows': len(selected), 'projected_distinct_at_least': len(baseline) + len(selected),
        'cefr_provisional': dict(Counter(row['cefr_level'] for row in selected)),
        'topics': dict(sorted(Counter(row['topic'] for row in selected).items())),
        'exclusions': excluded, 'human_approved': False,
        'notes': 'Structural validation and AI authoring only. Not an official Cambridge list. CEFR and distractors require expert review.',
    }
    (FOLDER / 'catalog_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key not in ('topics', 'exclusions')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
