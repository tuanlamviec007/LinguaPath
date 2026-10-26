# LinguaPath — vận hành, log an toàn và cảnh báo

Cập nhật 25/10/2026. Đã có mã phát log và test ngoại tuyến. **Chưa kết nối dịch vụ cảnh báo, chưa chỉ định người trực và chưa nghiệm thu staging/production.** Không gửi log tới endpoint trong tài liệu CloudShop đính kèm; endpoint đó thuộc một luồng demo khác, không phải quyền truy cập của dự án này.

## Gate và CI runtime M8

Entrypoint production dùng `python manage.py check_release` trước Gunicorn: kiểm tra cấu hình production, kết nối/schema và projection từ cần ôn. Thất bại thì server không chạy; không tự migrate/backfill. `--local` chỉ kiểm tra development, không dùng tùy chọn này để bỏ gate trong entrypoint. Xem `STABILITY_M8.md` và `release_checks_m8.json`; local hiện đạt, cấu hình production hiện bị chặn đúng dự kiến.

PostgreSQL có timeout kết nối mặc định5 giây mỗi host; `DJANGO_DB_CONNECT_TIMEOUT` cho phép1–30 giây. Đây không phải statement timeout. CI bắt buộc backend PostgreSQL và có smoke image sau build để thử cookie/CSRF/login/session sau restart. Harness chỉ chạy trên Linux GitHub Actions với DB disposable đúng tên/user loopback; không được trỏ sang production. Hiện chỉ unit/hợp đồng Django đã chạy, chưa có Docker/PG runtime hoặc run ID thật.

## Sự kiện ứng dụng

`RequestObservationMiddleware` đứng đầu middleware để bọc cả phản hồi lỗi/redirect. Mỗi request có UUID mới do máy chủ tạo, trả trong `X-Request-ID`; bỏ qua mọi correlation ID do client tự gửi. Sự kiện JSON gồm thời gian UTC, mức log, event, request ID, HTTP method, **route template**, status và duration_ms. URL không khớp dùng `<unmatched>`; không ghi raw path hoặc query string. `/healthz/` trả 5xx được ghi riêng là `readiness_failure`.

`SafeJSONFormatter` chỉ giữ các trường đã cho phép, không serialize message/args/traceback/stack/request của Python/Django. Log thông thường được thay bằng code `message_redacted`. Vì thế lỗi sâu phải tái hiện trong môi trường phát triển bằng dữ liệu giả; không bật lại traceback/prompt logging trên production để tìm nhanh một lỗi. Middleware cố ý không làm hỏng response khi collector stdout thất bại.

Startup truyền `--logger-class config.observability.SafeGunicornLogger`. Class này thay formatter error/access của Gunicorn; error chỉ ghi mức và code server_lifecycle/server_error. Access chỉ ghi method/status/duration/UUID response, route `<server>`; không tạo tập atoms chứa raw URL/IP/header của logger mặc định. Django middleware cung cấp route template chi tiết hơn. Không bỏ cờ logger class hoặc ghi đè handler bằng cấu hình log ngoài chưa rà soát khi triển khai.

Worker tạo `X-Edge-Request-ID` mới, ghi event `worker_request` với nhóm application/readiness/liveness/internal_ai, status và duration. Trên hop vào Container, Worker xóa `X-Request-ID` do browser gửi và thay edge ID. Khi Django trả UUID hợp lệ, Worker ghi cả hai ID để nối hai hop; không coi ID từ browser là nguồn tin cậy. Cấu hình log không thêm IP, user/email, cookie, Authorization, prompt, đáp án, raw URL hoặc exception của provider.

Application console log và Worker console event không tự chứng minh hệ thống có lưu trữ hay cảnh báo bền vững. `wrangler.jsonc` vẫn tắt remote observability cho tới khi chủ dự án chọn collector, quyền truy cập và retention. Các kênh bên ngoài mã ứng dụng (ingress, Cloudflare account logs, managed PostgreSQL, hệ điều hành và debug tools) cần rà riêng trước khi triển khai; không suy ra redaction toàn hạ tầng từ formatter này.

## Handoff vận hành trước beta

| Việc cần chốt | Hiện tại |
|---|---|
| Người chịu trách nhiệm release và người thay thế | Chưa phân công |
| Người nhận cảnh báo/kênh nhận và giờ trực | Chưa cấu hình; không có email/webhook được tạo |
| Staging URL, release commit/image digest | Chưa có bản staging được nghiệm thu |
| Collector/access control/retention | Chưa chọn; đề xuất bàn giao log tối thiểu cần thiết, thời hạn ngắn có lý do |
| Backup PostgreSQL và người có quyền restore | Cần xác minh ở môi trường triển khai; không đưa credential vào repo |
| Ngưỡng và ngân sách AI | Cần chốt sau pilot; request cap không phải trần hóa đơn |

## Probe và ngưỡng khởi điểm cần hiệu chuẩn

Kiểm tra `/livez/` để biết HTTP process hoạt động; `/healthz/` để biết DB/schema sẵn sàng. GET health không tự migrate hoặc seed. Ví dụ dưới chỉ là mẫu cấu hình để chạy khi có hostname thật:

```bash
curl --fail --silent --show-error --max-time 5 https://YOUR_VERIFIED_HOST/livez/
curl --fail --silent --show-error --max-time 5 https://YOUR_VERIFIED_HOST/healthz/
```

Không dùng endpoint nội bộ AI làm uptime probe; probe không được gọi model hoặc tạo dữ liệu học. Chưa cài scheduler hoặc cảnh báo theo các lệnh mẫu.

| Tín hiệu | Điều kiện khởi điểm đề xuất | Xử lý |
|---|---|---|
| Readiness | 3 lần lỗi liên tiếp, cách 60 giây | Giữ/đưa release khỏi traffic; kiểm tra DB và `check_schema` bằng đúng mã release |
| HTTP 5xx | >1% trong 5 phút và ít nhất 50 request; với lưu lượng thấp xem từng lỗi lặp | Dùng request/edge ID tìm nhóm route; so sánh với release vừa thay |
| Latency | p95 >2 giây liên tục 5 phút | Tách cold start, DB và AI; đo trên staging trước khi coi là SLO |
| DB | Readiness fail, connection error hoặc pool bão hòa | Xác minh dịch vụ DB/TLS/quyền/schema; không ghi URL chứa mật khẩu vào log |
| AI | Global quota tiến gần mức đã chốt hoặc internal_ai tăng 429/5xx | Kiểm tra số lượt đã đặt/chi phí thực ở provider; tắt inference mới nếu cần |

Đây là ngưỡng dự án để bắt đầu hiệu chuẩn, **không phải số đo production hoặc cam kết SLO**. Middleware duration đo tới lúc response được tạo, không đo toàn bộ thời gian truyền streaming/body hoặc thời gian thiết bị người học render.

## Runbook sự cố

1. Ghi release ID, thời gian, status, `X-Request-ID`/`X-Edge-Request-ID`; không yêu cầu người học gửi cookie/token hoặc chụp dữ liệu riêng tư.
2. Kiểm tra liveness/readiness. Nếu process sống nhưng schema/DB lỗi, giữ traffic ở release cũ. Không bỏ readiness gate để làm health xanh giả.
3. Với AI, `AI_TUTOR_ENABLED=false` chặn inference mới; request đã chạy có thể hoàn tất và lượt đã đặt vẫn tính. Tra cứu và các luồng học deterministic tiếp tục theo khả năng DB.
4. Xác nhận migration tương thích trước rollback. Rollback mã không mặc nhiên rollback schema; không xóa bảng/data mới chỉ để quay lại image cũ.
5. Nếu cần restore, dùng bản backup đã xác minh vào database **khác**, chạy `check_schema`, kiểm tra số bản ghi và hành trình học, rồi mới quyết định chuyển traffic. Không restore đè production khi chưa có điểm khôi phục và phương án giữ dữ liệu mới.
6. Ghi nguyên nhân, tác động, thao tác khôi phục và regression cần bổ sung; không ghi secret hoặc prompt của người học vào biên bản.

Môi trường kiểm tra cục bộ hiện không có `postgres`, `pg_dump` hay Docker CLI. Tài liệu này không phải bằng chứng đã diễn tập PostgreSQL restore, restart Container hoặc alert delivery. O01/O04 chỉ được nghiệm thu vận hành sau khi các bước đó chạy trên hạ tầng thực có người chịu trách nhiệm.
