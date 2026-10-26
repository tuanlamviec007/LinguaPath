# Chi phí duy trì LinguaPath — 26/10/2026

Giá USD được kiểm tra từ nguồn chính thức ngày 26/10/2026. Đây là dự toán hạ tầng,
không phải hóa đơn tài khoản. Không nâng cấp plan hoặc mua tài nguyên trong đợt này.
Quy đổi minh họa 1 USD = 26.000 VND, không phải tỷ giá thanh toán thực tế; chưa thuế/phí thẻ.

## Cấu hình hiện có

- Render Web Service Free, Singapore, một worker Python/Django; Neon Free PostgreSQL16.
- Subdomain onrender.com và TLS do Render cấp; không bắt buộc mua tên miền.
- AI inference tắt, nên không có chi phí model do website gọi.
- Truy vấn chỉ đọc xác nhận database 20.357.120 byte (~19,4 MiB) tại thời điểm kiểm tra.
- Mẫu memory Render gần nhất khoảng 160 MB (152,6 MiB); chưa phải kết quả load test.
  HTTP count/latency metrics không có mẫu trong API của workspace, nên chưa có p95.

## Ba phương án hàng tháng

| Phương án | Web | Database | Tổng USD | VND minh họa |
|---|---:|---:|---:|---:|
| Tiếp tục thử nghiệm trong hạn mức Free | 0 | 0 | 0 | 0 |
| Web không ngủ, database còn trong hạn mức Free | 7 | 0 | 7 | 182.000 |
| Web không ngủ + Neon Launch 0,25 CU, active 8h/ngày, 1GB, 30 ngày | 7 | 6,71 | 13,71 | 356.460 |
| Web không ngủ + Neon Launch 0,25 CU, active 24h/ngày, 1GB, 30 ngày | 7 | 19,43 | 26,43 | 687.180 |

Render Starter (tên mới 0.5c-512mb) 7 USD/tháng: 0,5CPU, 512MB; workspace Hobby
không có phí cố định. Không cần workspace Pro25USD chỉ để chạy một web nhỏ có phí.
Neon Launch tính theo sử dụng: 0,106USD/CU-hour +0,35USD/GB-month. Ví dụ8h:
0,25×8×30×0,106+1×0,35=6,71USD. Ví dụ24h:0,25×24×30×0,106+0,35=19,43USD.
Không coi con số “typical spend15USD” trên bảng giá Neon là giá cố định hoặc phí tối thiểu.
Các ví dụ giả định một compute, 1GB storage, không có compute/storage/branch phụ,
không có phần history/backup/egress vượt mức hay workload tăng CU.

## Hạn mức và chi phí có thể phát sinh

- Render Free ngủ sau15 phút không truy cập; tối ưu mã không loại bỏ thời gian thức dậy.
  750 giờ instance Free/tháng dùng chung workspace. Hobby hiện có5GB outbound và
  500 phút pipeline/tháng. Outbound công khai vượt mức0,15USD/GB; build Starter vượt
  mức5USD/1.000phút. Không có phương thức thanh toán có thể bị tạm dừng khi hết quota.
- Neon Free hiện100CU-hour/tháng/project,1GB storage/project,5GB public egress/project.
  0,25CU tương đương400 giờ compute active trong100CU-hour, không phải24/7 cả tháng.
  Docs mô tả ngủ sau5phút idle; endpoint tài khoản này vẫn trả suspend_timeout_seconds=0,
  nên chưa xác minh được chính sách ngủ/đồng hồ tính phí thực tế từ API. Các usage counter
  MCP trả0 không được dùng làm bằng chứng tổng tiêu thụ/hóa đơn bằng0; cần đối chiếu Usage.
- Neon Launch public egress500GB/project đã gồm, vượt0,10USD/GB theo bảng giá hiện tại.
  History/backup/nhánh phụ có đơn giá riêng. Giữ trong dự toán khi bật thêm.
- Tên miền riêng: tùy tên/đuôi, giá mua và gia hạn của nhà đăng ký; không nằm trong bảng.
- AI/LLM, email giao dịch, lưu file upload và sao lưu ngoài hệ thống chưa được bật:
  chưa có phí hiện tại từ các chức năng đó; cần dự toán riêng trước khi bật.
- SSL hiện có không cần mua chứng chỉ riêng. Chi phí biên soạn/duyệt học liệu và
  công quản trị/bảo trì không được tính như chi phí cloud trong bảng.

## Lựa chọn phù hợp hiện tại

Tiếp tục Free cho học tập/demo khi chấp nhận cold start và theo dõi hạn mức. Nếu
chỉ muốn web ít chờ hơn, cân nhắc7USD/tháng cho web trước; database Free vẫn có thể
thức dậy và hết quota. Nếu muốn cả web/database không ngủ với tải nhỏ đã nêu,
dự trù khoảng27USD/tháng trước thuế/phí và dịch vụ phụ. Không đưa số người dùng
đồng thời tối đa khi chưa có load test; đo rồi mới tăng cấu hình.

## Nguồn chính thức

- https://render.com/docs/free
- https://render.com/docs/compute-plans
- https://render.com/articles/best-railway-alternatives
- https://render.com/docs/platform-features-by-plan
- https://render.com/docs/build-pipeline
- https://render.com/docs/outbound-bandwidth
- https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses
- https://neon.com/pricing
