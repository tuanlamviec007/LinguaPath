# Từ cần ôn — 23/10/2026

Cập nhật: có thể chọn [Gõ từ tiếng Anh](TYPED_RECALL.md) khi luyện nguồn từ cần ôn. Cách luyện này không cần phương án nhiễu; chỉ chọn từ có gợi ý phù hợp, vẫn từ một câu và không cộng XP. Câu trả lời gần nhất ở cả hai cách luyện đều cập nhật hàng ôn. Mô tả bốn lựa chọn bên dưới áp dụng cách luyện Chọn nghĩa.

## Sử dụng

Mở **Từ cần ôn** trong điều hướng cá nhân, dashboard hoặc trang tiến độ. Mỗi mục có từ, nghĩa, ví dụ song ngữ nếu học liệu có, số lần từng trả lời sai, thời điểm và liên kết tới lượt quiz gần nhất. Có tìm theo từ/nghĩa/ví dụ tiếng Anh, lọc cấp độ và chủ đề, phân trang 20 mục, lưu từ vào sổ cá nhân hoặc chuyển sang flashcard.

Danh sách dựa trên lần trả lời hợp lệ mới nhất đã nộp của từng thẻ từ, gồm cả quiz thường, quiz từ sổ cá nhân và các lượt ôn. Trả lời đúng đưa từ ra khỏi hàng ôn; trả lời sai ở lượt sau đưa từ trở lại. Đây là hàng đợi luyện lại, không phải chứng nhận đã ghi nhớ lâu dài. Số lần từng sai tính toàn bộ lịch sử phù hợp của thẻ, kể cả trước lần trả lời đúng. Không cần hoàn thành quiz mới để nhập lịch sử cũ.

Chọn **Luyện từ cần ôn** để mở nguồn thứ ba trong khu quiz. Chọn tối đa 5/10/15 câu; nếu chỉ có 1–4 từ phù hợp, vẫn tạo lượt ngắn. Câu hỏi chỉ lấy từ danh sách cần ôn của chính người học; không lấy thêm câu hỏi từ thư viện để đủ số câu. Phương án nhiễu dùng thư viện khả dụng để có bốn nghĩa phân biệt. Nếu không có từ phù hợp hoặc không đủ phương án nhiễu, hệ thống giải thích và không tạo quiz.

Lượt này không cộng XP, không dùng suất thưởng quiz mới đầu ngày và không thay đổi lịch ôn flashcard. Hoàn thành vẫn ghi nhận hoạt động học, chuỗi ngày học và nhiệm vụ hoàn thành quiz. Thống kê tiến độ ghi nhận là lượt ôn, tách khỏi tỷ lệ đúng quiz mới. Tính năng lưu nháp, tiếp tục, hết hạn và nộp lặp vẫn áp dụng.

## Dữ liệu và quyền truy cập

- Chỉ đọc lịch sử của tài khoản hiện tại, đúng mục tiêu thi, đã nộp và không ở tương lai. Bản nháp, lượt dừng hoặc thiếu thời điểm nộp không tác động danh sách.
- Chỉ hiển thị thẻ thuộc nội dung từ vựng còn được xuất bản và có trạng thái rà soát cho phép người học xem. Đổi mục tiêu hoặc gỡ xuất bản ẩn các mục không còn phù hợp.
- Bằng chứng gắn với mã thẻ, từ và nghĩa tiếng Việt của snapshot. Nếu giáo viên đổi từ/nghĩa, kết quả cũ không gán lỗi cho nội dung mới; sửa hoa/thường, khoảng trắng và dạng Unicode tương đương vẫn giữ cùng danh tính. Xóa thẻ cũng loại bằng chứng khỏi hàng ôn.
- Lượt ôn cũ vẫn có thể giữ snapshot lịch sử như thiết kế trước đó. Trả lời đúng một nghĩa cũ không xóa lỗi của nghĩa đã sửa hiện tại.
- Khi nhiều lượt có cùng thời điểm nộp, mã lượt lớn hơn được xem là mới hơn. Danh sách sắp lần sai gần nhất trước, với thứ tự ổn định khi bằng thời điểm.
- Danh sách là dữ liệu tính từ lịch sử, không tạo một bảng lỗi hay đánh dấu thành thạo riêng. Giao diện quiz trước khi nộp chỉ nhận các trường được phép, không có khóa đáp án hoặc ví dụ dịch.

## Cập nhật và xác minh

Giữ database và cấu hình hiện có, chép mã mới rồi chạy:

```bash
python manage.py migrate
python manage.py runserver
```

Migration `0016_quiz_weak_words` bổ sung lựa chọn nguồn `weak`; không seed lại, không chuyển đổi hoặc xóa lịch sử quiz cũ.

Toàn bộ **348 kiểm thử Django và 58 kiểm thử JavaScript đạt**; trong đó có 15 kiểm thử hành trình mới cho tính năng này. Django check và kiểm tra migration không phát hiện vấn đề.

Kiểm tra backend bằng Django test client bao gồm lịch sử đúng/sai, dữ liệu nhiều người học, mục tiêu thi, sửa/gỡ học liệu, tìm/lọc/phân trang, quiz một từ, không cộng XP và giữ thưởng quiz mới, không lộ khóa đáp án, nguồn rỗng và tham số bị sửa. Giao diện được xem bằng HTML render từ Django với tài khoản/database fixture riêng ở desktop và iframe 360/390 px. Hành trình fixture thực sự gọi endpoint quiz: 6 từ cần ôn → 2 → 0; các lượt ôn nhận 0 XP. Kiểm thử mạng JavaScript dùng mô phỏng có kiểm soát; trình duyệt QA xem các trang render tĩnh, không chạy máy chủ Django trực tiếp.

Số truy vấn tổng hợp không tăng theo số mục, nhưng vẫn đọc toàn bộ lịch sử quiz phù hợp của người học bằng iterator. Chi phí tăng theo lượng lịch sử; khi có dữ liệu lớn cần đo tải và cân nhắc bảng tổng hợp. Chưa deploy Cloudflare hoặc kiểm thử trên thiết bị vật lý trong đợt này.
