# Kiểm tra mã nguồn và cổng phát hành

Workflow `.github/workflows/checks.yml` chạy khi push, mở/cập nhật pull request hoặc khởi động thủ công trong một repository GitHub. Workflow chỉ có quyền đọc mã nguồn, không có secret production, không đăng nhập và không deploy Cloudflare. Tệp workflow đã được thêm; chưa có bằng chứng workflow chạy trên GitHub vì bản bàn giao hiện chưa gắn repository.

## Chạy kiểm tra cục bộ

Trong môi trường đã cài dependency, tại thư mục gốc. Python 3.12/Linux x86_64 dùng `python -m pip install --require-hashes -r requirements.lock`; development Windows hiện dùng direct manifest `requirements.txt` (chưa có Windows hash lock):

```bash
sh scripts/check-project.sh
# Nếu không activate virtualenv:
PYTHON=.venv/bin/python sh scripts/check-project.sh
```

Lệnh kiểm tra Django, migration chưa được tạo, toàn bộ Django tests và tất cả `scripts/test_*.cjs`. Django tạo database test riêng; cấu hình `DATABASE_URL` phải trỏ tới database phát triển/test có quyền tạo database test, không dùng tài khoản production cho test. Script không migrate hay seed database ứng dụng.

CI dùng Python 3.12, Node 24 và PostgreSQL 16 tạm thời. CI cài mới Python bằng lock/hash và npm bằng lock, chạy cùng bộ kiểm tra, xác nhận database rỗng bị chặn, áp dụng migration vào database CI, kiểm tra schema/projection readiness, production settings, collectstatic, đóng gói Worker dry-run và build Docker image. Dry-run Worker không gọi model hoặc deploy container. Hai cảnh báo HSTS subdomains/preload được giữ có chủ đích; lỗi mức ERROR vẫn chặn build.

## Liveness, readiness và phát hành

- `/livez/`: HTTP process còn phục vụ; không truy vấn database. Dùng cho kiểm tra tiến trình.
- `/healthz/`: database truy cập được, lịch sử migration nhất quán, không còn migration cần áp dụng và đủ bảng của model đang quản lý cho phiên bản mã nguồn hiện tại. Lỗi trả 503 chung, không cache hoặc lộ chi tiết. Dùng cho kiểm tra sẵn sàng nhận traffic.
- `python manage.py check_schema`: cùng phép kiểm tra chỉ đọc, trả exit code khác 0 khi chưa sẵn sàng. Không áp dụng migration hoặc seed.

Startup phải chạy `check_schema` thành công trước Gunicorn. Trong phiên release quản trị riêng, sau backup và xem xét tương thích, chạy `migrate --plan`, `migrate --noinput`, rồi `check_schema` bằng đúng phiên bản mã nguồn sắp phát hành. Giữ traffic vào phiên bản cũ cho đến khi gate đạt; không chạy migrate/seed tự động mỗi lần container thức dậy. Probe đọc lịch sử migration và tên bảng mỗi lần kiểm tra; không gọi probe với tần suất như một API nghiệp vụ. Gate phát hiện thiếu bảng nhưng không thay thế kiểm tra toàn vẹn dữ liệu, cột/index/constraint hoặc schema bị sửa thủ công sau khi đã đánh dấu migration.

## Việc W0 còn mở

- Tạo/kết nối repository, chạy CI thật và bật branch protection theo kết quả đã quan sát. Không có remote được tạo trong đợt này.
- Chưa có PostgreSQL server/Docker CLI tại môi trường bàn giao để chạy workflow hạ tầng; service CI và image build chưa được xác nhận thực thi. Cần nghiệm thu trên runner, sau đó staging với PostgreSQL/TLS và Cloudflare thật.
- M4 thêm `requirements.lock` 25 package kèm wheel SHA-256 cho Python 3.12/Linux x86_64; đã cài sạch trong venv riêng và pip check đạt. Base image Docker và PostgreSQL service vẫn chưa pin digest; chưa có hash lock Windows hoặc chứng cứ Docker build/run. Ba GitHub Actions đã pin commit của release v7.0.0 được xác nhận từ repository chính thức. Không coi toàn bộ build là tái lập hoàn toàn; cập nhật lock cần tải wheel từ registry tin cậy, cài sạch và chạy suite.
- npm có lock kèm integrity, nhưng cài sạch offline tại môi trường audit bị thiếu cache. `npm ci` trong CI có mạng sẽ là phép kiểm tra cần đạt.
- Docker build/Worker dry-run thành công cũng chưa thay thế chạy image, session/CSRF qua ingress, kiểm thử restart, tải đồng thời, backup/restore, monitoring và rollback tại staging.

Release chính thức dùng cho workflow: [checkout v7.0.0](https://github.com/actions/checkout/releases/tag/v7.0.0), [setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0), [setup-node v7.0.0](https://github.com/actions/setup-node/releases/tag/v7.0.0). Cập nhật SHA cùng ghi chú release trong một thay đổi có kiểm tra; không đổi sang tag di động để bỏ qua kiểm tra.
