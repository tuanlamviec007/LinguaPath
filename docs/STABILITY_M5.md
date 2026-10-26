# LinguaPath — chuẩn bị duyệt học liệu pilot M5

Cập nhật **25/10/2026**. Thêm công cụ chuẩn bị C01/C05: kiểm kê độ phủ, workspace admin và phiếu mẫu cho người duyệt. **Chưa có phê duyệt chuyên môn mới, chưa thêm học liệu hay đóng điều kiện pilot.** Không gọi model hoặc deploy. Không phát sinh migration; bản đã chạy M4 vẫn dùng schema0021.

## Dùng trong admin

Mở danh sách LearningContent → **Chuẩn bị duyệt pilot**. Tài khoản phải active/staff và có quyền view hoặc change đối với cả LearningContent, Question, AnswerOption và Flashcard. Quyền được đọc lại mỗi request; học viên/ẩn danh không được tải phiếu có đáp án. Tải phiếu dùng POST+CSRF, phản hồi private/no-store. Trang GET chỉ hiện metadata/count, không đưa lời giải hoặc khóa chấm vào HTML.

Lọc kỳ thi/kỹ năng/mức, chọn1–10 bộ trên một trang, tối đa100 mẫu mỗi loại trong mỗi bộ (mặc định20). Danh sách20 bộ/trang; đổi trang bỏ lựa chọn chưa xuất và giao diện nói rõ điều đó. Các query đếm cards/questions tách nhau để tránh nhân số đếm do JOIN.

Coverage của toàn kỳ thi được hiển thị riêng với bộ lọc chọn mẫu. Metadata thiếu được giữ rõ; không suy ra TOEIC Part chính thức từ tên bài hoặc tự gán CEFR. Cờ cấu trúc chỉ tìm thiếu dữ liệu/keycount, không chứng minh sense, distractor, nguồn/quyền hoặc audio đúng.

## Dùng bằng command

```bash
python manage.py audit_content_coverage --exam TOEIC
python manage.py audit_content_coverage --exam TOEIC --output /tmp/coverage.json
python manage.py export_review_packet --content-id 5 --content-id 7 --max-items 10 --output /tmp/review-sample.json
```

Command không sửa DB/gọi AI. File có sẵn không bị ghi đè nếu thiếu `--overwrite`. API/CLI kiểm tra ID/bounds trước xuất, ghi file nguyên tử; phiếu tối đa20MiB. Chọn ít mẫu/bộ hơn nếu vượt giới hạn. Đây là command quản trị có thể đọc đáp án, không cung cấp CLI này cho học viên như một API.

Phiếu giữ nguyên source/provenance, đề, stimulus, lựa chọn, key, lời giải chung/từng distractor và metadata. Mỗi item có hash; content_hash bao gồm cả child ngoài mẫu. Checklist và thông tin người duyệt để trống; `approval_allowed=false`, scope là sample. Hash không phải chữ ký/chứng nhận; bốn query không tạo một snapshot khóa nhất quán theo thời gian. Xuất khi đợt biên tập tạm dừng, đối chiếu nguồn hiện tại trước duyệt, xuất lại khi thay đổi. Không có chức năng import phiếu để tự teacher_approve.

## Hồ sơ chuẩn bị sẵn

- `content_coverage_m5.json`: kiểm kê **429 bộ, 3.056 flashcard, 5.138 câu**,0teacher_approved,67 bộ chưa có question_type,3 bộ chưa có CEFR parent, thiếu câu R/L C1.
- `pilot_review_sample_m5.json`:10 parent IDs **5,7,9,11,71,72,75,76,130,205**; mẫu **20 thẻ và24 câu**. Các bài R/L dùng mức A2/B1 tham khảo; thẻ chọn từ các bộ công việc/dịch vụ sẵn có. Chưa khẳng định mọi thẻ khớp stimulus hoặc đã được chuyên môn duyệt.
- `PILOT_BLUEPRINT.md`: blueprint dự án đề xuất cho lô A2/B1 nhỏ, checklist và quy trình reviewer/pilot. Không phải blueprint TOEIC chính thức hoặc cỡ mẫu đủ để kết luận thống kê.

Phiếu có đáp án, dành cho người duyệt có quyền. Một parent lớn có mẫu chưa đầy đủ vẫn phải rà phần còn lại; không dùng việc xuất phiếu để chứng nhận cả parent. Các bộ nguồn và trạng thái xuất bản giữ nguyên.

## Kiểm tra

Toàn bộ **621 Django tests:613 đạt,8 PostgreSQL-only skip;91/91 JavaScript tests đạt**. Thêm23 tests cho packet/coverage/admin, kiểm tra quyền, revoke permission, CSRF, invalidID, hash source ngoài mẫu, cấm ghi DB và tránh đếm nhân JOIN. Sau chỉnh diễn đạt UI,6 tests admin chạy lại đạt. System/schema/projection check, migration drift và collectstatic đạt.

Browser QA dùng template thật render từ DB memory: desktop, iframe375px, tên checkbox và bảng cuộn. Đã sửa header mobile bị tràn/cắt, chỉ còn một h1; document không tràn ngang. Đây là QA giao diện tĩnh, backend HTTP kiểm tra Django Client; chưa phải browser–Django live E2E hoặc screen reader/thiết bị thật.

Vẫn cần người có chuyên môn duyệt C01/C05, calibration C04/C06, tập đánh giá độc lập A02, model evaluation A06 và các nghiệm thu PG/CI/Cloudflare thực. M5 chỉ đưa phần chuẩn bị thành công cụ cụ thể, không thay các bằng chứng đó.
