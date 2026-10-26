# Trợ lý học tập — vòng phát triển thứ hai, 20/10/2026

Đây là báo cáo lịch sử ngày 20/10. **Phép đo hiện tại ngày 24/10/2026** nằm trong [M3](STABILITY_M3.md), trên 3.056 thẻ: Recall@3 dev 75%, test cũ 67,5%, toàn bộ 71,25%; từ chối 5/16 ca âm và paraphrase 2/20. `retrieval_evaluation_v2.json` đã được cập nhật theo kho/mã hiện tại; JSON của vòng này được giữ riêng ở `retrieval_evaluation_v2_initial.json`. Không so sánh số liệu giữa hai corpus như một cải tiến thuật toán.

## Kết quả sử dụng

Mặc định **Tra cứu học liệu**: tìm trong kho đã xuất bản, hiển thị nguồn, không gọi dịch vụ AI và không tiêu hao lượt AI. Nếu máy chủ bật dịch vụ, người học có thể chủ động chọn **AI diễn giải**. Khi không tìm được nguồn hoặc cần làm rõ nghĩa của từ, hệ thống trả về trước bước đặt lượt/gọi API. Khi dịch vụ tắt hoặc chưa có khóa, yêu cầu chọn AI được đưa về chế độ tra cứu và giao diện giữ lựa chọn hợp lệ.

Thẻ nguồn hiện nghĩa tiếng Việt để phân biệt ngữ cảnh. Với nhiều nghĩa đang có cùng mức phù hợp, trợ lý hỏi lại và đưa tối đa năm gợi ý chọn nghĩa. Chọn gợi ý điền câu hỏi kèm nghĩa, không tự gửi; người học có thể sửa trước khi gửi. Các hàng trùng từ và cùng nghĩa chuẩn hóa được gộp khi đưa kết quả. Đây là cách xử lý mơ hồ có luật, chưa phải mô hình phân biệt nghĩa đã được huấn luyện.

Giao diện tăng cỡ chữ phần hướng dẫn, lựa chọn chế độ, thông báo riêng tư và nội dung nguồn. Chặn gửi lặp và khôi phục nút gửi khi trình duyệt mở lại trang từ bộ nhớ điều hướng. Chưa có kiểm tra thị giác hoặc thao tác trên trình duyệt thật trong đợt này.

## Thay đổi truy xuất

Nguồn từ vựng được xếp hạng theo từ đích và các từ ngữ cảnh trùng trong nghĩa, ví dụ, chủ đề. Khớp một từ tình cờ trong câu hỏi chung không tự được coi là yêu cầu tra từ. Câu hỏi thông thường vẫn có thể tìm trong lịch sử câu đã nộp của chính người học. Văn bản có dấu được giữ nguyên khi hiển thị; chỉ bỏ dấu ở bước so khớp.

Giữ các giới hạn: đúng kỳ thi, đã xuất bản, trạng thái rà soát hợp lệ; lời giải/đáp án/transcript chỉ dành cho người đã nộp lượt luyện chứa câu đó. ID tường minh không hợp lệ/bị từ chối không rơi sang tìm kiếm chung. Agent audit không phát hiện lỗi quyền truy cập trong các luồng đã đọc; điều này không thay thế đánh giá bảo mật toàn hệ thống.

## Thiết kế đánh giá

- Bộ v2 có 96 ca, 20 từ đích khác bộ v1: 80 ca dương thuộc bốn dạng hỏi và 16 ca âm ngoài phạm vi có từ trùng tình cờ. Tách 48 dev/48 test; mỗi tập có 40 ca dương, 8 ca âm. Các biến thể cùng từ ở cùng tập.
- Agent biên tập không đọc mã retriever. Agent triển khai và audit không đọc câu hỏi/nhãn gold v2. Nhãn vẫn là phán đoán AI biên tập, chưa có giáo viên độc lập xác nhận.
- Chốt mã trước lần đo test cuối; không điều chỉnh theo kết quả test trong vòng này. Lệnh mặc định chỉ chạy dev; nhãn test không được dùng để kiểm tra thiếu từ khi chạy dev. Báo cáo chỉ có số liệu tổng hợp, hash benchmark, hash corpus và hash mã.
- So sánh cùng kho từ: `baseline` là thuật toán ban đầu; `previous` là bản vòng một đóng băng trong `retrieval_v1.py`; `improved` là bản hiện tại. Chỉ đo truy xuất từ vựng, không gọi API và không dùng lịch sử cá nhân.
- Recall@3/MRR@3 chấm theo từ đầu mục; không đo khả năng chọn đúng nghĩa. Phân biệt nghĩa hiện được kiểm tra bằng các tình huống tổng hợp trong unit test, chưa có tập gán nhãn nghĩa ngoài thực tế.

## Kết quả đo v2

| Chỉ số trên tập test | Vòng một (`previous`) | Bản hiện tại (`improved`) |
|---|---:|---:|
| Nguồn đúng trong ba kết quả đầu (Recall@3) | 31/40 — 77,5% | 28/40 — 70% |
| MRR@3 | 0,7625 | 0,6875 |
| Từ chối đúng câu ngoài phạm vi | 0/8 — 0% | 2/8 — 25% |

Trên toàn bộ dev + test, Recall@3 giảm 80% → 73,75%; từ chối đúng ca âm tăng 0/16 → 6/16. Ở nhóm hỏi nghĩa tiếng Việt không nêu từ tiếng Anh (`paraphrase`), Recall@3 vẫn chỉ 20% trên 20 ca ở cả hai bản. Các chỉ số đo nguồn theo từ đầu mục, không đo chất lượng giải thích hoặc học tập.

Kết quả cho thấy luật mới giảm một phần khớp tình cờ, kèm mất một số truy vấn hợp lệ. Chưa đạt chất lượng để quảng bá trợ lý như gia sư đáng tin cậy. Tên khóa `improved` trong công cụ là tên nhánh đang thử, không có nghĩa mọi chỉ số đều tốt hơn. Tập test chỉ có tám ca âm nên chưa đủ để suy rộng tỷ lệ từ chối ra người dùng thực tế. Không sửa luật sau khi mở số liệu test đợt này.

Audit còn ghi nhận giới hạn: nhận diện câu hỏi chung dựa vào tiền tố có thể bỏ sót câu có phần dẫn nhập hoặc đặt từ trích dẫn trước mệnh đề hỏi; thẻ từ vẫn có thể vượt nguồn câu đã nộp trong các trường hợp đó. Điểm này được giữ trong backlog của vòng tiếp theo, cùng bộ câu hỏi có nhãn người thật. Không coi bộ guard hiện tại là bộ hiểu ý định tổng quát.

Số liệu và hash lịch sử vòng này: `docs/retrieval_evaluation_v2_initial.json`. Báo cáo lịch sử vòng một giữ nguyên; mã vòng một được lưu nguyên byte trong `learning/retrieval_v1.py` để so sánh cùng corpus.

## Tái lập

Sau ba lệnh seed trong README:

```bash
python manage.py evaluate_retrieval --benchmark-version 2
# Chỉ mở test khi kết thúc một vòng phát triển:
python manage.py evaluate_retrieval --benchmark-version 2 --include-test --output docs/retrieval_evaluation_v2.json
python manage.py test
node --test scripts/test_practice_draft.cjs scripts/test_tutor_workspace.cjs
```

Báo cáo vòng một ở `AI_RETRIEVAL.md` và `retrieval_evaluation.json` là số liệu lịch sử, không phải phép đo của mã hiện tại. Tập v1 đã được mở từ vòng trước nên không còn là test độc lập cho vòng này. Sau khi công bố số liệu v2, vòng tinh chỉnh tiếp theo cũng cần tập test mới hoặc tách test do người chấm độc lập giữ.

## Giới hạn sản phẩm

Luật nhận diện ý định và xếp hạng từ khóa vẫn có thể bỏ sót cách hỏi đúng hoặc chọn nguồn không phù hợp. Chưa đánh giá chất lượng câu trả lời LLM bằng người chấm; chưa có kết quả pilot học tập, kiểm định CEFR hay chứng minh nâng điểm TOEIC. Nội dung từ vựng/Reading/Listening và trạng thái duyệt giữ nguyên trong đợt này. Website vẫn là bản đồ án cần rà soát học liệu và thử nghiệm trước khi quảng bá rộng rãi.

## Kiểm tra bản bàn giao

163 test Python và 8 test JavaScript đều đạt. Django system check không có lỗi; không phát sinh migration. API thật không được gọi trong các test/đánh giá này: nhánh diễn giải dùng mock, phép đo nguồn chỉ đọc DB. Không có kiểm tra thị giác trên trình duyệt thật hoặc triển khai công khai trong vòng này.
