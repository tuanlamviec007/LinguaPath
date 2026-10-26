# M13 — Giao diện Daylight và kiểm tra D07 trên PostgreSQL

Ngày 26/10/2026. Tiếp tục từ bản Render + Neon đã live; không thay đổi schema,
logic chấm quiz, lịch SRS hoặc trạng thái duyệt học liệu. AI inference tiếp tục tắt.

## Giao diện

Thay bảng màu dùng chung bằng nền trắng/xanh rất nhạt, nút xanh dương, điểm nhấn
lilac và vàng nhạt. Trang chủ, đăng nhập/đăng ký, dashboard, flashcard, quiz, sổ từ,
sidebar và các form dùng cùng bảng màu. Thẻ giới thiệu nền xanh đậm được đổi thành
nền pastel. Giữ chữ đủ đậm để đọc, focus outline, giao diện mobile và reduced-motion.

Tỷ lệ tương phản đo bằng công thức relative luminance sRGB, trước nghiệm thu trình duyệt:

| Cặp màu | Tỷ lệ |
|---|---:|
| Chữ trắng / nút #4162d9 | 5,28:1 |
| Tiêu đề #2e3e60 / nền #fafcff | 10,35:1 |
| Điểm nhấn #4162d9 / nền #fafcff | 5,14:1 |
| Chữ phụ #63718a / trắng | 4,93:1 |
| Link #4162c5 / thẻ #edf5ff | 5,06:1 |
| Nhãn form #495e82 / trắng | 6,55:1 |
| Viền input #8393b1 / trắng | 3,10:1 |

Các cặp chữ trên đạt 4,5:1; viền input đạt 3:1 cho thành phần phi văn bản; đây không phải tuyên bố toàn website đạt WCAG hoặc
đã được kiểm tra bằng screen reader/điện thoại thật.

## D07: kiểm tra đọc projection trên PostgreSQL

`learning/test_weak_word_postgres_plans.py` bổ sung một kiểm thử riêng PostgreSQL
trong database test do Django tạo. Các mốc 10, 1.000, 5.000 phiên lịch sử, kho 3.000
thẻ và 15 từ sai được tạo tổng hợp; mỗi snapshot có ngữ cảnh dài. Dữ liệu mô phỏng
projection đã dựng, không dùng database production hay tài khoản người học.

Mỗi mốc đo 3 lượt, kiểm tra đúng 5 SELECT, không chọn snapshot/answers/draft_answers,
trả đủ 15 từ và số lần sai. Chạy EXPLAIN ANALYZE BUFFERS FORMAT JSON cho từng SELECT;
log chỉ xuất loại node, số hàng, số block và thời gian, không xuất SQL hoặc dữ liệu.
Không đặt ngưỡng mili-giây dễ nhiễu trong CI. Không ép planner chọn index.

Kết quả PostgreSQL phải lấy từ CI thực trên commit tương ứng. Chạy cục bộ SQLite
skip kiểm thử này rõ ràng, không coi skip là bằng chứng PostgreSQL.
Đây là phép đo read path tổng hợp; chưa đo load đồng thời, rebuild throughput,
Neon Free latency, toàn bộ trang HTTP hoặc restore/rollback production.

## Các mục còn mở

U01 vẫn cần screen reader và thiết bị thật. D07 vẫn cần tải đồng thời và workload
đại diện; chỉ ghi nhận phần query-plan/read scaling sau CI thực đạt. C01/C05 và
placement/mastery cần người đủ chuyên môn, dữ liệu pilot; không tự teacher-approve.

## Kết quả CI thực

[CI run 40301521253](https://github.com/tuanlamviec007/LinguaPath/actions/runs/40301521253) đạt toàn bộ trên commit `6f59576a48c64cd60aee3791070cfd0ac57cede2`: 866 kiểm thử Django (không skip), 109 Node, migration/static/Worker dry-run/Docker và smoke CSRF/login/session sau restart.

| Số phiên tổng hợp | JSON snapshot logic | SELECT | Median đọc (ms) | Thời gian kiểm tra receipt trong EXPLAIN (ms) |
|---:|---:|---:|---:|---:|
| 10 | 308010 byte | 5 | 173.378 | 0.039 |
| 1000 | 30801000 byte | 5 | 88.327 | 1.254 |
| 5000 | 154005000 byte | 5 | 94.127 | 5.976 |

[Bản đo JSON](measurements/m13-postgres-read.json) ghi ba mẫu và chỉ số plan. Không chọn cột payload ở cả ba mốc. Truy vấn kiểm tra thiếu receipt vẫn duyệt metadata lịch sử: shared-hit blocks tăng 5 → 3.175 → 15.860; không được mô tả toàn read path là O(1). Kho 3.000 thẻ được đọc ở mỗi lần; cần workload đại diện trước tối ưu tiếp. Các mẫu có nhiễu CPU/cache, không dùng làm cam kết latency hoặc kết luận nhanh hơn bản cũ.

## Nghiệm thu website sau rollout

Render đã live commit `6f59576a48c64cd60aee3791070cfd0ac57cede2` ngày 26/10/2026,
16:49:26 giờ Việt Nam. Trình duyệt thật xác nhận nền #fafcff, nút #4162d9,
thẻ giới thiệu pastel; ô nhập trắng với viền #8393b1. Skip-link chuyển focus tới
main; Enter lật thẻ và cập nhật vùng mặt sau được truy cập. Form đăng ký hiển thị
và `/healthz/` trả ok. Đã lưu ảnh trang chủ sau rollout; không đăng nhập/tạo dữ liệu
thử trên production. Thiết bị thật, screen reader và tải đồng thời vẫn chưa nghiệm thu.
