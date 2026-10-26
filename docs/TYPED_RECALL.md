# Quiz gõ từ tiếng Anh — 23/10/2026

## Cách luyện

Trong khu **Quiz thử thách**, chọn **Gõ từ tiếng Anh** ở phần cách luyện, nguồn từ và bộ lọc mong muốn, rồi bắt đầu. Mỗi câu hiện nghĩa tiếng Việt, loại từ, mức CEFR tham khảo, chữ đầu và số từ của đáp án gốc. Với từ dưới ba ký tự, không hiện chữ đầu để tránh gợi ý toàn bộ đáp án.

Gõ từ hoặc cụm từ đã học. Enter chuyển đến câu tiếp; ở câu cuối, Enter yêu cầu nộp sau khi kiểm tra đủ câu trả lời. Khi bàn phím còn ghép chữ, Enter giữ chức năng xác nhận chữ, không chuyển câu hoặc nộp quiz. Có thể dùng các nút chuyển câu thay cho bàn phím.

Câu trả lời tự lưu sau khi ngừng nhập, có nút **Lưu ngay** và xử lý xung đột nhiều tab như quiz chọn nghĩa. Xóa trắng ô nhập xóa câu đó khỏi bản nháp, không giữ đáp án cũ. Mở lại lượt đang làm khôi phục nguyên văn và mở ở câu chưa trả lời đầu tiên. Nếu tắt JavaScript, biểu mẫu vẫn hiện tất cả câu và nộp bình thường; không có tự lưu/chuyển từng câu.

Sau khi nộp, kết quả hiện từ gốc, nghĩa, ví dụ song ngữ và nội dung đã nhập sai. Có thể lưu từ, mở flashcard hoặc tạo lượt ôn chỉ những từ sai. Lượt ôn giữ chế độ gõ từ và không cộng thêm XP. Hàng **Từ cần ôn** dùng câu trả lời gần nhất qua cả hai chế độ; đúng ở một lượt sau có thể đưa từ khỏi hàng ôn, không đồng nghĩa với ghi nhớ lâu dài.

## Quy tắc chấm

Đây là bài nhớ lại từ gốc, không phải dịch tự do. Đáp án phải trùng từ/cụm từ trong snapshot sau khi chuẩn hóa Unicode NFKC, hoa/thường, khoảng trắng thừa và dấu nháy cong thành dấu nháy thẳng. Ví dụ `  MEET   A DEADLINE ` được chấp nhận cho `meet a deadline`; `manager’s agenda` tương đương `manager's agenda`.

Không tự chấp nhận từ đồng nghĩa, dạng chia động từ, số nhiều hoặc lỗi chính tả gần giống. Không xóa dấu gạch nối/dấu câu tùy ý; `carry on` và `carry-on` khác nhau. Định nghĩa có thể gợi nhiều từ gần nghĩa; gợi ý chữ đầu và yêu cầu từ đã học giúp định hướng nhưng chưa thay thế biên tập/giáo viên kiểm tra học liệu. Chưa dùng AI để chấm câu trả lời.

Mỗi câu tối đa 240 ký tự nhập. Lưu nháp không trả kết quả đúng/sai. Chấm điểm dựa trên chế độ và đáp án đã lưu ở máy chủ, bỏ qua điểm/chế độ người dùng tự gửi kèm khi nộp. Nộp lặp không tạo thêm điểm thưởng.

## Nguồn câu hỏi và hoạt động học

- Có cả ba nguồn: thư viện khả dụng, sổ của chính người học và hàng từ cần ôn. Nguồn cá nhân không được bù thêm câu hỏi ngoài tập đã chọn.
- Quiz mới cần ít nhất 5 từ phù hợp; nguồn từ cần ôn có thể bắt đầu từ một từ. Chọn 5/10/15 là số câu tối đa theo bộ lọc.
- Gõ từ không cần bốn phương án nhiễu. Các thẻ có đáp án tiếng Anh xuất hiện nguyên như một từ/cụm độc lập trong nghĩa tiếng Việt bị loại khỏi chế độ gõ từ, ví dụ `email → gửi email`. Chế độ chọn nghĩa vẫn giữ chúng. Lượt gõ đang dở có snapshot không phù hợp cũng dừng; tạo retry bỏ qua các câu đó.
- Trước khi nộp, trang chỉ nhận nghĩa, loại từ, mức, gợi ý chữ đầu/số từ và bản nháp của chính người dùng; không gửi từ đích đầy đủ, ví dụ tiếng Anh, ví dụ dịch hoặc danh sách phương án. Bản nháp do người dùng tự nhập có thể chứa từ đúng và được giữ nguyên.
- Quiz mới dùng chung suất thưởng quiz đầu ngày của tài khoản: 20 + 2 XP/câu đúng, tối đa 50 XP. Đổi cách luyện không mở thêm suất thưởng. Lượt ôn không cộng XP, vẫn được ghi nhận hoạt động/ngày học. Gõ từ không tự thay đổi lịch SRS flashcard.
- Lịch sử có bộ lọc **Cách luyện**; các thẻ kết quả gần đây và tiến độ có nhãn phân biệt. Tỷ lệ đúng quiz mới vẫn có thể tổng hợp hai cách luyện; nên lọc cùng cách luyện khi so sánh kết quả. Không dùng tỷ lệ này để quy đổi TOEIC/CEFR.

## Cập nhật

Giữ database và cấu hình hiện có, chép mã mới rồi chạy:

```bash
python manage.py migrate
python manage.py runserver
```

Migration `0017_vocabularyquizsession_mode` thêm cột cách luyện; các lượt cũ mặc định **Chọn nghĩa**. Không seed lại hoặc sửa/xóa kết quả đã nộp. Máy chủ dùng WhiteNoise cần thu thập lại static theo quy trình hiện có.

## Xác minh và giới hạn

**380 kiểm thử Django và 67 kiểm thử JavaScript đều đạt**, gồm 20 kiểm thử backend mới và 9 kiểm thử JavaScript mới. Django check và kiểm tra migration không phát hiện vấn đề.

Các kiểm thử mới bao gồm chấm chuẩn hóa và đối sánh nghiêm ngặt, không lộ từ đích/ví dụ trước nộp, nháp rỗng/quá dài/trùng tham số, CAS và quyền sở hữu/CSRF, snapshot bất biến, retry giữ mode/không XP, hàng từ cần ôn qua hai chế độ, lọc lịch sử, prompt chứa đáp án và JSON cũ sai cấu trúc. JavaScript có kiểm thử nhập/xóa, phản hồi đến muộn, xung đột, khôi phục, Enter và IME.

QA dùng tài khoản/database fixture tách biệt: lưu 2/5 câu rồi khôi phục; nộp 3/5 với hoa thường/khoảng trắng nhận 26 XP; ôn lại 2/2 nhận 0 XP và hàng từ cần ôn giảm 2 → 0. Đã xem HTML render ở desktop và iframe 360/390 px, kiểm tra không tràn ngang và Enter chuyển câu đã khôi phục. Endpoint được kiểm tra bằng Django test client; mạng JavaScript dùng mô phỏng có kiểm soát, trình duyệt QA xem các trang render tĩnh. Chưa kiểm thử trên điện thoại vật lý hoặc deploy Cloudflare.
## Cập nhật M2 — 24/10/2026

Gõ từ hiện tạm loại cả các prompt trùng nghĩa, POS và hint nhưng có term khác nhau trên toàn kho đang xuất bản của cùng kỳ thi. Kiểm tra áp dụng cho nguồn all/saved/weak, retry và phiên đang làm; không sửa điểm lịch sử. Trên kho hiện tại có 4 nhóm/8 thẻ bị loại vì cue mơ hồ, ngoài 19 mục lộ đáp án. Bộ lọc tự động không thay thế duyệt chuyên môn hoặc tự chấp nhận từ đồng nghĩa. Xem [M2](STABILITY_M2.md).

