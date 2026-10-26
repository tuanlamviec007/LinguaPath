# Lưu nháp quiz và ôn từ sai

## Trải nghiệm mới

- Chọn đáp án sẽ tự lưu sau khoảng 600ms; có nút **Lưu ngay**, số câu và thời điểm đã lưu. Lựa chọn được lưu ở máy chủ theo tài khoản, có thể mở lại từ thiết bị đã đăng nhập khác.
- Mở lại quiz đi thẳng đến câu chưa trả lời đầu tiên. Dashboard và khu Quiz có liên kết tiếp tục cùng số câu đã lưu.
- Khi lỗi mạng, lựa chọn hiện có vẫn được giữ trên trang và nút lưu cho phép thử lại. Yêu cầu lưu hết thời gian sau 15 giây; hệ thống không tự gọi lại liên tục. Cảnh báo rời trang xuất hiện khi có thay đổi chưa được xác nhận.
- Hai tab cùng quiz dùng phiên bản bản nháp. Tab cũ nhận thông báo xung đột và dừng ghi; nút mở bản mới dùng GET để tránh gửi lại biểu mẫu cũ. Khi quay lại bằng Back với trang từ bộ nhớ trình duyệt, cần mở lại bản đã lưu trước khi ghi tiếp.
- Nộp bài đợi yêu cầu lưu đang chạy kết thúc, rồi gửi lựa chọn hiện tại và phiên bản đã xác nhận. Lượt lưu đến sau khi nộp không thể đổi điểm hoặc đáp án. Không bật JavaScript vẫn có thể làm và nộp toàn bộ bài; tự lưu cần JavaScript.

## Ôn riêng các từ vừa sai

Trang kết quả có nút **Ôn lại N từ đã nhầm** khi còn từ sai khả dụng. Lượt ôn giữ đúng ngữ cảnh/nghĩa trong snapshot của bài gốc, xáo lại vị trí phương án và chỉ lấy từ sai còn được xuất bản. Có thể ôn một từ. Nếu một lượt quiz đang dở, cần tiếp tục hoặc dừng lượt đó trước khi tạo lượt ôn.

Lượt ôn có liên kết về kết quả trước, vẫn có lưu nháp và không cộng XP quiz hoặc tiêu hao phần thưởng quiz đầu ngày. Việc ôn được ghi nhận vào chuỗi học và nhiệm vụ hoàn thành quiz trong ngày. Đây không tự động là đánh giá “đã nhớ” cho flashcard/SRS.

Trang Tiến độ thống kê quiz 30 ngày gần nhất theo mục tiêu thi đang chọn: số quiz mới, câu đúng/tổng câu, tỷ lệ đúng lượt đầu và số lượt ôn từ sai. Lượt ôn không được gộp vào tỷ lệ lượt đầu. Lịch sử vẫn ghi rõ loại từng lượt. XP, mức trò chơi và tỷ lệ đúng không quy đổi thành điểm TOEIC/IELTS.

## Cập nhật

Giữ database và cấu hình hiện có, chép mã nguồn mới rồi chạy:

```bash
python manage.py migrate
python manage.py runserver
```

Migration `0014_quiz_drafts_and_retry` thêm bản nháp, phiên bản, thời điểm lưu, liên kết lượt cha và cờ ôn lại; các lượt quiz cũ được giữ. Không cần nhập lại bộ từ Workplace hoặc bộ 3.000 từ cho đợt này. Gói mã nguồn không kèm database, môi trường Python hoặc thông tin đăng nhập.

## Kiểm tra

- 323 kiểm thử Django đạt; bổ sung kiểm tra quyền sở hữu, CSRF, snapshot/đáp án bí mật, phiên bản lưu, ghi trễ sau nộp, nộp lặp, ôn từ sai sau gỡ học liệu/đổi mục tiêu, XP và chuỗi học khi chỉ ôn lại.
- 53 kiểm thử JavaScript đạt; kiểm tra lưu khi có chỉnh sửa mới trong lúc request trước đang chạy, phản hồi không thay đổi phiên bản, xung đột, timeout, chờ lưu trước nộp và khôi phục câu chưa trả lời.
- Kiểm tra trực quan HTML render bằng Django với tài khoản/database fixture tách biệt: nhãn đã lưu, mở ở câu tiếp theo, nút ôn sai và trang tiến độ. Các endpoint lưu/nộp/ôn được kiểm tra qua Django test client; kiểm tra JavaScript dùng các phản hồi mạng mô phỏng có kiểm soát.
- Kiểm tra schema/migration không phát hiện thay đổi còn thiếu. Chưa kiểm thử cạnh tranh đồng thời trên PostgreSQL production, Edge hoặc điện thoại thật; chưa triển khai bản mới lên Cloudflare.

Quiz đang dở vẫn hết hạn sau 24 giờ kể từ lúc bắt đầu. Nhãn CEFR và học liệu hiện có giữ trạng thái tham khảo, chưa được giáo viên duyệt toàn bộ.
