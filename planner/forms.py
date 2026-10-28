from django import forms

from learning.models import CEFR_LEVELS
from .models import LearnerProfile


class LearningGoalForm(forms.ModelForm):
    class Meta:
        model = LearnerProfile
        fields = ['current_cefr', 'target_cefr', 'target_score', 'daily_minutes', 'target_date']
        labels = {
            'current_cefr': 'Trình độ từ vựng hiện tại',
            'target_cefr': 'Trình độ từ vựng mục tiêu',
            'target_score': 'Điểm TOEIC mong muốn',
            'daily_minutes': 'Số phút có thể học mỗi ngày',
            'target_date': 'Ngày dự kiến thi (không bắt buộc)',
        }
        widgets = {'target_date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        descriptions = {'A1': 'Mới bắt đầu', 'A2': 'Các tình huống quen thuộc', 'B1': 'Chủ đề thông dụng', 'B2': 'Nội dung đa dạng hơn', 'C1': 'Từ vựng nâng cao'}
        for name in ('current_cefr', 'target_cefr'):
            self.fields[name].choices = [(value, f'{value} · {descriptions[value]}') for value, _ in CEFR_LEVELS]
        self.fields['daily_minutes'].widget.attrs.update(min=5, max=240)
        self.fields['daily_minutes'].help_text = 'Chọn từ 5 đến 240 phút mỗi ngày; có thể điều chỉnh sau.'
        self.fields['current_cefr'].help_text = 'Chưa chắc mình ở mức nào? Có thể bắt đầu với A1 rồi điều chỉnh sau. Đây là lựa chọn nội dung khởi đầu, không phải chứng nhận CEFR.'
        self.fields['target_cefr'].help_text = 'Mức mục tiêu dùng để giới hạn từ vựng được gợi ý; không phải quy đổi điểm TOEIC.'
        self.fields['target_score'].help_text = 'Mốc cá nhân để theo dõi; hiện chưa được dùng để suy ra trình độ hoặc thay đổi độ khó kế hoạch.'
        self.fields['target_date'].help_text = 'Thông tin theo dõi; phiên bản hiện tại chưa tự chia lộ trình ngược từ ngày thi.'

    def clean(self):
        cleaned = super().clean()
        levels = [value for value, _ in CEFR_LEVELS]
        current = cleaned.get('current_cefr')
        target = cleaned.get('target_cefr')
        if current in levels and target in levels and levels.index(target) < levels.index(current):
            self.add_error('target_cefr', 'Trình độ mục tiêu cần bằng hoặc cao hơn trình độ hiện tại.')
        return cleaned

    def clean_target_score(self):
        score = self.cleaned_data.get('target_score')
        if score is not None and not 10 <= score <= 990:
            raise forms.ValidationError('Nhập điểm TOEIC từ 10 đến 990.')
        return score

    def clean_daily_minutes(self):
        minutes = self.cleaned_data['daily_minutes']
        if not 5 <= minutes <= 240:
            raise forms.ValidationError('Thời lượng học cần từ 5 đến 240 phút mỗi ngày.')
        return minutes
