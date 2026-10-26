"""Repair only the exact, known CSV-shifted starter trip record."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from learning.models import Flashcard, LearningContent, Question


PARENT_MATCH = {
    'title': 'Ngân hàng từ vựng A1–C1: Học tập và đời sống',
    'exam_type': 'TOEIC', 'content_type': 'vocabulary',
    'source_name': 'Tự biên soạn; mức từ đối chiếu sơ bộ với English Vocabulary Profile',
}
OLD_MATCH = {
    'term': 'trip', 'part_of_speech': 'noun', 'meaning_vi': 'chuyến đi', 'cefr_level': 'B1',
    'example_en': 'We took a short trip to the coast last weekend.',
    'example_vi': 'Cuối tuần trước', 'topic': 'chúng tôi đã có chuyến đi ngắn đến bờ biển.',
    'source_name': 'AI hỗ trợ soạn thảo; cần giảng viên rà soát', 'source_url': '',
    'rights_note': 'Nội dung gốc, không sao chép Cambridge/ETS; CEFR tạm thời, cần rà soát ngôn ngữ.',
    'pronunciation': '', 'audio_url': '', 'order': 609,
}
REPAIRED_VALUES = {
    'example_vi': 'Cuối tuần trước, chúng tôi đã có chuyến đi ngắn đến bờ biển.',
    'topic': 'Travel',
}

DERIVED_PARENT = {'title': 'Vocabulary B1: Chọn nghĩa đúng · Bộ 11', 'exam_type': 'TOEIC',
    'content_type': 'vocabulary', 'source_name': 'Tự biên soạn từ bộ flashcard starter'}
DERIVED_OLD = {'order': 14, 'prompt': '“trip” có nghĩa gần nhất là gì?', 'passage': '',
    'audio_url': '', 'audio_script': '', 'transcript': '',
    'explanation': 'trip: chuyến đi. Ví dụ: We took a short trip to the coast last weekend.',
    'explanation_vi': 'trip nghĩa là “chuyến đi”. Ví dụ: We took a short trip to the coast last weekend. — Cuối tuần trước'}
DERIVED_NEW = DERIVED_OLD['explanation_vi'] + ', chúng tôi đã có chuyến đi ngắn đến bờ biển.'
HOLD_NOTE = 'Đã sửa lỗi lệch cột CSV của trip; tạm giữ riêng thẻ để người có chuyên môn rà lại trước khi sử dụng.'


def _invalidate(parent):
    parent.is_published = False
    parent.review_status = 'draft'
    parent.reviewer = ''
    parent.reviewed_at = None
    parent.review_note = ''
    parent.source_checked_on = None
    parent.save(update_fields=['is_published', 'review_status', 'reviewer', 'reviewed_at',
        'review_note', 'source_checked_on', 'updated_at'])


class Command(BaseCommand):
    help = 'Sửa đúng bản ghi trip bị lệch cột CSV; mặc định chỉ xem trước, không ghi dữ liệu.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--dry-run', action='store_true', help='Chỉ hiển thị bản ghi khớp; đây là chế độ mặc định.')
        mode.add_argument('--apply', action='store_true', help='Áp dụng sửa hai trường và đưa bộ học liệu về nháp.')
        parser.add_argument('--quarantine-card', action='store_true',
            help='Tạm giữ riêng thẻ sau sửa; chỉ dùng cho bộ chưa giảng viên duyệt. Bản sao lời giải cũ được sửa và bộ câu liên quan về nháp.')

    @transaction.atomic
    def handle(self, *args, **options):
        quarantine = options['quarantine_card']
        # A stable parent ordering also covers the small derivative question set.
        from django.db.models import Q
        locked = list(LearningContent.objects.select_for_update().filter(
            Q(**PARENT_MATCH) | Q(**DERIVED_PARENT)).order_by('pk'))
        parents = [parent for parent in locked if all(getattr(parent, key) == value for key, value in PARENT_MATCH.items())]
        matches = list(Flashcard.objects.select_for_update().filter(
            content__in=parents, **OLD_MATCH,
        ).order_by('pk'))
        if len(matches) > 1:
            raise CommandError('Có nhiều bản ghi khớp; không tự chọn hoặc thay đổi dữ liệu.')
        if not matches:
            self.stdout.write('Không có bản ghi trip khớp chính xác lỗi/nguồn đã biết. Không thay đổi dữ liệu.')
            return
        card = matches[0]
        self.stdout.write(f'Khớp flashcard #{card.pk}, content #{card.content_id}: sửa example_vi và topic.')
        parent = next(item for item in parents if item.pk == card.content_id)
        derivatives = []
        if quarantine:
            if parent.review_status not in ('draft', 'language_checked'):
                raise CommandError('Không giữ nhãn duyệt chuyên môn khi sửa nguồn; dùng quy trình rà soát lại cả bộ.')
            derived_parents = [item for item in locked if all(getattr(item, key) == value for key, value in DERIVED_PARENT.items())]
            candidates = list(Question.objects.select_for_update().filter(
                content__in=derived_parents, prompt=DERIVED_OLD['prompt']).prefetch_related('options').order_by('pk'))
            if len(candidates) > 1:
                raise CommandError('Bản sao câu hỏi không duy nhất; không tự sửa dữ liệu.')
            expected_options = [('A', 'địa danh nổi bật', False), ('B', 'chuyến đi', True),
                ('C', 'nhân viên lễ tân', False), ('D', 'tài liệu điện tử', False)]
            for question in candidates:
                if (any(getattr(question, key) != value for key, value in DERIVED_OLD.items())
                        or [(option.label, option.text, option.is_correct) for option in question.options.all()] != expected_options):
                    raise CommandError('Bản sao lời giải đã được chỉnh sửa; giữ nguyên để người biên tập đối chiếu.')
                derivative_parent = next(item for item in derived_parents if item.pk == question.content_id)
                if derivative_parent.review_status not in ('draft', 'language_checked'):
                    raise CommandError('Bộ câu hỏi đã duyệt chuyên môn; không tự ghi đè nguồn đã duyệt.')
                derivatives.append((question, derivative_parent))
            self.stdout.write(f'Tạm giữ riêng thẻ #{card.pk}; giữ trạng thái xuất bản hiện tại của bộ từ vựng. Không tự mở lại thẻ.')
            for question, source in derivatives:
                self.stdout.write(f'Sửa bản sao lời giải câu #{question.pk}; bộ #{source.pk} gồm {source.questions.count()} câu về nháp/chưa xuất bản.')
            if not options['apply']:
                self.stdout.write('DRY RUN: không ghi dữ liệu.')
                return
            for key, value in REPAIRED_VALUES.items():
                setattr(card, key, value)
            card.is_available, card.availability_note = False, HOLD_NOTE
            card.save(update_fields=[*REPAIRED_VALUES, 'is_available', 'availability_note'])
            for question, source in derivatives:
                question.explanation_vi = DERIVED_NEW
                question.save(update_fields=['explanation_vi'])
                _invalidate(source)
            self.stdout.write(self.style.SUCCESS('Đã sửa nguồn lỗi và tạm giữ thẻ; lịch sử giữ nguyên, chưa duyệt hoặc xuất bản lại.'))
            return
        self.stdout.write(self.style.WARNING(
            f'CẢNH BÁO: --apply sẽ chuyển cả bộ #{parent.pk} "{parent.title}" về NHÁP/CHƯA XUẤT BẢN; '
            f'ảnh hưởng {parent.flashcards.count()} thẻ, {parent.questions.count()} câu hỏi '
            f'(hiện is_published={parent.is_published}, review_status={parent.review_status}). '
            'Không tự xuất bản lại hoặc xác nhận giáo viên duyệt.'
        ))
        if not options['apply']:
            self.stdout.write('DRY RUN: không ghi dữ liệu. --apply sẽ sửa thẻ và xóa trạng thái duyệt/xuất bản của bộ.')
            return
        for key, value in REPAIRED_VALUES.items():
            setattr(card, key, value)
        card.save(update_fields=list(REPAIRED_VALUES))
        _invalidate(parent)
        self.stdout.write(self.style.SUCCESS('Đã sửa trip; bộ học liệu cần rà soát và xuất bản lại.'))
