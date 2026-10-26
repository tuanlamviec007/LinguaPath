# LinguaPath — hiệu năng từ yếu, chỉ số và vận hành M4

Ngày **24/10/2026**. Tiếp tục D07, C07, O04/O05 và phần giao diện C04/G01. Xem [trạng thái 33 mục audit](AUDIT_STATUS_2026-10-24.md) và [áp dụng workflow CloudShop](CLOUDSHOP_WORKFLOW_APPLICABILITY.md). Đây là đợt triển khai cục bộ; không đồng nghĩa toàn bộ milestone production đã hoàn thành.

## 1. Từ cần ôn không đọc lại snapshot lịch sử

Lưu projection gọn lúc submit trong cùng transaction, khóa User trước Quiz. Nhóm theo tài khoản/kỳ thi/card/identity từ+nghĩa/mode/cue; lưu kết quả gần nhất theo submitted_at rồi ID, và tổng lần sai hợp lệ. Receipt bảo đảm cùng quiz không tăng counter nhiều lần. Quiz/snapshot/điểm/XP gốc không bị sửa.

Các nhóm recall riêng được kiểm tra lại theo toàn kho hiện visible. Prompt trở nên mơ hồ không mở lỗi mới hoặc xóa lỗi meaning hợp lệ trước đó. Thẻ sửa term/meaning không nhận nhầm bằng chứng từ bản cũ; ẩn/hiện lại nguồn vẫn theo quyền và identity. Dữ liệu future import giữ trong bảng mỏng, chỉ tham gia khi tới thời điểm; không đổ vào counter hiện tại sớm.

Bulk create/update, raw fixtures hoặc sửa trực tiếp lịch sử cần reconcile. GET không tự backfill; projection thiếu/dirty hiển thị “đang chờ đồng bộ”, số lượng là dấu gạch và chặn tạo quiz từ nguồn chưa đủ. Không hiển thị sai thành “không có từ cần ôn”. Sửa ordinary save có fingerprint khác hoặc xóa lịch sử đánh dấu cần rebuild; đổi owner làm bẩn cả hai bên.

**Policy dữ liệu lỗi:** canonical quiz có card ID duy nhất. Nếu legacy/import lặp card ID với identity hoặc recall cue xung đột, bỏ bằng chứng của card đó trong cả phiên; không đoán và không dùng nó để mở/xóa lỗi. Bản lặp cùng cue giữ câu trả lời hợp lệ đầu tiên một lần. Đây là hardening có chủ đích so với cách chọn phụ thuộc bản thẻ hiện tại của helper cũ. Đồng hồ quay ngược qua timestamp đã tổng hợp làm projection cần backfill thay vì tự đoán lịch sử trước đó.

### Nâng cấp có dữ liệu cũ

Backup trước, giữ traffic ở bản cũ trong lúc migration/backfill:

```bash
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py check_schema
# Xem phạm vi trước; mặc định tối đa 100 tài khoản:
python manage.py backfill_weak_word_outcomes
python manage.py backfill_weak_word_outcomes --apply --limit 100
# Nếu còn tài khoản, tiếp tục từ checkpoint lệnh đã in:
python manage.py backfill_weak_word_outcomes --apply --after-user-id LAST_COMPLETED_ID --limit 100
python manage.py check_weak_word_outcomes
python manage.py collectstatic --noinput
```

Migration **0021_weak_word_outcomes** thêm bốn bảng projection/receipt/pending/state. Backfill nguyên tử theo tài khoản, iterator/batch có giới hạn bộ nhớ và chạy lặp an toàn; command mặc định chỉ preview. Một tài khoản có lịch sử rất lớn vẫn giữ transaction User trong thời gian rebuild: đo trên staging trước rollout, không chạy trong request. Không seed hoặc tự publish/teacher_approve.

Gate chỉ kiểm tra metadata readiness/receipt, không phát hiện mọi raw SQL sửa payload; sau bulk repair luôn reconcile theo quy trình. Có thể rebuild một tài khoản với `--user-id ID --apply`. Không cấp quyền chạy command quản trị này cho học viên.

### Đo ngoại tuyến

Fixture cô lập SQLite memory: 3.000 thẻ, 15 câu/lượt, snapshot 30.687 byte, ba lần đọc mỗi mức.

| Lượt lịch sử | Dung lượng snapshot logic | Nhóm outcome | Query đọc | Median local |
|---:|---:|---:|---:|---:|
| 10 | 0,31 MB | 15 | 5 | 46,65 ms |
| 1.000 | 30,69 MB | 15 | 5 | 60,10 ms |
| 5.000 | 153,44 MB | 15 | 5 | 62,34 ms |

Không SELECT cột snapshot/answers của lịch sử trong đường đọc. Vẫn có phép EXISTS metadata receipt và quét kho current/projection; không gọi là O(1) theo mọi chiều dữ liệu hoặc bằng chứng latency production. Chưa đo PostgreSQL/query plan. Số đo audit cũ dùng môi trường khác nên không công bố hệ số tăng tốc trước/sau từ hai lần đo.

Tái lập bằng `python scripts/benchmark_weak_words.py --output /tmp/weak-word-benchmark.json`; script bắt buộc dùng DB memory riêng và tắt inference. Báo cáo/fingerprint: `weak_words_benchmark_m4.json`.

## 2. Chỉ số và học liệu

- Quiz mới chia nhóm theo meaning/recall, mức đã chọn và all/saved/weak. Tính tỷ lệ có trọng số theo số câu; nhóm dưới 5 câu ghi chưa đủ dữ liệu. Lượt ôn riêng, ngày/exam/ownership/future được lọc như trước.
- Tổng quiz chỉ mô tả hoạt động, không phải điểm năng lực; mức chọn là filter, mức trộn không chứng minh CEFR. Query recent không tải snapshot/answers/draft của quiz/parent.
- Placement đổi nhãn “Ước lượng vốn từ”, nói rõ chưa hiệu chuẩn, chỉ kiểm tra nhận biết; giữ lựa chọn mức dễ hơn và làm lại. C04 vẫn cần pilot/chuyên môn, không tự thay thuật toán.
- Sổ lỗi giải thích câu Listening chưa có audio không đủ điều kiện retry; có link về bài gốc. Nếu có script, người học có thể dùng giọng đọc thiết bị. Không mở transcript vào DTO retry trước submit.

## 3. Log và dependency

[OPERATIONS.md](OPERATIONS.md) mô tả UUID request, log JSON allowlist, Worker correlation, Gunicorn safe logger, health probes và ngưỡng đề xuất. Không ghi raw path/query/IP, prompt, secret hoặc traceback trong các kênh này. Chưa bật remote collector, alert delivery hoặc người trực; không gửi log vào endpoint CloudShop.

`requirements.lock` khóa **25 package** theo môi trường đã kiểm tra, có SHA-256 wheel và dùng `pip --require-hashes`. Đã cài sạch vào venv riêng từ wheel đã tải và pip check đạt. Docker/CI dùng lock; lock hiện cho **Python 3.12/Linux x86_64**, không hứa tái lập mọi OS/architecture. Windows development vẫn có `requirements.txt` direct manifest; cần lock riêng nếu muốn tái lập môi trường Windows.

Base Docker image và PostgreSQL CI image chưa pin digest, chưa build/run container; O05 còn mở phần này. Hash dependency không phải xác nhận không có CVE. Cập nhật package cần resolve/download wheel từ registry tin cậy, tạo lại hash, cài sạch và chạy đủ suite, không nới `--require-hashes` để bỏ qua lỗi.

## 4. Dữ liệu cá nhân

Trang `/settings/privacy/` chỉ xem thông tin trên GET. Tải JSON/xóa đều là POST có CSRF, yêu cầu mật khẩu hiện tại, khóa User để kiểm tra lại principal và dùng quota DB `privacy_reauth`: 30/IP, 5/IP+tài khoản trong 10 phút. Lỗi cấu hình/DB bị từ chối; lỗi quota trả429/Retry-After. Tham số tài khoản người dùng gửi không thay thế chủ sở hữu từ phiên đăng nhập.

Export dùng allowlist trường và iterator theo từng nhóm: hồ sơ/nhiệm vụ, practice/quiz/bản nháp, sổ lỗi/lượt ôn, Tutor, SRS, sổ từ, reward và projection. Không xuất password/hash, session/token, credentials hoặc dữ liệu người khác. Quiz chưa nộp chỉ xuất phần đề công khai/draft của chính người học, không mở target recall hoặc khóa chấm; snapshot/evidence đầy đủ chỉ cho lượt đã nộp. Tối đa20MiB tải trực tiếp; vượt trả413 và hướng tới quy trình xuất đầy đủ đã xác thực, không tạo bản bị cắt. Chưa có export nền cho tài khoản lớn.

Xóa cần đúng mật khẩu, nhập `XOA` và checkbox xác nhận rõ. Chặn tài khoản staff/superuser để tránh mất quyền vận hành; xóa cascade dữ liệu cá nhân trong DB hiện hành, giữ học liệu chung/người khác và đăng xuất sau commit. Chỉ fixture test thực hiện xóa; không xóa tài khoản DB làm việc trong phiên này.

Thao tác không tự xóa backup, file người học tải, shared HMAC abuse counters hoặc dữ liệu đã gửi provider. Vẫn cần chốt retention/backup restore reconciliation và quy trình xử lý các bản sao ngoài DB. Có decorator che trường nhạy cảm khỏi Django error report; các kênh log hạ tầng ngoài ứng dụng vẫn phải rà riêng. Không coi privacy center là chứng nhận hoàn tất mọi nghĩa vụ hoặc lifecycle dữ liệu.

## 5. Kiểm tra dữ liệu và giới hạn

DB làm việc đã backup trước0021; backfill không có tài khoản cũ trong DB này. Hash dữ liệu của tất cả bảng ứng dụng cũ giữ nguyên sau migration; chỉ metadata Django thêm 4 ContentType/16 permission/migration mới và bốn bảng rỗng. Integrity/FK check đạt. Một bản sao SQLite sau nâng cấp đã kiểm tra integrity/FK/count/schema ở đường dẫn khác; đây **không phải diễn tập restore PostgreSQL production**.

Giao diện progress được xem desktop và iframe 375 px; đã sửa một overflow do phần tử sr-only trong bảng kỹ năng. Tài liệu bảng có vùng cuộn ngang, không làm tràn cả trang. Trạng thái pending không báo nhầm queue rỗng; placement nói rõ giới hạn. Fixture dùng DB memory, chưa phải live browser–Django E2E hoặc screen reader/điện thoại thật.

Kiểm thử bản cuối bằng venv cài sạch từ hash lock: **598 Django tests — 590 đạt, 8 PostgreSQL-only skip; 91/91 JavaScript tests đạt**. System/schema/projection checks, migration drift, pip check, collectstatic và Gunicorn config/logger check đạt. Worker bundle dry-run đạt; không build/deploy container. Bộ privacy có13 regression, projection có20 regression và một concurrency test PG-only; browser kiểm tra GET trang privacy và các control xác nhận, không thực hiện xóa trên DB làm việc.

PostgreSQL thực, GitHub CI thật, Docker/Cloudflare staging, load test, alert delivery và đánh giá model thật vẫn chưa có bằng chứng thực thi. Môi trường thiếu server/client PG và Docker; lần thử chuẩn bị package PG không thực hiện được do giới hạn quyền môi trường, không thay đổi bảo vệ để vượt qua giới hạn.
