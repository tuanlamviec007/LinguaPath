"""Game XP derived from actual learning records; never an exam score.

Each local day: 5 XP per distinct reviewed card (at most 30 cards), 20 XP
per distinct completed practice set (at most 3 sets), and a bonus on the
first completed new vocabulary quiz (20 + 2 per correct answer, at most 50 XP).
Targeted reviews do not consume this bonus, but count as learning activity.
Reopening or resubmitting does not create additional XP.
"""
from datetime import timedelta
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone
from .models import FlashcardReview, MistakeReviewSession, PracticeAttempt, VocabularyQuizDailyReward, VocabularyQuizSession


def get_learning_rewards(user):
    now = timezone.now()
    today = timezone.localdate(now)
    reviews = FlashcardReview.objects.filter(user=user, reviewed_at__lte=now).order_by().annotate(day=TruncDate('reviewed_at')).values('day').annotate(count=Count('flashcard_id', distinct=True))
    practices = PracticeAttempt.objects.filter(user=user, status='submitted', submitted_at__isnull=False, submitted_at__lte=now).order_by().annotate(day=TruncDate('submitted_at')).values('day').annotate(count=Count('content_id', distinct=True))
    days = {}
    reviewed_today = practiced_today = 0
    for row in reviews:
        days[row['day']] = days.get(row['day'], 0) + min(row['count'], 30) * 5
        if row['day'] == today:
            reviewed_today = row['count']
    for row in practices:
        days[row['day']] = days.get(row['day'], 0) + min(row['count'], 3) * 20
        if row['day'] == today:
            practiced_today = row['count']
    for row in VocabularyQuizDailyReward.objects.filter(user=user, day__lte=today, quiz__status='submitted', quiz__submitted_at__lte=now).values('day').annotate(xp=Sum('xp')):
        days[row['day']] = days.get(row['day'], 0) + row['xp']
    for day in VocabularyQuizSession.objects.filter(user=user, status='submitted', submitted_at__lte=now).order_by().annotate(day=TruncDate('submitted_at')).values_list('day', flat=True).distinct():
        days.setdefault(day, 0)
    for day in MistakeReviewSession.objects.filter(user=user, status='submitted', submitted_at__lte=now).order_by().annotate(day=TruncDate('submitted_at')).values_list('day', flat=True).distinct():
        days.setdefault(day, 0)
    today_xp = days.get(today, 0)
    total_xp = sum(days.values())
    level = total_xp // 250 + 1
    xp_in_level = total_xp % 250
    streak_days = 0
    cursor = today if today in days else today - timedelta(days=1)
    while cursor in days:
        streak_days += 1
        cursor -= timedelta(days=1)
    longest_streak = current_streak = 0
    previous_day = None
    for day in sorted(days):
        current_streak = current_streak + 1 if previous_day and day == previous_day + timedelta(days=1) else 1
        longest_streak = max(longest_streak, current_streak)
        previous_day = day
    quiz_stats = VocabularyQuizSession.objects.filter(user=user, status='submitted', submitted_at__lte=now).aggregate(count=Count('pk'))
    quiz_today = VocabularyQuizSession.objects.filter(user=user, status='submitted', submitted_at__date=today, submitted_at__lte=now).exists()
    distinct_cards = FlashcardReview.objects.filter(user=user, reviewed_at__lte=now).values('flashcard_id').distinct().count()
    practice_count = PracticeAttempt.objects.filter(user=user, status='submitted', submitted_at__lte=now).count()
    quests = [
        {'title': 'Khởi động trí nhớ', 'description': 'Ôn 10 thẻ khác nhau hôm nay', 'current': min(reviewed_today, 10), 'target': 10, 'href': reverse('learning:flashcards')},
        {'title': 'Thử tài từ vựng', 'description': 'Hoàn thành một quiz hôm nay', 'current': int(quiz_today), 'target': 1, 'href': reverse('learning:quiz_hub')},
        {'title': 'Tiến thêm một bước', 'description': 'Nộp một bài luyện hôm nay', 'current': min(practiced_today, 1), 'target': 1, 'href': reverse('learning:practice_list')},
    ]
    for quest in quests:
        quest['done'] = quest['current'] >= quest['target']
        quest['progress'] = round(100 * quest['current'] / quest['target'])
    badges = [
        {'name': 'Bước đầu tiên', 'icon': '🌱', 'description': 'Ôn ít nhất một thẻ từ vựng', 'earned': distinct_cards >= 1},
        {'name': 'Bộ nhớ khởi động', 'icon': '🧠', 'description': 'Đã ôn 25 từ khác nhau', 'earned': distinct_cards >= 25},
        {'name': 'Quiz explorer', 'icon': '⚡', 'description': 'Hoàn thành quiz đầu tiên', 'earned': quiz_stats['count'] >= 1},
        {'name': 'Nhịp học ba ngày', 'icon': '🔥', 'description': 'Duy trì chuỗi học 3 ngày', 'earned': longest_streak >= 3},
        {'name': 'Chăm chỉ luyện tập', 'icon': '🎯', 'description': 'Hoàn thành 5 lượt luyện tập', 'earned': practice_count >= 5},
        {'name': 'Cột mốc 500 XP', 'icon': '🏆', 'description': 'Tích lũy 500 XP học tập', 'earned': total_xp >= 500},
    ]
    return {
        'total_xp': total_xp, 'level': level,
        'level_name': ['Người khám phá', 'Người chinh phục', 'Người bền bỉ', 'Ngôi sao học tập'][min((level - 1) // 3, 3)],
        'xp_in_level': xp_in_level, 'xp_to_next': 250 - xp_in_level,
        'level_progress': round(xp_in_level * 100 / 250),
        'streak_days': streak_days, 'longest_streak': longest_streak, 'today_xp': today_xp, 'daily_goal': 100,
        'daily_progress': min(round(today_xp), 100), 'badges': badges, 'quests': quests,
        'quiz_count': quiz_stats['count'], 'reviewed_today': reviewed_today,
        'rules': '5 XP/thẻ khác nhau/ngày (tối đa 30 thẻ), 20 XP/bộ luyện khác nhau/ngày (tối đa 3 bộ); quiz mới đầu ngày: 20 + 2 XP/câu đúng (tối đa 50 XP). Ôn từ sai không cộng XP hoặc dùng suất thưởng quiz mới, nhưng vẫn tính hoạt động học. XP và cấp độ trò chơi không quy đổi thành điểm TOEIC hay CEFR.',
    }
