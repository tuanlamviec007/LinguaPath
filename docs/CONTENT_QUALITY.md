# Chính sách biên tập và kiểm định học liệu LinguaPath

## Vai trò nguồn tham khảo

Các liên kết chính thức dưới đây dùng để thiết kế tiêu chí và kiểm tra mức độ phù hợp. Nội dung đang lưu trong ứng dụng (nghĩa tiếng Việt, câu ví dụ, đoạn văn, hội thoại, câu hỏi và đáp án) được nhóm đồ án tự biên soạn.

| Nguồn | Cách dùng trong LinguaPath | Không lấy vào kho nội dung |
|---|---|---|
| [Council of Europe – CEFR descriptors](https://www.coe.int/en/web/common-european-framework-reference-languages/cefr-descriptors) | Xây tiêu chí “người học làm được gì” theo kỹ năng và mức CEFR. | Không dán nguyên văn các mô tả dài vào sản phẩm. |
| [Cambridge English Profile](https://englishprofile.org/) | Tra cứu từ/nghĩa và kiểm tra mức CEFR như một tín hiệu biên tập; mức có thể phụ thuộc nghĩa cụ thể. | Không nhập hàng loạt Cambridge wordlists, định nghĩa, câu ví dụ hoặc đặt tên kho là “Cambridge 3000” khi chưa có giấy phép. |
| [British Council LearnEnglish – Reading A1](https://learnenglish.britishcouncil.org/free-resources/reading/a1), [Reading A2](https://learnenglish.britishcouncil.org/free-resources/reading/a2), [Listening A1](https://learnenglish.britishcouncil.org/free-resources/listening/a1), [Listening A2](https://learnenglish.britishcouncil.org/free-resources/listening/a2) | Tham khảo dạng văn bản, chủ đề và tải nhận thức phù hợp với cấp độ. | Không tải/copy bài đọc, transcript, câu hỏi, audio/video hoặc minh họa của trang. Có thể liên kết người học đến bài gốc. |
| [ETS – TOEIC Listening and Reading format](https://www.ets.org/content/ets-org/language-master/in/home/toeic/test-takers/about/listening-reading.html) | Lập blueprint dạng bài và cấu trúc luyện TOEIC. | Không lấy câu hỏi, audio, hình, đáp án hoặc nội dung đề ETS. Không gọi học liệu LinguaPath là đề chính thức. |
| [Cambridge Dictionary](https://dictionary.cambridge.org/dictionary/english/) | Kiểm tra chính tả, từ loại, phát âm và nghĩa của đúng sense; sau đó viết lại nghĩa tiếng Việt và câu ví dụ mới. | Không sao chép định nghĩa/câu ví dụ/audio nếu chưa có quyền sử dụng. |

## Checklist cho flashcard

1. Mỗi thẻ tập trung vào một nghĩa và từ loại cụ thể; nếu đưa thêm nghĩa thì phải có ví dụ riêng cho từng nghĩa.
2. CEFR được ghi là **mức biên tập tham khảo**, cần kiểm tra theo sense và có thể điều chỉnh sau khi thử với người học.
3. Nghĩa tiếng Việt, câu tiếng Anh và bản dịch phải được viết mới, tự nhiên, đúng ngữ cảnh.
4. Ghi chủ đề, nguồn tham khảo mức độ, ghi chú quyền sử dụng và người rà soát. Nút nghe phát âm hiện dùng giọng tổng hợp của thiết bị, không phải audio từ điển hay bản ghi người bản ngữ.
5. Dùng nhất quán một biến thể chính tả Anh-Mỹ hoặc Anh-Anh; LinguaPath hiện dùng chính tả Mỹ cho `practice` (động từ/danh từ).

## Checklist cho Reading/Listening

1. Viết mới văn bản/hội thoại, dùng chủ đề quen thuộc ở A1–A2 và tăng dần độ dài, từ vựng, cấu trúc câu, suy luận ở mức cao hơn.
2. Mỗi câu chỉ có một đáp án có thể chứng minh từ văn bản/audio. Distractors hợp lý nhưng bị bác bỏ bởi bằng chứng cụ thể.
3. Giải thích ngắn bằng tiếng Việt và dẫn đúng chi tiết hỗ trợ đáp án.
4. Listening ghi rõ nguồn/giấy phép và cách tạo audio. MP3 hiện được tổng hợp ngoại tuyến từ kịch bản tự viết bằng Flite; giọng máy, không thay thế bản thu chuẩn hóa để đo năng lực. Người học vẫn có tùy chọn dùng giọng trình duyệt hoặc mở transcript nếu audio không phát.
5. Rà soát nội dung bằng người có chuyên môn tiếng Anh, sau đó pilot với người học và sửa câu gây tranh cãi.

## Trạng thái gói khởi đầu

Gói hiện tại có 1.000 mục từ/cụm từ A1–C1 (79 A1, 235 A2, 286 B1, 263 B2, 137 C1) và 1.000 câu trắc nghiệm ôn nghĩa, chia thành các lượt tối đa 20 câu. Có 6 bài Reading/12 câu hỏi và 6 bài Listening/12 câu hỏi. `seed_demo` thêm 16 flashcard và 2 câu Reading; tổng sau khi chạy cả hai seed là 1.016 flashcard và 1.026 câu hỏi. Trong 1.000 mục, 152 thẻ nền tảng là nội dung tự biên soạn ban đầu; 848 mục mở rộng được AI hỗ trợ soạn thảo. Nghĩa, ví dụ và bản dịch đã được rà soát sơ bộ theo mẫu, nhưng toàn bộ lô cần giảng viên duyệt; nhãn CEFR chỉ là dự kiến, chưa được thẩm định độc lập theo từng sense hoặc kiểm chứng với người học. Đây không phải bộ Cambridge, placement chuẩn hóa hay ngân hàng đề TOEIC/IELTS hoàn chỉnh. Flashcard có mặt trước/mặt sau dạng lật; tìm kiếm theo từ/nghĩa/ví dụ, lọc theo mức/chủ đề, và mặt sau có ba lựa chọn tự đánh giá để lên lịch ôn. Listening dùng MP3 giọng tổng hợp Flite, có TTS thiết bị và transcript dự phòng.
## Cập nhật kiểm tra cấu trúc M2 — 24/10/2026

Importer và nguồn CSV starter dùng strict parser: từ chối header trùng/lạ, sai số ô, giá trị/độ dài/URL không hợp lệ trước khi ghi. Staff import cần thêm quyền parent LearningContent theo thao tác thực. Seed rerun giữ chỉnh sửa đã có. CSV nguồn trip đã sửa; DB cũ có lệnh repair_starter_trip mặc định chỉ dry-run, vì apply sẽ đưa cả parent về nháp. Không có học liệu được tự chuyển teacher_approved. Xem [M2](STABILITY_M2.md) trước khi vận hành.

