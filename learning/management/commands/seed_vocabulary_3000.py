"""Create-only seed: never overwrite teacher edits or learner history."""
import hashlib
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from learning.models import AnswerOption, Flashcard, LearningContent, Question
from learning.vocabulary_catalog import balanced_batches, chapter_for_topic, cloze_sentence, load_catalog, normalize_term


SOURCE = 'LinguaPath · nội dung gốc do AI hỗ trợ biên soạn'
RIGHTS = 'Nghĩa, ví dụ và bài tập tự biên soạn; không sao chép Cambridge. CEFR tạm thời, chưa giáo viên duyệt.'


def rotated_options(correct, decoys, key):
    if len(decoys) != 3 or len({normalize_term(value) for value in [correct, *decoys]}) != 4:
        raise CommandError('Mỗi câu cần một đáp án và ba phương án nhiễu khác nhau.')
    choices = [(correct, True), *((value, False) for value in decoys)]
    shift = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 4
    return choices[shift:] + choices[:shift]


class Command(BaseCommand):
    help = 'Thêm 2000 từ gốc +4000 câu luyện để mở rộng kho lên 3000+; không phải bộ Cambridge chính thức.'

    def add_arguments(self, parser):
        parser.add_argument('--publish-provisional', action='store_true', help='Cho phép dùng bản AI rà soát sơ bộ, chưa giáo viên duyệt.')
        parser.add_argument('--dry-run', action='store_true', help='Kiểm tra dữ liệu, không ghi database.')

    def handle(self, *args, **options):
        try:
            rows = load_catalog()
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Catalog: {len(rows)} từ; mức tạm thời: {dict(Counter(r['cefr_level'] for r in rows))}")
        if options['dry_run']:
            return
        groups = defaultdict(list)
        meanings = {}
        for row in rows:
            groups[(row['cefr_level'], chapter_for_topic(row['topic']))].append(row)
            meanings[normalize_term(row['term'])] = row['meaning_vi']
            meanings.setdefault(normalize_term(row['cloze_answer']), row['meaning_vi'])
        created = skipped = 0
        with transaction.atomic():
            # Existing managed decks are never updated, including human edits.
            # Run a single seed process; titles are not a database unique key.
            existing_terms = {normalize_term(term) for term in Flashcard.objects.exclude(content__question_type='lp3000-v1-deck').values_list('term', flat=True)}
            overlap = existing_terms & {normalize_term(row['term']) for row in rows}
            if overlap:
                raise CommandError('Từ bổ sung trùng dữ liệu ngoài catalog: ' + ', '.join(sorted(overlap)[:12]))
            for (level, topic), group in sorted(groups.items()):
                group.sort(key=lambda row: (row['topic'], normalize_term(row['term'])))
                for batch, entries in enumerate(balanced_batches(group), 1):
                    for kind, label in [('deck', 'Thẻ từ'), ('meaning', 'Chọn nghĩa'), ('cloze', 'Điền từ')]:
                        title = f'Bổ sung {level} · {topic} · {label} {batch:02d}'
                        if LearningContent.objects.filter(title=title, exam_type='TOEIC', content_type='vocabulary').exists():
                            skipped += 1
                            continue
                        published = options['publish_provisional']
                        content = LearningContent.objects.create(
                            title=title, exam_type='TOEIC', content_type='vocabulary', skill='vocabulary',
                            topic=topic, cefr_level=level, question_type=f'lp3000-v1-{kind}',
                            difficulty=1 if level in ('A1', 'A2') else 2 if level == 'B1' else 3,
                            estimated_minutes=max(3, round(len(entries) * (0.4 if kind != 'cloze' else 0.6))),
                            description=f'{len(entries)} mục · {label.lower()} theo chủ đề. Nội dung tự biên soạn có AI hỗ trợ; CEFR tạm thời, chưa giáo viên duyệt. Không phải đề Cambridge/TOEIC/IELTS chính thức.',
                            source_name=SOURCE, rights_note=RIGHTS,
                            review_status='language_checked' if published else 'draft',
                            reviewer='AI kiểm tra cấu trúc và tự rà soát; chưa giáo viên duyệt' if published else '',
                            reviewed_at=timezone.now() if published else None,
                            review_note='Câu/nghĩa/distractor cần giáo viên kiểm tra; không xác nhận đối chiếu từng mục với Cambridge.',
                            is_published=published,
                        )
                        if kind == 'deck':
                            for index, row in enumerate(entries, 1):
                                Flashcard.objects.create(
                                    content=content, order=index, source_name=SOURCE, rights_note=RIGHTS,
                                    **{key: row[key] for key in ('term', 'cefr_level', 'part_of_speech', 'meaning_vi', 'example_en', 'example_vi', 'topic')},
                                )
                        else:
                            for index, row in enumerate(entries, 1):
                                correct = row['meaning_vi'] if kind == 'meaning' else row['cloze_answer']
                                if kind == 'meaning':
                                    # Reuse author-selected contextual alternatives
                                    # when their meanings exist in this catalog.
                                    decoys = []
                                    for index_decoy in range(1, 4):
                                        value = meanings.get(normalize_term(row[f'distractor_{index_decoy}']))
                                        if value and value != correct and value not in decoys:
                                            decoys.append(value)
                                    for pool in (
                                        [other['meaning_vi'] for other in rows if other['topic'] == row['topic'] and other['part_of_speech'] == row['part_of_speech']],
                                        [other['meaning_vi'] for other in rows if other['part_of_speech'] == row['part_of_speech']],
                                        [other['meaning_vi'] for other in rows],
                                    ):
                                        if len(decoys) == 3:
                                            break
                                        for value in sorted(set(pool), key=lambda value: hashlib.sha256((row['term'] + value).encode()).hexdigest()):
                                            if value != correct and value not in decoys:
                                                decoys.append(value)
                                            if len(decoys) == 3:
                                                break
                                        if len(decoys) == 3:
                                            break
                                    if len(decoys) != 3:
                                        raise CommandError('Không đủ phương án nghĩa khác nhau để tạo bài luyện.')
                                else:
                                    decoys = [row[f'distractor_{i}'] for i in range(1, 4)]
                                question = Question.objects.create(
                                    content=content, order=index,
                                    prompt=f'Trong câu trên, “{row["term"]}” có nghĩa gần nhất là gì?' if kind == 'meaning' else 'Chọn từ phù hợp để hoàn thành câu.',
                                    passage=row['example_en'] if kind == 'meaning' else cloze_sentence(row),
                                    explanation=f'{row["term"]}: {row["meaning_vi"]}. {row["example_en"]}',
                                    explanation_vi=f'Đáp án: {correct}. {row["term"]} nghĩa là “{row["meaning_vi"]}”. Câu đầy đủ: {row["example_en"]} — {row["example_vi"]}',
                                )
                                for label_key, (value, is_correct) in zip('ABCD', rotated_options(correct, decoys, row['term'] + kind)):
                                    AnswerOption.objects.create(
                                        question=question, label=label_key, text=value, is_correct=is_correct,
                                        explanation_vi=f'{value}: phù hợp với nghĩa và ngữ cảnh câu đã cho.' if is_correct else f'“{value}” không phải lựa chọn mục tiêu ở câu này. Đối chiếu câu đầy đủ và bản dịch trong lời giải.',
                                    )
                        created += 1
        self.stdout.write(self.style.SUCCESS(f'Tạo {created} bộ, giữ nguyên {skipped} bộ đã có. Không ghi đè nội dung đã chỉnh sửa.'))
