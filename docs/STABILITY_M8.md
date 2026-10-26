# LinguaPath — kiểm tra khởi động và container M8

Cập nhật **25/10/2026**. Siết điều kiện trước khi Gunicorn phục vụ và bổ sung smoke cho image trên CI. Không có migration mới, không thay dữ liệu người học hoặc triển khai Cloudflare. **Chưa nghiệm thu Docker/PostgreSQL/staging thực tế trong phiên này.**

## Gate khởi động

`scripts/start-production.sh` chạy `python manage.py check_release` trước Gunicorn. Gate lỗi trả exit code khác0 và server không chạy. Không tự migrate, seed, backfill hoặc gọi AI.

```bash
# Chỉ kiểm tra kết nối/schema/projection của máy phát triển:
python manage.py check_release --local --format json
# Kiểm tra điều kiện production:
python manage.py check_release --format json
```

Mặc định yêu cầu DEBUG=false, PostgreSQL, secret không mặc định đủ độ dài, cookie session/CSRF secure, redirect HTTPS, host/origin hợp lệ. Khi bật header IP, cần header đúng dạng và CIDR proxy rõ, không chấp nhận /0. Nếu bật inference, provider/quota phải được cấu hình hợp lệ; không thử key bằng inference. Origin HTTPS có thể dùng cổng hợp lệ; same-origin mặc định vẫn được hỗ trợ.

Sau cấu hình, gate kiểm tra kết nối/migration/bảng, rồi metadata và receipt của projection từ cần ôn. Quiz đã nộp thiếu projection ready/đúng version hoặc receipt làm gate thất bại. Không đọc snapshot/answer lịch sử. Bulk SQL/repair vẫn phải reconcile bằng backfill; gate metadata không phát hiện mọi sai lệch payload.

HSTS chưa bật, quota đang dùng socket peer và ingress chưa xác minh là **warning**. Vẫn cần xác minh peer/header thật trước beta. Báo cáo không xuất secret, URL database, địa chỉ proxy hoặc exception sâu. `release_approval=false` kể cả khi đạt: chưa chứng nhận nội dung, model, tải, backup/restore hoặc toàn bộ audit.

PostgreSQL có `connect_timeout` mặc định5 giây mỗi host. `DJANGO_DB_CONNECT_TIMEOUT` cho phép1–30 giây; nếu không đặt env, dùng `connect_timeout` hợp lệ trong DATABASE_URL. Giá trị0/âm/quá30/không phải số làm settings dừng bằng thông báo chung. Đây là timeout thiết lập kết nối libpq theo host, không phải giới hạn truy vấn/toàn bộ readiness request.

`release_checks_m8.json` ghi kết quả thật ở máy phát triển: **local ready=true, production ready=false**. DEBUG/SQLite/secret/cookie/HTTPS mặc định và AI chưa có provider bị chặn đúng dự kiến. Local đạt không phải bằng chứng đã thử PostgreSQL hoặc production.

## CI và smoke image

Workflow gọi `sh scripts/check-project.sh --require-postgresql`: backend SQLite bị chặn trước kiểm thử để tránh run xanh với concurrency skip. Sau migrate CI có check_release dưới cấu hình production. Sau build image có:

```bash
python scripts/smoke-production.py --image "linguapath-ci:$GITHUB_SHA"
```

Harness chỉ nhận Linux GitHub Actions, CI=true, image cục bộ dạng linguapath-ci:TAG và database PostgreSQL loopback đúng tên/user `linguapath_ci`, cổng5432, không có query tùy ý. Dùng `--pull=never`, không cài Docker hoặc chạm production. Secret/tài khoản ngẫu nhiên ở bộ nhớ, truyền Docker bằng tên biến môi trường, không đưa giá trị vào argv/log/file.

Fixture tạo học viên thường và hồ sơ đã hoàn tất mục tiêu, không tạo staff. Kiểm tra livez/healthz không cache, cookie secure/HttpOnly cho session, POST thiếu CSRF phải403, đăng nhập hợp lệ, dashboard200/private/no-store, rồi restart container và dùng lại cookie để kiểm tra session PostgreSQL. Luôn thử cleanup tài khoản fixture/container kể cả khi lỗi; cleanup lỗi làm run thất bại. Service DB của CI bị hủy cuối job.

HTTP localhost với Host/X-Forwarded-Proto và cookie secure được gửi chủ động để **mô phỏng TLS proxy**. Chưa kiểm tra HTTPS công khai, Cloudflare ingress/cold start, browser, tải hoặc backup/restore. Giới hạn body/request timeout5 giây, chờ readiness có hạn; không in password, cookie, body riêng hoặc stderr Docker. Thiếu điều kiện CI/Docker thì thất bại, không báo giả thành công.

## Kiểm chứng và giới hạn

**731 Django tests:723 đạt,8 PostgreSQL-only skip;103/103 JavaScript tests đạt.** Thêm33 tests Django, gồm gate/config, timeout, shell entrypoint và smoke contracts. System/schema/projection check và migration drift đạt. Toàn bộ36 bảng DB chính không đổi so với M4 checkpoint, integrity_check OK. Có kiểm tra shell: gate lỗi chặn Gunicorn; khi đạt vẫn dùng logger an toàn. Kiểm tra settings timeout, config/schema/projection lỗi và đầu ra đã lược thông tin nhạy cảm.

Harness có unit tests giả lập Docker và test hợp đồng Django thật: form, CSRF, secure cookie, session DB nạp lại qua client mới; session mất hiệu lực không được báo còn đăng nhập. Đây là kiểm tra trong process trên test DB, **chưa phải restart container/PostgreSQL thật**. Không có thay đổi giao diện hoặc browser QA mới.

O01/O02 còn chờ repository/runner, run ID, build/runtime image và biên bản PostgreSQL/Cloudflare. S01 cần ingress thật; các mục vận hành, review chuyên môn, holdout/model/calibration và sửa dữ liệu còn treo giữ trạng thái riêng trong bảng audit.
