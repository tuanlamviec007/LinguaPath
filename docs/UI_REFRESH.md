# Làm mới giao diện LinguaPath — 20/10/2026

## Thay đổi chính

| Khu vực | Giao diện mới |
|---|---|
| Trang khách | Bố cục giới thiệu hai cột, thông điệp học theo nhịp cá nhân, thẻ từ mẫu thực sự lật được, ba bước học và các đường dẫn đăng ký/đăng nhập rõ ràng. Không dùng số người học, đánh giá hay thành tích giả. |
| Khu học tập | Thanh điều hướng bên trái trên desktop, nhóm cài đặt riêng, đường dẫn Sổ lỗi luôn có trong menu. Trên màn hình hẹp chuyển sang menu `details` mở bằng chuột/bàn phím, đóng bằng Escape. |
| Tổng quan | Hành động tiếp theo ở đầu trang, giữ ưu tiên tiếp tục bài đang dở rồi nhiệm vụ chưa xong. Các thẻ chỉ số và nhiệm vụ nằm trước lịch hoạt động/CEFR/lịch sử. Các dữ liệu vẫn lấy từ context thật của tài khoản. |
| Đăng nhập/đăng ký | Bố cục hai cột, vùng form riêng, nhãn tiếng Việt, lỗi trường nhập rõ hơn và hướng dẫn mật khẩu giữ nguyên từ Django. Trên điện thoại chuyển một cột. |
| Trang học hiện có | Bộ màu và kiểu chữ chung; tăng cỡ nhãn, dữ liệu hoạt động và vùng bấm. Nút đánh giá flashcard có thể xuống dòng; nút nhiệm vụ giữ chữ thay vì bị ẩn ở điện thoại. |
| Quản trị | Header/sidebar, bảng, bộ lọc, form và trạng thái chỉ đọc theo cùng bảng màu. Bảng inline nhiều cột có vùng cuộn riêng trên màn hình hẹp. Quyền truy cập và các block Django admin được giữ nguyên. |

## Quy ước thiết kế

Nền ivory, khung giấy sáng, chữ xanh đậm và nút teal; lime là điểm nhấn. Font chính Inter, dự phòng Segoe UI/Arial. Nội dung chính khoảng 15–16px; metadata quan trọng được tăng lên 12–14px. Khung nội dung có chiều rộng giới hạn, khoảng cách nhất quán và focus nhìn thấy khi dùng bàn phím. Có hỗ trợ giảm chuyển động khi người dùng bật tùy chọn hệ thống.

`static/css/design-system.css` chứa token `--lp-*` và khung dùng chung, tải sau CSS cũ để giữ các tương tác đã có. `landing.css`, `dashboard.css`, `auth.css` tách bố cục từng khu vực. CSS của flashcard, luyện bài, tutor và Sổ lỗi vẫn giữ các hook chức năng hiện có. Các selector ưu tiên đã được rà soát để không ép màu liên kết trên khung tối hoặc làm cỡ chữ nhiệm vụ thành 0.

Thẻ ở trang chủ là ví dụ minh họa tự biên soạn, không phải kết quả học của người dùng. Giữ thông báo phạm vi TOEIC nền tảng; chưa quảng bá IELTS/Writing/Speaking như chức năng đã có. Trạng thái học liệu AI rà soát sơ bộ vẫn được phân biệt với phê duyệt giáo viên; lần làm giao diện này không thay chính sách xuất bản.

## Sửa lỗi nhỏ trong thao tác quản trị

Bấm Save một flashcard không thay đổi trường nào giờ giữ nguyên trạng thái duyệt/xuất bản của bộ từ. Nếu thực sự sửa thẻ hoặc chuyển thẻ sang bộ khác, các bộ liên quan vẫn chuyển nháp và yêu cầu rà soát lại. Đã bổ sung regression test cho thao tác lưu không chỉnh sửa.

## Kiểm tra và giới hạn

Bản giao diện được kiểm tra qua Django HTTP/template, Django system check, kiểm tra migration và các test JavaScript mô phỏng tương tác menu/lưu nháp/nộp bài. Các chức năng học tập và dữ liệu không được đổi nhằm làm đẹp số liệu.

Yêu cầu mở bản chạy cục bộ bằng trình duyệt kiểm tra bị timeout, nên **chưa xác nhận trực quan trên trình duyệt thật** và chưa có ảnh chụp kiểm chứng. Không coi source audit hoặc test mô phỏng là kiểm tra bố cục thực tế. Cần xem lại desktop/mobile, zoom, trạng thái lật thẻ, menu, audio và bảng inline khi chạy trên máy của người dùng.

Agent frontend phụ trách khung dùng chung/menu; agent backend phụ trách giao diện admin; agent thiết kế rà soát source; root triển khai trang chủ, tổng quan, đăng nhập/đăng ký và tích hợp. Không phát sinh migration hay yêu cầu cấu hình mới. Chạy dự án theo README, sau đó tải lại trang để nhận CSS mới; bản triển khai có static collection cần chạy lại `collectstatic`.

Kết quả kiểm tra bản bàn giao: **194 test Python, 14 test JavaScript đạt**; các trang khách/trang đăng nhập/trang đăng ký trả HTTP 200, template biên dịch được, Django system check sạch và không có migration mới. Các kết quả này xác nhận hồi quy chức năng, không thay thế kiểm tra trực quan.
