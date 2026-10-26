# Áp dụng workflow CloudShop AI vào LinguaPath

Đối chiếu file `TONG_QUAN_WORKFLOW_DU_AN.md` người dùng cung cấp, ngày **24/10/2026**. Tài liệu mô tả một dự án bán hàng khác; không phải bằng chứng các dịch vụ/tốc độ trong đó đã được triển khai hoặc đo cho LinguaPath. Không sao chép endpoint ingest, bucket, group ID hoặc secrets của dự án đó.

## Nên dùng gì

| Ý trong file | Ứng dụng vào website học TOEIC | Quyết định |
|---|---|---|
| Gắn AI vào một đối tượng cụ thể | Hỏi về câu đã nộp/thẻ từ, kiểm tra quyền, gửi nguồn có phiên bản | Đã có Tutor và ngữ cảnh câu hỏi; giữ kiến trúc hiện tại |
| Grounded context | Chỉ diễn giải dựa học liệu, từ chối thiếu nguồn, giữ key/lời giải, version prompt và model | M3 đã triển khai các guard; vẫn phải chấm lời giải model thật |
| Bindings và secrets phía server | Worker gọi AI bằng binding, Django gọi bridge nội bộ có khóa; frontend không nhận credentials | Đã có; không gọi là “bảo mật tuyệt đối” |
| Analytics dashboard | Tỷ lệ quiz theo mode/mức/nguồn, lượt đầu tách lượt ôn; trạng thái từ yếu cập nhật lúc submit | M4 triển khai C07 và D07; dữ liệu chấm điểm vẫn ở DB giao dịch |
| Telemetry và correlation | Status, thời lượng, nhóm route, mã request; chẩn đoán health/5xx mà không ghi prompt/token | M4 thêm log allowlist; collector/cảnh báo thực cần cấu hình riêng |
| Streamlit + Plotly | Dashboard nghiên cứu/pilot riêng cho người có quyền, đọc dữ liệu tổng hợp đã giảm nhận dạng | Có thể làm sau; chưa cần thêm framework cho màn hình tiến độ hiện tại |
| R2 lưu object | Audio/học liệu lớn hoặc bản backup có quyền truy cập/retention rõ ràng | Thiết kế sau khi có nhu cầu và tài khoản; không tự public backup |
| Basin Pipelines + Catalog/Iceberg | Kho sự kiện phục vụ phân tích nhiều kỳ, có schema/version và giới hạn lưu | Giai đoạn sau, tùy ngân sách; không dùng như DB chấm điểm |

## Không nên sao chép nguyên xi

1. **Không chuyển Django/PostgreSQL sang D1 chỉ vì file dùng D1.** LinguaPath phụ thuộc transaction, row lock, lịch sử riêng, revision và các constraint; đổi DB/backend là một dự án migration cần kiểm chứng riêng. R2/Iceberg là kho phân tích phụ trợ, không thay nguồn giao dịch.
2. **Grounding không bảo đảm hết bịa đặt.** Không đặt nguyên dữ liệu không tin cậy vào system instructions. Giữ instructions cố định, nguồn là dữ liệu, chặn inference khi phần thiết yếu thiếu và chấm cả đáp án sai, abstention, injection, latency/chi phí bằng người chấm.
3. **Không gửi toàn bộ kho trong mỗi prompt.** Chọn đúng nguồn được phép, đóng gói có ngân sách; kho hiện có hơn 3.000 thẻ nên gửi toàn bộ vừa tốn vừa dễ lệch ngữ cảnh.
4. **Không coi quét mọi Parquet là đọc bảng Iceberg đúng.** Một bucket có thể chứa file của snapshot cũ, file đã được thay hoặc orphan. Đọc qua catalog/engine tương thích và snapshot đã chọn; không cộng tất cả file vật lý để đếm lượt.
5. **Demo HTTP POST không chứng minh clickstream tự động.** Muốn báo cáo truy cập thật phải có nguồn sự kiện thật, schema, kiểm tra quyền, chống giả/đếm trùng và định nghĩa rõ page view/session/learner. Unique IP không bằng số người; không thu IP thô/câu hỏi AI nếu báo cáo không cần.
6. **Không dùng dữ liệu trình duyệt gửi làm điểm/XP.** Từ góc analytics có thể theo dõi tương tác, nhưng thành tích chính thức phải phát từ transaction submit phía server; dùng event ID/idempotency để xử lý retry.
7. **Không hứa dưới 1 giây, không crash hoặc chịu hàng triệu request khi chưa đo.** Báo latency/phân vị/tải/chi phí của cấu hình thực. Container hiện tại giới hạn một instance và còn DB, cold start, quota AI.

## Lộ trình phù hợp

- **Hiện tại:** hoàn thành ổn định deterministic; projection từ yếu, metric phân tầng và console log an toàn. Không phát sinh dịch vụ/billing mới.
- **Trước beta:** kho pilot được chuyên môn duyệt; PostgreSQL/CI/staging, restore và rollback thực; collector/retention/alert owner được chốt; privacy export/xóa dữ liệu có quy trình.
- **Khi có nhu cầu phân tích lớn:** thêm outbox phía server trong cùng transaction, schema event v1, ID duy nhất, consumer idempotent, retry/dead-letter. Chỉ export trường cần thiết sang pipeline riêng của LinguaPath. Đây là thiết kế đề xuất, chưa có outbox hay đồng bộ Basin trong bản này.
- **Dashboard nghiên cứu:** Streamlit/Pandas/Plotly hoặc notebook trên dữ liệu tổng hợp, kiểm tra sample size và so sánh cùng nhóm/cách luyện. Không gọi thay đổi test mix là tăng năng lực và không gọi lượng dữ liệu demo nhỏ là bằng chứng Big Data.

## Đối chiếu tài liệu chính thức ngày 24/10/2026

- [Basin Pipelines](https://developers.cloudflare.com/basin-pipelines/): ingest/transform sang R2/Iceberg/Parquet, hiện ghi cần Workers Paid. Vì ưu tiên ngân sách thấp, đây là hạng mục sau chứ không phải dependency bắt buộc.
- [Basin Catalog](https://developers.cloudflare.com/basin-catalog/) và [PyIceberg](https://developers.cloudflare.com/basin-catalog/config-examples/pyiceberg/): catalog theo chuẩn Iceberg REST, dùng engine tương thích; không cần tự suy ra trạng thái bảng bằng cách list mọi object.
- [Gemma 4 26B A4B](https://developers.cloudflare.com/workers-ai/models/gemma-4-26b-a4b-it/): identifier trong file có trong danh mục Workers AI. Chưa có A/B evaluation tiếng Việt/TOEIC để đổi model mặc định của LinguaPath; không đổi chỉ từ mô tả nhà cung cấp.

Các nguồn trên xác nhận tính năng nền tảng; không chứng minh tài khoản của dự án có quyền, bucket đã tồn tại, endpoint trong file thuộc người dùng hoặc kết quả vận hành đã đạt.
