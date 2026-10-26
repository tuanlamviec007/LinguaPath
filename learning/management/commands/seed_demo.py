from django.core.management.base import BaseCommand
from django.utils import timezone
from learning.models import AnswerOption, Flashcard, LearningContent, Question


class Command(BaseCommand):
    help = 'Load a small, original TOEIC-style demo dataset (not official exam material).'

    ai_reviewer = 'AI rà soát sơ bộ; chưa được giáo viên duyệt'
    vocab_review_note = 'Rà soát sơ bộ nghĩa, từ loại và ví dụ; nhãn CEFR cần xác minh theo đúng sense và giáo viên.'
    reading_review_note = 'Rà soát sơ bộ tính rõ ràng của câu hỏi, đáp án và ngôn ngữ; cần pilot người học.'

    def handle(self, *args, **options):
        vocab, created = LearningContent.objects.get_or_create(
            title='Từ vựng: Meetings and schedules',
            defaults={'description': 'Bộ demo tự biên soạn trong ngữ cảnh công sở. Mức CEFR chỉ là nhãn tham khảo chưa hiệu chuẩn; không dùng để xếp trình độ chính thức.', 'exam_type': 'TOEIC', 'content_type': 'vocabulary', 'skill': 'vocabulary', 'topic': 'Meetings and schedules', 'difficulty': 1, 'estimated_minutes': 8, 'source_name': 'Tự biên soạn; mức CEFR provisional', 'source_url': 'https://www.englishprofile.org/wordlists', 'rights_note': 'Từ, nghĩa và ví dụ được tự biên soạn; CEFR chưa được giáo viên xác nhận.', **self._review_defaults(self.vocab_review_note), 'is_published': True},
        )
        description = 'Bộ demo tự biên soạn trong ngữ cảnh công sở. Mức CEFR chỉ là nhãn tham khảo chưa hiệu chuẩn; không dùng để xếp trình độ chính thức.'
        description_changed = not created and vocab.description != description
        if description_changed:
            vocab.description = description
            vocab.save(update_fields=['description', 'updated_at'])
        self._refresh_review_metadata(vocab, self.vocab_review_note, content_changed=description_changed)
        demo_words = [
            ('arrive', 'A1', 'verb', 'đến một địa điểm', 'The delivery will arrive this afternoon.', 'Đơn hàng sẽ đến vào chiều nay.'),
            ('room', 'A1', 'noun', 'căn phòng hoặc không gian trong một tòa nhà', 'The meeting is in Room 12.', 'Cuộc họp diễn ra ở Phòng 12.'),
            ('send', 'A1', 'verb', 'gửi thư, tin nhắn hoặc đồ vật đến ai đó', 'Please send me the new schedule.', 'Vui lòng gửi cho tôi lịch trình mới.'),
            ('invite', 'A2', 'verb', 'mời ai đó tham gia một sự kiện', 'We invited all staff to the training session.', 'Chúng tôi đã mời toàn bộ nhân viên tới buổi đào tạo.'),
            ('repair', 'A2', 'verb', 'sửa chữa thứ bị hỏng', 'The technician will repair the printer tomorrow.', 'Kỹ thuật viên sẽ sửa máy in vào ngày mai.'),
            ('schedule', 'A2', 'noun', 'kế hoạch thời gian cho các hoạt động', 'The updated schedule is on the notice board.', 'Lịch trình đã cập nhật được dán trên bảng thông báo.'),
            ('postpone', 'B1', 'verb', 'hoãn một sự kiện hoặc hoạt động sang thời điểm muộn hơn', 'The manager postponed the presentation until 3 p.m. because the projector was not working.', 'Người quản lý đã hoãn buổi thuyết trình đến 3 giờ chiều vì máy chiếu không hoạt động.'),
            ('available', 'B1', 'adjective', 'có thời gian rảnh; có thể tham gia hoặc thực hiện việc gì', 'Ms. Nguyen is available for a short call after 2 p.m.', 'Cô/bà Nguyễn có thể tham gia một cuộc gọi ngắn sau 2 giờ chiều.'),
            ('coordinate', 'B1', 'verb', 'phối hợp các hoạt động hoặc công việc', 'Lan coordinates the weekly project meetings.', 'Lan phối hợp các cuộc họp dự án hằng tuần.'),
            ('employee', 'B1', 'noun', 'người làm việc cho một công ty hoặc tổ chức', 'Every employee must complete the safety course.', 'Mỗi nhân viên phải hoàn thành khóa học an toàn.'),
            ('negotiate', 'B2', 'verb', 'trao đổi để đạt được thỏa thuận', 'The teams negotiated a new delivery date.', 'Hai nhóm đã thương lượng ngày giao hàng mới.'),
            ('deadline', 'B2', 'noun', 'thời hạn cuối để hoàn thành việc gì', 'Please submit the expense report before the deadline.', 'Vui lòng nộp báo cáo chi phí trước thời hạn.'),
            ('applicant', 'B2', 'noun', 'người nộp đơn xin việc hoặc chương trình', 'Each applicant will receive an email this week.', 'Mỗi ứng viên sẽ nhận được email trong tuần này.'),
            ('allocate', 'C1', 'verb', 'phân bổ nguồn lực cho một mục đích cụ thể', 'The director allocated additional funds to staff training.', 'Giám đốc đã phân bổ thêm ngân sách cho việc đào tạo nhân viên.'),
            ('feasible', 'C1', 'adjective', 'có thể thực hiện được trong điều kiện thực tế', 'The team proposed a feasible plan for the software migration.', 'Nhóm đề xuất một kế hoạch khả thi cho việc chuyển đổi phần mềm.'),
            ('implement', 'C1', 'verb', 'đưa kế hoạch, quyết định hoặc hệ thống vào thực hiện', 'The company will implement the revised policy next month.', 'Công ty sẽ triển khai chính sách sửa đổi vào tháng tới.'),
        ]
        for order, (term, level, part, meaning, example_en, example_vi) in enumerate(demo_words, 1):
            Flashcard.objects.update_or_create(content=vocab, term=term, defaults={
                'cefr_level': level, 'topic': 'Workplace and schedules', 'part_of_speech': part,
                'meaning_vi': meaning, 'example_en': example_en, 'example_vi': example_vi,
                'source_name': 'Tự biên soạn',
                'rights_note': 'Nội dung gốc do nhóm đồ án tự biên soạn.', 'order': order,
            })
        Flashcard.objects.filter(content=vocab).exclude(term__in=[row[0] for row in demo_words]).delete()
        reading, created = LearningContent.objects.get_or_create(
            title='Reading: Workplace notices',
            defaults={'description': 'Bài Reading demo tự biên soạn theo phong cách thông báo công sở; không phải bài thi chính thức.', 'exam_type': 'TOEIC', 'content_type': 'reading', 'skill': 'reading', 'topic': 'Workplace announcements', 'difficulty': 1, 'estimated_minutes': 8, 'source_name': 'Tự biên soạn; định dạng tham khảo TOEIC', 'source_url': 'https://www.ets.org/toeic/test-takers/prepare.html', 'rights_note': 'Đoạn văn, câu hỏi và đáp án tự biên soạn; không phải tài liệu ETS/TOEIC chính thức.', **self._review_defaults(self.reading_review_note), 'is_published': True},
        )
        description = 'Bài Reading demo tự biên soạn theo phong cách thông báo công sở; không phải bài thi chính thức.'
        description_changed = not created and reading.description != description
        if description_changed:
            reading.description = description
            reading.save(update_fields=['description', 'updated_at'])
        self._refresh_review_metadata(reading, self.reading_review_note, content_changed=description_changed)
        items = [
            (1, 'When will the maintenance team install the new printer cartridges?', 'To: Maintenance Team\nSubject: Printer Cartridge Installation\n\nThe replacement printer cartridges will arrive on Thursday, one day later than expected. Please keep the spare cartridges in Room 204 until the delivery arrives. The maintenance team will install the new cartridges on Friday morning.', 'Câu cuối nêu rõ đội bảo trì sẽ lắp hộp mực mới vào sáng thứ Sáu.', 'C'),
            (2, 'Why was the safety briefing moved to Thursday?', 'To: All Employees\nSubject: Change to the Safety Briefing Schedule\n\nThe safety briefing planned for Tuesday at 10 a.m. has been moved to Thursday at 2:30 p.m. The auditorium will be unavailable on Tuesday because repair work is taking place there. The briefing will now be held in Training Room B. Employees who registered do not need to register again.', 'Thông báo nói khán phòng không sử dụng được vào thứ Ba vì đang sửa chữa, nên buổi hướng dẫn được chuyển lịch.', 'B'),
        ]
        choices = {
            1: [('A', 'Wednesday morning'), ('B', 'Thursday afternoon'), ('C', 'Friday morning'), ('D', 'Friday afternoon')],
            2: [('A', 'The presenter will be traveling on Tuesday.'), ('B', 'The auditorium will be under repair on Tuesday.'), ('C', 'Too few employees registered for Tuesday.'), ('D', 'Training Room B is being prepared for a different event.')],
        }
        rationale = {
            1: {'A': 'Đoạn văn không nói việc lắp đặt diễn ra vào thứ Tư.', 'B': 'Thứ Năm là ngày hộp mực được giao, không phải ngày lắp đặt.', 'C': 'Đúng: câu cuối ghi Friday morning.', 'D': 'Đoạn văn nêu buổi sáng, không phải buổi chiều.'},
            2: {'A': 'Không có thông tin người thuyết trình đi công tác.', 'B': 'Đúng: khán phòng đang được sửa chữa vào thứ Ba.', 'C': 'Không có thông tin quá ít người đăng ký; người đã đăng ký không cần đăng ký lại.', 'D': 'Training Room B là địa điểm mới, không phải lý do đổi lịch.'},
        }
        for order, prompt, passage, explanation, key in items:
            question, _ = Question.objects.update_or_create(content=reading, order=order, defaults={'prompt': prompt, 'passage': passage, 'explanation': explanation, 'explanation_vi': explanation})
            for label, text in choices[order]:
                AnswerOption.objects.update_or_create(question=question, label=label, defaults={'text': text, 'is_correct': label == key, 'explanation_vi': rationale[order][label]})
        reading.questions.filter(order__gt=len(items)).delete()
        self.stdout.write(self.style.SUCCESS('Loaded original TOEIC-style demo flashcards and Reading questions. Not official ETS content.'))

    def _review_defaults(self, review_note):
        return {
            'review_status': 'language_checked',
            'reviewer': self.ai_reviewer,
            'reviewed_at': timezone.now(),
            'review_note': review_note,
            # This is an AI content review, not a verification of the source URL.
            'source_checked_on': None,
        }

    def _refresh_review_metadata(self, content, review_note, *, content_changed=False):
        reviewer = self.ai_reviewer
        needs_refresh = content_changed or any((
            content.review_status != 'language_checked',
            content.reviewer != reviewer,
            content.review_note != review_note,
            content.source_checked_on is not None,
        ))
        if not needs_refresh:
            return
        content.review_status = 'language_checked'
        content.reviewer = reviewer
        content.reviewed_at = timezone.now()
        content.review_note = review_note
        content.source_checked_on = None
        content.save(update_fields=[
            'review_status', 'reviewer', 'reviewed_at', 'review_note',
            'source_checked_on', 'updated_at',
        ])
