# Đăng nhập Google và Facebook

Mã tích hợp đã có; chưa thể gọi là đăng nhập mạng xã hội hoạt động khi chưa cấu hình
ứng dụng OAuth thật. Không gửi Client Secret vào chat hoặc commit.

## Cấu hình trong Render Environment

- SOCIAL_AUTH_ENABLED=true
- GOOGLE_CLIENT_ID và GOOGLE_CLIENT_SECRET: OAuth client loại Web application của Google.
- FACEBOOK_CLIENT_ID và FACEBOOK_CLIENT_SECRET: App ID và App Secret của Meta Facebook Login.

Chỉ provider có đủ hai giá trị mới có nút hoạt động. Nếu chưa cấu hình, nút hiển thị
“Chưa kích hoạt”; tài khoản/mật khẩu hiện tại tiếp tục dùng được. Build có migrate;
khi bật flag, các bảng allauth được tạo bởi migration của thư viện. Không seed lại dữ liệu.

## Callback chính xác trên ứng dụng thật

Google: https://linguapath-app.onrender.com/social/google/login/callback/
Facebook: https://linguapath-app.onrender.com/social/facebook/login/callback/

Google: tạo OAuth consent screen, khai báo tên ứng dụng/email hỗ trợ; khai báo callback
trên client Web. Khi còn Testing, thêm tài khoản test trong Google Console. Thực hiện
các yêu cầu xác minh/publishing do Google Console hiển thị trước mở rộng cho công chúng.

Meta: cấu hình Facebook Login cho website, khai báo callback/domain đúng. Bổ sung URL
chính sách riêng tư, thông tin/yêu cầu xóa dữ liệu theo Meta App Dashboard; hoàn tất
các điều kiện review/publishing của Meta cho người dùng ngoài vai trò developer/tester.
Trang quản lý dữ liệu hiện tại yêu cầu đăng nhập; không coi đó tự động là URL chính
sách riêng tư công khai đã đáp ứng Meta. Không tự bấm chấp nhận điều khoản hoặc tạo
ứng dụng nhà cung cấp thay chủ tài khoản.

## Hành vi

POST có CSRF để bắt đầu đăng nhập; OAuth state/callback do django-allauth xử lý.
Không tự ghép tài khoản dựa trên email, không lưu access token lâu dài. Tài khoản
mạng xã hội mới tạo LearnerProfile, rồi đi qua dashboard tới chọn nhịp học. Không
cấp quyền admin từ thông tin provider. Đăng nhập tên/mật khẩu giữ backend hiện tại.
Không mở thêm bộ endpoint mật khẩu allauth để né quota đăng nhập hiện có.

Cần nghiệm thu với tài khoản Google/Meta thật sau cấu hình, gồm từ chối consent,
callback state sai, trùng email, tài khoản bị vô hiệu hóa và Facebook không trả email.
Chưa nghiệm thu đăng nhập provider thật khi không có credentials/app được duyệt.

Nguồn: https://docs.allauth.org/en/latest/installation/quickstart.html
https://docs.allauth.org/en/latest/socialaccount/providers/google.html
https://docs.allauth.org/en/latest/socialaccount/providers/facebook.html
