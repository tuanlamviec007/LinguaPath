# Chuẩn bị pilot học liệu LinguaPath

Ngày chuẩn bị: **25/10/2026**. Đây là **đề xuất phạm vi và quy trình của dự án**, chưa phải blueprint TOEIC chính thức, chưa được giảng viên chốt, chưa hiệu chuẩn CEFR và chưa có học liệu nào được công cụ này duyệt chuyên môn.

## 1. Kiểm kê hiện tại

Lệnh chỉ đọc `python manage.py audit_content_coverage` kiểm kê nguồn theo kỳ thi, kỹ năng, nhãn CEFR, trạng thái duyệt và xuất bản. Báo cáo có ba query theo batch, không đọc tài khoản, câu trả lời, kết quả hoặc lịch sử người học. “Visible” chỉ là đã xuất bản với trạng thái cho phép học; không cấp quyền đọc đáp án câu chưa nộp.

Kho TOEIC tại thời điểm chuẩn bị có **429 bộ, 3.056 flashcard, 5.138 câu hỏi**, toàn bộ 429 bộ xuất bản ở `language_checked`, **0 bộ `teacher_approved`**. Reading có30 câu, Listening có28 câu. Có67 bộ chưa có `question_type` và3 bộ chưa có nhãn CEFR ở cấp parent. Không tự suy ra TOEIC Part từ tên bài hoặc từ các nhãn nội bộ như `foundation-advanced`.

| Kỹ năng | A1: bộ/câu | A2: bộ/câu | B1: bộ/câu | B2: bộ/câu | C1: bộ/câu | Chưa gán mức: bộ/câu |
|---|---:|---:|---:|---:|---:|---:|
| Reading | 3/6 | 3/6 | 2/8 | 2/8 | 0/0 | 1/2 |
| Listening | 2/4 | 4/8 | 2/8 | 2/8 | 0/0 | 0/0 |

Các kiểm tra cấu trúc hiện không phát hiện câu thiếu đề, thiếu lời giải, dưới hai lựa chọn hoặc khác một khóa đúng; không có Listening thiếu cả audio/script. **Điều này không chứng minh khóa đúng, ví dụ tự nhiên, distractor hợp lý, quyền sử dụng hợp lệ hay file audio phát được.** Các phần đó cần người duyệt.

```bash
# In JSON ra stdout, không ghi DB:
python manage.py audit_content_coverage --exam TOEIC
# Lưu báo cáo; không ghi đè file có sẵn nếu chưa dùng --overwrite:
python manage.py audit_content_coverage --exam TOEIC --output /tmp/toeic-coverage.json
```

Báo cáo nhóm thẻ theo CEFR của chính thẻ; nhóm câu theo CEFR của parent. Hai loại nhãn này không được thay thế cho nhau. Kho đang được biên tập đồng thời có thể thay đổi giữa ba query, nên cần đóng băng đợt biên tập và ghi lại version/hash khi xuất gói reviewer. Báo cáo ghi cảnh báo nếu child mới không còn khớp parent đã tải; không coi báo cáo đó là snapshot nhất quán để phê duyệt.

## 2. Phạm vi nhỏ đề xuất cho đợt đầu

Ưu tiên một lô **A2/B1 tham khảo**, để nhóm dự án kiểm tra hành trình từ nguồn → câu hỏi → đáp án → lời giải → ôn lại trước khi mở rộng. Lựa chọn này là phạm vi khả thi dựa kho hiện tại, không phải khẳng định phù hợp mọi người học hoặc mọi mục tiêu điểm thi.

| Nhóm pilot đề xuất | Phạm vi tối thiểu để chuẩn bị | Chủ điểm cần đa dạng |
|---|---|---|
| Reading A2 | 2 bài, ít nhất4 câu | Thông báo/lịch hẹn/email ngắn; thông tin cụ thể và mục đích |
| Reading B1 | 2 bài, ít nhất4 câu | Email/công việc; diễn đạt tương đương và suy luận có bằng chứng |
| Listening A2 | 2 bài, ít nhất4 câu | Hội thoại/thông báo ngắn; người, thời gian và địa điểm |
| Listening B1 | 2 bài, ít nhất4 câu | Thay đổi kế hoạch/công việc; lý do, hành động tiếp theo và paraphrase |
| Từ vựng liên quan | 20–30 thẻ được chọn từ ngữ cảnh các bài | Một nghĩa/POS/ngữ cảnh rõ, ví dụ Anh–Việt tự nhiên |

Đây là **mục tiêu chuẩn bị mẫu**, không phải cỡ mẫu đủ để kết luận thống kê. Người duyệt phải chốt loại nhiệm vụ, mức tham khảo và số item cuối cùng. Chưa tự thêm câu, gán Part hoặc sửa hàng loạt metadata hiện hành. C1 thiếu không có nghĩa phải biên soạn C1 trước pilot A2/B1.

## 3. Reviewer cần ghi gì

Mỗi phiếu phải giữ ID/version nguồn và nguyên văn câu/thẻ đã xem. Các mục gợi ý gồm:

| Mục rà soát | Bằng chứng cần ghi |
|---|---|
| Nghĩa và ngữ cảnh | Nghĩa/POS có đúng ngữ cảnh không; ví dụ song ngữ có tự nhiên và phân biệt được sense không |
| Khóa đúng | Trích bằng chứng trong stimulus; có đúng một lựa chọn hợp lý hay không |
| Phương án nhiễu | Giải thích từng phương án; loại distractor vô lý hoặc có thể đúng trong cùng ngữ cảnh |
| CEFR và độ khó | Nhãn hiện tại là tham khảo; ghi lý do đề nghị giữ/đổi, không gọi là calibration đã hoàn thành |
| Listening | Nghe file thực, đối chiếu script/transcript, đánh dấu dùng giọng tổng hợp/TTS, kiểm tra tốc độ và khả năng tiếp cận |
| Nguồn/quyền sử dụng | Kiểm tra provenance, nguồn và quyền thực tế; việc có chuỗi rights_note không phải chứng cứ đủ |
| Kết luận từng item | Đồng ý / cần sửa / chưa đủ thông tin; ghi lỗi, sửa đề xuất, tên người duyệt/chuyên môn và ngày |

Agent chỉ giúp xuất/kiểm tra cấu trúc và tổng hợp lỗi; không được ghi tên giảng viên giả, tự điền kết luận con người hoặc tự chuyển `teacher_approved`. Gói mẫu không đủ để chứng nhận cả parent có hàng trăm câu/thẻ. Sau sửa phải tạo phiên bản và rà lại phần bị ảnh hưởng; không dùng phiếu cũ để duyệt nguồn mới.

## 4. Sau khi được người duyệt chốt

1. Chọn và đóng băng đúng lô/version, lưu kết quả review từng item, xử lý bất đồng và rà lại bản sửa.
2. Người có quyền và chuyên môn chịu trách nhiệm duyệt/xuất bản qua quy trình admin; tách việc chuẩn bị packet khỏi hành động phê duyệt. Không tự xuất bản từ báo cáo coverage.
3. Chạy pilot có phạm vi và sự đồng ý phù hợp; thu kết quả bằng mã người tham gia giả danh, không cần IP thô/câu chat riêng. Theo dõi hoàn thành, lỗi kỹ thuật, câu hay gây nhầm, thời gian và phản hồi theo kỹ năng/cách luyện.
4. Kiểm tra độ khó, khả năng phân biệt và độ ổn định khi có đủ dữ liệu; đặt tiêu chí nghiệm thu trước phân tích. Không đổi `current_cefr`, mastery hoặc kết luận tăng năng lực từ một quiz nhỏ/XP/self-rating.
5. Chuẩn bị tập intent/sense/negative mới cho Tutor do người chấm giữ độc lập trước khi điều chỉnh retrieval/model. Bộ regression đã biết chỉ dùng chống tái phát lỗi, không gọi là holdout mới.

Các điều kiện chuyên môn C01/C04/C05/C06 và đánh giá độc lập A02 vẫn giữ mở đến khi có bằng chứng thật. Tài liệu này không cấp quyền dùng tài nguyên inference hoặc kết nối bất kỳ endpoint telemetry nào.
