# Giao diện sáng — 23/10/2026

Theme chung trong `static/css/bright-theme.css`, được nạp qua template nền của khu học. Nền trắng hơi xanh giúp tách thẻ trắng, thanh điều hướng trắng, viền nhẹ và bóng mềm. Màu nhấn emerald giữ nét nhận diện; các nhóm chức năng dùng mint, lavender, đào và vàng nhạt.

Dashboard và đầu trang từ vựng chuyển từ mảng xanh tối sang gradient mint sáng. Flashcard cũng có mặt trước sáng, chữ xanh đậm, nút nghe/lưu/lật đồng bộ màu; mặt sau giữ trắng. Cập nhật tương ứng nhãn trình độ, thông tin lộ trình, footer, focus và hover. Quiz, sổ từ cá nhân, từ cần ôn, thư viện, trang chủ và đăng nhập dùng cùng palette. Giữ bố cục responsive và hỗ trợ giảm chuyển động có sẵn.

## Xác minh

- Django check và kiểm tra migration sạch; render thành công dashboard, flashcard, sổ từ, quiz, thư viện bài luyện, trợ lý, tiến độ, trang chủ và đăng nhập bằng tài khoản/database fixture riêng.
- Xem trực quan desktop, dashboard 390 px, flashcard 360 px và quiz 390 px; không có tràn ngang ở ba khung này. Đã thử lật thẻ, quay về mặt trước và xem các nút đánh giá.
- Các cặp màu mới được kiểm tra có tỷ lệ tương phản: chữ trắng/nút emerald 4,95:1; nội dung hero 5,28:1; từ trên flashcard 7,64:1; footer 5,03:1. Đây là các cặp màu cụ thể, không phải xác nhận WCAG cho toàn bộ website.
- Các kiểm thử JavaScript liên quan điều hướng, phát âm và lưu từ đạt. Không thêm backend, sửa dữ liệu học hoặc gọi dịch vụ AI.

Trình duyệt QA xem HTML render tĩnh từ Django; không phải triển khai production hoặc kiểm thử trên điện thoại vật lý. Không tạo migration mới. Với máy chủ dùng WhiteNoise, chạy lại `python manage.py collectstatic --noinput` theo quy trình triển khai hiện có; trên môi trường phát triển chỉ cần cập nhật mã và tải lại trang (Ctrl+F5 nếu còn cache).
