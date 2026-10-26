# M14 — Giảm tải thẻ và tài nguyên cho khách

Ngày 26/10/2026, tiếp tục từ M13. Không có migration hoặc đổi quy tắc chấm/SRS/XP.

## Điểm đã tối ưu

- Reader từ cần ôn lấy projection và pending theo người học/exam, kiểm tra nguồn còn
  khả dụng trong SQL, rồi chỉ hydrate các thẻ có bằng chứng tương ứng. Luồng trắc
  nghiệm không cần hydrate cả kho 3.000 thẻ khi chỉ có 15 từ liên quan.
- Giữ kiểm tra thiếu receipt, trạng thái backfill, identity, thẻ bị giữ, thời gian
  tương lai và bookmark. Kiểm tra recall vẫn cần toàn kho cue: tái sử dụng một bank
  SELECT để giữ ngân sách 5 SELECT, không bỏ kiểm tra mơ hồ để tăng tốc.
- SDK OpenAI chuyển sang lazy factory: chỉ import SDK khi thực sự tạo client cho
  lượt inference; giữ đối số timeout/retry và vị trí mock của bộ kiểm thử. Không
  bật AI, không gọi provider để đo. Regression chạy process riêng xác nhận trang
  chủ inference-off không import SDK, và factory vẫn chuyển đúng cấu hình.
- Khách chưa đăng nhập không tải gamification.css, saved-words.css, saved-words.js:
  giảm 3 tệp, 21.136 byte chưa nén (gzip ước tính 6.358 byte) ở lượt tải chưa cache.
  Trang đã đăng nhập vẫn nhận đủ tài nguyên; app.js giữ chức năng lật thẻ mẫu.

## Nghiệm thu

Regression bổ sung kiểm tra chỉ hydrate thẻ liên quan mà vẫn giữ bookmark, và
không bỏ qua cue recall mơ hồ nằm ngoài bank con do caller cung cấp. Kiểm thử
PostgreSQL M13 được giữ cùng fixture 10/1.000/5.000 phiên, 3.000 thẻ/15 từ; thêm
assert plan trả đúng 15 hàng ở SELECT hydrate bank. Bản đo mới ghi bank_rows_hydrated.

M13 đã đo bank SELECT trả 3.000 hàng; CI M14 xác nhận 15 hàng cho fixture meaning,
giảm 99,5% số hàng bank được hydrate. Đây không phải giảm 99,5% thời gian toàn trang.
Kết quả CI thực và bản đo JSON phải được ghi sau khi workflow hoàn tất.

Không tuyên bố O(1): kiểm tra receipt vẫn tăng theo metadata lịch sử. Chưa có
HTTP p95 đại diện, concurrent load hoặc benchmark latency trên Neon/Render Free.
Tối ưu mã không loại bỏ thời gian đánh thức dịch vụ của gói Free.

## Khởi tạo cục bộ: trước và sau lazy SDK

Ba process Python mới cho mỗi phiên bản, cùng môi trường, SQLite memory, AI tắt,
đo từ trước import Django tới sau GET trang chủ bằng Django Client. Median:
1.068,110 ms → 346,596 ms; peak RSS median 70.528 KiB → 43.260 KiB.
[Bản đo JSON](measurements/m14-local-startup.json) lưu cả 6 mẫu và phạm vi.
Không dùng số này làm TTFB production; Render Free còn thời gian cấp máy/thức dậy,
Neon còn kết nối/đánh thức và môi trường mạng khác. SDK vẫn có chi phí nạp lần đầu
khi inference thật được bật và được yêu cầu.

## Kết quả PostgreSQL CI

[CI run 40306276885](https://github.com/tuanlamviec007/LinguaPath/actions/runs/40306276885) đạt trên commit `57e422bed2243fe045821d43aab6d0397fe45eac`: 869 Django không skip,109 Node, migration/fixture/static/Worker/Docker và smoke CSRF/login/session sau restart.

| Phiên tổng hợp | Median read M14 (ms) | SELECT | Hàng hydrate bank |
|---:|---:|---:|---:|
| 10 | 9.759 | 5 | 15 |
| 1000 | 10.877 | 5 | 15 |
| 5000 | 15.877 | 5 | 15 |

[Bản đo JSON](measurements/m14-postgres-read.json) ghi ba mẫu và plan cho từng mốc. Cùng fixture meaning như M13: bank3.000 thẻ,15 từ; nay hydrate15 hàng thay vì3.000. Hai báo cáo CI ở các run khác nhau, không coi chênh lệch median là thử nghiệm A/B có kiểm soát hoặc p95 HTTP.

## Xác minh sau triển khai

Deploy `dep-dbfik8u7bikc73dn3q3g` live commit `57e422bed2243fe045821d43aab6d0397fe45eac`
lúc17:24:29 giờ Việt Nam ngày26/10/2026. Browser xác nhận guest homepage chỉ5 stylesheet
thay vì7, không có3 tệp tính năng riêng; app.js còn và Enter lật thẻ hiển thị nghĩa.
`/healthz/` trả ok. Không tạo tài khoản/quiz thử trên production; có ảnh trang chủ sau rollout.
