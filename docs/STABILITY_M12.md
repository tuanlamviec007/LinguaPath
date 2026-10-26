# LinguaPath — tìm từ theo mô tả M12

Cập nhật **26/10/2026**. Thêm một cách tìm có lựa chọn rõ ràng trong Tutor, dùng hoàn toàn trong ứng dụng và trả ứng viên để người học chọn. **Không có migration mới**, tiếp tục schema0023 của M10. Không seed lại, không sửa học liệu, không cài model/dịch vụ/vector database hoặc dùng lượt inference.

## Sử dụng

Trong Trợ lý học tập, chọn **Tìm từ theo mô tả** rồi nhập vài từ khóa tiếng Việt về nghĩa. Kết quả có tối đa3 mục từ cùng nghĩa nguyên văn trong nguồn. Chọn một mục để mở phần tra cứu miễn phí; có thể sửa mô tả nếu chưa đúng ý. Đây là gợi ý dựa vào từ ngữ trùng, chưa xác nhận đáp án hoặc hiểu mọi từ đồng nghĩa.

Hai cách tìm tách rõ: **Hỏi từ / kiến thức** giữ luồng tự động M11, còn mô tả chỉ chạy khi người học chọn. Không nới gate của luồng tự động để câu xin lời khuyên vô tình trở thành tra từ. API tùy chọn `retrieval_mode='description'`, web dùng `query_mode=description`; mode không hợp lệ hoặc trùng trên POST bị từ chối.

Bước mô tả luôn miễn phí, kể cả người dùng sửa POST thành `response_mode=ai` hoặc API gọi với `use_ai=True`. Ứng viên trả về `needs_context` kèm `retrieval_mode=description`, trước khi đóng gói context, đặt quota hoặc gọi provider. Không tự giải thích ứng viên đứng đầu. Không có kết quả thì gợi ý viết thêm từ khóa, không suy đoán một mục từ mới.

Các nút chọn từ dùng POST có CSRF với `action=select_candidate`, ID/hash phiên bản nguồn, `query_mode=auto`, `response_mode=lookup`; hoạt động khi tắt JavaScript. Nút gợi ý điền câu hỏi cũng chuyển về tra cứu miễn phí, xóa context câu hỏi cũ và không tự gửi. Đổi từ mô tả về cách hỏi thường không tự khôi phục lựa chọn AI có trả phí. Sau khi tra từ, người học vẫn có thể chủ động chọn AI ở lượt hỏi khác theo quota hiện có.

## Cách xếp hạng và giới hạn

`learning/retrieval_description.py`, policy `description-lexical-v1`:

- Dựng chỉ mục trong bộ nhớ theo request từ thẻ vocabulary khả dụng, parent đã xuất bản với review cho phép và đúng kỳ thi. Không dùng cache lâu dài nên held/edit được đọc lại ở request tiếp theo. Không đọc lịch sử/câu hỏi riêng hoặc ghi chú grammar; mode mô tả có question_id sẽ từ chối, không rơi xuống tìm nguồn khác.
- Tách từ có fold Unicode/dấu để tìm, giữ nguyên nội dung nguồn khi hiển thị. Bỏ token chức năng/request và số đứng riêng. Đếm độ hiếm trên các tài liệu đã bỏ trùng mục từ/nghĩa theo NFC/casefold/khoảng trắng/dấu câu; giữ khác biệt dấu khi nhận diện nguyên văn nghĩa. Với bản trùng, giữ đại diện có ID sớm nhất; ví dụ khác ở dòng trùng có thể không được dùng.
- Nghĩa tiếng Việt là chính, ví dụ tiếng Việt trọng số thấp hơn; không dùng topic, ví dụ tiếng Anh, alias hoặc synonym tự tạo làm bằng chứng quyết định. Độ hiếm/tần suất có bão hòa và chuẩn hóa độ dài; trọng số nghĩa3, ví dụ0,5, cộng hỗ trợ cặp từ liền kề. Không ghép cặp từ mới sau khi xóa stopword.
- Cần ít nhất2 token trùng phần nghĩa; hoặc1 token nghĩa hiếm được củng cố bởi một cặp từ liền kề trong ví dụ. Ví dụ/topic trùng đơn độc không tạo ứng viên. Từ lặp trong query không tự tăng trọng số. Điểm chỉ xếp hạng, không phải xác suất/độ tin cậy, không tự chọn nghĩa hoặc chứng nhận chính xác.
- Giới hạn500 ký tự query,2.000 ký tự mỗi field lập chỉ mục,10.000 thẻ theo ID từ queryset và3 ứng viên. Chỉ mục không bền; số thẻ lớn hơn cap sẽ chưa được tìm hết. Không có tuyên bố hiệu năng/plan PostgreSQL từ fixture1 query SQLite.

Tìm từ chưa biết qua cách diễn đạt khác hẳn nguồn vẫn khó. Ví dụ mô tả không chứa từ nào trong nghĩa/ví dụ không thể được tìm chỉ nhờ trọng số lexical. Nguồn AI rà soát sơ bộ vẫn chưa được giảng viên duyệt; xếp hạng không cải thiện tính đúng đắn ngôn ngữ của nguồn. Không coi M12 là semantic search hoặc hoàn tất A02.

## Lịch sử và quyền riêng tư

Lượt mô tả vẫn theo lịch sử riêng tối đa50 lượt và ownership hiện có. `retrieval_mode` được giữ trong result JSON và bản xuất dữ liệu của chính tài khoản; không có trường/model/migration mới. Ghi nhận mô tả không tạo XP, thay CEFR/SRS hoặc phê duyệt học liệu.

Nguồn gợi ý có fingerprint hiện hành như các nguồn Tutor khác. Khi mở lịch sử, giữ nguyên câu trả lời cũ nhưng kiểm tra lại source: chỉ nguồn current được đưa vào nút chọn và shortcut sống. Nguồn stale/withdrawn/legacy không còn nút chọn; không sửa snapshot trong DB. Khi chọn, server kiểm tra định dạng ID/hash rồi tự đối chiếu thẻ vocabulary khả dụng đúng kỳ thi và fingerprint hiện tại. ID/hash trong HTML là điều kiện độ mới, không cấp quyền. Nguồn đã sửa/giữ, sai kỳ thi hoặc version sai trả no_match, không rơi sang một nghĩa/nguồn khác. Câu hỏi tra cứu được dựng từ nguồn thật, không tin prompt/AI mode gửi kèm. Context câu hỏi sai không thể được dùng để chuyển sang tìm nguồn công khai.

## Đánh giá ngoại tuyến

Lệnh có thêm `--retrieval-mode auto|description` (mặc định auto). Description chỉ báo cáo ứng viên của chính cách tìm này, không so với baseline tự động khác tác vụ. Báo cáo giữ hash corpus/fixture/scorer, thêm hash module chỉ mục và command; M7 runner cũng fingerprint module mới. Các bảo vệ file/bounds/overwrite của M11 được giữ.

```bash
python manage.py evaluate_retrieval --benchmark-version 2 --include-test --output docs/auto-check.json
python manage.py evaluate_retrieval --benchmark-version 2 --include-test --retrieval-mode description --output docs/description-check.json
```

Nếu đích đã có, thêm `--overwrite` theo quy tắc M11. Không dùng báo cáo thay fixture.

`retrieval_evaluation_m12.json`: luồng tự động vẫn **61/80 mục từ**, **16/16 ca âm** và paraphrase1/20 trên v2 đã biết. `tutor_router_evaluation_m12.json` vẫn16/16 ca router. Không sửa byte benchmark hoặc gold.

`description_retrieval_m12.json`: khi chủ động dùng mô tả, ứng viên đúng nằm top3 ở **2/20 ca paraphrase**, MRR@3=0,075. Dev có2/10, split test lịch sử0/10. Toàn bộ file96 ca còn chứa nhiều câu nêu trực tiếp headword, không phải tác vụ phù hợp cho mode mô tả: tổng dương4/80 không dùng để so trực tiếp với auto61/80. Cả16 ca âm đều không trả ứng viên trên bộ đó; phần âm tiếng Anh chưa chứng minh xử lý câu âm tiếng Việt thực tế.

Các bộ này đã được mở trong các vòng trước, không phải holdout độc lập. Không đo chất lượng câu trả lời model hoặc suy ra độ chính xác tìm theo nghĩa tổng quát. Hai cách tìm khác nhiệm vụ và mức tương tác. M12 cung cấp luồng có kiểm soát để thử ứng viên, kết quả lexical còn thấp; A02 tiếp tục mở. Cần nguồn mô tả được duyệt/nhãn độc lập và phương án truy xuất ngữ nghĩa được đánh giá trước khi thay luồng mặc định.

## Kiểm chứng

**855 Django tests:847 đạt,8 PostgreSQL-only skip;109/109 JavaScript tests đạt.** Thêm28 test Django cho xếp hạng/bounds, duplicate/Unicode/cặp từ, nguồn public/held/exam, từ chối question_id, không pack/quota/provider, lựa chọn/free POST, pin ID/version, nguồn sửa/giữ không fallback, CSRF, history/export và thêm2 CLI tests cho mode/tập nguồn phù hợp. Thêm4 JS tests cho radio/AI disable/prompt reset/BFCache, giữ các luồng Tutor cũ. Sau rà soát bổ sung shortcut lịch sử chỉ giữ nguồn current,65 test hợp đồng liên quan đạt lại.

Agent thực hiện UI và rà backend; không có quyền truy cập hay inference mới được bật. System/schema/projection/local-release, migration drift và collectstatic đạt. Kiểm tra browser dùng template Django render từ database memory với tài khoản QA tổng hợp: form, kết quả, chọn từ, không khớp, lịch sử nguồn giữ. Desktop1348px và iframe375px (document360px có scrollbar) không tràn ngang; radio/input có label. Backend kiểm chứng bằng Django Client, không phải browser→Django live E2E hoặc thiết bị thật.

Database chính không thêm tài khoản hoặc dữ liệu pilot; dữ liệu test nằm riêng. Không triển khai PostgreSQL/Docker/CI/Cloudflare thực tế trong đợt này. Chưa hoàn tất toàn bộ audit.
