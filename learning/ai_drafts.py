"""Validate AI Part 5 output and save drafts requiring human review."""
import json
import re

from django.db import transaction

from .models import AnswerOption, LearningContent, Question


def validate_part5_draft(raw):
    if not isinstance(raw, str) or len(raw) > 6000:
        raise ValueError('Invalid draft size')
    raw = raw.strip()
    if raw.startswith('```json\n') and raw.endswith('\n```'):
        raw = raw[8:-4]
    result = json.loads(raw)
    if not isinstance(result, dict) or set(result) != {'questions'}:
        raise ValueError('Invalid draft schema')
    questions = result['questions']
    if not isinstance(questions, list) or len(questions) != 3:
        raise ValueError('Exactly three draft questions required')
    prompts = set()
    for item in questions:
        if not isinstance(item, dict) or set(item) != {'prompt', 'options', 'correct_label', 'explanation_vi'}:
            raise ValueError('Invalid question schema')
        prompt, options, explanation = item['prompt'], item['options'], item['explanation_vi']
        if not isinstance(prompt, str) or not 25 <= len(prompt) <= 500 or prompt.count('_____') != 1:
            raise ValueError('Invalid question sentence')
        if len(re.findall(r'_+', prompt)) != 1 or len(prompt.split()) < 5:
            raise ValueError('Invalid blank')
        normalized = ' '.join(prompt.casefold().split())
        if normalized in prompts:
            raise ValueError('Duplicate prompt')
        prompts.add(normalized)
        if not isinstance(options, dict) or set(options) != {'A', 'B', 'C', 'D'}:
            raise ValueError('Four options required')
        if any(not isinstance(text, str) or not 1 <= len(text.strip()) <= 100 for text in options.values()):
            raise ValueError('Invalid option')
        if len({' '.join(text.casefold().split()) for text in options.values()}) != 4:
            raise ValueError('Distinct options required')
        if not isinstance(item['correct_label'], str) or item['correct_label'] not in options:
            raise ValueError('Invalid answer key')
        if not isinstance(explanation, str) or not 40 <= len(explanation.strip()) <= 1200:
            raise ValueError('Missing explanation')
        if any(re.search(r'<[^>]*>', text) for text in [prompt, explanation, *options.values()]):
            raise ValueError('HTML is not allowed')
    return questions


@transaction.atomic
def save_part5_draft(raw, note):
    questions = validate_part5_draft(raw)
    content = LearningContent.objects.create(
        title=f'TOEIC Part 5 · {note["title"]} · AI draft',
        description='Bản nháp 3 câu do Workers AI gợi ý. Cần người có chuyên môn kiểm tra từng đáp án, lời giải, mức độ và quyền sử dụng trước khi xuất bản.',
        content_type='reading', skill='reading', exam_type='TOEIC',
        question_type='TOEIC Part 5 · AI draft', topic=note['title'],
        source_name='Workers AI · ghi chú tự biên soạn: ' + note['title'],
        rights_note='AI hỗ trợ soạn nội dung mới; biên tập viên cần kiểm tra trước khi công bố.',
        estimated_minutes=5, review_status='draft', is_published=False,
    )
    for index, item in enumerate(questions, 1):
        question = Question.objects.create(content=content, order=index, prompt=item['prompt'],
                                           explanation=item['explanation_vi'], explanation_vi=item['explanation_vi'])
        AnswerOption.objects.bulk_create([
            AnswerOption(question=question, label=label, text=text.strip(), is_correct=label == item['correct_label'])
            for label, text in item['options'].items()
        ])
    return content
