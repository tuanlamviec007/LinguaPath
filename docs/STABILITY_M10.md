# LinguaPath — gõ từ đến lịch ôn M10

Cập nhật **25/10/2026**. Thêm cách luyện có chấm đáp án cho thẻ đến lịch ôn, tách kết quả khỏi nút tự đánh giá. **Cần migration0023**. Đây là công cụ chuẩn bị pilot C06; chưa nghiệm thu khả năng nhớ sau trễ hoặc thay tiêu chí mở mức.

## Nâng cấp và sử dụng

Backup database trước khi cập nhật mã nguồn, dừng tiến trình cũ trong lúc migrate rồi khởi động lại cùng phiên bản mã nguồn:

```bash
python manage.py migrate
python manage.py check_schema
python manage.py check_weak_word_outcomes
```

Không seed lại hoặc backfill bằng chứng nhớ từ lịch sử. Nếu nâng từ bản trước M9, thực hiện thêm các bước sửa nguồn được mô tả trong `STABILITY_M9.md`. Migration0023 thêm lựa chọn nguồn `due` và bảng `DueRecallObservation`; không sửa lịch học, điểm hoặc học liệu hiện có. Rollback mã nguồn và schema cần đi cùng nhau; export/backup trước khi reverse migration vì bảng quan sát mới sẽ bị xóa.

Vào **Quiz thử thách → Gõ từ đến lịch ôn**, hoặc từ **Tiến độ → Gõ từ đến lịch ôn**. Bài chỉ gõ từ tiếng Anh, dùng cùng gợi ý nghĩa/từ loại/chữ đầu/số từ và quy tắc chấm hiện có. Có thể bắt đầu từ1 câu, tối đa5/10/15 câu, lọc mức/chủ đề và không bù bằng từ mới. Không có từ phù hợp thì hiển thị cách quay về flashcard.

## Điều kiện chọn và ghi nhận

- Thẻ khả dụng, parent vocabulary đã xuất bản/trạng thái được phép, đúng kỳ thi của người học; gợi ý phải qua kiểm tra mơ hồ trên toàn kho hiện hành.
- Có `UserFlashcardState` của chính tài khoản, `due_at <= now`, `reviewed_at <= now - 24 giờ`. Áp dụng cho cả ba lựa chọn tự đánh giá, không chỉ “Đã nhớ”. Mốc24 giờ là quy tắc sản phẩm cho cách luyện, chưa phải ngưỡng mastery được hiệu chuẩn.
- Snapshot mới giữ policy `due-self-rating-gap-v1`, thời điểm chọn, thời điểm tự đánh giá gần nhất, parent ID và hash nguồn tại lúc chọn quiz. Không có snapshot nguồn tại lần tự đánh giá cũ; không suy luận rằng người học đã học cùng phiên bản nguồn ở mốc đó.
- Một mốc tự đánh giá chỉ được dùng một lần sau khi nộp quiz nguồn due. Câu bị loại khỏi thống kê vẫn tiêu thụ mốc vì người học đã xem feedback. Cần tự đánh giá flashcard lại, chờ đủ24 giờ và đến hạn để có lần ghi nhận tiếp theo.
- Trước tạo quiz: khóa User rồi parent/card theo ID; đọc lại lịch, receipt và nguồn. Hai tab chuẩn bị cùng một mốc không được tái sử dụng mốc đã tiêu thụ ở tab kia. Card chuyển sang parent chưa được khóa làm lựa chọn hết hiệu lực, không khóa thêm parent sai thứ tự.
- Nộp bài giữ thứ tự User → Quiz → Parent → Card; kiểm tra visibility dưới khóa trước chấm/thưởng. Thẻ bị giữ/ẩn/xóa làm lượt hết hiệu lực. Nguồn đổi câu chữ/parent hoặc người học tự đánh giá lại trong lúc làm làm quan sát bị loại; điểm quiz vẫn theo snapshot đề đã lưu.
- Ghi điểm, thưởng và quan sát trong cùng transaction; lỗi ghi quan sát rollback toàn bộ lượt nộp. Nộp lặp chỉ trả kết quả cũ. Luyện lại từ sai xóa metadata due khỏi snapshot mới và không tạo quan sát mới.

Quiz nguồn due đầu tiên không phải retry, dùng quy tắc thưởng quiz mới hiện có: tối đa một thưởng/ngày, không có thưởng riêng cho khoảng trễ. Retry không cộng XP. Các kết quả vẫn vào danh sách từ cần ôn qua projection hiện có. Quiz không thay SRS, self-rating, lịch nhiệm vụ hoặc `current_cefr`.

## Hiển thị kết quả và quyền riêng tư

Trang kết quả hiện mốc tự đánh giá/nộp và trạng thái gõ đúng/sai hoặc lý do loại cho từng mục. Panel Tiến độ tính30 ngày bằng SQL aggregate trên bảng quan sát, không đọc snapshot các quiz cũ. Chỉ hiện tỷ lệ khi có ít nhất5 câu được tính; đây là điều kiện hiển thị, không phải đủ mẫu để kết luận thống kê. Quiz tổng hợp vẫn là điểm theo đề đã lưu; panel riêng loại nguồn/mốc thay đổi và không gộp retry. Lịch sử có bộ lọc nguồn due, giữ rõ lượt mới/luyện lại.

Bảng quan sát liên kết quiz để kiểm tra ownership, cascade khi tài khoản bị xóa; bản xuất dữ liệu riêng có section `due_recall_observations`. Không lưu lại nội dung nguồn vào bảng này; wording/key nằm trong snapshot quiz vốn có. ID thẻ dạng số cho phép giữ ghi nhận lịch sử khi thẻ bị xóa hoặc giữ, không tự sửa lịch sử sau biên tập. Không công khai đáp án/hash/mốc private trong play context. Dữ liệu nguồn cũ không được tạo thành quan sát hồi tố.

Planner vẫn mở thêm phạm vi mức kế khi ít nhất80% thẻ mức hiện tại có tự đánh giá gần nhất “Đã nhớ”, trong giới hạn mục tiêu; thuật toán không đổi. Lời giải thích và từng hàng/aria tiến độ đã dùng thuật ngữ tự đánh giá, tránh gọi tỷ lệ này là bằng chứng đã thành thạo. Thử nội dung mức kế không nâng `current_cefr`.

## Giới hạn và bước pilot còn lại

Bài vẫn có gợi ý và hệ thống không quan sát mọi lần xem lại qua các luồng khác, tab khác hoặc ngoài ứng dụng. Khoảng cách giữa hai bản ghi không chứng minh người học không học lại. Chưa đo nhớ không gợi ý, chưa có nguồn baseline cũ bất biến, chưa có nhóm đối chứng hoặc kết luận nhân quả. Không dùng tỷ lệ mới tự mở mức/đổi CEFR.

Trước pilot thực tế: người có chuyên môn duyệt lô thẻ; chốt phiên bản nguồn/loại gợi ý, thiết kế các mốc thời gian và cách ghi nhận học xen kẽ, lấy chấp thuận người học và quy định lưu dữ liệu. Thu kết quả gõ đúng/sai lẫn câu loại, xem mức tham gia/bỏ dở và khác biệt giữa nhóm. Việc chọn mẫu, cỡ mẫu, ngưỡng mastery và thay chính sách planner vẫn cần chuyên môn; dữ liệu QA không thay cho pilot. C06 tiếp tục mở.

## Kiểm chứng

Bộ đầy đủ: **783 Django tests:775 đạt,8 PostgreSQL-only skip;105/105 JavaScript tests đạt**. M10 thêm22 Django tests và1 JS test cho thời điểm biên24 giờ, ownership/exam/visibility, gợi ý mơ hồ, nguồn/chủ đề/mức, snapshot không lộ key, baseline tiêu thụ/đánh giá lại, nguồn sửa/chuyển/giữ khi khóa, retry/idempotency/CAS, rollback, thống kê và privacy cascade/export. Giữ một query cho đọc candidate/aggregate trong fixture SQLite; chưa phải bằng chứng plan/load PostgreSQL.

Hai agent thực hiện UI/nhãn và rà backend; đã sửa race tái dùng baseline ở hai tab và kiểm tra nguồn dưới khóa trước chấm. Browser QA dùng template Django thật render từ database memory với tài khoản QA tổng hợp: hub/result/progress và trạng thái trống. Desktop1348px và khung iframe375px (document360px có scrollbar) không tràn ngang. Đây là QA tĩnh; backend kiểm chứng bằng Django Client, chưa phải browser→Django live E2E/thiết bị thật.

Database dự án có0 tài khoản học; đã backup trước migration0023, kiểm tra integrity và đối chiếu mọi dòng bảng cũ. Các dòng cũ giữ nguyên; Django thêm1 content type,4 định nghĩa quyền chuẩn cho model mới và1 migration record, không gán quyền cho tài khoản/nhóm. Không có dữ liệu người học hoặc quan sát pilot được tự tạo trong database chính. `due_recall_migration_m10.json` ghi bằng chứng schema/đối chiếu và giới hạn. CI/PG/Docker/Cloudflare, chuyên môn và model thật vẫn chưa được nghiệm thu.
