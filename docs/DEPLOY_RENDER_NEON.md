# Chạy đầy đủ LinguaPath trên Render Free + Neon Free

Cập nhật 26/10/2026. Website: https://linguapath-app.onrender.com/.
Xem [trạng thái nghiệm thu](DEPLOY_RENDER_NEON_STATUS.md). Đây là ứng dụng Django thật: giữ template, đăng ký/đăng nhập,
quiz chấm ở máy chủ, flashcard, kế hoạch học và lịch sử riêng. Không dùng thư mục
`preview/` hoặc `wrangler.jsonc` để chạy ứng dụng này.

## Cấu hình đã chuẩn bị

- `render.yaml`: một Web Service Python, **plan free**, Singapore; không tạo database
  Render, đĩa trả phí, worker hoặc cron. Auto-deploy tắt trong giai đoạn nghiệm thu.
- `.python-version`: Python 3.12, phù hợp requirements.lock có hash cho Linux x86_64.
- Build: `sh scripts/build-render.sh`; start: `sh scripts/start-production.sh`.
- `config.settings_render`: dùng hostname Render được cấp, HTTPS/cookie an toàn,
  hỗ trợ URL PostgreSQL trực tiếp hoặc pooled; tắt server-side cursors.
- `DJANGO_SECRET_SEED` được Render tạo một lần; dẫn xuất thành secret ổn định cho
  Django. Không sinh secret mới mỗi lần khởi động. Có thể dùng DJANGO_SECRET_KEY
  riêng đủ ít nhất 50 ký tự thay cho seed nếu đã có.
- Startup kiểm tra release rồi mới mở Gunicorn, không tự seed lại khi máy thức dậy.
- Blueprint đặt `/livez/` làm HTTP probe. Service tạo trực tiếp ngày 26/10 dùng
  probe TCP mặc định của Render; chưa áp dụng HTTP healthCheckPath. Gate startup
  đã kiểm tra database trước khi mở cổng.
  `/healthz/` dùng kiểm tra database khi nghiệm thu; không cấu hình poll liên tục
  chỉ để giữ dịch vụ thức, tránh tiêu hao hạn mức của các gói Free.

## Học liệu và dữ liệu người dùng

Gói nén `learning/data/production/initial_content.json.gz` là bản xuất **chỉ học liệu**
từ database hiện tại: 429 bộ, 3.056 thẻ, 5.138 câu, 20.552 lựa chọn.
`manifest.json` giữ hash SHA-256 và số lượng để kiểm tra nhập.

Giữ nguyên trạng thái nháp, tạm giữ và rà soát. Sau nhập có 428 bộ khả dụng,
3.055 thẻ khả dụng và 5.118 câu trong nguồn đã xuất bản; vẫn **0 bộ teacher_approved**.
Không tự mở lại thẻ 778 hoặc bộ 45. Không xuất tài khoản, phiên đăng nhập, tiến độ,
AI prompt, API key hoặc dữ liệu cá nhân trong fixture. Nguồn hiện tại chưa có tài khoản.

Lệnh `bootstrap_learning_content --if-empty` chỉ nhập khi cả bốn bảng học liệu
còn trống, kiểm tra hash, model allowlist, số lượng và transaction. Deploy lại
thấy dữ liệu có sẵn sẽ bỏ qua, không ghi đè sửa đổi của người biên tập.
Đây không phải công cụ chuyển lịch sử học từ máy khác; nếu đã có người học,
cần quy trình backup và chuyển dữ liệu riêng trước khi đổi database.

## Triển khai

1. Đưa các tệp đã kiểm tra lên nhánh triển khai của repository LinguaPath.
   Mã nguồn cần nằm ở gốc repo: có `manage.py` và `render.yaml`.
2. Tạo PostgreSQL 16 trên Neon Free, khu vực Singapore. Giữ xác thực Django hiện tại;
   không bật Neon Auth, Data API hoặc dịch vụ AI mới.
3. Lấy connection string **direct/unpooled**, có `sslmode=require` hoặc mạnh hơn,
   lưu vào `DATABASE_URL` của Render bằng cơ chế secret. Không gửi URL vào chat,
   commit, issue hoặc log. Một worker và `CONN_MAX_AGE=0` phù hợp khởi đầu nhỏ;
   nếu chuyển pooled URL, dùng URL direct riêng cho migration.
4. Render: chọn đúng workspace, liên kết GitHub và tạo Blueprint từ `render.yaml`.
   Điền DATABASE_URL trong bước tạo. Kiểm tra gói **Free** trước khi Apply.
5. Build cài dependency có hash, collectstatic, migrate, nhập học liệu nếu trống và
   check_release. Render Free không có pre-deploy job hoặc shell, nên các bước
   chuẩn bị database nằm trong build đã ghi rõ. Không dùng build production để
   chạy seed_demo/seed_starter_content với cờ bỏ qua lỗi.
6. Chỉ thông báo URL sau khi deploy đạt và đã kiểm tra trang thật.

Với service tạo trực tiếp thay vì Blueprint, dùng cùng build/start command và các
biến trong render.yaml; tạo secret đủ dài qua cơ chế bảo mật của dịch vụ.
Không có literal secret trong các tệp được giao.

## Nghiệm thu

- `/livez/`, `/healthz/` đạt và trang chủ/CSS không lỗi.
- Đăng ký tài khoản của bạn, đăng nhập, làm quiz, lưu từ, kiểm tra lịch sử đúng tài khoản.
- Kiểm tra POST thiếu CSRF bị từ chối và cookie Secure, HttpOnly theo cấu hình.
- Restart rồi đăng nhập/kiểm tra bài đã nộp còn trong Neon; không seed lại.
- Kiểm tra ingress/client IP trước khi bật tin tưởng header IP. Cấu hình mặc định
  giữ socket-peer fallback; hạn mức có thể gộp người dùng cùng proxy, cần nghiệm thu.
- Muốn tạo admin: từ máy có môi trường Python, cấu hình kết nối Neon bảo mật rồi
  chạy `python manage.py createsuperuser` tương tác. Không có mật khẩu admin mặc định
  hoặc endpoint HTTP để tạo admin/chạy migration.
- Trước lần nâng cấp có migration ảnh hưởng dữ liệu, backup và thử trên nhánh Neon;
  kiểm tra tính tương thích với phiên bản đang phục vụ trước khi build. Rollback
  mã nguồn không tự rollback schema hoặc phục hồi database.

## Giới hạn của bản Free

Render Free ngủ sau 15 phút không truy cập, đánh thức có thể mất khoảng một phút;
không phù hợp cam kết production luôn sẵn sàng. File ghi lên máy Render không bền:
dữ liệu học nằm trong Neon, asset đóng gói nằm trong Git; không dùng SQLite hoặc
đặt file upload mới trên đĩa Render để lưu lâu dài. Nếu thêm upload, cần kho đối tượng.
Neon Free có hạn mức compute/storage/network; không chọn nâng cấp trả phí tự động.

AI Tutor inference ban đầu tắt, tra cứu nội bộ vẫn hoạt động. Bật inference sau khi
cấu hình provider/quota và kiểm tra; cài Neon không tự cấp ngân sách model.
Các mục audit cần người duyệt, PostgreSQL concurrency và thiết bị thật chưa tự đóng
chỉ vì ứng dụng đã có cấu hình triển khai.
