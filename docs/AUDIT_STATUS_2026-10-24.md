# Trạng thái thực hiện audit LinguaPath

Đối chiếu **33 mã phát hiện** trong `AUDIT_PLAN_2026-10-23.md`, cập nhật **26/10/2026** sau M1–M14 và triển khai Render + Neon. **Chưa hoàn tất toàn bộ audit.** “Đã sửa cục bộ” là có mã và regression đạt, không thay cho các điều kiện PostgreSQL, thiết bị thật, chuyên môn hoặc production ghi riêng.

| Mã | Trạng thái | Bằng chứng / việc còn lại |
|---|---|---|
| D01 | Đã sửa cục bộ · M1 | Snapshot practice/answer bất biến; legacy nói rõ thiếu bản gốc. |
| D02 | Đã sửa cục bộ · M1 | CAS revision practice/mistake review, conflict 409, idempotent submit; bộ PostgreSQL concurrency đã chạy và đạt trong CI 40294128144. |
| D03 | Đã sửa cục bộ · M1 | Timeout 15 giây, dirty state, BFCache và save/submit sequencing. |
| D04 | Đã sửa cục bộ · M1 | Early Hard không đẩy lịch/khoảng ôn xa; giữ relearning Again. |
| D05 | Đã sửa cục bộ · M1 | Giữ task done, trừ phút đã học, chỉ replan khi trường liên quan đổi. |
| D06 | Đã sửa cục bộ · M1 | SQL aggregate, order/pagination/link practice history. |
| D07 | M14 giảm hydrate; load thực còn mở | CI 40306276885, 10/1.000/5.000 phiên meaning: 5 SELECT, hydrate15 thẻ liên quan thay vì3.000, không chọn payload; EXPLAIN ANALYZE BUFFERS. Recall giữ toàn cue để chặn mơ hồ. Receipt vẫn quét metadata; chưa load đồng thời/Neon thực. Xem PERFORMANCE_M14.md. |
| S01 | Đã triển khai · M2; proxy thực chưa nghiệm thu | DB auth quota sau CSRF, fail closed, không khóa username toàn cục. Cần xác minh peer/header/IP thật ở Cloudflare. |
| S02 | Đã sửa cục bộ · M2 | Import kiểm tra quyền parent và khóa nhất quán; Bộ PostgreSQL lock tests đã chạy và đạt trong CI 40294128144. |
| S03 | Đã triển khai cục bộ · M2/M4; lifecycle ngoài DB còn mở | private/no-store; privacy center xuất/xóa có mật khẩu, CSRF, quota, giới hạn export và ownership. Retention backup/provider/log hạ tầng cần cấu hình vận hành. |
| C01 | M5/M6 có công cụ duyệt; chưa nghiệm thu chuyên môn | Workspace admin, phiếu mẫu20 thẻ/24 câu; M9 có phiếu v2 chứa trạng thái tạm giữ và ưu tiên thẻ cần rà; có biểu mẫu ghi nhận xét và đối chiếu nguồn/annotation khi mở lại;0 bộ teacher_approved. Cần người duyệt đủ chuyên môn, kết luận từng item; agent không tự phê duyệt. |
| C02 | Đã chặn prompt mơ hồ · M2 | Loại 4 nhóm/8 thẻ trùng cue toàn kho; không fuzzy nhận synonym; vẫn cần biên tập/human review. |
| C03 | Đã sửa và tạm giữ nguồn lỗi · M9 | Sau backup/migration0022: sửa #778 và lời giải sao chép #706; giữ riêng thẻ778, parent3 vẫn xuất bản999 thẻ khả dụng. Bộ45 gồm20 câu về nháp chờ rà lại. Không tự duyệt/mở lại; lịch sử giữ nguyên. |
| C04 | UI rõ giới hạn · M4; calibration còn mở | Ước lượng vốn từ/chọn mức dễ hơn/làm lại; chưa có bank riêng hoặc thống kê pilot hiệu chuẩn. |
| C05 | M5/M6 có kiểm kê/blueprint/luồng nhận xét; chưa hoàn tất nội dung | Báo cáo rawmetadata/gaps và blueprint lô A2/B1, chưa là blueprint chính thức. Vẫn cần thay ví dụ chung, thêm lô được người duyệt; không tự tăng teacher_approved. |
| C06 | M10 có cách luyện/ghi nhận; pilot còn mở | Gõ từ đến lịch ôn với mốc tự đánh giá ≥24 giờ, snapshot/receipt riêng, loại nguồn hoặc mốc đổi, retry tách riêng. Nhãn self-rating rõ hơn; không suy luận nhớ không gợi ý và không đổi quy tắc80%/SRS/CEFR. Cần người duyệt, thiết kế và pilot thực trước đổi mastery. |
| C07 | Đã triển khai cục bộ · M4 | Nhóm mode/mức chọn/nguồn, trọng số số câu, lượt ôn tách riêng; không diễn giải test mix là năng lực. |
| A01 | Đã sửa cục bộ · M3 | Ưu tiên key/lời giải, loại transcript trùng, fail closed thiếu cấu trúc; kiểm tra 32 nguồn dài. |
| A02 | M11/M12 có lexical/ứng viên; chưa nghiệm thu | Cùng kho3.055 thẻ và regression v2 đã biết:Recall@3 57→61/80, ca âm5→16/16; paraphrase2→1/20 là đánh đổi. Thêm nhãn nguyên văn nghĩa/ambiguity, mẫu số riêng và CLI an toàn; bộ12 ca mới là regression dev, không phải holdout. M12 có mode mô tả riêng trả tối đa3 ứng viên để chọn, không gọi AI; mới2/20 ca paraphrase có ứng viên đúng trong regression đã biết, không đổi luồng auto. Cần nhãn/người chấm độc lập và truy xuất theo nghĩa tốt hơn. |
| A03 | Đã sửa các ca audit · M3/M11 | Giữ nhiều ghi chú, sửa What-is/định nghĩa Việt, trích đúng mục từ, chặn từ tình cờ cả trong ngoặc kép ở yêu cầu dài; ngữ cảnh nghĩa yếu hỏi lại trước quota. Heuristic vẫn có giới hạn, cần tập intent mới độc lập. |
| A04 | Đã triển khai cục bộ · M3 | Source version/model/prompt/context/date, revalidate current/stale/withdrawn/legacy; giữ lịch sử bất biến. |
| A05 | Đã triển khai cục bộ · M3 | DB global reservation cả provider/admin; DO lớp thêm; PostgreSQL concurrency đạt trong CI 40294128144, chưa benchmark model thật. |
| A06 | M7 có runner/phiếu chấm; chưa nghiệm thu | Chạy pipeline offline, snapshot context/version, CLI live cap1–10 qua quota hiện hành và phiếu chấm bound theo run đã có test. Chưa gọi/chấm model thật, chưa có bounded pilot với người chấm độc lập. |
| U01 | M13 đổi theme, kiểm tra tương phản; thiết bị còn mở | Nền trắng/pastel xanh dương; chữ chính đo ≥4,5:1, viền input ≥3:1, giữ focus/reduced-motion. Chưa tuyên bố toàn website đạt WCAG; screen reader/điện thoại thật còn mở. |
| U02 | Đã sửa cục bộ · M2 | Rating flashcard giữ filter/page/context, allowlist redirect. |
| U03 | Đã sửa cục bộ · M2 | Đổi nguồn quiz giữ mode/level/topic/count, có no-JS hướng dẫn. |
| O01 | Render live; CI smoke đạt; vận hành còn mở | HTTPS/trang chủ/form/health đã kiểm tra trên Render + Neon. CI PostgreSQL/Docker/CSRF/login/cookie/session sau restart đạt. Chưa auth/quiz/restart production, backup/restore PostgreSQL, load, rollback biên bản hoặc Cloudflare staging. |
| O02 | Repository/CI thực đã đạt | GitHub tuanlamviec007/LinguaPath; CI 40306276885 trên 57e422be:869 Django PostgreSQL,109 Node, migration/static/Worker dry-run/Docker/runtime smoke đạt. Render đã live M14 tại57e422be, auto-deploy vẫn tắt; biên bản trong DEPLOY_RENDER_NEON_STATUS.md. |
| O03 | Đã sửa cục bộ · M1/M4/M8 | Tách livez/healthz; startup bắt buộc check_release cho config production/schema/projection trước Gunicorn. Có test chặn khởi động khi gate lỗi; không tự migrate/backfill. |
| O04 | Mã log/runbook có · M4; collector còn mở | UUID và allowlist/redaction Django/Gunicorn/Worker, probe/ngưỡng đề xuất. Chưa collector/retention/alert owner/delivery. |
| O05 | Lock/hash, build/run Docker đã đạt; digest còn mở | 25 package Linux/Python3.12; hash install, Docker build và runtime smoke đạt trong CI 40294128144. Chưa pin base/service image digest. |
| O06 | Đã sửa · M1 | Một lệnh aggregate chạy mọi scripts/test_*.cjs và Django suite, dùng trong CI. |
| G01 | Đã có giải thích/đường quay lại · M4 | Script-only Listening vẫn không vào retry DTO; sổ lỗi giải thích và link bài gốc/TTS khi có script. |

## Công việc kế tiếp

1. Giữ regression đầy đủ cho các thay đổi M4 và thực hiện migration/backfill/gate theo tài liệu khi nâng cấp máy khác; giữ bản sao dữ liệu trước thay đổi schema.
2. Giữ CI PostgreSQL/Node/Docker đang đạt; đo plan/load D07, xác minh ingress và diễn tập auth/quiz/restart/restore/rollback trên môi trường phù hợp.
3. Chọn bộ pilot và mời người đủ chuyên môn duyệt C01/C05; chuẩn bị nhãn sense/intent/negative độc lập A02, sau đó chấm model A06 có ngân sách.
4. Chốt mastery nhớ trễ/placement calibration từ dữ liệu pilot; không thay bằng tự nhận CEFR từ XP hoặc self-rating.
5. Chốt người vận hành, collector/retention/cảnh báo, restore/rollback và privacy lifecycle ngoài DB hiện hành.

Các mục cần tài khoản/hạ tầng/người duyệt được giữ mở có chủ đích. Repository và URL Render đã được xác minh; xem [biên bản triển khai](DEPLOY_RENDER_NEON_STATUS.md). Giảng viên và ngân sách inference không được tự tạo/giả định. Ý tưởng Big Data/Streamlit từ file người dùng được đánh giá trong `CLOUDSHOP_WORKFLOW_APPLICABILITY.md`; không cài dịch vụ tính phí hoặc gửi dữ liệu tới endpoint demo.
