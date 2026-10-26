"""Deterministic learner tools; do not delegate grades or writes to a model."""
from datetime import timedelta
from urllib.parse import urlencode

from django.db.models import Count, F, Sum
from django.urls import reverse
from django.utils import timezone

from planner.services import generate_daily_plan
from .models import ErrorNotebookEntry, LearningContent, LEARNER_REVIEW_STATUSES, PracticeAttempt


def visible_content(exam):
    return LearningContent.objects.filter(exam_type=exam, is_published=True, review_status__in=LEARNER_REVIEW_STATUSES)


def practice_recommendations(profile):
    return list(visible_content(profile.exam_goal).filter(
        cefr_level=profile.current_cefr, questions__isnull=False,
    ).annotate(question_total=Count('questions', distinct=True)).order_by('difficulty', 'id')[:3])


def learner_progress(user, profile):
    attempts = PracticeAttempt.objects.filter(
        user=user, status='submitted', content__exam_type=profile.exam_goal,
        submitted_at__gte=timezone.now() - timedelta(days=30),
    )
    totals = attempts.aggregate(correct=Sum('correct_count'), total=Sum('question_count'), count=Count('id'))
    total = totals['total'] or 0
    lines = [f'Tiến độ {profile.exam_goal} trong 30 ngày gần đây:',
             f'Đã nộp {totals["count"]} lượt luyện; trả lời đúng {totals["correct"] or 0}/{total} câu.']
    if total:
        lines.append(f'Tỷ lệ đúng theo tổng số câu: {round(100 * (totals["correct"] or 0) / total)}%.')
    else:
        lines.append('Chưa đủ kết quả để xác định kỹ năng cần ưu tiên. Hãy làm một bài luyện trước.')
    for row in attempts.values('content__skill').annotate(correct=Sum('correct_count'), total=Sum('question_count')).order_by('content__skill'):
        if row['total']:
            lines.append(f'{row["content__skill"].capitalize()}: {round(100 * row["correct"] / row["total"])}% ({row["total"]} câu).')
    errors = ErrorNotebookEntry.objects.filter(
        answer__attempt__user=user, answer__attempt__status='submitted', answer__is_correct=False,
        answer__attempt__content__exam_type=profile.exam_goal,
        answer__question__content_id=F('answer__attempt__content_id'),
        answer__question__content__in=visible_content(profile.exam_goal), reviewed_at__isnull=True,
    ).values('category').annotate(count=Count('id')).order_by('-count', 'category')[:3]
    labels = dict(ErrorNotebookEntry.CATEGORIES)
    if errors:
        lines.append('Nhóm lỗi đang chờ ôn trong sổ tay (theo nhãn hiện có): ' + '; '.join(f'{labels.get(r["category"], r["category"])}: {r["count"]}' for r in errors) + '.')
    lines.append('Đây là kết quả luyện trên website, không phải dự đoán hoặc quy đổi thành điểm TOEIC chính thức.')
    return {'answer': '\n'.join(lines), 'mode': 'learning_data', 'sources': [], 'evidence_sources': [],
            'actions': [{'title': 'Xem tiến độ chi tiết', 'href': reverse('progress')}, {'title': 'Ôn lỗi sai', 'href': reverse('learning:mistake_notebook')}]}


def daily_tasks(user, profile):
    tasks = list(generate_daily_plan(user, profile).filter(content__exam_type=profile.exam_goal))
    lines = [f'Kế hoạch hôm nay · {profile.daily_minutes} phút dự kiến · mức {profile.current_cefr}:']
    actions = []
    for index, task in enumerate(tasks, 1):
        lines.append(f'{index}. {task.content.title} — {task.estimated_minutes} phút · {task.get_status_display()}. {task.reason}')
        if task.status in ('todo', 'in_progress'):
            cards = task.content.flashcards.filter(is_available=True)
            if task.cefr_level:
                cards = cards.filter(cefr_level=task.cefr_level)
            if cards.exists():
                href = reverse('learning:flashcards_content', args=[task.content_id])
                if task.cefr_level:
                    href += '?' + urlencode({'level': task.cefr_level})
            elif task.content.content_type != 'vocabulary' and task.content.questions.exists():
                href = reverse('learning:practice', args=[task.content_id])
            else:
                continue
            actions.append({'title': task.content.title, 'href': href})
    if not tasks:
        lines.append('Chưa có học liệu phù hợp trong thời lượng hiện tại. Bạn có thể điều chỉnh mục tiêu hoặc chọn bài trong thư viện.')
    lines.append('Kế hoạch do quy tắc đề xuất từ mục tiêu và lịch sử học; AI không tự sửa mục tiêu hoặc đánh dấu hoàn thành.')
    return {'answer': '\n'.join(lines), 'mode': 'daily_plan', 'sources': [], 'evidence_sources': [], 'actions': actions}
