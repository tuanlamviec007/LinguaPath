from copy import copy

from django import forms
from django.contrib.auth import get_user_model
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import path, reverse
from .models import AnswerOption, AttemptAnswer, ErrorNotebookEntry, Flashcard, FlashcardReview, LearningContent, PracticeAttempt, Question, UserFlashcardState, TutorUsageBudget
from .vocabulary_import import import_vocabulary_csv
from .locking import nonkey_row_lock
from .ai_provider import generate_cloudflare_answer, provider_name, tutor_ai_available
from .ai_limits import reserve_tutor_call
from .ai_drafts import save_part5_draft
from .tutor_knowledge import KNOWLEDGE
from .admin_review import can_prepare_review, review_check, review_workspace


def lock_content_rows(content_ids):
    """Use the same parent-before-child lock order as learner grading."""
    return list(LearningContent.objects.select_for_update().filter(
        pk__in=sorted(content_id for content_id in set(content_ids) if content_id is not None),
    ).order_by('pk'))


def invalidate_content_review(content):
    """Unpublish changed learning content and clear its stale review record."""
    content.is_published = False
    content.review_status = 'draft'
    content.reviewer = ''
    content.reviewed_at = None
    content.review_note = ''
    content.save(update_fields=[
        'is_published', 'review_status', 'reviewer', 'reviewed_at',
        'review_note', 'updated_at',
    ])


class AnswerInline(admin.TabularInline):
    model = AnswerOption
    extra = 4


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0


class FlashcardInline(admin.TabularInline):
    model = Flashcard
    extra = 0
    fields = ('term', 'cefr_level', 'topic', 'meaning_vi', 'part_of_speech', 'example_en', 'example_vi', 'pronunciation', 'audio_url', 'source_name', 'source_url', 'rights_note', 'order')


@admin.register(LearningContent)
class LearningContentAdmin(admin.ModelAdmin):
    list_display = ('title', 'exam_type', 'content_type', 'cefr_level', 'review_status', 'difficulty', 'is_published')
    list_filter = ('exam_type', 'content_type', 'cefr_level', 'review_status', 'difficulty', 'is_published')
    search_fields = ('title', 'topic', 'source_name')
    inlines = [QuestionInline, FlashcardInline]
    change_list_template = 'admin/learning/learningcontent/change_list.html'

    class AIDraftForm(forms.Form):
        topic = forms.ChoiceField(label='Chủ điểm ngữ pháp', choices=[
            (note['id'], note['title']) for note in KNOWLEDGE if note['id'] not in ('listening-strategy', 'reading-strategy')
        ])

    def can_generate_ai(self, request):
        return all(request.user.has_perm(f'learning.{action}_{model}')
                   for action in ('add', 'change') for model in ('learningcontent', 'question', 'answeroption'))

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, extra_context={**(extra_context or {}), 'can_generate_ai': self.can_generate_ai(request), 'can_prepare_review': can_prepare_review(request.user)})

    def get_urls(self):
        return [
            path('review-workspace/', self.admin_site.admin_view(self.review_workspace), name='learning_learningcontent_review_workspace'),
            path('review-check/', self.admin_site.admin_view(self.review_check), name='learning_learningcontent_review_check'),
            path('ai-draft/', self.admin_site.admin_view(self.ai_draft), name='learning_learningcontent_ai_draft'),
        ] + super().get_urls()

    def review_workspace(self, request):
        return review_workspace(request, self)

    def review_check(self, request):
        return review_check(request, self)

    def ai_draft(self, request):
        if not self.can_generate_ai(request):
            raise PermissionDenied
        form = self.AIDraftForm(request.POST or None)
        available = provider_name() == 'cloudflare' and tutor_ai_available()
        if request.method == 'POST' and form.is_valid():
            if not available:
                form.add_error(None, 'Workers AI chưa được cấu hình hoặc đang tắt. Chưa gửi yêu cầu tới mô hình.')
            else:
                allowed, _ = reserve_tutor_call(request.user)
                if not allowed:
                    form.add_error(None, 'Chưa thể cấp lượt AI. Hãy kiểm tra hạn mức hoặc thử lại sau.')
                else:
                    note = next(note for note in KNOWLEDGE if note['id'] == form.cleaned_data['topic'])
                    try:
                        raw = generate_cloudflare_answer('Create exactly 3 original Part 5 draft questions from this grammar note.', note['text'], task='draft_part5')
                        content = save_part5_draft(raw, note)
                    except Exception:
                        form.add_error(None, 'Chưa tạo được bộ nháp hợp lệ. Không có học liệu mới được lưu. Lượt đã gửi vẫn được tính; không tự gọi lại AI.')
                    else:
                        self.message_user(request, 'Đã tạo 3 câu ở trạng thái NHÁP. Hãy kiểm tra từng đáp án và lời giải trước khi duyệt/xuất bản.', level=messages.SUCCESS)
                        return redirect(reverse('admin:learning_learningcontent_change', args=[content.pk]))
        return render(request, 'admin/learning/learningcontent/ai_draft.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Soạn bản nháp TOEIC Part 5 với Workers AI', 'form': form, 'ai_available': available,
        })

    @transaction.atomic
    def save_related(self, request, form, formsets, change):
        # Any change to the learning material or provenance invalidates its
        # previous review. A reviewer must save the review separately.
        review_only_fields = {'is_published', 'review_status', 'reviewer', 'reviewed_at', 'review_note'}
        content_changed = change and bool(set(form.changed_data) - review_only_fields)
        children_changed = change and any(formset.has_changed() for formset in formsets)
        lock_content_rows([form.instance.pk])
        super().save_related(request, form, formsets, change)
        content = form.instance
        if content_changed or children_changed:
            invalidate_content_review(content)
            self.message_user(
                request,
                'Nội dung đã thay đổi; trạng thái duyệt đã được xóa và bài được chuyển về nháp. Hãy rà soát lại trước khi xuất bản.',
                level=messages.WARNING,
            )
        issues = content.publication_issues() if content.is_published else []
        if issues:
            content.is_published = False
            content.save(update_fields=['is_published', 'updated_at'])
            self.message_user(
                request,
                'Bài đang ở trạng thái nháp vì chưa đạt kiểm tra xuất bản: ' + ' '.join(issues),
                level=messages.WARNING,
            )

    @transaction.atomic
    def delete_model(self, request, obj):
        lock_content_rows([obj.pk])
        super().delete_model(request, obj)

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        lock_content_rows(queryset.values_list('pk', flat=True))
        super().delete_queryset(request, queryset)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('content', 'order', 'prompt')
    inlines = [AnswerInline]

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        affected_content_ids = {obj.content_id}
        if change and obj.pk:
            old_content_id = Question.objects.filter(pk=obj.pk).values_list('content_id', flat=True).first()
            if old_content_id:
                affected_content_ids.add(old_content_id)
        request._linguapath_question_content_ids = affected_content_ids
        lock_content_rows(affected_content_ids)
        super().save_model(request, obj, form, change)

    @transaction.atomic
    def save_related(self, request, form, formsets, change):
        changed = bool(form.changed_data) or any(formset.has_changed() for formset in formsets)
        content_ids = getattr(request, '_linguapath_question_content_ids', {form.instance.content_id})
        lock_content_rows(content_ids)
        super().save_related(request, form, formsets, change)
        if changed:
            for content in LearningContent.objects.filter(id__in=content_ids):
                invalidate_content_review(content)
            self.message_user(
                request,
                'Câu hỏi hoặc đáp án đã thay đổi; bài học liên quan được chuyển về nháp và cần rà soát lại.',
                level=messages.WARNING,
            )

    @transaction.atomic
    def delete_model(self, request, obj):
        content, = lock_content_rows([obj.content_id])
        super().delete_model(request, obj)
        invalidate_content_review(content)
        self.message_user(
            request,
            'Câu hỏi đã xóa; bài học liên quan được chuyển về nháp và cần rà soát lại.',
            level=messages.WARNING,
        )

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        content_ids = set(queryset.values_list('content_id', flat=True))
        contents = lock_content_rows(content_ids)
        super().delete_queryset(request, queryset)
        for content in contents:
            invalidate_content_review(content)
        if content_ids:
            self.message_user(
                request,
                'Câu hỏi đã xóa; các bài học liên quan được chuyển về nháp và cần rà soát lại.',
                level=messages.WARNING,
            )


@admin.register(Flashcard)
class FlashcardAdmin(admin.ModelAdmin):
    list_display = ('term', 'cefr_level', 'topic', 'content', 'source_name', 'is_available')
    list_filter = ('is_available', 'cefr_level', 'topic', 'content__exam_type')
    search_fields = ('term', 'meaning_vi', 'topic', 'content__title')
    change_list_template = 'admin/learning/flashcard/change_list.html'

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if field is not None and db_field.name == 'is_available':
            field.help_text += ' Bật lại thẻ sẽ đưa bộ học liệu về nháp để rà soát; không tự xuất bản lại cả bộ.'
        return field

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        changed = not change or bool(form.changed_data)
        affected_content_ids = {obj.content_id}
        if change and obj.pk:
            old_content_id = Flashcard.objects.filter(pk=obj.pk).values_list('content_id', flat=True).first()
            if old_content_id:
                affected_content_ids.add(old_content_id)
        contents = lock_content_rows(affected_content_ids)
        super().save_model(request, obj, form, change)
        if not changed:
            return
        if change and not obj.is_available and set(form.changed_data) <= {'is_available', 'availability_note'}:
            self.message_user(request, 'Đã tạm giữ riêng thẻ; lịch sử học và trạng thái các thẻ khác được giữ nguyên.', level=messages.WARNING)
            return
        for content in contents:
            invalidate_content_review(content)
        self.message_user(
            request,
            'Thẻ từ đã thay đổi; bộ học liệu liên quan được chuyển về nháp và cần rà soát lại.',
            level=messages.WARNING,
        )

    @transaction.atomic
    def delete_model(self, request, obj):
        content, = lock_content_rows([obj.content_id])
        super().delete_model(request, obj)
        invalidate_content_review(content)
        self.message_user(
            request,
            'Thẻ từ đã xóa; bộ học liệu liên quan được chuyển về nháp và cần rà soát lại.',
            level=messages.WARNING,
        )

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        content_ids = set(queryset.values_list('content_id', flat=True))
        contents = lock_content_rows(content_ids)
        super().delete_queryset(request, queryset)
        for content in contents:
            invalidate_content_review(content)
        if content_ids:
            self.message_user(
                request,
                'Thẻ từ đã xóa; các bộ học liệu liên quan được chuyển về nháp và cần rà soát lại.',
                level=messages.WARNING,
            )

    class ImportForm(forms.Form):
        csv_file = forms.FileField(label='Tệp CSV UTF-8')
        title = forms.CharField(max_length=180, label='Tên bộ từ')
        topic = forms.CharField(max_length=80, required=False, label='Chủ đề')
        source_name = forms.CharField(max_length=180, label='Nguồn')
        source_url = forms.URLField(required=False, label='URL nguồn')
        rights_note = forms.CharField(max_length=240, label='Quyền sử dụng')

    def get_urls(self):
        custom = [path('import-csv/', self.admin_site.admin_view(self.import_csv), name='learning_flashcard_import_csv')]
        return custom + super().get_urls()

    def import_csv(self, request):
        if not self.has_add_permission(request) or not self.has_change_permission(request):
            raise PermissionDenied
        form = self.ImportForm(request.POST or None, request.FILES or None)
        if request.method == 'POST' and form.is_valid():
            uploaded = form.cleaned_data['csv_file']
            if uploaded.size > 2 * 1024 * 1024:
                form.add_error('csv_file', 'Tệp CSV không được lớn hơn 2 MB.')
                uploaded = None
            if uploaded is None:
                context = {
                    **self.admin_site.each_context(request), 'opts': self.model._meta,
                    'title': 'Nhập từ vựng từ CSV', 'form': form,
                    'expected_columns': 'term, meaning_vi, cefr_level, part_of_speech, topic, example_en, example_vi, pronunciation, audio_url',
                }
                return render(request, 'admin/learning/flashcard/import_csv.html', context)
            try:
                text = uploaded.read().decode('utf-8-sig')
                with transaction.atomic():
                    # Practice takes this same owner's lock before the parent.
                    # Keep that order here; authorization must not acquire the
                    # user lock after the importer has locked learning content.
                    principal = nonkey_row_lock(get_user_model().objects.all()).filter(pk=request.user.pk).first()
                    if principal is None:
                        raise PermissionDenied
                    content, created, updated = import_vocabulary_csv(
                        text,
                        title=form.cleaned_data['title'],
                        topic=form.cleaned_data['topic'],
                        source_name=form.cleaned_data['source_name'],
                        source_url=form.cleaned_data['source_url'],
                        rights_note=form.cleaned_data['rights_note'],
                        permission_check=lambda content: self.check_import_permission(request, content, principal=principal),
                    )
            except (UnicodeDecodeError, ValueError) as exc:
                form.add_error('csv_file', str(exc))
            else:
                self.message_user(
                    request,
                    f'Đã nhập bộ “{content.title}”: thêm {created}, cập nhật {updated} từ. Đây là thao tác gộp/cập nhật: các từ không có trong CSV vẫn được giữ lại. Bộ đã chuyển về nháp và cần rà soát lại.',
                    level=messages.SUCCESS,
                )
                return redirect(reverse('admin:learning_flashcard_changelist'))
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Nhập từ vựng từ CSV',
            'form': form,
            'expected_columns': 'term, meaning_vi, cefr_level, part_of_speech, topic, example_en, example_vi, pronunciation, audio_url',
        }
        return render(request, 'admin/learning/flashcard/import_csv.html', context)

    def check_import_permission(self, request, content, *, principal):
        """Authorize the actual parent operation after the importer locks it."""
        checked_request = copy(request)
        # Do not reuse permissions cached by the initial page-access check.
        checked_request.user = principal
        if not checked_request.user.is_active or not checked_request.user.is_staff:
            raise PermissionDenied
        if not self.has_add_permission(checked_request) or not self.has_change_permission(checked_request):
            raise PermissionDenied
        parent_admin = self.admin_site._registry[LearningContent]
        allowed = (parent_admin.has_add_permission(checked_request) if content is None
                   else parent_admin.has_change_permission(checked_request, content))
        if not allowed:
            raise PermissionDenied


admin.site.site_header = 'LinguaPath · Quản trị nội dung'
admin.site.site_title = 'Quản trị LinguaPath'
admin.site.index_title = 'Quản lý học liệu và hoạt động học tập'
admin.site.register([PracticeAttempt, AttemptAnswer, ErrorNotebookEntry, FlashcardReview, UserFlashcardState])


@admin.register(TutorUsageBudget)
class TutorUsageBudgetAdmin(admin.ModelAdmin):
    list_display = ('user', 'day', 'day_count', 'minute_count', 'minute_started_at')
    list_filter = ('day',)
    search_fields = ('user__username',)
    readonly_fields = ('user', 'day', 'day_count', 'minute_started_at', 'minute_count')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


from .models import MistakeReviewSession


@admin.register(MistakeReviewSession)
class MistakeReviewSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'exam_type', 'status', 'correct_count', 'question_count', 'started_at', 'submitted_at')
    list_filter = ('exam_type', 'status')
    search_fields = ('user__username',)
    readonly_fields = tuple(field.name for field in MistakeReviewSession._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
