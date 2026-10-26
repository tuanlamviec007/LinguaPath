# Sổ từ cá nhân

Cập nhật: quiz từ sổ cũng hỗ trợ [Gõ từ tiếng Anh](TYPED_RECALL.md), vẫn cần ít nhất 5 từ phù hợp. Cách gõ từ không cần bốn phương án nhiễu và loại các gợi ý chứa nguyên đáp án; mô tả phương án lựa chọn bên dưới áp dụng Chọn nghĩa.

## Cách sử dụng

1. Ở flashcard hoặc kết quả quiz, nhấn **Lưu từ**. Hai mặt thẻ đồng bộ trạng thái; nhấn **Đã lưu** để bỏ từ.
2. Mở **Sổ từ cá nhân** trong điều hướng hoặc lối vào trên dashboard. Sổ có nghĩa, ví dụ song ngữ, ngày lưu và liên kết ôn flashcard.
3. Tìm theo từ/nghĩa/ví dụ hoặc lọc trình độ, chủ đề. Mỗi trang tối đa 20 từ, sắp theo lần lưu gần nhất.
4. Chọn **Quiz từ sổ cá nhân**, rồi chọn trình độ, chủ đề và 5/10/15 câu. Khu quiz có ba nguồn: toàn bộ thư viện, sổ cá nhân và [từ cần ôn](WEAK_WORDS.md).

Sổ gắn với tài khoản, chỉ hiển thị thẻ đang xuất bản/rà soát tối thiểu và thuộc mục tiêu TOEIC/IELTS hiện chọn. Đổi mục tiêu hoặc gỡ xuất bản sẽ ẩn các thẻ không còn phù hợp, không tự xóa dấu lưu; chúng xuất hiện lại nếu trở nên khả dụng. Nội dung thẻ trong sổ theo phiên bản hiện tại của nguồn học liệu.

Quiz cá nhân chỉ chọn câu hỏi từ sổ của chính người học. Phương án nhiễu lấy từ nghĩa trong thư viện khả dụng để tạo bốn lựa chọn khác nhau. Cần ít nhất 5 từ phù hợp; nếu không đủ, hệ thống thông báo thay vì tự lấy thêm câu hỏi ngoài sổ. Đây vẫn là quiz mới, áp dụng giới hạn XP ngày hiện có. Lượt ôn sai giữ cơ chế không cộng thêm XP.

Quiz đã bắt đầu giữ snapshot. Bỏ dấu lưu sau đó không đổi câu hỏi hoặc đáp án của lượt đang làm; gỡ xuất bản nguồn vẫn tuân theo kiểm tra khả dụng hiện có. Kết quả cũ không hiển thị nút lưu nếu thẻ nguồn đã đổi sang từ/nghĩa khác, tránh lưu nhầm nội dung hiện tại vào sổ.

## Lưu từ và hoạt động học

Lưu/bỏ từ không chấm điểm, không cộng XP và không tự đánh giá flashcard là “đã nhớ”. Bạn vẫn cần làm quiz hoặc ôn flashcard để ghi nhận hoạt động tương ứng. Lệnh lưu/bỏ là thao tác rõ ràng, chạy lại không đảo trạng thái ngoài ý muốn hoặc tạo trùng dữ liệu.

Khi có JavaScript, nút lưu cập nhật tại chỗ và chặn yêu cầu trùng cho cùng thẻ; lỗi mạng giữ trạng thái hiển thị trước đó và cho phép thử lại. Timeout là 12 giây, không tự gọi lại liên tục. Không bật JavaScript vẫn lưu/bỏ bằng biểu mẫu và chuyển về trang đang học; sổ dùng biểu mẫu bỏ từ thông thường để làm mới danh sách/phân trang chính xác.

## Cập nhật

Giữ database và cấu hình hiện có, chép mã nguồn mới rồi chạy:

```bash
python manage.py migrate
python manage.py runserver
```

Migration `0015_saved_words` tạo bảng dấu lưu với ràng buộc duy nhất tài khoản/thẻ và thêm nguồn từ cho phiên quiz (các lượt cũ mặc định thư viện chung). Các bài luyện, lịch ôn và kết quả đã có được giữ nguyên. Không cần chạy lại seed từ vựng.

## Kiểm tra và giới hạn

- 333 kiểm thử Django đạt, gồm lưu/bỏ lặp, phân quyền/CSRF, nguồn bị ẩn hoặc khác mục tiêu, tìm/lọc/phân trang, redirect an toàn, quiz từ sổ, bảo toàn snapshot sau bỏ từ và thẻ nguồn đã đổi nội dung.
- 58 kiểm thử JavaScript đạt, gồm đồng bộ hai mặt thẻ, chặn yêu cầu đồng thời, timeout, phản hồi lỗi và thử lại thao tác rõ ràng sau mất phản hồi.
- Django check và kiểm tra migration không phát hiện thay đổi còn thiếu. Xem trực quan HTML render từ Django với database/tài khoản fixture tách biệt ở desktop và iframe rộng 360/390 px; đã kiểm tra lật thẻ cùng nút lưu.
- Các endpoint lưu/bỏ/quiz được kiểm tra bằng Django test client, phản hồi mạng JavaScript được mô phỏng có kiểm soát. Chưa kiểm thử trên Edge/điện thoại vật lý hoặc production. Không triển khai Cloudflare trong đợt này.

Nhãn CEFR và học liệu hiện có vẫn là tham khảo; chức năng lưu từ không thay thế việc giáo viên kiểm định nội dung.
