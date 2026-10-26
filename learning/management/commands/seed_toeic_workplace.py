"""Create-only, original workplace collocations and contextual practice."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from learning.models import AnswerOption, Flashcard, LearningContent, Question
from learning.vocabulary_catalog import answer_pattern, normalize_term

PACK_PATH = Path(__file__).resolve().parents[2] / 'data' / 'toeic_workplace_pack.json'
SOURCE = 'LinguaPath · Workplace v1 · nội dung gốc có AI hỗ trợ'
RIGHTS = 'Nghĩa, ví dụ và bài tập tự biên soạn. CEFR tạm thời, chưa giáo viên duyệt; không phải học liệu Cambridge/ETS chính thức.'
TOPICS = {
    'Office collaboration': 'Cộng tác văn phòng',
    'Finance and purchasing': 'Tài chính và mua sắm',
    'Business travel': 'Đi công tác',
    'People and careers': 'Nhân sự và nghề nghiệp',
}


def validate_pack(entries):
    if not isinstance(entries, list) or len(entries) != 40:
        raise ValueError('Bộ Workplace v1 cần đúng 40 mục.')
    terms, ids, counts = set(), set(), Counter()
    fields = ('id', 'topic', 'term', 'meaning_vi', 'cefr_level', 'part_of_speech',
              'example_en', 'example_vi', 'cloze_answer', 'explanation_vi')
    for entry in entries:
        if not isinstance(entry, dict) or any(not isinstance(entry.get(k), str) or not entry[k].strip() for k in fields):
            raise ValueError('Mỗi mục phải có đủ định danh, nghĩa, ví dụ song ngữ và lời giải.')
        term, identifier = normalize_term(entry['term']), entry['id']
        if term in terms or identifier in ids:
            raise ValueError('Không được trùng từ hoặc định danh trong bộ.')
        if entry['topic'] not in TOPICS or entry['cefr_level'] not in ('B1', 'B2'):
            raise ValueError('Chủ đề hoặc mức CEFR không hợp lệ.')
        for key, limit in {'term': 120, 'meaning_vi': 240, 'part_of_speech': 40, 'topic': 80}.items():
            if len(entry[key]) > limit:
                raise ValueError(f'{identifier}: {key} quá dài.')
        if any('<' in entry[key] or '>' in entry[key] for key in fields):
            raise ValueError('Không chấp nhận HTML trong học liệu.')
        if len(answer_pattern(entry['term']).findall(entry['example_en'])) != 1:
            raise ValueError(f'{identifier}: cụm từ phải xuất hiện đúng một lần trong ví dụ.')
        if len(answer_pattern(entry['cloze_answer']).findall(entry['example_en'])) != 1:
            raise ValueError(f'{identifier}: từ điền phải xuất hiện đúng một lần trong ví dụ.')
        for decoy_key, correct in [('meaning_distractors', entry['meaning_vi']), ('cloze_distractors', entry['cloze_answer'])]:
            decoys = entry.get(decoy_key)
            if not isinstance(decoys, list) or len(decoys) != 3 or any(not isinstance(v, str) or not v.strip() for v in decoys):
                raise ValueError(f'{identifier}: cần ba phương án nhiễu cho từng dạng bài.')
            if len({normalize_term(value) for value in [correct, *decoys]}) != 4:
                raise ValueError(f'{identifier}: các phương án phải khác nhau.')
        ids.add(identifier)
        terms.add(term)
        counts[entry['topic']] += 1
    if counts != Counter({topic: 10 for topic in TOPICS}):
        raise ValueError('Mỗi chủ đề cần đúng 10 mục.')
    return entries


def load_pack(path=None):
    with Path(path or PACK_PATH).open(encoding='utf-8') as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict) or payload.get('version') != 1:
        raise ValueError('Không nhận dạng được phiên bản bộ học liệu.')
    return validate_pack(payload.get('entries'))


def rotated_choices(correct, decoys, identifier):
    choices = [(correct, True), *((value, False) for value in decoys)]
    shift = int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16) % 4
    return choices[shift:] + choices[:shift]


class Command(BaseCommand):
    help = 'Thêm 40 cụm từ công việc và 80 câu luyện gốc; giữ nguyên các chỉnh sửa đã có.'

    def add_arguments(self, parser):
        parser.add_argument('--publish-provisional', action='store_true', help='Xuất bản sơ bộ nội dung có AI hỗ trợ, chưa giáo viên duyệt.')
        parser.add_argument('--dry-run', action='store_true', help='Chỉ kiểm tra cấu trúc dữ liệu; không ghi database.')

    def handle(self, *args, **options):
        try:
            entries = load_pack()
        except (OSError, ValueError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write('Workplace v1: 40 cụm từ · 4 chủ đề · 80 câu luyện · CEFR tham khảo B1/B2.')
        if options['dry_run']:
            return
        groups = defaultdict(list)
        for entry in entries:
            groups[entry['topic']].append(entry)
        created = skipped = 0
        with transaction.atomic():
            existing = {normalize_term(term) for term in Flashcard.objects.exclude(
                content__question_type__startswith='lp-workplace-v1-'
            ).values_list('term', flat=True)}
            overlap = existing & {normalize_term(row['term']) for row in entries}
            if overlap:
                raise CommandError('Cụm từ trùng bộ khác; chưa thay đổi dữ liệu: ' + ', '.join(sorted(overlap)))
            for group_index, (topic, topic_vi) in enumerate(TOPICS.items(), 1):
                rows = groups[topic]
                for kind, label in [('deck', 'Thẻ từ'), ('meaning', 'Chọn nghĩa trong ngữ cảnh'), ('cloze', 'Điền từ')]:
                    identifier = f'lp-workplace-v1-{group_index:02d}-{kind}'
                    if LearningContent.objects.filter(question_type=identifier).exists():
                        skipped += 1
                        continue
                    publish = options['publish_provisional']
                    content = LearningContent.objects.create(
                        title=f'Workplace · {topic_vi} · {label}',
                        description=f'10 cụm từ trong ngữ cảnh công việc · {label.lower()}. CEFR B1/B2 là nhãn tham khảo, chưa được giáo viên duyệt.',
                        exam_type='TOEIC', content_type='vocabulary', skill='vocabulary',
                        question_type=identifier, topic=topic, cefr_level='B2', difficulty=2,
                        estimated_minutes=5 if kind == 'deck' else 7,
                        source_name=SOURCE, rights_note=RIGHTS,
                        review_status='language_checked' if publish else 'draft',
                        reviewer='AI hỗ trợ soạn và kiểm tra cấu trúc; chưa giáo viên duyệt' if publish else '',
                        reviewed_at=timezone.now() if publish else None,
                        review_note='Cần người có chuyên môn rà soát nghĩa, ví dụ, mức CEFR và độ khó phương án nhiễu.',
                        is_published=publish,
                    )
                    for order, row in enumerate(rows, 1):
                        if kind == 'deck':
                            Flashcard.objects.create(
                                content=content, order=order, source_name=SOURCE, rights_note=RIGHTS,
                                **{key: row[key] for key in ('term', 'meaning_vi', 'cefr_level', 'part_of_speech', 'example_en', 'example_vi', 'topic')},
                            )
                            continue
                        is_meaning = kind == 'meaning'
                        correct = row['meaning_vi'] if is_meaning else row['cloze_answer']
                        decoys = row['meaning_distractors'] if is_meaning else row['cloze_distractors']
                        passage = row['example_en'] if is_meaning else answer_pattern(row['cloze_answer']).sub('_____', row['example_en'], count=1)
                        explanation = f'{row["explanation_vi"]} Câu đầy đủ: {row["example_en"]} — {row["example_vi"]}'
                        question = Question.objects.create(
                            content=content, order=order,
                            prompt=f'Trong câu trên, “{row["term"]}” có nghĩa là gì?' if is_meaning else 'Chọn từ phù hợp để hoàn thành cụm từ trong câu.',
                            passage=passage, explanation=explanation, explanation_vi=explanation,
                        )
                        for label_key, (text, is_correct) in zip('ABCD', rotated_choices(correct, decoys, row['id'] + kind)):
                            AnswerOption.objects.create(
                                question=question, label=label_key, text=text, is_correct=is_correct,
                                explanation_vi=row['explanation_vi'] if is_correct else (
                                    f'“{text}” không diễn đạt nghĩa “{row["meaning_vi"]}” của cụm từ trong câu.' if is_meaning else
                                    f'“{text}” không tạo cụm từ mang nghĩa “{row["meaning_vi"]}” trong ngữ cảnh này. Cụm cần dùng: {row["term"]}.'
                                ),
                            )
                    created += 1
        self.stdout.write(self.style.SUCCESS(f'Tạo {created} bộ mới; giữ nguyên {skipped} bộ đã có. Không ghi đè nội dung đã chỉnh sửa.'))
