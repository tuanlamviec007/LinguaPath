# LinguaPath — đánh giá câu trả lời Tutor M7

Cập nhật **25/10/2026**. Bổ sung công cụ chạy pipeline trả lời, giữ snapshot nguồn/ngữ cảnh và chuẩn bị phiếu chấm của con người. **Chưa nghiệm thu A02/A06:** chưa có tập holdout độc lập, chưa gọi hoặc chấm model thật trong đợt này. Không có migration mới, không thay retrieval scorer hoặc nâng trạng thái duyệt học liệu.

## Chạy ngoại tuyến

```bash
python manage.py evaluate_tutor_answers --output /tmp/tutor-run.json
python manage.py review_tutor_answers --run /tmp/tutor-run.json --output /tmp/tutor-scorecard.json
# Sau khi người duyệt thực sự điền phiếu:
python manage.py review_tutor_answers --run /tmp/tutor-run.json --scorecard /tmp/tutor-scorecard.json --output /tmp/tutor-human-summary.json
```

Mặc định dùng16 ca trong `learning/data/tutor_router_regression_v1.json`: bộ hồi quy AI biên tập đã biết từ M3, **không phải holdout mới hoặc nhãn do người chấm độc lập**. Có thể truyền `--cases` trỏ tới fixture do người chịu trách nhiệm đánh giá cung cấp. Định dạng fixture giữ nguyên version/provenance và danh sách case có id,category,query,expected; expected chỉ hỗ trợ knowledge_id hoặc headword flashcard, chưa chấm đúng sense. Giới hạn1MiB,1–50 ca, query tối đa500 ký tự; từ chối ID trùng, khóa JSON trùng, số không hữu hạn và trường lạ. Đây không phải luồng xuất lịch sử người học.

Mỗi ca chạy `answer_tutor_question` thật với `use_ai=False` và `public_context_only=True`: không dùng tài khoản, lịch sử câu đã nộp, quota hoặc provider. Công cụ ghi câu trả lời, nguồn đã trích dẫn, generation metadata, thời gian toàn pipeline, snapshot nguồn đã truy xuất và bản context được pack trong chính lần gọi. Các snapshot có hash. Observer nhận bản sao, không sửa được ngữ cảnh thực; khi có inference, pack đã quan sát được tái sử dụng cho lời gọi model.

Ở chế độ không inference hoặc khi quota/provider chặn, bản packed context chỉ là ngữ cảnh đã chuẩn bị, **không phải bằng chứng đã gửi model**. `needs_context`/`no_match` có thể không có packed context. Báo cáo phân biệt mode và số lần gọi suy từ mode; không tự coi mỗi ca là một lời gọi model. Không ghi token sử dụng, chi phí hoặc model identity khi provider không cung cấp thông tin đó.

## Kết quả chạy kèm gói nguồn

- `tutor_answer_evaluation_m7.json`:16 ca,0 lỗi;12 `retrieval_only`,4 `no_match`; khớp định danh nguồn16/16, phủ14/14 nguồn kỳ vọng, abstention4/4 ca âm tính. Chỉ là kiểm tra cấu trúc/luồng trả lời trên bộ hồi quy đã biết, không phải độ chính xác ngôn ngữ hoặc khả năng chống prompt injection của model.
- `tutor_scorecard_m7.json`:16 phiếu với80 tiêu chí, tất cả để trống cho người duyệt thực sự. Không điền tên/chuyên môn hoặc kết luận thay con người.
- `tutor_human_summary_m7.json`:0 phiếu hoàn thành,16 còn chờ;0 câu trả lời model thật. Không có phê duyệt phát hành.

Thời gian trong báo cáo ngoại tuyến là đo tại máy chạy hiện tại, gồm truy xuất/pack/observer. Mẫu nhỏ, không có warm-up/load test; không dùng median/p95 này làm latency inference hoặc SLO production. Hash canonical fixture ghi dữ liệu đã nạp; hash file/mã nguồn kèm theo giúp đối chiếu phiên bản, không phải chữ ký hay snapshot khóa filesystem/DB khi đang biên tập đồng thời.

## Chạy pilot có model khi đã có điều kiện

```bash
# Chỉ do người vận hành thực hiện với fixture nhỏ đã chọn và tài khoản staff thật:
python manage.py evaluate_tutor_answers --cases /path/to/pilot-cases.json --live --user-id STAFF_ID --max-live-calls 3 --output /tmp/tutor-live-run.json
```

Thay STAFF_ID bằng ID của staff active hiện có. Live chỉ cho1–10 ca và toàn bộ số ca phải nằm trong cap; bộ mặc định16 ca sẽ bị từ chối trước mọi inference. Thiếu `--live` mà có user/cap cũng bị từ chối để tránh hiểu nhầm. Không tự tạo tài khoản hoặc sửa quyền. Ngữ cảnh vẫn chỉ công khai, kể cả khi staff có lịch sử làm bài riêng; tài khoản chỉ dùng đặt quota. Đây là phạm vi **Tutor công khai**, chưa đánh giá riêng lời giải câu Reading/Listening đã nộp hoặc tool dữ liệu cá nhân.

Live đi qua quota per-user/global hiện hành, kill switch và cấu hình provider. Không retry, sleep chờ quota, nới hạn mức hay tạo ledger đánh giá riêng. Cap là trần số yêu cầu pipeline có thể dẫn tới inference, không phải trần hóa đơn/token. Với quota phút hiện tại, các ca sau có thể `budget_limited`; điều đó phải được giữ trong báo cáo, không gọi là đã đánh giá model cho các ca đó. Lỗi provider dùng fallback và vẫn tính lượt đã đặt như luồng thường.

Chưa chạy lệnh live trong phiên này. Người vận hành cần cấu hình hạ tầng/provider và chọn phạm vi/ngân sách trước khi thực hiện.

## Chấm bởi người duyệt

Phiếu gắn với SHA256 canonical của **toàn bộ run**, gồm câu trả lời, context, metadata và thời gian; thay run thì không dùng lại phiếu cũ. Kiểm tra cả hash nội bộ snapshot nguồn trước tạo/chấm phiếu. Hash không xác thực người tạo run hoặc người duyệt. Không sửa các trường version/run_sha256/template/labels/case_id, thêm/bớt hoặc đổi thứ tự ca trong phiếu.

Mỗi ca có tên người duyệt, chuyên môn/vai trò tự khai và ngày ISO; tiêu chí: đúng nội dung (`correctness`), bám nguồn (`grounding`), rõ ràng (`clarity`), biết hỏi thêm/từ chối khi thiếu nguồn (`abstention`), chống chỉ dẫn trái nhiệm vụ trong dữ liệu (`injection_resistance`). Kết quả `pass`/`fail`/`not_applicable` hoặc null khi chưa chấm. Fail/không áp dụng phải có lý do; correctness/clarity không được bỏ qua, grounding của câu `llm_rag` cũng phải được đánh giá. Muốn nghiệm thu injection phải có bộ ca tấn công phù hợp, không đánh dấu đạt chỉ vì chạy bộ mặc định.

Tổng hợp tách theo mode và câu `llm_rag`, đếm lỗi/ca chưa chấm/ca đã đủ trường/ca có tiêu chí fail. Một phiếu có nhận xét fail đầy đủ vẫn là **đủ trường**, không phải chất lượng đạt. Ca lỗi không có câu trả lời không thể được chấm thành công. Báo cáo tổng hợp không chép tên/chuyên môn/ghi chú người duyệt hoặc nguyên văn câu trả lời. `release_approval`, `reviewer_identity_verified`, `independent_holdout_verified` luôn false. Không tự cấp điểm chuyên môn, phê duyệt hoặc tự suy ra model đạt từ source coverage.

Các command ghi JSON nguyên tử, không ghi đè khi chưa có `--overwrite`, chặn ghi lên input/symlink/hardlink hoặc thư mục mã ứng dụng. Output cần thư mục đã tồn tại và tối đa20MiB. Run lỗi từng ca vẫn lưu lỗi đã lược nội dung nhạy cảm rồi trả exit code khác0; sai định danh nguồn được báo cáo nhưng không tự coi là chấm ngôn ngữ fail. Phiếu không hợp lệ không ghi đè báo cáo cũ.

## Kiểm tra và điều kiện còn mở

**698 Django tests:690 đạt,8 PostgreSQL-only skip;103/103 JavaScript tests đạt.** Thêm48 tests Django cho runner/CLI, observer công khai và phiếu chấm: kiểm tra cap/quota, không gọi provider khi offline, tách lịch sử riêng, đa nghĩa, snapshot/hash, kết luận fail, input lỗi và ghi file nguyên tử. System/schema/projection check và migration drift đạt. Không đổi giao diện/Worker nên không phát sinh kiểm tra browser hoặc Worker build trong đợt này. Cả36 bảng DB chính khớp M4 checkpoint và integrity_check OK. Vẫn cần nguồn nhãn độc lập A02, người duyệt có chuyên môn, pilot model thật A06, PostgreSQL/concurrency/Cloudflare staging và các mục vận hành trong bảng audit. Không có thay đổi dữ liệu chính hoặc deployment trong đợt này.
