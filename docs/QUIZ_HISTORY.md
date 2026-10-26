# Lịch sử quiz — 23/10/2026

Cập nhật: lịch sử có thêm bộ lọc **Cách luyện** để tách **Chọn nghĩa** và [Gõ từ tiếng Anh](TYPED_RECALL.md). Nếu không lọc, thống kê quiz mới tổng hợp cả hai cách luyện; nên so sánh trong cùng cách luyện.

## Sử dụng

Trong **Quiz thử thách**, chọn **Xem toàn bộ lịch sử** ở phần kết quả gần đây. Trang Tiến độ và kết quả từng lượt cũng có lối vào. Mỗi dòng lịch sử mở lại kết quả và lời giải của chính lượt đó; hiển thị thời gian nộp, nguồn từ, quiz mới/luyện lại, số câu đúng và XP đã nhận.

Mặc định hiển thị **30 ngày gần nhất**. Có thể chọn 7 ngày hoặc toàn bộ thời gian, kết hợp nguồn thư viện/sổ cá nhân/từ cần ôn, quiz mới/luyện lại, mức và chủ đề đã chọn. Nguồn từ và loại lượt làm độc lập: ví dụ có thể tìm lượt ôn từ một quiz trước đó vốn lấy từ sổ cá nhân.

Mức và chủ đề là thông tin đã chọn khi tạo quiz, không phải tìm trong từng câu hỏi. Quiz “Mọi cấp độ” có thể chứa từ ở nhiều mức; chúng không xuất hiện khi lọc riêng B1 chỉ vì có một câu B1 bên trong. Lượt không chọn một chủ đề cụ thể có tiêu đề chung.

Phân trang 20 lượt, mới nộp trước; nếu cùng thời điểm thì mã lượt lớn hơn đứng trước. Chuyển trang giữ các bộ lọc. Tham số không hợp lệ trở về giá trị mặc định an toàn, trang rỗng hướng dẫn đổi bộ lọc hoặc làm quiz đầu tiên.

## Thống kê và dữ liệu

Ba thẻ thống kê áp dụng toàn bộ bộ lọc hiện tại: số quiz mới, số lượt luyện lại và tỷ lệ đúng của quiz mới. Tỷ lệ là **tổng câu đúng / tổng câu hỏi** của các quiz mới, không lấy trung bình phần trăm từng lượt. Ví dụ 5/5 và 3/15 cho 8/20 = 40%. Nếu chỉ có lượt ôn hoặc chưa có câu hỏi ở quiz mới, tỷ lệ hiển thị “—”. Đây là kết quả làm bài, không phải điểm TOEIC, CEFR hay bằng chứng ghi nhớ lâu dài.

Chỉ hiển thị lịch sử của tài khoản hiện tại, thuộc mục tiêu thi hiện chọn, đã nộp và không nằm ở tương lai. Bản nháp, lượt dừng hoặc thiếu thời điểm nộp không vào thống kê. Bộ lọc chủ đề cũng theo cùng phạm vi này. Đổi mục tiêu chuyển danh sách lịch sử tương ứng, không sửa kết quả đã lưu.

Mốc 7/30 ngày tính theo ngày địa phương của ứng dụng (`Asia/Ho_Chi_Minh`), gồm hôm nay và 6/29 ngày trước, từ đầu ngày; không phải cửa sổ chính xác 168/720 giờ. Lượt ôn vẫn được nhận diện bằng cờ bền vững sau khi lượt cha bị xóa. Học liệu gỡ xuất bản/xóa không làm mất snapshot kết quả đã nộp; nút lưu từ và tạo lượt ôn vẫn tuân theo khả dụng học liệu hiện có.

Trang lịch sử là GET yêu cầu đăng nhập và không cho cache lưu dữ liệu. Xem lịch sử không cộng XP, không nộp lại quiz và không đổi lịch SRS. Các hàng chỉ tải thông tin tổng quan, trì hoãn JSON snapshot/đáp án để giảm dữ liệu đọc. Danh sách gần đây ở khu quiz nay dùng cùng quy tắc mục tiêu thi, thời điểm nộp và thứ tự ổn định.

## Kiểm tra và cập nhật

**360 kiểm thử Django và 58 kiểm thử JavaScript đều đạt**, gồm 12 kiểm thử hành trình mới: quyền riêng tư/mục tiêu, nguồn/type, mốc ngày địa phương, tổng hợp có trọng số, phân trang giữ bộ lọc và escape, dữ liệu nguồn bị xóa, lượt ôn mất cha và không ghi thêm hoạt động. Django check và kiểm tra migration sạch.

QA dùng database/tài khoản fixture tách biệt: 25 lượt, trang đầu 20, trang sau 5, bộ lọc còn 4 và bộ lọc không có kết quả. Đã xem HTML render từ Django trên desktop và iframe 360/390 px, kiểm tra không tràn ngang và focus bàn phím ở dòng kết quả. Các bộ lọc/endpoint được xác minh bằng Django test client; trình duyệt xem trang render tĩnh, không phải máy chủ Django trực tiếp hay kiểm thử thiết bị vật lý.

Chép mã mới, giữ database và cấu hình hiện có, khởi động lại ứng dụng. Không có migration hoặc seed mới. Nếu triển khai bằng WhiteNoise, thu thập lại static theo quy trình hiện có. Chưa deploy Cloudflare trong đợt này.
