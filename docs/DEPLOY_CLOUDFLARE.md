# Triển khai LinguaPath trên Cloudflare

## Trạng thái bản bàn giao

Đã chuẩn bị Django production, image container và Worker ingress. **Chưa có deployment production được xác nhận**, chưa có URL công khai được kiểm thử. Email tài khoản không tự cấp quyền deploy. Chưa khởi tạo PostgreSQL, chưa nâng cấp gói trả phí. Không đưa SQLite, tài khoản local hoặc secret vào image/gói mã nguồn.

Kiến trúc đề xuất: trình duyệt → HTTPS Worker → Django/Gunicorn trong Cloudflare Containers → PostgreSQL có lưu trữ bền vững và TLS. CSS/JS/MP3 được đóng trong image và phục vụ bằng WhiteNoise. Filesystem container không dùng để giữ dữ liệu học tập. Durable Object APP điều phối container; AI_BUDGET giữ bộ đếm lượt Workers AI toàn hệ thống. Cả hai không thay thế database Django.

Cloudflare Python Workers có hỗ trợ Django, nhưng backend D1/DO của `django-cf` hiện không hỗ trợ transaction. Dự án này dùng transaction khi nộp bài và quản lý phiên học, vì vậy bản cấu hình này chọn container với PostgreSQL. Không chuyển trực tiếp DATABASE_URL sang D1.

Containers dùng Workers Paid (mức nền công bố 5 USD/tháng, có phí vượt mức, Worker/DO và database riêng). `max_instances: 1`, ngủ sau 5 phút chỉ giới hạn quy mô khởi đầu, **không phải trần hóa đơn**. Cần chốt tài khoản, gói và ngân sách trước khi kích hoạt dịch vụ trả phí.

## 1. Điều kiện thực hiện

- Cloudflare đã xác thực đúng tài khoản chủ sở hữu; xác nhận gói hỗ trợ Containers và ngân sách.
- PostgreSQL được tạo ở nhà cung cấp đã chọn, bật backup và kết nối TLS. Dùng URL có `sslmode=require` hoặc `verify-full` theo hướng dẫn nhà cung cấp. Không dùng kết nối không mã hóa cho database qua Internet.
- Máy build có Docker chạy được và Node.js >=22. Môi trường soạn bản này không có Docker nên chưa build/run image.
- Khởi đầu với hostname `workers.dev` thực của tài khoản; không cần mua tên miền để thử. Gắn domain riêng sau khi site hoạt động ổn định.

## 2. Cấu hình và xác thực trên máy triển khai

Từ thư mục dự án:

```bash
cd deploy/cloudflare
npm ci
npx wrangler login
npx wrangler whoami
```

Xác nhận tài khoản trong `whoami` đúng chủ sở hữu trước khi tiếp tục. Nếu có nhiều tài khoản, đặt `account_id` đúng vào `wrangler.jsonc`. Không gửi token/mật khẩu vào chat hoặc commit vào Git.

Thay tất cả hostname `REPLACE_WITH_YOUR_SUBDOMAIN` trong `wrangler.jsonc`, gồm cả `CLOUDFLARE_AI_ENDPOINT`. Nếu dùng domain riêng, thay cả `DJANGO_ALLOWED_HOSTS` và `DJANGO_CSRF_TRUSTED_ORIGINS`; một hostname mỗi mục, danh sách cách nhau bằng dấu phẩy. Không đặt wildcard `*`.

Lưu `DJANGO_SECRET_KEY` (ngẫu nhiên >=50 ký tự) và `DATABASE_URL` bằng secret manager của Worker:

```bash
npx wrangler secret put DJANGO_SECRET_KEY
npx wrangler secret put DATABASE_URL
```

Các lệnh nhận secret ở prompt riêng. Không đặt secret trong command arguments, `vars`, Docker build arguments hoặc file được commit. Worker từ chối phục vụ nếu thiếu hai secret. Ban đầu `AI_TUTOR_ENABLED=false`, trợ lý tra cứu nội dung vẫn dùng được và không gọi model trả phí.

## 3. Chuẩn bị dữ liệu trước khi mở traffic

Trong một phiên shell quản trị tin cậy đã được cấp môi trường từ secret manager (tham khảo tên biến ở `.env.production.example`), dùng cùng phiên bản mã nguồn sẽ deploy:

```bash
python manage.py check --deploy
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py check_schema
python manage.py seed_demo
python manage.py seed_starter_content
python manage.py seed_advanced_content
# Mặc định tạo bản nháp, cần biên tập/duyệt trước khi công bố.
python manage.py seed_vocabulary_3000
python manage.py createsuperuser
```

Chỉ chạy các lệnh seed khi khởi tạo database mới có chủ đích. **Không đưa seed vào mỗi lần deploy**: chúng có thể ghi đè nội dung giáo viên đã chỉnh sửa. Backup trước mọi migration/seed trên database đã có người dùng. Không có mật khẩu admin mặc định; `createsuperuser` nhận mật khẩu tương tác. Không mở endpoint HTTP để chạy migrate, seed hoặc tạo admin.

Sau khi nạp cả phần mở rộng, dữ liệu có 3.016 flashcard, 417 bộ học liệu, 5.058 câu hỏi. Riêng phần mở rộng 2.000 từ/4.000 câu mặc định là nháp: chỉ xuất bản sau rà soát, hoặc dùng `--publish-provisional` khi chủ đích thử bản beta có nhãn AI sơ bộ. Đây là nội dung tự biên soạn/AI hỗ trợ, chưa phải kho đề chính thức hoặc được giáo viên chứng nhận; public beta cần ghi rõ giới hạn trên giao diện hiện có.

## 4. Build và deploy

Từ `deploy/cloudflare` với Docker đang chạy:

```bash
npm run check
npm run deploy
npx wrangler containers list
```

Wrangler dùng Dockerfile ở gốc dự án và build context gốc. Image chạy non-root, Gunicorn nghe cổng 8000, không tự migrate/seed. Phải chạy bước release phía trên trước khi nhận traffic. Giữ image/phiên bản mã cũ để rollback. Không rollback schema bằng lệnh tự động thiếu đánh giá tương thích.

Worker thay thế `X-Forwarded-Proto` bằng `https` và chỉ chấp nhận hostname đã cấu hình. `DJANGO_TRUST_PROXY_SSL_HEADER=true` chỉ an toàn vì cổng container đi qua ingress tin cậy này; khi chạy image ở VPS khác, phải chặn truy cập trực tiếp origin hoặc cấu hình lại proxy. HTTPS redirect và cookie Secure vẫn bật.

Đã có cầu nối Workers AI qua binding `AI`, khóa `AI_BRIDGE_SECRET` và Durable Object giới hạn lượt toàn hệ thống. Xem [hướng dẫn AI Tutor](CLOUDFLARE_AI_TUTOR.md) để cấu hình và xác minh trước khi bật `AI_TUTOR_ENABLED=true`. Không cần OpenAI API key cho nhánh này.

## 5. Xác nhận production

- `https://HOST/healthz/` kiểm tra database, migration cần thiết và bảng model; trả JSON `{"status":"ok"}` khi sẵn sàng, lỗi/thiếu schema trả 503 chung. `/livez/` chỉ xác nhận tiến trình HTTP đang chạy. Startup chạy `check_schema` trước Gunicorn; xem [CI và cổng phát hành](CI.md).
- Trang chủ, CSS/font, MP3 và admin tải được qua HTTPS, không vòng lặp redirect.
- Đăng ký → đăng nhập → lật/đánh giá flashcard → lưu nháp bài → nộp → xem tiến độ → đăng xuất. Kiểm tra CSRF bằng form thật, không chỉ GET.
- Khởi động lại container, đăng nhập lại và xác nhận dữ liệu học vẫn còn trong PostgreSQL.
- Không cache HTML cá nhân, `/admin/`, `/accounts/`, `/tutor/`, `/healthz/` hoặc response có cookie; không tạo quy tắc Cloudflare Cache Everything toàn site.
- Sau khi HTTPS/proxy ổn định tăng `DJANGO_SECURE_HSTS_SECONDS`; bản mẫu để 0 lúc xác minh. Mặc định Django production nếu không override là 31536000.
- Theo dõi 5xx, độ trễ, kết nối database, dung lượng và hóa đơn. Lập lịch backup theo nhà cung cấp PostgreSQL và kiểm tra restore vào database riêng trước khi quảng bá rộng.

## Kiểm chứng hiện tại và giới hạn

Cập nhật 21/10/2026: có thêm Workers AI và lịch sử trợ lý (migration0012). Kết quả kiểm tra mới cùng giới hạn hiện tại được ghi tại [CLOUDFLARE_AI_TUTOR.md](CLOUDFLARE_AI_TUTOR.md). Đoạn dưới là kết quả lịch sử của cấu hình container ban đầu.


202 Django tests đã pass trên SQLite cục bộ, gồm cấu hình production và health endpoint. 18 Node tests pass (14 giao diện, 4 ingress Worker: giữ POST/cookie, ghi đè header TLS, chặn host/thiếu secret và lỗi container). Wrangler đã xác nhận gói Worker bằng dry-run với `--containers-rollout=none`; cách này không build hoặc deploy container. Dry-run đầy đủ dừng vì thiếu Docker CLI. `check --deploy` không có lỗi, còn hai cảnh báo HSTS includeSubdomains/preload được giữ tắt có chủ đích cho tới khi xác nhận toàn bộ domain. Chưa kiểm thử tích hợp PostgreSQL thực, build image Docker, vòng đăng nhập/CSRF qua Worker, phục hồi backup hoặc tải đồng thời trên Cloudflare. Các kiểm tra đó cần hạ tầng thật trước khi gọi bản này là production đã nghiệm thu.

Tài liệu chính thức tham khảo (20/10/2026):

- https://developers.cloudflare.com/containers/get-started/
- https://developers.cloudflare.com/containers/examples/env-vars-and-secrets/
- https://developers.cloudflare.com/containers/platform/pricing/
- https://developers.cloudflare.com/workers/languages/python/packages/django/
- https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
## Cập nhật auth M2 — 24/10/2026

Quota auth dùng DB chung sau migration 0019. Mặc định dựa REMOTE_ADDR, nên người dùng sau cùng proxy có thể dùng chung quota. Worker đã có private client-IP header được ghi đè từ edge và forward hai biến DJANGO_AUTH_TRUSTED_PROXIES / DJANGO_AUTH_CLIENT_IP_HEADER vào Container; chỉ bật trust sau khi xác minh direct-peer CIDR thực trên staging. Không dùng trust-all. Xem [hướng dẫn M2](STABILITY_M2.md) để biết hạn mức, retention và gate kiểm tra IP trước public beta.

