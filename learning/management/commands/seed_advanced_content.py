"""Load original B1/B2 practice; CEFR bands are editorial estimates."""
import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from learning.models import AnswerOption, LearningContent, Question


DATA_PATH = Path(__file__).resolve().parents[2] / 'data' / 'advanced_lessons.json'


def load_lessons(path=DATA_PATH):
    try:
        lessons = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CommandError('Không đọc được bộ bài luyện nâng cao.') from exc
    if not isinstance(lessons, list) or not lessons:
        raise CommandError('Bộ bài luyện phải là một danh sách không rỗng.')
    titles, slugs = set(), set()
    for lesson in lessons:
        if not isinstance(lesson, dict):
            raise CommandError('Mỗi bài phải là một đối tượng dữ liệu.')
        title, slug = lesson.get('title', ''), lesson.get('slug', '')
        if not title or title in titles or slug in slugs or not re.fullmatch(r'[a-z0-9-]+', slug):
            raise CommandError('Tên hoặc slug bài luyện không hợp lệ/trùng lặp.')
        titles.add(title); slugs.add(slug)
        if lesson.get('kind') not in {'reading', 'listening'} or lesson.get('cefr_level') not in {'B1', 'B2'}:
            raise CommandError(f'{title}: kỹ năng hoặc nhãn mức không hợp lệ.')
        if not lesson.get('stimulus', '').strip() or not isinstance(lesson.get('estimated_minutes'), int) or not 1 <= lesson['estimated_minutes'] <= 60:
            raise CommandError(f'{title}: thiếu đoạn bài hoặc thời lượng không hợp lệ.')
        questions = lesson.get('questions', [])
        if not isinstance(questions, list) or not questions:
            raise CommandError(f'{title}: thiếu câu hỏi.')
        for question in questions:
            options = question.get('options', [])
            if not question.get('prompt', '').strip() or not question.get('explanation_vi', '').strip():
                raise CommandError(f'{title}: thiếu câu hỏi hoặc lời giải.')
            if len(options) != 4 or {o.get('label') for o in options} != set('ABCD'):
                raise CommandError(f'{title}: cần bốn phương án A–D khác nhau.')
            if sum(o.get('is_correct') is True for o in options) != 1 or any(type(o.get('is_correct')) is not bool for o in options):
                raise CommandError(f'{title}: cần đúng một đáp án đúng.')
            if any(not o.get('text', '').strip() or not o.get('explanation_vi', '').strip() for o in options):
                raise CommandError(f'{title}: thiếu nội dung hoặc giải thích từng phương án.')
    return lessons


class Command(BaseCommand):
    help = 'Nạp 8 bài Reading/Listening B1–B2 tự biên soạn (32 câu), mức tham khảo.'

    @transaction.atomic
    def handle(self, *args, **options):
        lessons = load_lessons()
        for lesson in lessons:
            kind = lesson['kind']
            content, _ = LearningContent.objects.update_or_create(title=lesson['title'], defaults={
                'description': lesson['description'], 'exam_type': 'TOEIC',
                'content_type': kind, 'skill': kind, 'question_type': 'foundation-advanced',
                'topic': lesson['topic'], 'cefr_level': lesson['cefr_level'],
                'difficulty': 2 if lesson['cefr_level'] == 'B1' else 3,
                'estimated_minutes': lesson['estimated_minutes'],
                'source_name': 'Nội dung tự biên soạn có AI hỗ trợ', 'source_url': '',
                'rights_note': 'Đoạn bài, câu hỏi và lời giải tự biên soạn; audio tổng hợp Flite. Không sao chép đề thi hoặc audio từ điển.',
                'review_status': 'language_checked', 'reviewer': 'AI rà soát chéo; chưa giảng viên duyệt',
                'reviewed_at': None, 'source_checked_on': None,
                'review_note': 'CEFR là nhãn dự kiến. Cần giảng viên kiểm tra theo nghĩa/ngữ cảnh và thử với người học.',
                'is_published': True,
            })
            audio_file = settings.BASE_DIR / 'static' / 'audio' / f"{lesson['slug']}.mp3"
            if kind == 'listening' and not audio_file.exists():
                raise CommandError(f"Thiếu audio đi kèm: {audio_file.name}")
            for order, item in enumerate(lesson['questions'], 1):
                question, _ = Question.objects.update_or_create(content=content, order=order, defaults={
                    'prompt': item['prompt'], 'explanation': item['explanation_vi'],
                    'explanation_vi': item['explanation_vi'],
                    'passage': lesson['stimulus'] if kind == 'reading' else '',
                    'audio_script': lesson['stimulus'] if kind == 'listening' else '',
                    'transcript': lesson['stimulus'] if kind == 'listening' else '',
                    'audio_url': f"/static/audio/{lesson['slug']}.mp3" if kind == 'listening' else '',
                })
                for option in item['options']:
                    AnswerOption.objects.update_or_create(question=question, label=option['label'], defaults={
                        'text': option['text'], 'is_correct': option['is_correct'], 'explanation_vi': option['explanation_vi'],
                    })
                question.options.exclude(label__in=list('ABCD')).delete()
            content.questions.filter(order__gt=len(lesson['questions'])).delete()
            if content.publication_issues():
                raise CommandError(f"{content.title}: " + ' '.join(content.publication_issues()))
        self.stdout.write(self.style.SUCCESS(f'Nạp {len(lessons)} bài và {sum(len(l["questions"]) for l in lessons)} câu B1–B2; CEFR tham khảo, chưa giáo viên duyệt.'))
