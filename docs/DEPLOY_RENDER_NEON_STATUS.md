# Trạng thái triển khai Render + Neon — 26/10/2026

**Django đã chạy tại https://linguapath-app.onrender.com/.**
Đây là ứng dụng đầy đủ, giữ đăng ký/đăng nhập, quiz, flashcard, kế hoạch học và
lịch sử cá nhân. Cloudflare Containers chưa được triển khai.

## Bản triển khai thực tế

- Workspace `My Workspace` (`tea-dbfb042vcj2c73ffcqsg`), đã được người dùng xác nhận.
- Render `linguapath-app`, service `srv-dbfgv95g1s2s73fpgpog`: Python 3.12,
  Free, Singapore; auto-deploy tắt, một Gunicorn worker, không có disk/database trả phí.
- Bản M13 deploy `dep-dbfi3joae00c7386c7e0` đã live lúc 16:49:26 giờ Việt Nam
  (UTC+7) ngày 26/10/2026; bổ sung giao diện Daylight.
- Mã ứng dụng đang chạy: `6f59576a48c64cd60aee3791070cfd0ac57cede2`, nhánh
  `deploy/render-neon` của `tuanlamviec007/LinguaPath`; chưa merge vào main.
  Các cập nhật biên bản sau đó không thay đổi mã ứng dụng đang chạy.
- Neon PostgreSQL 16, Free, Singapore: project `flat-sun-74939022`, branch
  `br-fancy-truth-azceaiwp`. DATABASE_URL và Django secret chỉ đặt trong môi trường
  dịch vụ; không lưu trong repository hay tài liệu này.
- Build đã cài dependency có hash, collectstatic, migrate, nhập snapshot và đạt
  `check_release`. Startup chỉ gate rồi Gunicorn, không migrate/seed lại khi thức dậy.
- Service tạo trực tiếp dùng probe TCP mặc định. `render.yaml` có HTTP probe
  `/livez/`, nhưng chưa áp dụng cấu hình HTTP probe đó lên service hiện tại.
- Service Docker cũ `srv-dbfb0q8m7kps738dofqg` không bị sửa hoặc xóa.

## Học liệu đã nhập và kiểm tra

Người dùng đã cho phép công bố snapshot chỉ học liệu lên repository công khai.
Hash gzip khớp manifest:
`715d67a251945d44909bc7e650f3d8511ae9bdac18e718ba1bc53cf2cfa9f0c0`.

Truy vấn read-only Neon xác nhận 429 bộ, 3.056 thẻ, 5.138 câu và 20.552 lựa chọn.
Thẻ 778 vẫn bị giữ, bộ 45 vẫn chưa xuất bản; không có tài khoản nào được nhập/tạo
để kiểm thử trên production. Giữ nguyên trạng thái rà soát; 0 bộ teacher_approved.

## Nghiệm thu đã thực hiện

- Trình duyệt thật xác nhận HTTPS, trang chủ/CSS, lật thẻ minh họa và biểu mẫu
  đăng nhập/đăng ký hiển thị đúng. `/livez/` và `/healthz/` đều trả `{"status":"ok"}`.
- 85 kiểm thử liên quan đạt cục bộ khi biến môi trường AI_TUTOR_ENABLED=false.
  Sửa kiểm thử provider mock để khai báo bật AI riêng, unit test backend để mô phỏng
  SQLite rõ ràng, và nhận diện SELECT cursor của PostgreSQL mà vẫn giữ số truy vấn.
- [CI run 40294128144](https://github.com/tuanlamviec007/LinguaPath/actions/runs/40294128144)
  đạt trên commit `66c8e119f8c3a67011c99f7e4e930e9b4df7fed7`: **865/865 Django**
  trên PostgreSQL 16 (không skip, gồm 8 kiểm thử chỉ chạy trên PostgreSQL), **109/109 Node**,
  migration drift, empty-schema gate, migrate/nhập fixture hai lần, production check,
  collectstatic, Worker dry-run và build Docker đều đạt.
- Container smoke trên PostgreSQL CI dùng một lần đạt: liveness/readiness,
  secure cookies, CSRF rejection, synthetic login và phiên sau restart.
  Đây là proxy TLS mô phỏng trong CI; không thay cho đăng nhập/restart production.
- M13: [CI run 40301521253](https://github.com/tuanlamviec007/LinguaPath/actions/runs/40301521253)
  đạt trên commit `6f59576a48c64cd60aee3791070cfd0ac57cede2`: **866/866 Django**
  PostgreSQL không skip, **109/109 Node**, đầy đủ các bước build/smoke như trên.
  D07 bổ sung phép đo 10/1.000/5.000 phiên tổng hợp; xem
  [bằng chứng M13](DAYLIGHT_AUDIT_M13.md).
- Sau rollout M13, trình duyệt xác minh màu CSS tính toán đúng bảng Daylight,
  focus của skip-link đến main, lật thẻ bằng Enter, viền/ chữ input đăng ký và
  `/healthz/` trả ok. Không tạo tài khoản thử hoặc ghi dữ liệu học trên production.
- Các cập nhật tài liệu sau M13 không thay đổi mã ứng dụng hoặc kiểm thử.

## Giới hạn còn lại

- Chưa thực hiện đăng ký/đăng nhập, nộp quiz hoặc restart trực tiếp trên production;
  không dùng dữ liệu thử để làm đầy database người dùng. CI dùng database dùng một lần.
- HSTS đặt 0 trong giai đoạn xác minh. Ingress/client IP chưa nghiệm thu; auth dùng
  socket-peer fallback, có thể gộp hạn mức cho người dùng cùng proxy.
- Render Free có thể ngủ khi không có truy cập. Chưa xác minh timeout tự ngủ Neon:
  API trả 0 và yêu cầu đặt khoảng ngủ ban đầu bị tài khoản dịch vụ từ chối.
  Không bật nâng cấp hoặc dịch vụ trả phí.
- AI inference tắt; tra cứu học liệu nội bộ vẫn hoạt động. Không gọi model thật.
- Triển khai không đóng các mục audit cần giáo viên duyệt, pilot người học,
  benchmark AI/semantic retrieval, backup/restore và kiểm tra thiết bị thực tế.
