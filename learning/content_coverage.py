"""Read-only inventory for editorial planning; never certifies language quality.

Three batched queries keep parent counts separate from child counts, so a deck
with cards and questions cannot multiply either side through a SQL cross join.
No learner/session/history models are read and no answer text is returned.
"""
from collections import Counter, defaultdict

from django.db.models import Count, Q, Value
from django.db.models.functions import Trim
from django.db.models.lookups import Exact
from django.utils import timezone

from .models import CEFR_LEVELS, Flashcard, LearningContent, LEARNER_REVIEW_STATUSES, Question


COVERAGE_VERSION = 'editorial-coverage-v2'
_LEVELS = {key for key, _ in CEFR_LEVELS}


def _blank(value):
    return not isinstance(value, str) or not value.strip()


def content_coverage(exam='TOEIC'):
    """Return aggregate source metadata and structural flags, without writes.

    ``visible`` means published with a learner-allowed review status. It is not
    an authorization to disclose question answers: those still require the
    learner's submitted attempt. CEFR and question_type are stored labels, not
    independently calibrated difficulty or an inferred official TOEIC Part.
    """
    if exam not in dict(LearningContent.EXAMS):
        raise ValueError('Exam must be TOEIC or IELTS.')
    parents = {}
    groups = defaultdict(lambda: {'contents': 0, 'cards': 0, 'questions': 0})
    types = defaultdict(lambda: {'contents': 0, 'questions': 0, 'visible_questions': 0})
    levels = defaultdict(lambda: {'cards': 0, 'visible_cards': 0})
    skill_level_questions = Counter()
    structural = {
        'content': Counter({key: 0 for key in ('skill_type_mismatch', 'missing_source_or_rights',
            'teacher_approval_missing_reviewer_or_time', 'empty_content')}),
        'question': Counter({key: 0 for key in ('blank_prompt', 'fewer_than_two_options',
            'not_exactly_one_correct_option', 'missing_explanation', 'has_blank_option_text',
            'has_missing_option_explanation', 'listening_without_audio_or_script')}),
        'flashcard': Counter({key: 0 for key in ('blank_term_or_meaning', 'missing_english_example',
            'missing_vietnamese_example', 'missing_source_or_rights')}),
    }
    metadata = Counter({key: 0 for key in ('contents_without_cefr', 'contents_with_unrecognized_cefr',
        'question_type_unclassified_contents', 'contents_with_unrecognized_skill',
        'contents_with_unrecognized_review_status', 'cards_with_unrecognized_cefr',
        'child_rows_without_loaded_parent')})
    totals = Counter(contents=0, published_contents=0, visible_contents=0, cards=0, questions=0,
                     visible_cards=0, visible_questions=0, teacher_approved_contents=0, held_cards=0)
    parent_rows = LearningContent.objects.filter(exam_type=exam).order_by('pk').values(
        'id', 'skill', 'content_type', 'cefr_level', 'review_status', 'is_published',
        'question_type', 'source_name', 'rights_note', 'reviewer', 'reviewed_at',
    )
    for row in parent_rows.iterator(chunk_size=200):
        row['visible'] = row['is_published'] and row['review_status'] in LEARNER_REVIEW_STATUSES
        row['group'] = (row['skill'], row['content_type'], row['cefr_level'], row['review_status'], row['is_published'])
        row['cards'] = row['questions'] = 0
        parents[row['id']] = row
        groups[row['group']]['contents'] += 1
        types[row['question_type']]['contents'] += 1
        totals['contents'] += 1
        totals['published_contents'] += int(row['is_published'])
        totals['visible_contents'] += int(row['visible'])
        totals['teacher_approved_contents'] += int(row['review_status'] == 'teacher_approved')
        metadata['contents_without_cefr'] += int(_blank(row['cefr_level']))
        metadata['contents_with_unrecognized_cefr'] += int(bool(row['cefr_level']) and row['cefr_level'] not in _LEVELS)
        metadata['question_type_unclassified_contents'] += int(_blank(row['question_type']))
        metadata['contents_with_unrecognized_skill'] += int(row['skill'] not in dict(LearningContent.SKILLS))
        metadata['contents_with_unrecognized_review_status'] += int(row['review_status'] not in dict(LearningContent.REVIEW_STATUS))
        structural['content']['skill_type_mismatch'] += int(row['skill'] != row['content_type'])
        structural['content']['missing_source_or_rights'] += int(_blank(row['source_name']) or _blank(row['rights_note']))
        structural['content']['teacher_approval_missing_reviewer_or_time'] += int(
            row['review_status'] == 'teacher_approved' and (_blank(row['reviewer']) or row['reviewed_at'] is None))

    # Only one child relation is joined in this query. Option counts are per
    # question, never combined with Flashcard joins.
    question_rows = Question.objects.filter(content__exam_type=exam).order_by('pk').annotate(
        option_count=Count('options'),
        correct_option_count=Count('options', filter=Q(options__is_correct=True)),
        blank_option_count=Count('options', filter=Q(Exact(Trim('options__text'), Value('')))),
        blank_option_explanations=Count('options', filter=Q(Exact(Trim('options__explanation_vi'), Value('')))),
    ).values('content_id', 'prompt', 'explanation', 'explanation_vi', 'audio_url', 'audio_script',
             'option_count', 'correct_option_count', 'blank_option_count', 'blank_option_explanations')
    for row in question_rows.iterator(chunk_size=200):
        parent = parents.get(row['content_id'])
        if parent is None:
            metadata['child_rows_without_loaded_parent'] += 1
            continue
        parent['questions'] += 1
        groups[parent['group']]['questions'] += 1
        types[parent['question_type']]['questions'] += 1
        types[parent['question_type']]['visible_questions'] += int(parent['visible'])
        totals['questions'] += 1
        totals['visible_questions'] += int(parent['visible'])
        if parent['visible']:
            skill_level_questions[(parent['skill'], parent['cefr_level'])] += 1
        structural['question']['blank_prompt'] += int(_blank(row['prompt']))
        structural['question']['fewer_than_two_options'] += int(row['option_count'] < 2)
        structural['question']['not_exactly_one_correct_option'] += int(row['correct_option_count'] != 1)
        structural['question']['missing_explanation'] += int(_blank(row['explanation']) and _blank(row['explanation_vi']))
        structural['question']['has_blank_option_text'] += int(row['blank_option_count'] > 0)
        structural['question']['has_missing_option_explanation'] += int(row['blank_option_explanations'] > 0)
        structural['question']['listening_without_audio_or_script'] += int(
            parent['content_type'] == 'listening' and _blank(row['audio_url']) and _blank(row['audio_script']))

    card_rows = Flashcard.objects.filter(content__exam_type=exam).order_by('pk').values(
        'content_id', 'cefr_level', 'term', 'meaning_vi', 'example_en', 'example_vi', 'source_name', 'rights_note', 'is_available')
    for row in card_rows.iterator(chunk_size=200):
        parent = parents.get(row['content_id'])
        if parent is None:
            metadata['child_rows_without_loaded_parent'] += 1
            continue
        parent['cards'] += 1
        groups[parent['group']]['cards'] += 1
        levels[row['cefr_level']]['cards'] += 1
        levels[row['cefr_level']]['visible_cards'] += int(parent['visible'] and row['is_available'])
        totals['cards'] += 1
        totals['visible_cards'] += int(parent['visible'] and row['is_available'])
        totals['held_cards'] += int(not row['is_available'])
        metadata['cards_with_unrecognized_cefr'] += int(row['cefr_level'] not in _LEVELS)
        structural['flashcard']['blank_term_or_meaning'] += int(_blank(row['term']) or _blank(row['meaning_vi']))
        structural['flashcard']['missing_english_example'] += int(_blank(row['example_en']))
        structural['flashcard']['missing_vietnamese_example'] += int(_blank(row['example_vi']))
        structural['flashcard']['missing_source_or_rights'] += int(_blank(row['source_name']) or _blank(row['rights_note']))
    structural['content']['empty_content'] = sum(not row['cards'] and not row['questions'] for row in parents.values())

    content_groups = [dict(zip(('skill', 'content_type', 'cefr_level', 'review_status', 'is_published'), key)) | values
                      for key, values in sorted(groups.items())]
    gaps = [{'skill': skill, 'cefr_level': level, 'visible_questions': 0,
             'reason': 'No published learner-visible question is labelled with this skill/level.'}
            for skill in ('reading', 'listening') for level, _ in CEFR_LEVELS
            if not skill_level_questions[(skill, level)]]
    return {
        'version': COVERAGE_VERSION, 'generated_at': timezone.now().isoformat(), 'exam': exam,
        'scope': 'Source-library inventory only; stored labels and structural flags, not teacher approval, CEFR calibration, official TOEIC Part coverage or learner analytics.',
        'visible_definition': 'Published with language_checked or teacher_approved; cards must also be individually available; does not release question answers to a learner.',
        'totals': dict(totals), 'content_groups': content_groups,
        'card_levels': [{'cefr_level': key, **values} for key, values in sorted(levels.items())],
        'question_types': [{'question_type': key, **values} for key, values in sorted(types.items())],
        'structural': {kind: dict(flags) for kind, flags in structural.items()},
        'metadata': dict(metadata), 'gaps': gaps,
        'limitations': [
            'Counts do not judge sense, distractor plausibility, answer correctness or rights validity.',
            'Question type values are raw metadata; no official TOEIC Part is inferred.',
            'Blank/unrecognized labels remain explicit and are not assigned a level automatically.',
            'The three read queries are not one database snapshot; export during an editorial freeze for a stable inventory.',
        ],
    }
