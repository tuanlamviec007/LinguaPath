# Trợ lý và đánh giá truy xuất — 20/10/2026

Báo cáo lịch sử vòng một. Phép đo hiện tại ngày 24/10/2026 được mô tả trong [M3](STABILITY_M3.md); [vòng hai](TUTOR_V2.md) giữ bối cảnh trước đó. Các chỉ số phía dưới không áp dụng cho kho/mã retriever hiện tại.

## Thay đổi người học nhìn thấy

Trang Trợ lý có gợi ý từ vựng theo mức CEFR đang chọn và kỳ thi trong hồ sơ. Chọn gợi ý điền câu hỏi, giữ focus ở ô nhập và xóa ngữ cảnh câu hỏi cũ; chưa tự gửi. Ô nhập giới hạn 500 ký tự, có bộ đếm và chặn gửi lặp khi đang xử lý.

Phản hồi có thẻ nguồn và liên kết về học liệu. Liên kết từ vựng mở toàn thư viện theo từ tìm được, kể cả thẻ chưa đến hạn ôn. Nội dung `language_checked` hiện nhãn AI rà soát sơ bộ, chưa giảng viên duyệt. Chế độ tra cứu được phân biệt với diễn giải bằng LLM. Chưa có API key thì chỉ hiện nguyên văn học liệu; không gọi dịch vụ ngoài.

Truy xuất chuẩn hóa Unicode và chữ đ, bỏ dấu khi so khớp nhưng giữ nguyên chữ có dấu trong nguồn. Từ chính xác, từ đặt trong ngoặc kép và cụm từ được ưu tiên so với trùng trong nghĩa/ví dụ. Đây là xếp hạng từ khóa có luật, không phải tìm kiếm ngữ nghĩa hoặc mô hình đã huấn luyện. Điểm xếp hạng không phải xác suất đúng.

## Ranh giới dữ liệu

- Flashcard phải thuộc kỳ thi đang học, được xuất bản và có trạng thái rà soát cho phép người học truy cập.
- Lời giải, phương án đúng và transcript chỉ được truy xuất khi người dùng hiện tại đã nộp lượt luyện chứa câu đó; người khác, lượt đang làm và người chưa đăng nhập không được dùng nguồn này.
- ID câu hỏi tường minh không hợp lệ/bị từ chối không chuyển sang tìm kiếm chung. ID được giới hạn số nguyên dương 64 bit.
- Chỉ tải phương án của câu hỏi được chọn vào kết quả; không tải phương án cho toàn lịch sử khi xếp hạng.
- Giữ hạn mức dịch vụ AI hiện có. Không có nguồn thì không gọi LLM. Khi vượt hạn mức/lỗi dịch vụ, thẻ nguồn chỉ liệt kê phần học liệu thực sự hiển thị.

## Phương pháp thực nghiệm

`learning/retrieval_baseline.py` đóng băng nhánh tra cứu flashcard trước lần nâng cấp này: SQL `icontains`, tối đa 100 ứng viên theo ID, điểm trùng từ cũ. So sánh trên cùng 1.016 flashcard nhìn thấy, không dùng lịch sử cá nhân và không gọi LLM. Không dùng kết quả này để kết luận chất lượng giải thích hay hiệu quả học tập.

Agent biên tập độc lập tạo 96 truy vấn: 20 mục từ A1–C1, mỗi từ có bốn cách hỏi (tiếng Anh, tiếng Việt, không dấu, diễn đạt vòng) và 16 ca dự kiến không có nguồn. Tách cố định 48 dev/48 test; mỗi tập có 40 ca dương, 8 ca âm. Các biến thể của cùng mục từ luôn nằm cùng một tập. Nhãn do AI biên tập, chưa có giáo viên/người chấm độc lập xác nhận. Nhiều câu hỏi tiếng Việt/không dấu chứa sẵn từ tiếng Anh cần tìm; kết quả không chứng minh hiểu nghĩa tiếng Việt tổng quát.

Retriever được chốt trước khi mở số liệu test. Sau lần đo, không sửa luật xếp hạng theo kết quả test. Sau audit, lệnh đo được sửa để mặc định chỉ chạy dev; `--include-test` mở test trong lần đánh giá cuối. Báo cáo lưu số liệu tổng hợp và SHA-256 của benchmark/hai retriever, không lưu truy vấn/gold từng ca. Lần xuất lại báo cáo chỉ thay định dạng và cơ chế mở test, giữ nguyên mã retriever.

## Kết quả

| Chỉ số | Cũ: dev | Mới: dev | Cũ: test | Mới: test |
|---|---:|---:|---:|---:|
| Recall@3 trên ca dương | 35% | 75% | 20% | 75% |
| MRR@3 trên ca dương | 0,2917 | 0,7500 | 0,1583 | 0,7500 |
| Từ chối đúng ca âm | 75% | 25% | 62,5% | 37,5% |

Recall@3: tỷ lệ nguồn được gán nhãn xuất hiện trong ba kết quả đầu. MRR@3: trung bình nghịch đảo thứ hạng của nguồn đúng; không tìm thấy tính 0. Mỗi ca dương hiện chỉ có một từ đích nên Hit@3 trùng Recall@3. Từ chối đúng ca âm: số ca âm trả kết quả rỗng / tổng ca âm.

Trên cả 96 ca, Recall@3 tăng 27,5% → 75%, nhưng số ca âm vẫn trả nguồn tăng 5/16 → 11/16. Nhóm diễn đạt vòng giảm 10% → 0%; các nhóm có từ đích rõ tăng mạnh. Kết luận phù hợp là cải thiện tra từ tường minh, kèm đánh đổi bất lợi về truy vấn ngoài phạm vi và chưa hỗ trợ tốt diễn đạt ngữ nghĩa. Không kết luận trợ lý tốt hơn trên mọi nhu cầu.

Số liệu chi tiết tổng hợp nằm trong `docs/retrieval_evaluation.json`.

## Giới hạn và bước tiếp theo

1. Bổ sung nhãn từ người có chuyên môn, truy vấn thật có đồng ý và ca âm khó; tạo tập test mới trước khi tiếp tục điều chỉnh theo phản hồi đợt này. Tập test hiện đã được mở để báo cáo nên không còn độc lập cho vòng tinh chỉnh tiếp theo.
2. Chấm theo nghĩa/ngữ cảnh, không chỉ từ đầu mục. Audit phát hiện nhiều thẻ cùng đầu mục có thể hòa điểm và ưu tiên ID cũ; hỏi từ đa nghĩa có nguy cơ nhận nhầm nghĩa. Chưa giải quyết trong phiên bản này.
3. Đánh giá lời giải LLM riêng: đúng, bám nguồn, đủ thông tin, xử lý thiếu nguồn, chỉ dẫn gây nhiễu, độ trễ và chi phí. Chưa gọi API thật hoặc chấm câu trả lời LLM trong đợt này.
4. Quét tối đa 10.000 flashcard theo ID; kho lớn hơn cần chỉ mục tìm kiếm thay vì bỏ sót phần đuôi. Lịch sử câu đã nộp vẫn quét trong bộ nhớ; cần đo hiệu năng ở dữ liệu lớn.
5. Giao diện đã qua Django HTTP/template và test JavaScript mô phỏng DOM; chưa kiểm tra thị giác và tương tác trên trình duyệt thật trong đợt này. Chưa triển khai công khai.

## Tái lập

Nạp đủ ba bộ seed theo README, sau đó:

```bash
python manage.py evaluate_retrieval
# Chỉ dùng khi kết thúc vòng phát triển:
python manage.py evaluate_retrieval --include-test --output docs/retrieval_evaluation.json
python manage.py test
node --test scripts/test_practice_draft.cjs scripts/test_tutor_workspace.cjs
```

Lệnh đo không thay đổi DB hoặc gọi dịch vụ AI. Nên giữ nguyên tập dữ liệu và lưu hash cùng báo cáo khi so sánh.

Kiểm tra bản bàn giao: 141 test Python đạt, 7 test JavaScript đạt; Django system check không có lỗi và không có migration chưa tạo. Đây là kiểm thử tự động, chưa thay thế pilot và kiểm tra trình duyệt thật.
