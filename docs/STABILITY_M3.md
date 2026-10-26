# LinguaPath — AI Tutor: nguồn, ngữ cảnh và quota chung

Cập nhật **24/10/2026** sau M1/M2. Đợt này xử lý A01/A03/A04/A05 trong audit và thêm số liệu ngoại tuyến cho A02. Chưa đóng điều kiện đánh giá độc lập, model thật hoặc vận hành production; không gọi API trả phí hay deploy.

## Thay đổi

| Phần | Hành vi hiện tại |
|---|---|
| Ngữ cảnh câu hỏi | Giữ nguyên đề, lựa chọn, khóa đúng, lời giải chung và từng distractor trước đoạn văn/lời thoại trong ngân sách 5.400 ký tự. Loại audio_script/transcript trùng; phần stimulus dư được trích đoạn có nhãn. |
| Nguồn không đủ | Cấu trúc lỗi hoặc phần thiết yếu quá dài trả `context_insufficient` với học liệu gốc; không đặt quota/gọi model. Nguồn legacy được ghi rõ không có bảo đảm cấu trúc; không cắt câu hỏi legacy quá dài. |
| Định tuyến | Trả nhiều ghi chú khi hỏi nhiều chủ điểm; “reading” trong câu hỏi nhiệt kế không tự thành chiến thuật đọc. Từ được trích dẫn kèm ý định tra nghĩa đi qua lexical retrieval. `question_id` luôn là ranh giới quyền, không fallback sang nguồn khác. |
| Lịch sử | Lưu source_ref có kind/ID/content/exam/hash/trạng thái duyệt, cùng provider/model/prompt/context/thời điểm. Mở lượt cũ so với nguồn hiện tại theo batch. Giữ nguyên câu trả lời, hiển thị ngày và trạng thái nguồn; GET không viết lại JSON. |
| Liên kết | Nguồn đổi vẫn có thể mở bản hiện tại với cảnh báo; nguồn thu hồi, khác kỳ thi, mất quyền hoặc thiếu phiên bản không có link mở. Liên kết tiến độ/kế hoạch cũ chỉ giữ sau kiểm tra route và học liệu hiện hành. |
| Quota | Singleton DB dùng chung cho Cloudflare, OpenAI và admin soạn nháp; đặt lượt chung/cá nhân trong cùng transaction. Không lưu prompt/IP trong ledger. |
| Giao diện | Cảnh báo lịch sử có ngày, nhãn duyệt ghi “Lúc trả lời”, trạng thái thiếu ngữ cảnh rõ ràng; duy trì nền sáng, focus và bố cục mobile. |

Hash bao gồm nội dung người học được xem và metadata nguồn/duyệt, không dựa vào timestamp cập nhật chung. Thay đổi khóa đúng hoặc lời giải phương án cũng làm nguồn cũ thành “đã thay đổi”. Không thể khôi phục wording/model của các lượt legacy thiếu metadata; không tự gán phiên bản mới cho lượt cũ.

Model Cloudflare ghi identifier Worker thực chọn, bridge cũ không báo thì để trống. OpenAI ghi identifier trong response khi có, cùng identifier yêu cầu. Đây có thể là alias, không phải chứng cứ về trọng số bất biến. `toeic-evidence-v3` và `question-essentials-v1` là phiên bản prompt/ngữ cảnh ứng dụng; bridge có phiên bản prompt riêng.

## Quota

Mặc định 20 request/tài khoản/ngày, 3/60 giây; toàn ứng dụng 200/ngày, 20/60 giây. Ngày DB theo múi giờ Django, DO Cloudflare có thêm ngày UTC. Các cửa sổ ngày và 60 giây hoạt động độc lập; quay đồng hồ ngược không cấp lại quota.

Thứ tự khóa: singleton global → User (NO KEY UPDATE khi hỗ trợ) → ledger cá nhân. Chỉ tăng cả hai khi mọi hạn mức cho phép. Lỗi provider sau khi đặt lượt vẫn tiêu lượt; DB/cấu hình lỗi bị từ chối. Biến `AI_TUTOR_GLOBAL_DAILY_LIMIT`/`AI_TUTOR_GLOBAL_MINUTE_LIMIT` được forward từ Worker vào Container. Giá trị 0 chặn request mới; `AI_TUTOR_ENABLED=false` tắt inference mới. Đây là **giới hạn request, không phải trần hóa đơn**.

## Đánh giá ngoại tuyến

Kho kiểm tra: **3.056 flashcard visible**, không dùng lịch sử người học hay gọi model. Báo cáo JSON lưu corpus/code/fixture fingerprints để tái lập.

| Phép đo | Kết quả |
|---|---|
| Bộ hồi quy router mới | 16/16 exact source sets; phủ 14/14 nguồn kỳ vọng; 4/4 ca âm từ chối |
| Benchmark lexical v2 — dev | Recall@3 30/40 = 75%; từ chối ca âm 3/8 |
| Benchmark lexical v2 — test đã mở trước đây | Recall@3 27/40 = 67,5%; từ chối ca âm 2/8 |
| Lexical v2 — toàn bộ | Recall@3 57/80 = 71,25%; từ chối 5/16 ca âm; paraphrase 2/20 = 10% |

Router fixture là **AI-editorial regression**, viết theo router/kho đã biết; không phải holdout độc lập hoặc nhãn do giảng viên xác nhận. V2 cũng đã mở test trước đợt này. Không chỉnh lexical scoring theo tập test trong đợt này; nguồn metadata và packing được bổ sung. Router vẫn là heuristic và có thể hiểu sai “reading” ngẫu nhiên nếu câu có từ chỉ học/luyện. Không suy ra độ đúng lời giải LLM, hiệu quả học hoặc khả năng hiểu ngữ nghĩa từ các con số trên.

```bash
python manage.py evaluate_tutor_router --output /tmp/tutor-router.json
python manage.py evaluate_retrieval --benchmark-version 2 --include-test --output /tmp/retrieval-v2.json
```

Xem `tutor_router_evaluation.json` và `retrieval_evaluation_v2.json`. Chỉ mở test cũ để báo cáo; vòng tinh chỉnh tiếp theo cần tập đánh giá mới và người chấm độc lập.

## Nâng cấp

Giữ database và cấu hình riêng trên máy triển khai, backup trước khi chạy:

```bash
python manage.py check
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py check_schema
python manage.py collectstatic --noinput
```

Migration **0020_global_tutor_usage_budget** chỉ thêm bảng quota; metadata lịch sử dùng JSON hiện có. DB làm việc đã backup rồi migrate, integrity/FK check đạt. Row counts các bảng học liệu và học tập giữ nguyên; chỉ thêm bảng rỗng và metadata/4 permission chuẩn của Django. Giữ 3.056 flashcard, 5.138 câu hỏi và 429 bộ xuất bản ở language_checked, 0 bộ teacher_approved. Không seed lại hoặc tự chuyển trạng thái duyệt. Source ZIP không chứa database, backup hoặc credentials.

## Kiểm tra và giới hạn

Kiểm tra cuối: **545 Django tests — 538 đạt, 7 PostgreSQL-only skip trên SQLite; 88/88 JavaScript tests đạt**. System check, migration drift, pip check và collectstatic đạt. Worker bundle dry-run thành công với `containers-rollout=none`; không deploy/build container.

Kiểm tra thêm bằng nguồn thật hiện xuất bản, chỉ đọc DB: cả 32 nguồn câu hỏi dài hơn 1.800 ký tự đều đóng gói được trong 5.400 ký tự và giữ đủ đề/lựa chọn/lời giải phương án. q1206: nguồn mới dài 4.109 ký tự, payload 2.743 ký tự sau loại lời thoại trùng, phần thiết yếu và stimulus đều đầy đủ. Đây là kiểm tra đầu vào, không gọi/chấm model.

Browser QA dùng template thật render từ DB memory cô lập: current/stale/withdrawn/legacy/context_insufficient; nguồn thu hồi/legacy không có link, cảnh báo có ngày. Iframe rộng 375 px không tràn ngang. Đây là kiểm tra giao diện tĩnh, không phải browser–Django E2E; chưa chạy screen reader/điện thoại thật.

Chưa có model inference thật, PostgreSQL concurrency thật, Docker build/run hoặc Cloudflare deployment. Test concurrency PostgreSQL-only được giữ trong suite và CI, skip khi chạy SQLite. Vẫn cần bộ học liệu pilot được chuyên môn duyệt, đánh giá model có người chấm, staging, backup/restore và kiểm tra proxy thực tế trước beta.
