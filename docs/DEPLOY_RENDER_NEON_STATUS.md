# Trạng thái triển khai Render + Neon — 26/10/2026

**Chưa có website production được xác nhận.** Nhánh triển khai là bản chuẩn bị,
không được coi là release sẵn sàng khi còn thiếu snapshot học liệu đã được phép tải lên.

## Đã hoàn thành

- Xác minh repository `tuanlamviec007/LinguaPath`, nhánh main tại commit
  `8442362e40bfdf433adc1418c9980e1724f82227` trước thay đổi.
- Thêm cấu hình một Render Web Service plan free, Python 3.12, Singapore.
- Tạo Neon project `LinguaPath`, PostgreSQL 16, Singapore trên tổ chức Free;
  project ID `flat-sun-74939022`, branch production `br-fancy-truth-azceaiwp`.
- Truy vấn read-only qua Neon xác nhận PostgreSQL 16.15, 0 bảng public trước migration.
  Chưa migrate hoặc nhập học liệu lên database này.
- Chuẩn bị snapshot chỉ học liệu, không có người học hoặc secret; bảo toàn trạng thái giữ/nháp.
- 865 kiểm thử Django: 857 đạt, 8 PostgreSQL-only chưa chạy tại môi trường cục bộ.
- 10 kiểm thử mới cho bootstrap, chống ghi đè, rollback, model allowlist, settings/health.
- Nhập đầy đủ và chạy lại bootstrap trên database memory riêng đạt; không đụng DB chính.
- Blueprint đạt schema JSON chính thức; syntax shell và migration drift đạt.

## Điều kiện còn thiếu

1. Render trả về workspace `My Workspace` của tài khoản đã kết nối nhưng chưa có workspace
   được người dùng xác nhận. Theo yêu cầu công cụ Render, chưa tạo dịch vụ trong workspace này.
2. Automatic approval review từ chối tải snapshot học liệu đầy đủ lên GitHub công khai
   vì chưa có chấp thuận rõ cho việc công bố dữ liệu tới repository đó.
   `initial_content.json.gz` chưa được đưa lên GitHub. Mã bootstrap cố ý báo lỗi nếu
   chưa có snapshot; không phục vụ kho rỗng hoặc tạo dữ liệu thay thế để giả thành hoàn tất.
3. Chưa chạy build/deploy Render, nghiệm thu HTTPS/CSRF/session, restart hoặc PostgreSQL
   concurrency. Kết nối TCP từ môi trường cục bộ tới Neon chưa thực hiện được;
   truy vấn qua kết nối Neon thành công không thay cho kiểm thử Django với PostgreSQL.
4. Chưa xác minh được cấu hình tự ngủ của compute qua tài khoản này: API trả timeout 0;
   yêu cầu đặt khoảng ngủ khi tạo ban đầu bị dịch vụ từ chối. Không tự nâng cấp plan.
5. AI inference vẫn tắt; không phát sinh yêu cầu model hoặc tự bật dịch vụ mới.

Nhánh chuẩn bị giữ nguyên sửa Docker/chmod/LF trên main. Startup được đổi về gate rồi
Gunicorn; migrate và bootstrap chuyển sang build đã mô tả, bỏ auto-seed lặp mỗi restart.
Không thay đổi logic học, quiz, SRS hoặc đánh giá nội dung của người học.
