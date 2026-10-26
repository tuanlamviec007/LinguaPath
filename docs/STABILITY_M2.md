# LinguaPath — Bảo mật, chất lượng quiz và giao diện M2

Ngày cập nhật: **24/10/2026**. Đây là đợt triển khai tiếp theo sau M1, tập trung S01–S03, C02–C03 và U01–U03 của audit. Bộ học liệu được giáo viên duyệt và nghiệm thu production vẫn là các điều kiện còn mở.

## Thay đổi chính

| Phần | Hành vi mới |
|---|---|
| Đăng nhập/đăng ký | Quota chung trong DB cho login, signup, admin login và password reset; kiểm tra sau CSRF. Quá hạn mức trả 429 với Retry-After; lỗi DB/cấu hình trả 503 chung. |
| Dữ liệu cá nhân | Trang học, tài khoản, admin, JSON và redirect cá nhân có private/no-store và Vary: Cookie. Asset tĩnh do WhiteNoise phục vụ không bị áp policy cá nhân. |
| Import học liệu | Kiểm tra đúng quyền parent tạo mới/cập nhật, làm mới principal, validate CSV toàn bộ trước ghi và dùng thứ tự khóa nhất quán. |
| Gõ từ | Tạm loại prompt trùng nghĩa/từ loại/gợi ý nhưng có các term khác nhau trên toàn kho đang xuất bản của cùng kỳ thi; không tự nhận từ đồng nghĩa. |
| Giao diện | Giữ mode/level/topic/count khi đổi nguồn quiz; liên kết nghĩa Việt với input recall; tăng tương phản chữ và cho focus cuộn tới câu mới. |
| Flashcard | Đánh giá xong vẫn ở workspace/bộ lọc/trang đang học; anchor tới thẻ hiện tại hoặc thẻ kế bên còn lại. Redirect chỉ cho phép route flashcard nội bộ. |

## 1. Giới hạn auth

Các cửa sổ cố định dùng UTC; đây là hạn mức request, không phải khóa toàn tài khoản hoặc giải pháp chống DDoS. Mọi POST hợp lệ qua CSRF đều tiêu hạn mức, kể cả đăng nhập thành công. GET và request CSRF bị từ chối không tiêu quota.

| Luồng | Cửa sổ | Mỗi IP | IP + định danh |
|---|---:|---:|---:|
| Login | 10 phút | 100 | 10 |
| Admin login | 10 phút | 30 | 5 |
| Đăng ký | 1 giờ | 10 | 5 |
| Password reset | 1 giờ | 20 | 5 |

Định danh được chuẩn hóa NFKC/casefold. Key HMAC kết hợp IP/định danh; DB không lưu IP, username hoặc email thô. IP nằm trong key cặp nên một IP không khóa cùng username ở mọi IP khác. Quota IP cũng chặn việc tạo vô hạn key cặp bằng cách thay username liên tục. Không dùng LocMemCache cho quota nhiều worker.

Có thể điều chỉnh trong settings.py bằng AUTH_RATE_LIMITS, từng action login/admin_login/register/password_reset chứa window, ip, identifier. Số lượng 0 nghĩa chặn luồng tương ứng, không phải bỏ giới hạn. Cấu hình sai bị từ chối; không có fallback cho phép auth khi bộ đếm hỏng. Cửa sổ cố định có thể cho phép burst sát ranh giới hai cửa sổ; cần theo dõi và hiệu chuẩn theo tải/NAT thực tế.

### Dọn bộ đếm cũ

```bash
# Mặc định chỉ xem trước, tối đa 1.000 row mỗi batch.
python manage.py purge_expired_auth_buckets
# Xóa batch đã hết hạn hơn 24 giờ; không xóa cửa sổ đang dùng.
python manage.py purge_expired_auth_buckets --apply --batch-size 1000
```

Lệnh kiểm tra lại expires_at lúc xóa để không xóa row vừa được request khác làm mới. Không có lịch tác vụ tự động được cài trong đợt này. Đây chỉ là retention của counter; chưa thay quy trình export/xóa toàn bộ tài khoản và backup.

## 2. Proxy và Cloudflare

Mặc định chỉ dùng REMOTE_ADDR. Không mặc nhiên tin X-Forwarded-For hoặc CF-Connecting-IP do request gửi lên. Khi direct peer nằm trong allowlist CIDR được cấu hình, middleware mới đọc một IP hợp lệ từ header đã chọn; header nhiều IP hoặc sai định dạng quay về socket IP.

Worker của dự án xóa Forwarded/X-Forwarded-Host, thay TLS/Host, loại X-Forwarded-For/X-Real-IP và ghi đè X-LinguaPath-Client-IP từ CF-Connecting-IP hợp lệ ở edge. Giá trị IPv4/IPv6 được kiểm tra cú pháp; private header giả hoặc không có nguồn edge hợp lệ không được relay.

**Chưa quan sát peer CIDR thật của Cloudflare Container.** Khi triển khai, không tự điền 0.0.0.0/0, ::/0 hoặc cả dải private rộng. Cần staging xác minh request thật đi qua Worker, origin không thể bị gọi trực tiếp và hai IP khách khác nhau được phân biệt đúng.

- DJANGO_AUTH_TRUSTED_PROXIES: danh sách CIDR direct peer thực đã được xác nhận, cách nhau bằng dấu phẩy.
- DJANGO_AUTH_CLIENT_IP_HEADER: chỉ khi cấu hình trên đã xác minh, dùng HTTP_X_LINGUAPATH_CLIENT_IP với Worker hiện tại.
- Hai biến được forward từ Worker env vào Container. Có thể đặt trong vars cấu hình triển khai sau khi biết giá trị đúng.
- Nếu chưa cấu hình, giới hạn vẫn hoạt động theo socket IP; nhiều người sau cùng proxy/NAT có thể dùng chung quota. Vì vậy per-client production quota chưa được nghiệm thu.

Tài liệu nền tảng đã đối chiếu: [Cloudflare HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/) và [Django security](https://docs.djangoproject.com/en/5.2/topics/security/). Header ở Worker subrequest có semantics riêng; không suy đoán toàn bộ topology từ tên header.

## 3. CSV, quyền và khóa giao dịch

Parser dùng cùng quy tắc strict cho importer và nguồn starter: header bắt buộc, không trùng/không lạ; đúng số ô mỗi dòng; đúng level; giới hạn độ dài theo model; URL HTTP(S) hợp lệ; không có term trùng sau chuẩn hóa. Dòng lỗi được báo trước khi ghi bất kỳ học liệu nào.

Staff cần quyền add/change Flashcard như trước. Import tạo deck còn cần quyền add LearningContent; gộp vào deck có sẵn cần quyền change đối với parent thực tế. Callback kiểm tra sau khi parent đã được khóa; thiếu quyền trả 403 và transaction không tạo/cập nhật row. Đây chưa phải hệ thống tách quyền duyệt chuyên môn riêng ở cấp trường.

Thứ tự khóa: principal User → mutex ContentType → parent LearningContent → child. Các khóa principal/mutex dùng FOR NO KEY UPDATE trên PostgreSQL, vẫn loại trừ writer khác nhưng cho phép KEY SHARE của foreign-key references, đặc biệt django_admin_log. Các luồng learner dùng khóa User cùng semantics để tránh chu trình với admin log. Backend không hỗ trợ dùng row lock thường; SQLite không chứng minh concurrency này.

Có regression PostgreSQL-only yêu cầu transaction LogEntry trên kết nối khác commit được trong lúc các khóa principal/mutex còn giữ, cùng test concurrent create→merge kiểm tra lại quyền parent. Nguồn tham khảo: [Django select_for_update](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update), [PostgreSQL row locking](https://www.postgresql.org/docs/16/explicit-locking.html).

### Nguồn starter và bản ghi trip cũ

CSV nguồn đã sửa dấu phẩy không quote của trip. Seed starter giờ preflight trước ghi, giữ nội dung/metadata người biên tập đã thay đổi, thêm mục còn thiếu và không tự xây lại bộ bài đã có. Không dùng seed để sửa hàng loạt một DB đang sử dụng.

DB làm việc cũ vẫn có #778 khớp lỗi đã biết. Đã cung cấp lệnh sửa có guard provenance và giá trị cũ chính xác:

```bash
python manage.py repair_starter_trip --dry-run
# Chỉ dùng sau backup và khi sẵn sàng rà soát/xuất bản lại cả bộ:
python manage.py repair_starter_trip --apply
```

**Chưa chạy --apply trên DB làm việc:** sửa nội dung sẽ hủy review/xuất bản của parent #3, ảnh hưởng 1.000 flashcard. Lệnh in rõ tác động trước khi sửa, không tự xuất bản lại hoặc teacher_approved. Giá trị đã được người biên tập sửa khác mẫu được bỏ qua; nhiều bản ghi khớp bị từ chối thay vì tự chọn. Mã nguồn CSV mới không còn lỗi này; sửa lịch sử DB là thao tác riêng có kiểm soát.

## 4. Recall công bằng hơn

Signature dựa chính các cue đang hiển thị: nghĩa Việt chuẩn hóa, POS và hint chữ đầu/số từ. Index dựng một lần từ toàn kho visible của cùng kỳ thi, không giới hạn theo nguồn đã lưu, topic hoặc level đã chọn. Hai card cùng normalized lemma không tự thành ambiguity.

Trên kho hiện tại phát hiện 4 nhóm/8 thẻ: speak/say, shop/store, client/customer, colleague/coworker. Cùng bộ lọc chặn prompt lộ đáp án đã có, hiện có **3.029 row recall khả dụng** trong 3.056 thẻ. Các từ này vẫn dùng trong chọn nghĩa và flashcard nếu học liệu còn xuất bản.

Áp dụng ở count/build/retry, validation phiên đang làm và weak-word evidence. Phiên đang dở trở nên mơ hồ dừng với lời giải thích, không chấm/không XP. Điểm lịch sử đã nộp giữ nguyên; evidence recall mơ hồ không tự tạo hoặc xóa trạng thái từ yếu từ evidence hợp lệ khác.

Đây là bộ lọc exact-cue bảo thủ, **không phát hiện mọi ambiguity ngôn ngữ**, không mở semantic/fuzzy grading và không thay thế biên tập/giáo viên. Chưa có accepted synonyms do chuyên môn xác nhận; không tự nhận đáp án mới.

## 5. UX và accessibility

- Link đổi nguồn luôn giữ mode/count/level/topic hiện tại khi có JS, bao gồm mở tab mới và BFCache. Không đưa CSRF vào URL GET.
- No-JS vẫn nộp POST bình thường; link giữ cấu hình đã tải. Nếu sửa control mà chưa gửi khi JS tắt, chọn nguồn trước rồi mới chỉnh cấu hình, theo hướng dẫn trên trang.
- Input recall có accessible name chứa số câu; description liên kết nghĩa tiếng Việt, hint và quy tắc. User navigation cho phép trình duyệt cuộn tới focus.
- Các màu chữ nhỏ mục tiêu trên quiz được nâng tương phản, khoảng 5,35–6,93:1 theo cặp CSS đã kiểm tra; chưa phải audit toàn bộ WCAG.
- Rating flashcard giữ mode all/due, level/topic/search/page và anchor phù hợp; chỉ chấp nhận URL flashcard nội bộ, loại query lạ và target ngoài workspace.
- Trang cá nhân, auth, redirect và JSON lỗi được áp no-store. Đây không chứng minh xóa mọi bản sao lịch sử trên thiết bị hoặc hoàn thành toàn bộ privacy lifecycle.

Browser QA dùng template hiện tại render từ DB memory riêng: đã xác nhận các href giữ control mới, accessible cue/input và focus, bố cục iframe 375 px không tràn ngang. Chưa chạy screen reader hoặc bàn phím ảo trên điện thoại thật; đây không phải E2E browser–Django live. Backend HTTP/DB kiểm tra bằng Django Client.

## 6. Nâng cấp và nghiệm thu

Sau backup, cập nhật mã nguồn rồi chạy:

```bash
python manage.py check
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py check_schema
python manage.py collectstatic --noinput
```

Migration **0019_auth_rate_buckets** chỉ thêm bảng counter; không chuyển học liệu thành teacher_approved hoặc sửa dữ liệu học lịch sử. DB làm việc đã được backup và migrate; dữ liệu học giữ nguyên, có thêm ContentType/4 permission chuẩn của Django cho model mới.

Kiểm tra bản cuối: **493 Django tests: 487 đạt, 6 PostgreSQL-only tests skip trên SQLite; 87/87 JavaScript tests đạt**. System check, migration drift, pip check và collectstatic đạt. Worker bundle dry-run thành công với containers-rollout=none; không build/run container hay deploy.

## Còn mở trong kế hoạch

- Học liệu pilot được con người có chuyên môn duyệt: hiện 0 bộ xuất bản ở teacher_approved; không thay bằng agent tự phê duyệt.
- Chạy PostgreSQL concurrency/CI thật, topology proxy và per-client quotas, TLS/session/CSRF qua Worker, backup/restore/load và rollout.
- Sửa trip trên DB cũ sau khi sẵn sàng review parent; theo dõi retention counter và request quota thực tế.
- Self-service export/xóa tài khoản/retention lịch sử và backup chưa hoàn thiện toàn bộ.
- Placement/mastery/metric phân tầng, chiều sâu Reading–Listening, tối ưu weak-word lifetime scan và chất lượng AI thuộc các gói tiếp theo. Không gọi model/API trả phí trong đợt này.

Audit gốc mô tả trạng thái trước sửa trong AUDIT_PLAN_2026-10-23.md; M1 ở STABILITY_M1.md. Không lấy các test SQLite hoặc dry-run làm bằng chứng production đã sẵn sàng.
