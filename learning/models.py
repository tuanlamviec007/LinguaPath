from django.conf import settings
from django.db import models, transaction


CEFR_LEVELS = [('A1', 'A1'), ('A2', 'A2'), ('B1', 'B1'), ('B2', 'B2'), ('C1', 'C1')]
LEARNER_REVIEW_STATUSES = ('language_checked', 'teacher_approved')


class LearningContent(models.Model):
    REVIEW_STATUS = [('draft', 'Chưa rà soát'), ('language_checked', 'AI rà soát sơ bộ (chưa giảng viên duyệt)'), ('teacher_approved', 'Giảng viên/người có chuyên môn duyệt')]
    EXAMS = [('TOEIC', 'TOEIC'), ('IELTS', 'IELTS')]
    KINDS = [('vocabulary', 'Từ vựng'), ('listening', 'Listening'), ('reading', 'Reading')]
    SKILLS = [('vocabulary', 'Vocabulary'), ('listening', 'Listening'), ('reading', 'Reading')]
    DIFFICULTIES = [(1, 'Cơ bản'), (2, 'Trung bình'), (3, 'Khá')]
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    exam_type = models.CharField(max_length=10, choices=EXAMS, default='TOEIC')
    content_type = models.CharField(max_length=16, choices=KINDS)
    skill = models.CharField(max_length=16, choices=SKILLS)
    question_type = models.CharField(max_length=60, blank=True)
    topic = models.CharField(max_length=80, blank=True)
    cefr_level = models.CharField(max_length=2, choices=CEFR_LEVELS, blank=True, db_index=True, help_text='Mức tham khảo của bộ nội dung; không phải chứng chỉ hoặc quy đổi điểm thi.')
    difficulty = models.PositiveSmallIntegerField(choices=DIFFICULTIES, default=1)
    estimated_minutes = models.PositiveSmallIntegerField(default=10)
    source_name = models.CharField(max_length=180, default='Nội dung tự biên soạn')
    source_url = models.URLField(blank=True)
    rights_note = models.CharField(max_length=240, default='Nội dung tự biên soạn cho mục đích luyện tập')
    review_status = models.CharField(max_length=24, choices=REVIEW_STATUS, default='draft', db_index=True)
    reviewer = models.CharField(max_length=120, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    source_checked_on = models.DateField(null=True, blank=True)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['exam_type', 'skill', 'difficulty', 'title']

    def __str__(self):
        return self.title

    def publication_issues(self):
        """Return concise content checks required before learner visibility."""
        issues = []
        if self.review_status == 'draft':
            issues.append('Học liệu đang ở trạng thái chưa rà soát; cần kiểm tra ngôn ngữ trước khi xuất bản.')
        if self.question_type == 'TOEIC Part 5 · AI draft':
            if self.review_status != 'teacher_approved' or not self.reviewer.strip() or not self.reviewed_at:
                issues.append('Bộ Part 5 do AI soạn cần duyệt chuyên môn, tên người duyệt và thời điểm duyệt trước khi xuất bản.')
        if self.content_type != self.skill:
            issues.append('Kỹ năng phải khớp với loại nội dung.')
        if self.content_type == 'vocabulary':
            has_cards = self.flashcards.exists()
            has_questions = self.questions.exists()
            if not has_cards and not has_questions:
                issues.append('Bộ từ vựng cần có ít nhất một flashcard.')
            if not self.source_name.strip() or not self.rights_note.strip():
                issues.append('Bộ từ vựng cần ghi nguồn và quyền sử dụng.')
            if not has_questions:
                return issues
        questions = list(self.questions.prefetch_related('options'))
        if not questions:
            issues.append('Bài luyện cần có ít nhất một câu hỏi.')
            return issues
        for question in questions:
            options = list(question.options.all())
            if len(options) < 2:
                issues.append(f'Câu {question.order}: cần ít nhất hai phương án.')
            if sum(option.is_correct for option in options) != 1:
                issues.append(f'Câu {question.order}: cần đúng một phương án đúng.')
            if not (question.explanation_vi or question.explanation).strip():
                issues.append(f'Câu {question.order}: cần lời giải thích.')
            if self.content_type == 'listening' and not (question.audio_url or question.audio_script.strip()):
                issues.append(f'Câu {question.order}: Listening cần audio hoặc kịch bản để phát bằng giọng đọc trình duyệt.')
        return issues


class QuestionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        from .question_search import SEARCH_FIELDS, sync_questions
        if not set(kwargs).intersection(SEARCH_FIELDS):
            return super().update(**kwargs)
        with transaction.atomic(using=self.db):
            ids = list(self.select_for_update().order_by('pk').values_list('pk', flat=True))
            count = super().update(**kwargs)
            sync_questions(self.model.objects.using(self.db).filter(pk__in=ids).iterator(), self.db)
            return count

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False,
                    update_conflicts=False, update_fields=None, unique_fields=None):
        from .question_search import sync_questions
        # Conflict-ignore cannot reliably return the affected primary keys.
        if ignore_conflicts or update_conflicts:
            raise ValueError('Question bulk conflicts require explicit update_or_create.')
        with transaction.atomic(using=self.db):
            created = super().bulk_create(objs, batch_size=batch_size)
            sync_questions(created, self.db)
            return created


class Question(models.Model):
    content = models.ForeignKey(LearningContent, on_delete=models.CASCADE, related_name='questions')
    prompt = models.TextField()
    passage = models.TextField(blank=True)
    audio_url = models.URLField(blank=True)
    audio_script = models.TextField(blank=True)
    transcript = models.TextField(blank=True)
    explanation = models.TextField()
    explanation_vi = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=1)
    objects = QuestionQuerySet.as_manager()

    def save(self, *args, **kwargs):
        from django.db import router
        using = kwargs.get('using') or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            return super().save(*args, **kwargs)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.content.title} – Câu {self.order}'


class QuestionSearchToken(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='search_tokens')
    token_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['question', 'token_hash'], name='unique_question_search_token')]
        indexes = [models.Index(fields=['token_hash', 'question'], name='question_search_lookup')]


class AnswerOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    label = models.CharField(max_length=4)
    text = models.TextField()
    is_correct = models.BooleanField(default=False)
    explanation_vi = models.TextField(blank=True, help_text='Giải thích vì sao phương án này đúng hoặc là phương án nhiễu.')

    class Meta:
        ordering = ['label']
        constraints = [models.UniqueConstraint(fields=['question', 'label'], name='unique_option_label_per_question')]

    def __str__(self):
        return f'{self.label}. {self.text[:50]}'


class FlashcardQuerySet(models.QuerySet):
    def learner_visible(self, exam=None):
        """Current public availability; administrative queries stay unfiltered."""
        cards = self.filter(is_available=True, content__is_published=True,
            content__review_status__in=LEARNER_REVIEW_STATUSES)
        return cards.filter(content__exam_type=exam) if exam is not None else cards


class Flashcard(models.Model):
    LEVELS = CEFR_LEVELS
    content = models.ForeignKey(LearningContent, on_delete=models.CASCADE, related_name='flashcards')
    term = models.CharField(max_length=120)
    cefr_level = models.CharField(max_length=2, choices=LEVELS, default='A1', db_index=True, help_text='Mức CEFR tham khảo cho từ này; không phải quy đổi điểm TOEIC.')
    topic = models.CharField(max_length=80, blank=True)
    part_of_speech = models.CharField(max_length=40, blank=True)
    meaning_vi = models.CharField(max_length=240)
    example_en = models.TextField(blank=True)
    example_vi = models.TextField(blank=True)
    pronunciation = models.CharField(max_length=120, blank=True)
    audio_url = models.URLField(blank=True)
    source_name = models.CharField(max_length=180, default='Tự biên soạn')
    source_url = models.URLField(blank=True)
    rights_note = models.CharField(max_length=240, default='Nội dung tự biên soạn hoặc được phép sử dụng')
    order = models.PositiveSmallIntegerField(default=1)
    is_available = models.BooleanField(default=True, db_index=True, verbose_name='Cho phép học thẻ',
        help_text='Tắt để tạm giữ riêng thẻ khỏi phiên học mới; không xóa lịch sử đã nộp.')
    availability_note = models.CharField(max_length=240, blank=True, verbose_name='Ghi chú tạm giữ',
        help_text='Lý do tạm giữ hoặc nội dung cần rà soát trước khi cho học lại.')

    objects = FlashcardQuerySet.as_manager()

    class Meta:
        ordering = ['order', 'term']

    def __str__(self):
        return self.term


class PracticeAttempt(models.Model):
    STATUS = [('in_progress', 'Đang làm'), ('submitted', 'Đã nộp'), ('abandoned', 'Đã dừng')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='practice_attempts')
    content = models.ForeignKey(LearningContent, on_delete=models.PROTECT, related_name='attempts')
    status = models.CharField(max_length=12, choices=STATUS, default='in_progress')
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    correct_count = models.PositiveSmallIntegerField(default=0)
    question_count = models.PositiveSmallIntegerField(default=0)
    question_ids = models.JSONField(default=list, blank=True, help_text='ID câu hỏi được chốt khi bắt đầu lượt luyện.')
    content_fingerprint = models.CharField(max_length=64, blank=True, default='')
    last_saved_at = models.DateTimeField(null=True, blank=True)
    draft_revision = models.PositiveIntegerField(default=0)
    result_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['user', 'content'], condition=models.Q(status='in_progress'),
            name='unique_active_practice_per_user_content',
        )]

    @property
    def accuracy(self):
        return round(100 * self.correct_count / self.question_count) if self.question_count else 0

    def __str__(self):
        return f'{self.user} – {self.content.title} – {self.status}'


class AttemptDraftAnswer(models.Model):
    attempt = models.ForeignKey(PracticeAttempt, on_delete=models.CASCADE, related_name='draft_answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_option = models.ForeignKey(AnswerOption, on_delete=models.CASCADE)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['attempt', 'question'], name='one_draft_answer_per_question_attempt')]


class AttemptAnswer(models.Model):
    attempt = models.ForeignKey(PracticeAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    selected_option = models.ForeignKey(AnswerOption, null=True, blank=True, on_delete=models.SET_NULL)
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now=True)
    evidence_snapshot = models.JSONField(default=dict, blank=True)

    @property
    def evidence(self):
        from .practice_sessions import answer_evidence, valid_answer_evidence
        if valid_answer_evidence(self.evidence_snapshot):
            return self.evidence_snapshot
        if self.evidence_snapshot != {}:
            return {'question': {'id': self.question_id, 'prompt': 'Không thể đọc bản gốc của câu trả lời này.',
                                 'options': [], 'explanation': '', 'explanation_vi': '', 'passage': ''},
                    'selected_option': None, 'is_correct': self.is_correct, 'content_title': 'Câu sai đã lưu',
                    'skill': '', 'legacy': False, 'unavailable': True}
        # Old answers have no recoverable historic wording. Never persist a
        # reconstruction from today's bank as if it were original evidence.
        return answer_evidence(self.question, self.selected_option, self.is_correct,
                               self.attempt.content, legacy=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['attempt', 'question'], name='one_answer_per_question_attempt')]


class ErrorNotebookEntry(models.Model):
    CATEGORIES = [
        ('vocabulary', 'Từ vựng'), ('grammar', 'Ngữ pháp'),
        ('detail', 'Tìm thông tin chi tiết'), ('inference', 'Suy luận'),
        ('paraphrase', 'Diễn đạt tương đương'), ('listening', 'Nghe hiểu'),
        ('other', 'Khác'),
    ]
    answer = models.OneToOneField(AttemptAnswer, on_delete=models.CASCADE, related_name='error_entry')
    category = models.CharField(max_length=16, choices=CATEGORIES, default='other')
    learner_note = models.CharField(max_length=1000, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['reviewed_at', '-created_at']

    def __str__(self):
        return f'{self.answer.attempt.user} – {self.answer.question}'


class FlashcardReview(models.Model):
    RATINGS = [('again', 'Chưa nhớ'), ('hard', 'Khó'), ('known', 'Đã nhớ')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='flashcard_reviews')
    flashcard = models.ForeignKey(Flashcard, on_delete=models.CASCADE, related_name='reviews')
    rating = models.CharField(max_length=8, choices=RATINGS)
    reviewed_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField()

    class Meta:
        ordering = ['due_at']


class UserFlashcardState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='flashcard_states')
    flashcard = models.ForeignKey(Flashcard, on_delete=models.CASCADE, related_name='user_states')
    last_rating = models.CharField(max_length=8, choices=FlashcardReview.RATINGS)
    reviewed_at = models.DateTimeField()
    due_at = models.DateTimeField()
    review_count = models.PositiveIntegerField(default=0)
    interval_days = models.PositiveIntegerField(default=0)
    ease_factor = models.FloatField(default=2.3)
    successful_reviews = models.PositiveIntegerField(default=0)
    lapse_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'flashcard'], name='unique_user_flashcard_state')]


class TutorUsageBudget(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tutor_usage_budget')
    day = models.DateField()
    day_count = models.PositiveIntegerField(default=0)
    minute_started_at = models.DateTimeField()
    minute_count = models.PositiveIntegerField(default=0)


class TutorTurn(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tutor_turns')
    question = models.CharField(max_length=500)
    result = models.JSONField(default=dict)
    response_mode = models.CharField(max_length=10, default='lookup')
    question_id_context = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']


class MistakeReviewSession(models.Model):
    STATUS = [('in_progress', 'Đang luyện'), ('submitted', 'Đã nộp'), ('abandoned', 'Đã dừng')]
    EXAMS = [('TOEIC', 'TOEIC'), ('IELTS', 'IELTS')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mistake_review_sessions')
    exam_type = models.CharField(max_length=10, choices=EXAMS)
    category = models.CharField(max_length=16, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default='in_progress')
    fingerprint = models.CharField(max_length=64)
    result_snapshot = models.JSONField(default=dict, blank=True)
    draft_answers = models.JSONField(default=dict, blank=True)
    draft_revision = models.PositiveIntegerField(default=0)
    last_saved_at = models.DateTimeField(null=True, blank=True)
    question_count = models.PositiveSmallIntegerField(default=0)
    correct_count = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['user', 'exam_type'], condition=models.Q(status='in_progress'),
            name='unique_active_mistake_review_user_exam',
        )]
        ordering = ['-created_at']


class MistakeReviewItem(models.Model):
    session = models.ForeignKey(MistakeReviewSession, on_delete=models.CASCADE, related_name='items')
    source_entry = models.ForeignKey(ErrorNotebookEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name='mistake_review_items')
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name='mistake_review_items')
    position = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['session', 'question'], name='unique_question_per_mistake_review'),
            models.UniqueConstraint(fields=['session', 'position'], name='unique_mistake_review_position'),
        ]
        ordering = ['position', 'id']


class MistakeReviewAnswer(models.Model):
    item = models.OneToOneField(MistakeReviewItem, on_delete=models.CASCADE, related_name='answer')
    selected_option = models.ForeignKey(AnswerOption, null=True, blank=True, on_delete=models.SET_NULL)
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now_add=True)

# Imported here so Django discovers quiz models without splitting the app.
from .quiz_models import DueRecallObservation, VocabularyQuizDailyReward, VocabularyQuizSession  # noqa: E402,F401
from .saved_word_models import SavedWord  # noqa: E402,F401
from .auth_models import AuthRateBucket  # noqa: E402,F401
from .global_ai_models import GlobalTutorUsageBudget  # noqa: E402,F401
from .weak_word_models import (  # noqa: E402,F401
    WeakWordOutcome, WeakWordPendingOutcome, WeakWordProjectionState, WeakWordQuizReceipt,
)
