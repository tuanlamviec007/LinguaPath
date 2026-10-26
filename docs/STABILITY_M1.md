# LinguaPath — Bản ổn định M1

Ngày hoàn thiện: **24/10/2026**. Bản này triển khai phần sửa lỗi học tập W1/W2 và một phần nền tảng W0 từ audit 23/10; chưa phải nghiệm thu production.

## Những thay đổi có thể kiểm tra

| Phát hiện audit | Thay đổi |
|---|---|
| D01 — Kết quả practice đổi theo nguồn | Lưu snapshot kết quả và bằng chứng từng câu lúc nộp. Trang kết quả và Sổ lỗi dùng đề/lựa chọn/lời giải đã lưu, kể cả khi option nguồn bị xóa. |
| D02 — Tab cũ ghi đè nháp | Practice và ôn câu sai kiểm tra draft_revision ở cả lưu và nộp. Tab cũ nhận 409, không ghi đè đáp án mới. Nộp lại lượt hoàn thành vẫn trả cùng kết quả. |
| D03 — Request lưu treo | Timeout 15 giây, giữ lựa chọn, mở lại thao tác sau lỗi. Chờ ACK đang chạy trước nộp; không cho ACK muộn sửa trạng thái sau conflict. |
| D04 — Hard trước hạn đẩy lịch xa | Giữ nguyên due_at và interval khi chọn Khó trước hạn. Again vẫn cho học lại sau khoảng ngắn; known sớm vẫn bị chặn tăng lịch. |
| D05 — Mục tiêu xóa task hoàn thành | Giữ task done và thời gian đã học. Chỉ xây lại phần chưa hoàn thành khi đầu vào planner thật sự đổi; score/date/no-op không xóa task. Áp dụng placement cũng giữ task done. |
| D06 — Lịch sử hiển thị cũ và tải toàn bộ | Tổng hợp số liệu bằng SQL; phân trang 20 lượt, sắp xếp mới nhất trước và có link kết quả. Loại lượt tương lai và của tài khoản khác. |
| O03/O06 và một phần W0 | Schema-aware readiness, liveness riêng, check_schema trước startup; lệnh test đầy đủ và workflow CI có PostgreSQL service. |

## Quy tắc bản nháp

- Server giữ revision tăng sau mỗi lần lưu thành công. Cả JSON autosave và form submit gửi draft_revision hiện tại.
- Hai tab cùng revision không thể cùng thay thế bản nháp thành công. Tab cũ nhận 409; chọn tải lại sẽ thay lựa chọn chưa lưu trên trang sau khi xác nhận.
- Trang được khôi phục bằng Back/Forward cache bị khóa lưu/nộp cho tới khi tải lại; không tự lưu trạng thái cũ.
- Lỗi mạng giữ lựa chọn và cảnh báo chưa lưu. Timeout không có nghĩa server chắc chắn chưa nhận request; lần thử lại vẫn qua kiểm tra revision.
- Không có tự hợp nhất hai bản nháp hoặc chế độ offline. No-JS vẫn dùng form thường, có hidden revision; nếu xung đột server giữ lựa chọn đã gửi trên trang lỗi và hướng dẫn tải lại.
- Trang cũ đã mở trước nâng cấp không có token được hiểu là revision 0; không thể ghi đè bản có revision lớn hơn 0.
- Xác nhận nộp bài chưa trả lời đủ có một controller sở hữu. Hủy xác nhận không khóa nút lưu/nộp hoặc làm mất lựa chọn.

## Bằng chứng kết quả và dữ liệu cũ

Migration 0018 thêm PracticeAttempt.result_snapshot, AttemptAnswer.evidence_snapshot và draft_revision cho practice/mistake review. Kết quả mới lưu đề, stimulus, các lựa chọn, đáp án đã chọn, khóa đúng, lời giải, tiêu đề/kỹ năng và thời điểm nộp.

**Không backfill bản gốc cho lịch sử cũ:** dữ liệu trước M1 không chứa câu chữ nguyên bản đầy đủ. Chúng được gắn thông báo nội dung giải thích đang lấy từ ngân hàng hiện tại; điểm lịch sử vẫn được giữ. Snapshot mới bị hỏng không được âm thầm thay bằng học liệu hiện tại.

Các trang đang làm không nhận evidence chứa đáp án. Hỏi Tutor từ kết quả được ghi rõ là hỏi về câu hiện tại; không khẳng định Tutor đã dùng snapshot lịch sử.

Các writer cùng chủ sở hữu dùng thứ tự khóa nhất quán; nguồn được khóa trước khi chấm. Admin sửa/xóa nội dung lấy khóa parent trước child để giảm nguy cơ đảo thứ tự khóa. GET đọc phiên cũ không được đổi một lượt đã nộp trở lại abandoned.

## Planner và lịch sử

Relevant planner inputs: exam_goal, current_cefr, target_cefr, daily_minutes. Tracking-only target_score/target_date không làm lại kế hoạch đã có.

Task done được giữ kể cả khi nguồn bị ẩn hoặc đổi kỳ thi; phút đã học tính vào cùng ngân sách ngày. Đổi mục tiêu chỉ thêm bài vừa thời gian còn lại và giới hạn số task; dashboard không tự nạp thêm bài sau khi làm xong. Danh sách hiển thị chỉ gồm nội dung hợp lệ của mục tiêu hiện tại.

Đây vẫn là planner heuristic; các hạn chế placement/mastery/độ phủ Reading–Listening trong audit chưa được giải quyết ở M1.

## Nâng cấp bản đã có dữ liệu

1. Dừng ghi hoặc dùng quy trình release phù hợp; sao lưu DB và kiểm tra khả năng phục hồi.
2. Cập nhật mã nguồn, giữ DB hiện có. Không chạy lại seed trên dữ liệu đã biên tập.
3. Trong môi trường Django đã cấu hình đúng DB, chạy:

```bash
python manage.py check
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py check_schema
python manage.py collectstatic --noinput
```

4. Khởi động phiên bản mới; /healthz/ phải ready. /livez/ chỉ kiểm tra tiến trình, không thay schema gate.
5. Thử mở tiếp phiên đang dở, lưu/nộp, lịch sử và Sổ lỗi. Tab đã mở từ trước nên tải lại để nhận controller/token mới.

Migration chỉ thêm trường, không chỉnh học liệu hoặc tự chuyển trạng thái teacher_approved. Trước downgrade phải đánh giá mất snapshot/revision; không chạy migration ngược tùy tiện trên dữ liệu đang dùng.

## Phạm vi kiểm chứng

Kết quả toàn bộ suite bản cuối ngày 24/10: **427 Django tests được phát hiện, 424 đạt và 3 PostgreSQL-only tests được skip trên SQLite; 78/78 JavaScript tests đạt**. Không có test thất bại. Django system check, migration drift và pip check đều đạt. Migration 0018 đã áp dụng trên DB làm việc sau khi sao lưu: số row nghiệp vụ giữ nguyên, SQLite integrity check đạt và không có vi phạm khóa ngoại.

Các regression bao phủ source edit/option delete, legacy/corrupt evidence, stale save/submit, save sau nộp, nộp lặp, stale GET invalidation, ownership/CSRF, Hard lặp, ngân sách/task done, history/pagination và schema gate.

Browser QA dùng template hiện tại render từ fixture riêng: xác nhận nộp chưa đủ câu → Cancel vẫn giữ lựa chọn và nút thao tác; tiếp tục đổi/lưu; xem kết quả, cảnh báo legacy và phân trang lịch sử. Autosave ở browser dùng network mock riêng cho fixture. Backend HTTP/DB được kiểm tra bằng Django Client; chưa phải E2E browser–Django live. Môi trường preview không chạy được Python nên không dựng server Django thứ hai để lách supervisor.

## Những phần vẫn còn mở

- PostgreSQL concurrency tests có trong suite nhưng bị skip trên SQLite; cần chạy CI thật để xác nhận khóa đồng thời.
- Workflow đã chuẩn bị, chưa có repository/runner được kết nối để chứng minh CI chạy; chưa có Python transitive hash lock hoặc image digest pin đầy đủ.
- Chưa build/run Docker hay nghiệm thu Cloudflare, PostgreSQL production, backup/restore/load test.
- Auth abuse, quyền CSV importer, recall ambiguity, học liệu được người duyệt, weak-word performance và AI quality thuộc các gói kế tiếp trong audit.
- Không gọi model thật, không deploy và không tạo remote repository trong bản cập nhật này.

Xem audit gốc trong AUDIT_PLAN_2026-10-23.md; báo cáo đó ghi nhận trạng thái trước sửa, còn tài liệu này mô tả bản M1 hiện tại.
