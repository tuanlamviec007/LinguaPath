# LinguaPath — truy xuất Tutor và đo theo nghĩa M11

Cập nhật **26/10/2026**. Cải thiện nhận diện yêu cầu tra từ, làm rõ nghĩa khi ngữ cảnh yếu và bổ sung nhãn nghĩa cho công cụ đánh giá. **Không có migration mới**; bản cài M10 tiếp tục dùng schema0023. Không seed lại, không cài dịch vụ/vector database, không gọi model hoặc gửi dữ liệu ra ngoài.

## Hành vi mới

- Nhận câu hỏi định nghĩa có/không có ngoặc kép theo mẫu What-is, các mẫu tiếng Việt và yêu cầu tra/phát âm rõ ràng. Không mở rộng What-is thành chấp nhận mọi câu hỏi thực tế như “What is the best bank ...”.
- Tách từ/cụm từ được yêu cầu khỏi câu ví dụ có ngoặc kép. Dấu nháy trong `manager's agenda` được giữ đúng; hỗ trợ ngoặc thẳng/cong. Cụm từ trích dẫn phải khớp toàn bộ, không tự thay bằng một từ con hoặc một từ tình cờ xuất hiện ở phần ngữ cảnh. Các mục từ trích dẫn liền nhau qua và/and có thể cùng được yêu cầu.
- Từ trích dẫn không có nguồn không tự rơi xuống nghĩa khác trong phần ngữ cảnh. Với câu dài xin lời khuyên hoặc miêu tả, từ trùng trong ví dụ/nghĩa không đủ để trả flashcard; điều này áp dụng cả từ tình cờ đặt trong ngoặc kép. Tra thư viện ngắn và yêu cầu tra rõ ràng vẫn dùng được.
- Nhiều nghĩa/biến thể nguồn của cùng mục từ không còn chỉ hỏi lại khi điểm hòa tuyệt đối. Một vài từ trùng trong ví dụ không đủ chọn nghĩa. Bộ lọc chỉ chọn một nghĩa khi có token nghĩa/chủ đề phân biệt và chênh điểm ít nhất6, hoặc người học chọn nguyên văn nghĩa qua mẫu làm rõ. Đây là heuristic bảo thủ, chưa hiệu chuẩn xác suất/độ tin cậy.
- Khi đã chọn nghĩa, bỏ các nghĩa cạnh tranh của cùng mục từ khỏi evidence gửi model. Khi chưa đủ ngữ cảnh, giữ các lựa chọn và trả `needs_context` trước quota/provider; không dùng lượt AI. Khóa nghĩa dùng Unicode NFC/casefold/tokens, giữ khác biệt dấu tiếng Việt, tránh gộp `ma` với `má`. Mẫu chọn nghĩa nguyên văn cũng giữ phân biệt này.

Luồng câu hỏi theo ID vẫn yêu cầu bài đã nộp của chính người học, kiểm tra kỳ thi/xuất bản/review; ID sai hoặc không được phép không rơi sang tìm chung. Nguồn held vẫn bị loại. Không đổi prompt/model/quota, không sửa lịch sử Tutor hoặc tự duyệt học liệu. Đây là sửa heuristic, không phải tìm kiếm ngữ nghĩa bằng embedding; các câu diễn đạt khác mẫu có thể bị bỏ sót.

## Công cụ đánh giá

Các nhãn cũ `expected_terms` vẫn giữ ý nghĩa đo mục từ. Có thể thêm:

```json
{
  "id": "finance-bank",
  "split": "dev",
  "category": "sense",
  "query": "What does “bank” mean in finance?",
  "expected_terms": ["bank"],
  "expected_senses": [{"term": "bank", "meaning_vi": "ngân hàng"}],
  "ambiguity_required": false
}
```

`expected_senses` khớp cặp mục từ/nguyên văn nghĩa nguồn bằng NFC, casefold và khoảng trắng. Giữ dấu và dấu câu, không chấp nhận synonym tự động. Nhãn tùy chọn cần dương, không rỗng/trùng hoặc có trường lạ, mục từ phải thuộc nhãn gốc. `sense_recall_at_3`, `sense_hit_at_3`, `sense_mrr_at_3` chỉ tính trên `sense_labeled_queries`; không có nhãn thì là null. Sai nghĩa có thể đạt Recall mục từ nhưng không đạt Recall nghĩa. Metric này không chấm đúng/sai ngôn ngữ của nhãn nguồn.

`ambiguity_required` đo riêng cờ hỏi lại của kết quả đầu, có mẫu số `ambiguity_labeled_queries`; không thay cho chấm nghĩa/câu trả lời. Không có kết quả đầu không được tính là quyết định đúng cho nhãn false. Nhãn câu hỏi vẫn do người biên tập chịu trách nhiệm; schema hợp lệ không xác minh người duyệt hoặc biến bộ ca thành holdout.

Lệnh `evaluate_retrieval` nhận `--benchmark-file` hoặc `--benchmark-version 1|2` (mặc định1); mặc định chỉ chạy dev. Tối đa1 MiB,200 ca,500 ký tự/truy vấn. Đọc bản byte cố định trước validate/hash, từ chối JSON trùng khóa/nonfinite và alias NFC/case/khoảng trắng của cùng mục từ ở cả dev/test. Chỉ đối chiếu mục từ/nghĩa nguồn của split đã chọn. In cảnh báo regression và chỉ ghi aggregate, không ghi query/gold vào báo cáo. Báo cáo có hash kho/fixture/retriever/scorer, policy khớp nghĩa và số ca được gán nhãn.

Ví dụ chạy từ thư mục gốc dự án (thư mục docs đã tồn tại):

```bash
python manage.py evaluate_retrieval --benchmark-version 2 --include-test --output docs/retrieval-check.json
python manage.py evaluate_retrieval --benchmark-file learning/data/retrieval_sense_regression_v1.json --output docs/sense-check.json
```

Nếu đích đã tồn tại, cần `--overwrite` rõ ràng. Kiểm tra đường dẫn trước truy xuất và trước ghi nguyên tử; từ chối ghi vào source, input, fixture cố định, symlink/hardlink alias, đích không phải JSON hoặc thư mục cha chưa có. Không truyền `--overwrite` để sửa fixture. Nhãn sense của split chưa chọn không bị kiểm tra nguồn hoặc tiết lộ qua thông báo lỗi thiếu nguồn.

## Kết quả và đánh đổi

Các file `retrieval_evaluation_m11_before.json` và `retrieval_evaluation_m11.json` dùng cùng hash fixture v2 và cùng kho **3.055 thẻ khả dụng**. M1–M10 đã từng mở bộ v2; split test trong file là split lịch sử, **không còn là holdout độc lập**. Không sửa byte benchmark v1/v2 hoặc thêm nhãn gold vào chúng.

| Chỉ số trên regression v2 | Trước M11 | Sau M11 |
|---|---:|---:|
| Tìm đúng mục từ trong top3 |57/80 (71,25%)|61/80 (76,25%)|
| MRR@3 |0,7000|0,7562|
| Không trả nguồn cho ca âm |5/16|16/16|
| Tiếng Anh có mục từ rõ |15/20|20/20|
| Tiếng Việt / không dấu có mục từ rõ |20/20 mỗi nhóm|20/20 mỗi nhóm|
| Diễn đạt lại theo nghĩa |2/20|1/20|

Bộ lọc bảo thủ giảm nhiễu nhưng bỏ sót thêm một ca paraphrase. Đây là đánh đổi thực tế, chưa đạt mục tiêu truy xuất ngữ nghĩa. Không suy ra hiệu quả trên người học mới hoặc dữ liệu độc lập. V2 không có nhãn nghĩa/ambiguity nên các mẫu số mới bằng0 và metric mới null.

`retrieval_sense_regression_v1.json` mới có12 ca đã biết, toàn bộ dev:8 ca dương dùng4 mục từ có biến thể nguyên văn nghĩa trong kho và4 ca âm. Các cách viết nghĩa của arrive/invite/repair có thể tương đương; nhãn này không chứng nhận chúng là những nghĩa ngôn ngữ học khác nhau. Báo cáo `retrieval_sense_evaluation_m11.json` đạt8/8 ca sense/ambiguity theo hợp đồng và4/4 ca âm. Đây là regression chức năng có nhãn AI/biên tập, không dùng để quảng bá độ chính xác nghĩa100%. Các ca bank/charge và phân biệt dấu được kiểm tra thêm trong database test tổng hợp.

Router ghi chú/từ vựng hiện có vẫn đạt16/16 ca trong `tutor_router_evaluation_m11.json`. Không gọi model, chấm chất lượng câu trả lời hoặc xác minh prompt-injection thực tế qua inference. A02/A03/A06 vẫn cần bộ nhãn độc lập, người duyệt và chạy model có giới hạn ngân sách.

## Kiểm chứng

**825 Django tests:817 đạt,8 PostgreSQL-only skip;105/105 JavaScript tests đạt.** M11 thêm42 test Django:21 intent/làm rõ nghĩa,8 đo nghĩa/validate nhãn và13 CLI/path/bounds. Kiểm tra toàn bộ suite và các ca quota/provider không được gọi, quyền nguồn, snapshot/provenance; giữ số query không N+1. Đổi2 fixture/assertion cũ để phản ánh chủ đích: không trả từ con của cụm trích dẫn và đo nhiều biến thể cùng headword cho test số query.

System/schema/projection/local-release, migration drift đạt. Không thay HTML/CSS/JS hoặc khởi chạy preview mới; backend được kiểm tra bằng Django Client/unit tests, chưa phải browser–Django live E2E. JavaScript regression chạy lại để giữ kiểm chứng gói dự án. Database chính không có tài khoản học hoặc quan sát pilot; lệnh đánh giá chỉ đọc. Không triển khai CI/PG/Docker/Cloudflare hoặc kết nối dịch vụ ngoài trong đợt này.

A02 vẫn mở vì paraphrase thấp và thiếu người chấm độc lập. Không đóng toàn bộ audit từ kết quả M11.
