# Không gian từ vựng và luyện nghe — 20/10/2026

## Thay đổi dành cho người học

- Từ vựng có tiêu đề, số thẻ theo bộ lọc, tab thẻ đến hạn/toàn bộ từ, tìm kiếm, CEFR và chủ đề. Mặt trước/sau dùng font Inter, nút lật rõ ràng, vùng đọc cuộn cho nội dung dài; thẻ có chế độ giảm chuyển động. Cơ chế đánh giá và lịch SRS giữ nguyên.
- Bài luyện có mục chuyển nhanh đến câu và thanh lưu nháp nằm dưới header. Chuyển vị trí/phát lại audio không xóa lựa chọn.
- Player giữ điều khiển audio gốc của trình duyệt, thêm tua lại 10 giây, phát từ đầu, tốc độ 0,75×/1×/1,25×. Không tự phát âm thanh khi mở trang.
- Giọng đọc thiết bị là phương án dự phòng cho nội dung có script, có tốc độ và nút dừng. Chỉ một nguồn phát tại một thời điểm; rời trang thì dừng. Thay tốc độ giọng đọc có hiệu lực từ lần phát tiếp theo.
- Khi file tải lỗi, kể cả lỗi có trước khi JavaScript chạy, thông báo và phương án hỗ trợ vẫn xuất hiện. Phát lại bị trình duyệt từ chối sẽ có hướng dẫn dùng thanh audio. Khi file phục hồi, nút điều khiển được bật lại.
- Trang kết quả hiển thị số đúng/tổng câu, điều hướng Sổ lỗi/tiến độ, nghe lại audio cạnh lời giải. Các câu dùng chung một đoạn nghe được nhóm theo thứ tự câu, không phụ thuộc thứ tự đáp án lưu trong database.

## Chính sách luyện tập

Đây là bài luyện có hỗ trợ: người học có thể phát nhiều lần, thay tốc độ và mở bản chép lời trước khi nộp. Bản chép lời có thể giúp chọn đáp án, nên tỷ lệ đúng là số liệu luyện tập trên web, không phải điểm thi chuẩn hóa hoặc kết quả kiểm tra không hỗ trợ. Việc dùng hỗ trợ chưa được ghi nhận riêng trên từng lượt.

Script TTS và transcript có trong HTML có chủ đích; không quảng bá đây là chế độ thi bảo mật. Lời giải, nhãn đáp án đúng và phân tích phương án vẫn chỉ hiển thị sau khi nộp. Trợ lý vẫn yêu cầu lịch sử câu đã nộp của chính tài khoản để truy xuất lời giải; người học đã nộp trước đó có thể xem lại lời giải khi làm lại.

Không thêm số lượng từ/bài mới trong đợt này. Nội dung, quyền sử dụng, nhãn CEFR tham khảo và trạng thái AI rà soát/giáo viên duyệt giữ như trước. Các agent đóng vai trò giáo viên/audit là AI, không phải kiểm định từ giáo viên thật.

## Kiểm tra cần phân biệt

Kiểm tra HTTP xác nhận quyền sở hữu lượt học, không hiện lời giải trước nộp, đường audio/TTS, kết quả và nhóm đoạn nghe. Kiểm tra JavaScript mô phỏng hành vi tua/phát lại/tốc độ/lỗi/focus và dừng nguồn phát; không thay thế kiểm tra trình duyệt thật. File MP3 được kiểm tra giải mã kỹ thuật, không phải đánh giá chất lượng giọng nói bởi người nghe.

Chưa xác nhận trực quan desktop/mobile, quyền phát âm thanh hoặc danh sách giọng trên Edge/Android/iOS thực tế. Cần mở các trang từ vựng/bài nghe/kết quả ở 320px, 375px và desktop, thử bàn phím và giảm chuyển động. Không có migration mới. Nếu triển khai với DEBUG=false, chạy lại collectstatic và build image để nhận CSS/JS mới. Bản này chưa được đưa lên Cloudflare.

Kết quả bàn giao: **209 Django tests + 28 Node tests pass**, không có migration mới. Đã giải mã 10 MP3 thành công (tổng khoảng 443 giây) bằng ffmpeg; điều này không xác nhận quyền autoplay hoặc chất lượng giọng trên trình duyệt người dùng.
