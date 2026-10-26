# Workplace collocations v1

Bộ học liệu gốc gồm **40 cụm từ về công việc**, **40 flashcard** và **80 câu trắc nghiệm**. Bốn chủ đề, mỗi chủ đề có 10 mục:

| Chủ đề | Ví dụ cụm từ |
| --- | --- |
| Cộng tác văn phòng | meet a deadline, take minutes, delegate a task |
| Tài chính và mua sắm | reimburse expenses, settle an invoice, waive a fee |
| Đi công tác | board a flight, collect baggage, make a connection |
| Nhân sự và nghề nghiệp | shortlist candidates, extend a job offer, undergo training |

Mỗi chủ đề tạo một bộ thẻ và hai bộ bài luyện, mỗi bộ bài luyện 10 câu: chọn nghĩa trong ngữ cảnh và điền từ vào cụm từ. Tổng cộng **12 bộ học liệu**, **320 phương án**, mỗi câu có đúng một đáp án được lưu phía máy chủ. Câu điền từ giữ lại phần còn lại của cụm từ để người học luyện kết hợp từ.

Nghĩa tiếng Việt, ví dụ song ngữ và lời giải được tự biên soạn có AI hỗ trợ. B1/B2 là mức tham khảo của từng thẻ; bộ hỗn hợp được gắn B2 để định tuyến. Đây **không phải danh sách hoặc đề thi Cambridge/ETS chính thức**. Nội dung chưa được giáo viên duyệt toàn bộ. Phương án nhiễu ở một số bài điền từ khá dễ, phù hợp học ban đầu hơn đánh giá chuẩn hóa.

## Nhập dữ liệu

Kiểm tra cấu trúc, không thay đổi dữ liệu:

```bash
python manage.py seed_toeic_workplace --dry-run
```

Nhập dưới dạng bản nháp để quản trị viên rà soát:

```bash
python manage.py seed_toeic_workplace
```

Xuất bản sơ bộ ngay khi tạo mới:

```bash
python manage.py seed_toeic_workplace --publish-provisional
```

Lệnh chỉ tạo bộ chưa có dựa trên định danh `question_type` ổn định. Chạy lại giữ nguyên mọi sửa đổi, tiêu đề, trạng thái duyệt và dữ liệu học tập của bộ đã nhập. Vì vậy, chạy cờ xuất bản sau khi đã nhập nháp **không tự xuất bản lại các bộ cũ**; hãy rà soát và xuất bản trong admin. Các cụm từ trùng bộ khác làm lệnh dừng và hoàn tác toàn bộ lượt nhập, tránh tạo thẻ trùng hoặc thay thế học liệu của người biên tập.

Kiểm tra tự động xác nhận: 40 mục khác nhau, bốn chủ đề cân bằng, ví dụ chứa đúng một cụm mục tiêu và một từ cần điền, bốn phương án khác nhau, một đáp án, seed lặp không tạo trùng, bản nháp mặc định và giữ nguyên sửa đổi. Các kiểm tra này không chứng minh mức CEFR hoặc độ khó đã được hiệu chuẩn.
