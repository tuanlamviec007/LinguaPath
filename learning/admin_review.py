"""Read-only staff workspace for inventory and sampled human-review packets."""
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .models import CEFR_LEVELS, AnswerOption, Flashcard, LearningContent, Question

FLAG_LABELS = {
    'skill_type_mismatch': 'Kỹ năng không khớp loại học liệu',
    'missing_source_or_rights': 'Thiếu nguồn hoặc ghi chú quyền sử dụng',
    'teacher_approval_missing_reviewer_or_time': 'Nhãn duyệt thiếu người hoặc thời điểm',
    'empty_content': 'Bộ chưa có câu hỏi hoặc flashcard', 'blank_prompt': 'Câu hỏi trống',
    'fewer_than_two_options': 'Câu có ít hơn hai lựa chọn',
    'not_exactly_one_correct_option': 'Câu không có đúng một khóa chấm',
    'missing_explanation': 'Câu thiếu lời giải', 'has_blank_option_text': 'Câu có lựa chọn trống',
    'has_missing_option_explanation': 'Câu thiếu lời giải cho lựa chọn',
    'listening_without_audio_or_script': 'Câu nghe thiếu audio và lời thoại',
    'blank_term_or_meaning': 'Thẻ thiếu từ hoặc nghĩa',
    'missing_english_example': 'Thẻ thiếu ví dụ tiếng Anh',
    'missing_vietnamese_example': 'Thẻ thiếu bản dịch ví dụ',
}

REVIEW_PROBLEM_LABELS = {
    'invalid_shape': 'Các trường dữ liệu không đúng cấu trúc phiếu gốc.',
    'invalid_annotation': 'Nhận xét sai kiểu dữ liệu hoặc vượt giới hạn ký tự.',
    'invalid_conclusion': 'Kết luận không hợp lệ; chọn Đồng ý, Cần sửa hoặc Chưa đủ thông tin.',
    'invalid_review_date': 'Ngày rà soát không hợp lệ; dùng ngày ISO hoặc thời điểm có múi giờ.',
    'missing_conclusion_notes': 'Cần ghi lý do cho kết luận Cần sửa hoặc Chưa đủ thông tin.',
    'invalid_check_result': 'Kết quả checklist không hợp lệ.',
    'missing_check_notes': 'Cần ghi lý do cho mục Cần sửa hoặc Không áp dụng.',
    'conflicting_conclusion': 'Kết luận Đồng ý đang mâu thuẫn với mục cần sửa hoặc chưa đủ thông tin.',
    'invalid_json_value': 'Phiếu vượt giới hạn dung lượng, độ sâu hoặc chứa dữ liệu không hợp lệ.',
    'unsupported_scope': 'Phiếu không đúng phiên bản/phạm vi đang hỗ trợ. Hãy xuất phiếu mới để đối chiếu.',
    'changed_template': 'Mẫu checklist đã bị thay đổi; cần giữ nguyên mẫu gốc.',
    'invalid_generation_date': 'Thời điểm xuất phiếu không hợp lệ.',
    'invalid_fingerprint': 'Mã phiên bản phiếu không hợp lệ.',
    'invalid_selection': 'Danh sách hoặc giới hạn mẫu không hợp lệ.',
    'wrong_parent': 'Mục không khớp bộ học liệu đã chọn.',
    'invalid_source_field': 'Một trường nguồn sai kiểu dữ liệu.',
    'invalid_source_hash': 'Mã phiên bản nguồn không hợp lệ.',
    'invalid_findings': 'Các ghi nhận cấu trúc gốc đã bị thay đổi.',
    'invalid_sample': 'Mẫu vượt giới hạn hoặc sai cấu trúc.',
    'invalid_coverage': 'Số mục đã xuất không khớp thông tin phạm vi mẫu.',
    'invalid_item_identity': 'ID mục bị trùng hoặc không thuộc bộ học liệu đã chọn.',
    'invalid_options': 'Danh sách lựa chọn không hợp lệ hoặc vượt giới hạn.',
    'invalid_option': 'ID hoặc dữ liệu lựa chọn không hợp lệ.',
    'item_hash_mismatch': 'Đề, thẻ hoặc lựa chọn không còn khớp mã phiên bản gốc.',
    'packet_hash_mismatch': 'Bằng chứng trong phiếu không còn khớp phiên bản gốc.',
    'source_unavailable': 'Nguồn không còn khả dụng hoặc không thể xuất trong giới hạn hiện tại.',
    'source_changed': 'Nguồn hiện tại đã khác phiếu. Hãy xuất phiếu mới và rà lại phần liên quan.',
}


def can_prepare_review(user):
    return bool(user.is_active and user.is_staff and all(
        user.has_perm(f'learning.view_{name}') or user.has_perm(f'learning.change_{name}')
        for name in ('learningcontent', 'question', 'answeroption', 'flashcard')
    ))


class ReviewPacketForm(forms.Form):
    exam = forms.ChoiceField(choices=LearningContent.EXAMS)
    skill = forms.ChoiceField(required=False, choices=[('', 'Mọi kỹ năng'), *LearningContent.SKILLS])
    level = forms.ChoiceField(required=False, choices=[('', 'Mọi mức'), *CEFR_LEVELS])
    max_items = forms.IntegerField(min_value=1, max_value=100, initial=20)


def _review_principal(request):
    user = get_user_model().objects.filter(pk=request.user.pk).first()
    if user is None or not can_prepare_review(user):
        raise PermissionDenied


def _editor_response(request, model_admin, packet):
    return render(request, 'admin/learning/learningcontent/review_editor.html', {
        **model_admin.admin_site.each_context(request), 'opts': model_admin.model._meta,
        'title': 'Rà soát phiếu học liệu', 'packet': packet,
    })


class ReviewUploadForm(forms.Form):
    packet = forms.FileField(label='Phiếu JSON cần đối chiếu',
        widget=forms.FileInput(attrs={'accept': '.json,application/json', 'aria-describedby': 'review-upload-help'}),
        help_text='Tối đa 20 MiB. Chỉ tải phiếu dành cho người duyệt có quyền.')

    def clean_packet(self):
        from .content_review import MAX_PACKET_BYTES
        upload = self.cleaned_data['packet']
        if upload.size > MAX_PACKET_BYTES:
            raise forms.ValidationError('Phiếu vượt giới hạn 20 MiB. Hãy chọn phiếu nhỏ hơn.')
        return upload


@csrf_protect
@require_http_methods(['GET', 'POST'])
def review_check(request, model_admin):
    """Inspect returned annotations against live sources, never import/approve."""
    _review_principal(request)
    from .review_validation import ReviewPacketLoadError, load_review_packet, validate_review_packet
    form = ReviewUploadForm(request.POST if request.method == 'POST' else None,
                            request.FILES if request.method == 'POST' else None)
    report, status = None, 200
    if request.method == 'POST':
        action = request.POST.get('action', 'check')
        if action not in ('check', 'reopen', 'report'):
            form.is_valid()
            form.add_error(None, 'Thao tác không hợp lệ.')
        if form.is_valid():
            try:
                packet = load_review_packet(form.cleaned_data['packet'])
            except ReviewPacketLoadError:
                form.add_error('packet', 'Không đọc được phiếu JSON hợp lệ. Kiểm tra định dạng, khóa trùng và giới hạn dung lượng.')
            else:
                report = validate_review_packet(packet)
                if action == 'report':
                    response = JsonResponse(report, json_dumps_params={'ensure_ascii': False})
                    response['Content-Disposition'] = 'attachment; filename="linguapath-review-check.json"'
                    response['X-Content-Type-Options'] = 'nosniff'
                    return response
                if action == 'reopen' and report['status'] == 'current':
                    return _editor_response(request, model_admin, packet)
                status = {'current': 200, 'stale': 409, 'invalid': 400}[report['status']]
        if form.errors:
            status = 400
    if report:
        # Keep the downloadable machine report unchanged; translate the staff UI.
        report = {**report, 'problems': [{**problem, 'display_message':
            REVIEW_PROBLEM_LABELS.get(problem['code'], 'Cần kiểm tra lại dữ liệu tại vị trí này.')}
            for problem in report['problems']]}
    return render(request, 'admin/learning/learningcontent/review_check.html', {
        **model_admin.admin_site.each_context(request), 'opts': model_admin.model._meta,
        'title': 'Đối chiếu phiếu người duyệt', 'form': form, 'report': report,
    }, status=status)


@csrf_protect
@require_http_methods(['GET', 'POST'])
def review_workspace(request, model_admin):
    # Re-read the principal and permissions rather than using a stale admin
    # permission cache when a role was changed in another tab.
    _review_principal(request)
    from .content_coverage import content_coverage
    from .content_review import build_review_packet

    data = request.POST if request.method == 'POST' else request.GET
    form = ReviewPacketForm({
        'exam': data.get('exam', 'TOEIC'), 'skill': data.get('skill', ''),
        'level': data.get('level', ''), 'max_items': data.get('max_items', '20'),
    })
    selected = request.POST.getlist('content_id') if request.method == 'POST' else []
    selected_ids = []
    if form.is_valid():
        exam, skill, level = (form.cleaned_data[key] for key in ('exam', 'skill', 'level'))
    else:
        exam, skill, level = 'TOEIC', '', ''
    parents = LearningContent.objects.filter(exam_type=exam)
    if skill:
        parents = parents.filter(skill=skill)
    if level:
        parents = parents.filter(cefr_level=level)
    status = 200
    if request.method == 'POST':
        if request.POST.get('action', 'export') not in ('export', 'editor'):
            form.add_error(None, 'Thao tác không hợp lệ.')
        if len(selected) < 1 or len(selected) > 10:
            form.add_error(None, 'Chọn từ 1 đến 10 bộ học liệu trong mỗi phiếu.')
        elif any(not 1 <= len(value) <= 19 or not value.isascii() or not value.isdigit() or not 0 < int(value) <= 2**63 - 1 for value in selected):
            form.add_error(None, 'Danh sách học liệu không hợp lệ.')
        else:
            selected_ids = sorted({int(value) for value in selected})
            if len(selected_ids) != len(selected) or parents.filter(pk__in=selected_ids).count() != len(selected_ids):
                form.add_error(None, 'Học liệu đã thay đổi hoặc không khớp bộ lọc. Hãy chọn lại.')
        if form.is_valid():
            try:
                packet = build_review_packet(selected_ids, max_items=form.cleaned_data['max_items'])
            except ValueError:
                form.add_error(None, 'Chưa thể tạo phiếu hợp lệ. Hãy tải lại danh sách và chọn lại học liệu.')
            else:
                if request.POST.get('action') == 'editor':
                    return _editor_response(request, model_admin, packet)
                response = JsonResponse(packet, json_dumps_params={'ensure_ascii': False})
                response['Content-Disposition'] = 'attachment; filename="linguapath-human-review-sample.json"'
                response['X-Content-Type-Options'] = 'nosniff'
                return response
        status = 400
    page = Paginator(parents.order_by('skill', 'cefr_level', 'id'), 20).get_page(request.GET.get('page'))
    ids = [content.pk for content in page]
    cards = dict(Flashcard.objects.filter(content_id__in=ids).values('content_id').annotate(n=Count('pk')).values_list('content_id', 'n'))
    questions = dict(Question.objects.filter(content_id__in=ids).values('content_id').annotate(n=Count('pk')).values_list('content_id', 'n'))
    for content in page:
        content.review_card_count = cards.get(content.pk, 0)
        content.review_question_count = questions.get(content.pk, 0)
    coverage = content_coverage(exam)
    flag_groups = [{'label': label, 'items': [{'label': FLAG_LABELS.get(flag, flag), 'count': n}
        for flag, n in coverage['structural'].get(key, {}).items()]}
        for key, label in (('content', 'Bộ học liệu'), ('question', 'Câu hỏi'), ('flashcard', 'Flashcard'))]
    return render(request, 'admin/learning/learningcontent/review_workspace.html', {
        **model_admin.admin_site.each_context(request), 'opts': model_admin.model._meta,
        'title': 'Chuẩn bị duyệt học liệu pilot', 'form': form,
        'coverage': coverage, 'flag_groups': flag_groups, 'page_obj': page,
        'exam': exam, 'skill': skill, 'level': level, 'selected_ids': selected_ids,
    }, status=status)
