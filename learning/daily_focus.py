"""One next action from the dashboard's already-authorized data."""
from urllib.parse import urlencode

from django.urls import reverse


def daily_focus(active_quiz, resume_attempts, next_task, tasks):
    if active_quiz:
        return {'kind': 'quiz', 'eyebrow': 'TIẾP TỤC NHỊP HỌC',
                'title': 'Quiz của bạn đang chờ.',
                'description': f'{active_quiz.saved_count}/{active_quiz.question_count} câu đã lưu. Tiếp tục từ chỗ bạn dừng lại.',
                'action': 'Tiếp tục quiz',
                'href': reverse('learning:quiz_take', args=[active_quiz.pk])}
    if resume_attempts:
        attempt = resume_attempts[0]
        return {'kind': 'practice', 'eyebrow': 'TIẾP TỤC NHỊP HỌC',
                'title': 'Hoàn thành bài đang làm.',
                'description': f'{attempt.content.title} · {attempt.saved_count}/{attempt.question_count} câu đã lưu.',
                'action': 'Tiếp tục bài luyện',
                'href': reverse('learning:take_attempt', args=[attempt.pk])}
    if next_task:
        vocabulary = next_task.content.content_type == 'vocabulary'
        href = reverse('learning:flashcards_content' if vocabulary else 'learning:practice', args=[next_task.content_id])
        if vocabulary and next_task.cefr_level:
            href += '?' + urlencode({'level': next_task.cefr_level})
        return {'kind': 'task', 'eyebrow': 'MỘT BƯỚC NHỎ HÔM NAY',
                'title': next_task.content.title,
                'description': (f'{next_task.estimated_minutes} phút · tự đánh giá {getattr(next_task, "vocabulary_goal", 0)} thẻ khác nhau, không cần học hết bộ. ' if vocabulary and getattr(next_task, 'vocabulary_goal', 0) else f'{next_task.estimated_minutes} phút theo kế hoạch của bạn. ') + next_task.reason,
                'action': 'Bắt đầu nhiệm vụ', 'href': href}
    complete = bool(tasks) and all(task.status == 'done' for task in tasks)
    return {'kind': 'complete' if complete else 'explore',
            'eyebrow': 'BẠN ĐÃ GIỮ NHỊP' if complete else 'THEO NHỊP CỦA BẠN',
            'title': 'Kế hoạch hôm nay đã xong!' if complete else 'Chọn một bài ngắn để bắt đầu.',
            'description': 'Bạn có thể nghỉ ngơi hoặc khám phá thêm khi muốn.' if complete else 'Xem những bài nghe và đọc đang có, rồi chọn chủ đề bạn thích.',
            'action': 'Khám phá thêm', 'href': reverse('learning:practice_list')}
